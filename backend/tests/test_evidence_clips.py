"""Evidence clips: compression, upload hardening, reviewer access, retention
after the review is final, and the Supabase Storage request shapes.

Tests marked `needs_ffmpeg` run in the Docker test image (which has ffmpeg):
    docker compose --profile test run --rm tests
"""
from __future__ import annotations

import json
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Any

import asyncpg
import httpx
import pytest
import pytest_asyncio
from httpx import AsyncClient

from app.config import settings
from app.routers import media as media_router
from app.services import mqtt, retention
from app.services.storage import SupabaseStorage
from tests.helpers import (
    ADMIN_EMAIL,
    CONTROLLER_EMAIL,
    HOD_EMAIL,
    INTERNAL_KEY,
    STUDENT_A_EMAIL,
    TEACHER_EMAIL,
    bearer,
    login,
)
from tests.test_detection_pipeline import (  # noqa: F401  (fixture)
    ACTIVE_SESSION_ID,
    _detection_body,
    _noop_publish,
    active_session,
)

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed (runs in Docker)")
INTERNAL_HEADERS = {"X-Internal-Api-Key": INTERNAL_KEY}
OTHER_TEACHER_EMAIL = "s.naqvi@students.au.edu.pk"


class FakeStorage(SupabaseStorage):
    def __init__(self) -> None:
        super().__init__(base_url="https://project.supabase.co", service_role_key="service-key")
        self.objects: dict[str, tuple[bytes, str]] = {}
        self.deleted: list[str] = []

    async def upload(self, path: str, data: bytes, content_type: str) -> None:
        self.objects[path] = (data, content_type)

    async def delete(self, paths: list[str]) -> None:
        self.deleted.extend(paths)

    async def signed_url(self, path: str, expires_in_seconds: int) -> str:
        return f"https://signed.test/{path}?ttl={expires_in_seconds}"


@pytest.fixture
def storage(monkeypatch: pytest.MonkeyPatch) -> FakeStorage:
    fake = FakeStorage()
    monkeypatch.setattr(media_router, "get_storage", lambda: fake)
    return fake


@pytest_asyncio.fixture
async def detection_case(
    client: AsyncClient, active_session: str, monkeypatch: pytest.MonkeyPatch  # noqa: F811
) -> dict[str, Any]:
    monkeypatch.setattr(mqtt.mqtt_service, "publish", _noop_publish)
    response = await client.post("/internal/detections", headers=INTERNAL_HEADERS, json=_detection_body(active_session))
    assert response.status_code == 201, response.text
    return response.json()


def _make_video(path: Path, *, seconds: float, size: str = "1280x720", rate: int = 30, audio: bool = True) -> Path:
    """A deliberately heavy source clip: 720p30, near-lossless, with an audio track."""
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
               "-f", "lavfi", "-i", f"testsrc2=size={size}:rate={rate}:duration={seconds}"]
    if audio:
        command += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}", "-c:a", "aac"]
    command += ["-c:v", "libx264", "-crf", "12", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(path)]
    subprocess.run(command, check=True)
    return path


def _probe(data: bytes, tmp_path: Path, name: str) -> dict[str, Any]:
    file = tmp_path / name
    file.write_bytes(data)
    output = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,codec_name,width,height,r_frame_rate",
         "-show_entries", "format=duration", "-of", "json", str(file)],
        check=True, capture_output=True,
    ).stdout
    return json.loads(output)


async def _upload(client: AsyncClient, case_id: str, data: bytes, headers: dict[str, str] | None = None) -> httpx.Response:
    return await client.post(
        f"/internal/cases/{case_id}/clip",
        content=data,
        headers={"Content-Type": "video/mp4", **(INTERNAL_HEADERS if headers is None else headers)},
    )


