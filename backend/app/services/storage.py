"""Minimal Supabase Storage client (REST) for evidence media.

Stored paths are '<bucket>/<object key>', e.g.
'evidence-clips/<session_id>/<detection_id>.mp4'. Buckets must be private;
reviewers get short-lived signed URLs, so video bytes never pass through
the API service.
"""
from __future__ import annotations

from urllib.parse import quote

import httpx

from app.config import settings

STORAGE_REQUEST_TIMEOUT_SECONDS = 60.0


class StorageNotConfiguredError(RuntimeError):
    """Raised when SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY are unset."""


def split_storage_path(path: str) -> tuple[str, str]:
    bucket, _, key = path.partition("/")
    if not bucket or not key:
        raise ValueError(f"storage path {path!r} must be '<bucket>/<key>'")
    return bucket, key


class SupabaseStorage:
    def __init__(
        self, *, base_url: str, service_role_key: str, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self._api = f"{base_url.rstrip('/')}/storage/v1"
        self._headers = {"Authorization": f"Bearer {service_role_key}", "apikey": service_role_key}
        self._transport = transport

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=STORAGE_REQUEST_TIMEOUT_SECONDS, headers=self._headers, transport=self._transport
        )

    async def upload(self, path: str, data: bytes, content_type: str) -> None:
        """Create an object; fails (409) rather than overwrite an existing one."""
        bucket, key = split_storage_path(path)
        async with self._client() as http:
            response = await http.post(
                f"{self._api}/object/{bucket}/{quote(key)}",
                content=data,
                headers={"Content-Type": content_type, "x-upsert": "false", "Cache-Control": "private, max-age=300"},
            )
            response.raise_for_status()

    async def delete(self, paths: list[str]) -> None:
        by_bucket: dict[str, list[str]] = {}
        for path in paths:
            bucket, key = split_storage_path(path)
            by_bucket.setdefault(bucket, []).append(key)
        async with self._client() as http:
            for bucket, keys in by_bucket.items():
                response = await http.request("DELETE", f"{self._api}/object/{bucket}", json={"prefixes": keys})
                response.raise_for_status()

    async def signed_url(self, path: str, expires_in_seconds: int) -> str:
        bucket, key = split_storage_path(path)
        async with self._client() as http:
            response = await http.post(
                f"{self._api}/object/sign/{bucket}/{quote(key)}", json={"expiresIn": expires_in_seconds}
            )
            response.raise_for_status()
        # The API returns a path relative to /storage/v1, e.g. "/object/sign/<bucket>/<key>?token=...".
        return f"{self._api}{response.json()['signedURL']}"


_storage: SupabaseStorage | None = None


def get_storage() -> SupabaseStorage:
    global _storage
    if _storage is None:
        if not settings.supabase_url or not settings.supabase_service_role_key:
            raise StorageNotConfiguredError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set.")
        _storage = SupabaseStorage(base_url=settings.supabase_url, service_role_key=settings.supabase_service_role_key)
    return _storage


def storage_configured() -> bool:
    return bool(settings.supabase_url and settings.supabase_service_role_key)
