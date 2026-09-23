"""Redis client (Upstash in production) and transport verification.

Upstash plan choice (re-derive only if the deployment shape changes):
Upstash's pay-as-you-go tier bills every command, including each command
inside a pipeline; pipelining saves round trips, not billed commands. The
detection buffer (app/services/detection.py) issues ~3 commands per seat per
signal per frame. One 40-seat room x 5 signals x 6 FPS is roughly 3,600
commands/s, about 39M per 3-hour exam, which is ~$78 per exam at $0.20/100K.
The Fixed 250MB plan ($10/month) has no per-command billing and a 10,000
commands/s ceiling, so it covers one or two concurrent rooms. Past that,
move the per-frame buffer update into a single EVALSHA (Upstash bills a
script call as one command) instead of buying a bigger plan.
"""
from __future__ import annotations

import logging
import ssl

import redis.asyncio as redis

from app.config import settings

logger = logging.getLogger("proctorai.redis")

_client: redis.Redis | None = None


class InsecureRedisTransportError(RuntimeError):
    """Raised when TLS is required but the live connection is not encrypted."""


def init_redis() -> redis.Redis:
    global _client
    if _client is None:
        # from_url picks SSLConnection for rediss:// and verifies the server
        # certificate against the system CA store by default.
        _client = redis.from_url(settings.redis_url, decode_responses=True, health_check_interval=30)
    return _client


async def close_redis() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def get_redis() -> redis.Redis:
    if _client is None:
        raise RuntimeError("Redis client not initialized; call init_redis() at startup.")
    return _client


async def negotiated_tls_version(client: redis.Redis) -> str | None:
    """Return the TLS version of a live pooled connection, or None if plaintext."""
    pool = client.connection_pool
    connection = await pool.get_connection()
    try:
        await connection.connect()
        # redis-py exposes no public accessor for the transport; _writer is the
        # asyncio StreamWriter every connection class uses.
        writer = getattr(connection, "_writer", None)
        ssl_object = writer.get_extra_info("ssl_object") if writer is not None else None
        if isinstance(ssl_object, (ssl.SSLObject, ssl.SSLSocket)):
            return ssl_object.version()
        return None
    finally:
        await pool.release(connection)


async def verify_redis_transport() -> None:
    """Ping Redis and, when TLS is required, fail startup if it isn't in use."""
    client = get_redis()
    await client.ping()
    tls_version = await negotiated_tls_version(client)
    if settings.require_redis_tls and tls_version is None:
        raise InsecureRedisTransportError("REQUIRE_REDIS_TLS is set but the Redis connection is not encrypted.")
    logger.info("redis connected tls=%s", tls_version or "none")