@needs_ffmpeg
async def test_clip_is_compressed_and_a_record_image_is_made(
    client: AsyncClient, detection_case: dict[str, Any], storage: FakeStorage,
    admin_conn: asyncpg.Connection, tmp_path: Path,
) -> None:
    source = _make_video(tmp_path / "raw.mp4", seconds=8).read_bytes()
    response = await _upload(client, detection_case["id"], source)
    assert response.status_code == 201, response.text
    body = response.json()

    clip_path = next(path for path in storage.objects if path.startswith("evidence-clips/"))
    record_path = next(path for path in storage.objects if path.endswith("-record.jpg"))
    video, video_type = storage.objects[clip_path]
    record, record_type = storage.objects[record_path]
    assert (video_type, record_type) == ("video/mp4", "image/jpeg")
    assert clip_path == f"evidence-clips/{ACTIVE_SESSION_ID}/{body['detection_id']}.mp4"

    assert body["original_bytes"] == len(source)
    assert body["stored_bytes"] == len(video) < len(source) / 5, "re-encode must shrink a heavy source substantially"
    info = _probe(video, tmp_path, "stored.mp4")
    streams = info["streams"]
    assert [s["codec_type"] for s in streams] == ["video"], "audio must be stripped"
    assert streams[0]["codec_name"] == "h264"
    assert streams[0]["width"] == settings.clip_max_width
    assert streams[0]["r_frame_rate"] == f"{settings.clip_fps}/1"
    assert abs(float(info["format"]["duration"]) - 8) < 0.5

    assert record[:3] == b"\xff\xd8\xff", "record image must be a JPEG"
    assert _probe(record, tmp_path, "record.jpg")["streams"][0]["width"] == 640  # 2 tiles x 320 px

    row = await admin_conn.fetchrow(
        "SELECT clip_path, clip_bytes, record_image_path, clip_uploaded_at FROM detection_events WHERE id = $1",
        body["detection_id"],
    )
    assert (row["clip_path"], row["clip_bytes"], row["record_image_path"]) == (clip_path, len(video), record_path)
    assert await admin_conn.fetchval("SELECT count(*) FROM audit_log WHERE action = 'clip_stored'") == 1

    duplicate = await _upload(client, detection_case["id"], source)
    assert duplicate.status_code == 409


@needs_ffmpeg
async def test_small_clip_is_never_upscaled(
    client: AsyncClient, detection_case: dict[str, Any], storage: FakeStorage, tmp_path: Path
) -> None:
    source = _make_video(tmp_path / "small.mp4", seconds=2, size="320x240", audio=False).read_bytes()
    assert (await _upload(client, detection_case["id"], source)).status_code == 201
    video = next(data for path, (data, _) in storage.objects.items() if path.endswith(".mp4"))
    assert _probe(video, tmp_path, "out.mp4")["streams"][0]["width"] == 320


@needs_ffmpeg
@pytest.mark.parametrize(("seconds", "limit"), [(0.5, None), (8, 3.0)])
async def test_clip_duration_limits(
    client: AsyncClient, detection_case: dict[str, Any], storage: FakeStorage, tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch, seconds: float, limit: float | None,
) -> None:
    if limit is not None:
        monkeypatch.setattr(settings, "clip_max_seconds", limit)
    source = _make_video(tmp_path / "clip.mp4", seconds=seconds, audio=False).read_bytes()
    response = await _upload(client, detection_case["id"], source)
    assert response.status_code == 422
    assert storage.objects == {}


@pytest.mark.parametrize(
    "payload",
    [
        b"#EXTM3U\n#EXT-X-TARGETDURATION:10\n#EXTINF:10,\nhttp://169.254.169.254/latest/meta-data\n",
        b"ffconcat version 1.0\nfile '/etc/passwd'\n",
        b"\x00\x00\x00\x18ftypisom" + b"\x00" * 64,  # MP4 header, no decodable content
        b"plain text, not a video",
    ],
)
async def test_non_video_and_playlist_uploads_are_rejected(
    client: AsyncClient, detection_case: dict[str, Any], storage: FakeStorage, payload: bytes
) -> None:
    if payload.startswith(b"\x00\x00\x00\x18ftyp") and shutil.which("ffprobe") is None:
        pytest.skip("ffprobe needed to reject undecodable MP4s")
    response = await _upload(client, detection_case["id"], payload)
    assert response.status_code == 422
    assert storage.objects == {}


