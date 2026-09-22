"""FastAPI application entrypoint.

`app` is the FastAPI instance (used directly by the tests); `asgi_app` wraps
it with Socket.IO and is what uvicorn serves in production. Socket.IO
forwards lifespan events to FastAPI because no Socket.IO startup hooks are
registered.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import socketio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings, validate_settings
from app.db import close_pool, init_pool
from app.redis_client import close_redis, init_redis, verify_redis_transport
from app.routers import admin_users, auth, cases, internal, media, sessions
from app.services.mqtt import mqtt_service
from app.services.media import ffmpeg_available
from app.services.retention import run_retention_loop
from app.services.storage import get_storage, storage_configured
from app.sockets import sio

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("proctorai")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    validate_settings(settings)
    await init_pool()
    init_redis()
    background_tasks: list[asyncio.Task[None]] = []
    try:
        await verify_redis_transport()
        await mqtt_service.start()
        if storage_configured():
            background_tasks.append(asyncio.create_task(run_retention_loop(get_storage()), name="evidence-retention"))
        else:
            logger.info("evidence storage and retention disabled (SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY not set)")
        if not ffmpeg_available():
            logger.warning("ffmpeg not found: evidence clip uploads will be rejected")
        yield
    finally:
        for task in background_tasks:
            task.cancel()
        await asyncio.gather(*background_tasks, return_exceptions=True)
        await mqtt_service.stop()
        await close_pool()
        await close_redis()


app = FastAPI(
    title="ProctorAI Backend",
    lifespan=lifespan,
    docs_url=None if settings.is_production else "/docs",
    redoc_url=None,
    openapi_url=None if settings.is_production else "/openapi.json",
)

def cors_options(origins: list[str]) -> dict[str, Any]:
    # Bearer tokens, not cookies, so credentials stay off.
    return {
        "allow_origins": origins,
        "allow_credentials": False,
        "allow_methods": ["GET", "POST", "PATCH", "DELETE"],
        "allow_headers": ["Authorization", "Content-Type"],
        "max_age": 600,
    }


app.add_middleware(CORSMiddleware, **cors_options(settings.cors_origins))

app.include_router(auth.router)
app.include_router(admin_users.router)
app.include_router(sessions.router)
app.include_router(cases.router)
app.include_router(internal.router)
app.include_router(media.internal_router)
app.include_router(media.router)


@app.get("/healthz", include_in_schema=False)
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


asgi_app = socketio.ASGIApp(sio, other_asgi_app=app)
