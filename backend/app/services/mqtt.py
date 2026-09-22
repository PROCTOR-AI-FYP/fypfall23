"""Persistent MQTT connection to HiveMQ Cloud.

Topics (one prefix per room so each device credential needs one filter):
  proctorai/rooms/{room}/heartbeat  device -> backend, JSON Heartbeat
  proctorai/rooms/{room}/alerts     backend -> device, JSON alert

HiveMQ Cloud Serverless (free tier, 100 connections) allows exactly one
permission per credential, scoped to one topic filter, and no finer ACLs:
  proctorai_backend  Publish and Subscribe on  proctorai/#
  proctorai_esp32    Publish and Subscribe on  proctorai/rooms/<room-slug>/#
So a device credential can still publish to its own room's alerts topic or
send junk heartbeats. The backend compensates: it subscribes only to
heartbeat topics, accepts nothing but a small, strictly validated heartbeat
payload, and never acts on anything received over MQTT beyond recording
the device's last-seen time.

Publishes that fail while disconnected go to a capped Redis outbox and are
replayed, in order, on reconnect.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
import ssl
import uuid
from datetime import datetime, timezone
from typing import Any

import aiomqtt
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from redis.exceptions import RedisError

from app.config import settings
from app.redis_client import get_redis

logger = logging.getLogger("proctorai.mqtt")

TOPIC_ROOT = "proctorai/rooms"
HEARTBEAT_SUBSCRIPTION = f"{TOPIC_ROOT}/+/heartbeat"
HEARTBEAT_TOPIC_RE = re.compile(r"^proctorai/rooms/([a-z0-9-]{1,64})/heartbeat$")
MAX_HEARTBEAT_BYTES = 512
DEVICE_LAST_SEEN_TTL_SECONDS = 120

OUTBOX_KEY = "mqtt:outbox"
OUTBOX_MAX_LENGTH = 1000
OUTBOX_DRAIN_BATCH = 100
PUBLISH_TIMEOUT_SECONDS = 5.0
KEEPALIVE_SECONDS = 30
RECONNECT_BACKOFF_MAX_SECONDS = 60.0


class InsecureMqttTransportError(RuntimeError):
    """Raised when TLS is required but the broker connection is plaintext."""


class Heartbeat(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    uptime_s: int = Field(ge=0)
    rssi: int | None = Field(default=None, ge=-150, le=0)


def room_slug(room: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", room.lower()).strip("-")[:64] or "unassigned"


def alert_topic(room: str) -> str:
    return f"{TOPIC_ROOT}/{room_slug(room)}/alerts"


def device_last_seen_key(room: str) -> str:
    return f"device:{room}:last_seen"


class MqttService:
    def __init__(self) -> None:
        self._client: aiomqtt.Client | None = None
        self._task: asyncio.Task[None] | None = None
        self._first_attempt_done = asyncio.Event()
        self._fatal_error: InsecureMqttTransportError | None = None

    @property
    def connected(self) -> bool:
        return self._client is not None

    async def start(self) -> None:
        """Start the connection loop; raises only if the broker link is insecure."""
        if not settings.mqtt_enabled:
            logger.info("mqtt disabled (MQTT_ENABLED=false)")
            return
        self._task = asyncio.create_task(self._run(), name="mqtt-client")
        try:
            await asyncio.wait_for(
                self._first_attempt_done.wait(), timeout=settings.mqtt_startup_connect_timeout_seconds
            )
        except TimeoutError:
            logger.warning("mqtt broker not reachable at startup; continuing to retry in the background")
        if self._fatal_error is not None:
            raise self._fatal_error

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    async def publish(self, topic: str, payload: dict[str, Any]) -> bool:
        """Publish at QoS 1; returns False if the message was queued instead."""
        if not settings.mqtt_enabled:
            return False
        data = json.dumps(payload, separators=(",", ":"))
        client = self._client
        if client is not None:
            try:
                await asyncio.wait_for(client.publish(topic, payload=data, qos=1), timeout=PUBLISH_TIMEOUT_SECONDS)
                return True
            except (aiomqtt.MqttError, TimeoutError) as exc:
                logger.warning("mqtt publish failed, queueing: %s", exc)
        await self._enqueue(topic, data)
        return False

    async def _enqueue(self, topic: str, data: str) -> None:
        pipe = get_redis().pipeline(transaction=False)
        pipe.rpush(OUTBOX_KEY, json.dumps({"topic": topic, "payload": data}))
        pipe.ltrim(OUTBOX_KEY, -OUTBOX_MAX_LENGTH, -1)
        try:
            await pipe.execute()
        except RedisError:
            logger.exception("mqtt outbox enqueue failed; alert dropped for topic %s", topic)

    async def _drain_outbox(self, client: aiomqtt.Client) -> None:
        redis = get_redis()
        while True:
            batch = await redis.lpop(OUTBOX_KEY, OUTBOX_DRAIN_BATCH)
            if not batch:
                return
            for index, raw in enumerate(batch):
                entry = json.loads(raw)
                try:
                    await asyncio.wait_for(
                        client.publish(entry["topic"], payload=entry["payload"], qos=1),
                        timeout=PUBLISH_TIMEOUT_SECONDS,
                    )
                except (aiomqtt.MqttError, TimeoutError):
                    # Put the unsent tail back at the head, preserving order.
                    await redis.lpush(OUTBOX_KEY, *reversed(batch[index:]))
                    raise

    def _tls_context(self) -> ssl.SSLContext | None:
        # HiveMQ Cloud presents a publicly trusted certificate: the default
        # context (system CAs + hostname verification) is sufficient.
        return ssl.create_default_context() if settings.mqtt_use_tls else None

    @staticmethod
    def _assert_tls(client: aiomqtt.Client) -> str | None:
        if not settings.mqtt_use_tls:
            return None
        # aiomqtt exposes no public accessor for the transport; _client is the
        # underlying paho client, whose socket() is an SSLSocket under TLS.
        sock = client._client.socket()
        if not isinstance(sock, ssl.SSLSocket):
            raise InsecureMqttTransportError("MQTT_USE_TLS is set but the broker connection is not encrypted.")
        return sock.version()

    async def _run(self) -> None:
        backoff = 1.0
        while True:
            try:
                async with aiomqtt.Client(
                    hostname=settings.mqtt_host,
                    port=settings.mqtt_port,
                    username=settings.mqtt_username or None,
                    password=settings.mqtt_password or None,
                    identifier=f"proctorai-backend-{uuid.uuid4().hex[:8]}",
                    keepalive=KEEPALIVE_SECONDS,
                    tls_context=self._tls_context(),
                ) as client:
                    tls_version = self._assert_tls(client)
                    logger.info("mqtt connected host=%s tls=%s", settings.mqtt_host, tls_version or "none")
                    self._client = client
                    self._first_attempt_done.set()
                    backoff = 1.0
                    await client.subscribe(HEARTBEAT_SUBSCRIPTION, qos=1)
                    await self._drain_outbox(client)
                    async for message in client.messages:
                        await self._handle_message(str(message.topic), message.payload)
            except InsecureMqttTransportError as exc:
                logger.critical("%s Refusing to use this broker connection.", exc)
                self._fatal_error = exc
                self._first_attempt_done.set()
                return
            except (aiomqtt.MqttError, RedisError) as exc:
                logger.warning("mqtt connection lost: %s; reconnecting in %.0fs", exc, backoff)
                self._first_attempt_done.set()
            finally:
                self._client = None
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, RECONNECT_BACKOFF_MAX_SECONDS)

    async def _handle_message(self, topic: str, payload: object) -> None:
        match = HEARTBEAT_TOPIC_RE.match(topic)
        if match is None or not isinstance(payload, (bytes, bytearray)) or len(payload) > MAX_HEARTBEAT_BYTES:
            logger.warning("mqtt message rejected: unexpected topic or payload on %r", topic)
            return
        try:
            Heartbeat.model_validate_json(payload)
        except ValidationError:
            logger.warning("mqtt heartbeat rejected: invalid payload on %r", topic)
            return
        await get_redis().set(
            device_last_seen_key(match.group(1)),
            datetime.now(timezone.utc).isoformat(),
            ex=DEVICE_LAST_SEEN_TTL_SECONDS,
        )


mqtt_service = MqttService()