async def test_upload_limits_and_auth(
    client: AsyncClient, detection_case: dict[str, Any], storage: FakeStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert (await _upload(client, detection_case["id"], b"x" * 10, headers={})).status_code == 401
    assert (await _upload(client, str(uuid.uuid4()), b"x" * 10)).status_code == 404
    assert (await _upload(client, detection_case["id"], b"")).status_code == 422
    monkeypatch.setattr(settings, "clip_max_upload_bytes", 1024)
    assert (await _upload(client, detection_case["id"], b"\x00" * 4096)).status_code == 413


async def _attach_clip(admin_conn: asyncpg.Connection, detection_id: str, session_id: str = ACTIVE_SESSION_ID) -> None:
    await admin_conn.execute(
        """
        UPDATE detection_events
        SET clip_path = $2, clip_bytes = 180000, clip_duration_seconds = 9.8, clip_uploaded_at = now(),
            record_image_path = $3
        WHERE id = $1
        """,
        detection_id,
        f"evidence-clips/{session_id}/{detection_id}.mp4",
        f"snapshots/{session_id}/{detection_id}-record.jpg",
    )


async def _detection_id(admin_conn: asyncpg.Connection, case_id: str) -> str:
    return str(await admin_conn.fetchval("SELECT detection_event_id FROM cases WHERE id = $1", case_id))


@pytest_asyncio.fixture
async def other_teacher(admin_conn: asyncpg.Connection) -> str:
    await admin_conn.execute(
        """
        INSERT INTO users (full_name, email, password_hash, role, registration_or_employee_no, status, email_verified)
        SELECT 'Sana Naqvi', $1, password_hash, 'teacher', 'EMP-1005', 'active', true FROM users WHERE email = $2
        """,
        OTHER_TEACHER_EMAIL,
        TEACHER_EMAIL,
    )
    return OTHER_TEACHER_EMAIL


async def test_reviewers_get_signed_urls_and_others_do_not(
    client: AsyncClient, detection_case: dict[str, Any], storage: FakeStorage,
    admin_conn: asyncpg.Connection, other_teacher: str,
) -> None:
    case_id = detection_case["id"]
    detection_id = await _detection_id(admin_conn, case_id)

    teacher = await login(client, TEACHER_EMAIL)
    pending = (await client.get(f"/api/cases/{case_id}/media", headers=bearer(teacher))).json()
    assert pending["clip_status"] == "pending_upload"
    assert pending["clip"] is None and pending["record_image_url"] is None
    assert pending["snapshot_url"].startswith("https://signed.test/snapshots/")

    await _attach_clip(admin_conn, detection_id)
    for email in (TEACHER_EMAIL, HOD_EMAIL):
        media = (await client.get(f"/api/cases/{case_id}/media", headers=bearer(await login(client, email)))).json()
        assert media["clip_status"] == "available"
        assert media["clip"]["url"] == f"https://signed.test/evidence-clips/{ACTIVE_SESSION_ID}/{detection_id}.mp4?ttl=300"
        assert media["clip"]["duration_seconds"] == 9.8 and media["clip"]["size_bytes"] == 180000
        assert media["record_image_url"].endswith(f"{detection_id}-record.jpg?ttl=300")

    by_detection = await client.get(f"/api/detections/{detection_id}/media", headers=bearer(teacher))
    assert by_detection.json()["case_id"] == case_id

    other = await login(client, other_teacher)
    assert (await client.get(f"/api/cases/{case_id}/media", headers=bearer(other))).status_code == 404
    for email in (STUDENT_A_EMAIL, ADMIN_EMAIL, CONTROLLER_EMAIL):
        response = await client.get(f"/api/cases/{case_id}/media", headers=bearer(await login(client, email)))
        assert response.status_code == 403
    assert await admin_conn.fetchval("SELECT count(*) FROM audit_log WHERE action = 'evidence_media_viewed'") == 4


async def _case_with_clip(
    admin_conn: asyncpg.Connection, seat: int, status: str, *, age_hours: float, penalty_age_days: float | None = None
) -> str:
    detection_id = str(await admin_conn.fetchval(
        """
        INSERT INTO detection_events (session_id, seat_number, behaviour_types, per_signal, composite_score,
                                      snapshot_path, detected_at)
        VALUES ($1, $2, ARRAY['PHONE_DETECTED'], '{"PHONE_DETECTED": 0.9}', 0.9, $3, now())
        RETURNING id
        """,
        ACTIVE_SESSION_ID, seat, f"snapshots/{ACTIVE_SESSION_ID}/seat-{seat}.jpg",
    ))
    await _attach_clip(admin_conn, detection_id)
    case_id = await admin_conn.fetchval(
        """
        INSERT INTO cases (session_id, seat_number, reference_no, status, detection_event_id, updated_at)
        VALUES ($1, $2, $3, $4, $5, now() - make_interval(secs => $6))
        RETURNING id
        """,
        ACTIVE_SESSION_ID, seat, f"AU-CS-INT-2026-7{seat:02d}", status, detection_id, age_hours * 3600,
    )
    if penalty_age_days is not None:
        await admin_conn.execute(
            """
            INSERT INTO penalties (case_id, penalty_type, description, issued_by, notice_reference, created_at)
            SELECT $1, 'formal_warning', 'Warning.', id, 'ref', now() - make_interval(days => $2)
            FROM users WHERE email = $3
            """,
            case_id, int(penalty_age_days), HOD_EMAIL,
        )
    return detection_id


async def test_clips_are_deleted_only_once_review_is_final(
    client: AsyncClient, active_session: str, admin_conn: asyncpg.Connection, storage: FakeStorage  # noqa: F811
) -> None:
    grace, window = settings.clip_grace_hours_after_dismissal, settings.appeal_window_days
    final = {
        await _case_with_clip(admin_conn, 1, "dismissed", age_hours=grace + 1),
        await _case_with_clip(admin_conn, 2, "confirmed", age_hours=1, penalty_age_days=window + 1),
    }
    kept = {
        await _case_with_clip(admin_conn, 3, "dismissed", age_hours=grace - 1),
        await _case_with_clip(admin_conn, 4, "confirmed", age_hours=1, penalty_age_days=window - 1),
        await _case_with_clip(admin_conn, 5, "confirmed", age_hours=24 * 60),  # no penalty yet
        await _case_with_clip(admin_conn, 6, "pending_review", age_hours=24 * 60),
        await _case_with_clip(admin_conn, 7, "escalated", age_hours=24 * 60),
    }

    assert await retention.purge_finalized_clips(admin_conn, storage) == 2
    assert sorted(storage.deleted) == sorted(f"evidence-clips/{ACTIVE_SESSION_ID}/{d}.mp4" for d in final)
    rows = await admin_conn.fetch("SELECT id, clip_purged_at, record_image_path FROM detection_events")
    purged = {str(r["id"]) for r in rows if r["clip_purged_at"] is not None}
    assert purged == final
    assert all(r["record_image_path"] for r in rows if str(r["id"]) in final), "record image must survive"
    assert await retention.purge_finalized_clips(admin_conn, storage) == 0
    assert kept.isdisjoint(purged)

    detection_id = next(iter(final))
    hod = await login(client, HOD_EMAIL)
    media = (await client.get(f"/api/detections/{detection_id}/media", headers=bearer(hod))).json()
    assert media["clip_status"] == "deleted_after_review"
    assert media["clip"] is None and media["clip_deleted_at"] is not None
    assert media["record_image_url"].endswith(f"{detection_id}-record.jpg?ttl=300")


async def test_dismissed_evidence_purge_also_removes_the_record_image(
    client: AsyncClient, active_session: str, admin_conn: asyncpg.Connection, storage: FakeStorage  # noqa: F811
) -> None:
    detection_id = await _case_with_clip(
        admin_conn, 9, "dismissed", age_hours=24 * (settings.snapshot_retention_days + 1)
    )
    assert await retention.purge_dismissed_evidence(admin_conn, storage) == 1
    assert sorted(storage.deleted) == sorted([
        f"snapshots/{ACTIVE_SESSION_ID}/seat-9.jpg",
        f"snapshots/{ACTIVE_SESSION_ID}/{detection_id}-record.jpg",
    ])


async def test_storage_client_request_shapes() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if "/object/sign/" in request.url.path:
            return httpx.Response(200, json={"signedURL": "/object/sign/evidence-clips/s/d.mp4?token=abc"})
        return httpx.Response(200, json={})

    storage = SupabaseStorage(
        base_url="https://project.supabase.co/", service_role_key="service-key", transport=httpx.MockTransport(handler)
    )
    await storage.upload("evidence-clips/s/d.mp4", b"video", "video/mp4")
    url = await storage.signed_url("evidence-clips/s/d.mp4", 300)
    await storage.delete(["evidence-clips/s/d.mp4", "snapshots/s/a.jpg", "snapshots/s/b.jpg"])

    upload, sign, delete_clips, delete_snaps = seen
    assert (upload.method, upload.url.path) == ("POST", "/storage/v1/object/evidence-clips/s/d.mp4")
    assert upload.headers["x-upsert"] == "false" and upload.headers["content-type"] == "video/mp4"
    assert upload.headers["authorization"] == "Bearer service-key" and upload.headers["apikey"] == "service-key"
    assert json.loads(sign.content) == {"expiresIn": 300}
    assert url == "https://project.supabase.co/storage/v1/object/sign/evidence-clips/s/d.mp4?token=abc"
    assert (delete_clips.method, delete_clips.url.path) == ("DELETE", "/storage/v1/object/evidence-clips")
    assert json.loads(delete_clips.content) == {"prefixes": ["s/d.mp4"]}
    assert json.loads(delete_snaps.content) == {"prefixes": ["s/a.jpg", "s/b.jpg"]}
