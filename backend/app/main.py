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
from app.csrf import CSRF_HEADER, CSRFMiddleware
from app.db import close_pool, init_pool
from app.redis_client import close_redis, init_redis, verify_redis_transport
from app.routers import (
    admin_config,
    admin_users,
    appeals,
    auth,
    cases,
    classrooms,
    detections,
    internal,
    media,
    notifications,
    reports,
    schedule,
    sessions,
)
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


from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

app = FastAPI(
    title="ProctorAI Backend",
    lifespan=lifespan,
    docs_url=None if settings.is_production else "/docs",
    redoc_url=None,
    openapi_url=None if settings.is_production else "/openapi.json",
)

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc):
    print(f"OMG 422: {exc.errors()} body: {exc.body}")
    return JSONResponse(status_code=422, content={"detail": exc.errors()})

def cors_options(origins: list[str]) -> dict[str, Any]:
    # The session is an httpOnly cookie, so credentials must be allowed; that
    # is only safe because origins are an exact allowlist (wildcards are
    # refused at startup) and unsafe methods also need the CSRF header.
    return {
        "allow_origins": origins,
        "allow_credentials": True,
        "allow_methods": ["GET", "POST", "PUT", "PATCH", "DELETE"],
        "allow_headers": ["Content-Type", "Accept", CSRF_HEADER],
        "max_age": 600,
    }


# Starlette runs the last-added middleware first: CORS answers preflights
# before the CSRF check sees the request.
app.add_middleware(CSRFMiddleware, allowed_origins=settings.cors_origins)
app.add_middleware(CORSMiddleware, **cors_options(settings.cors_origins))

app.include_router(auth.router)
app.include_router(admin_users.router)
app.include_router(admin_config.router)
app.include_router(classrooms.router)
app.include_router(sessions.router)
app.include_router(schedule.router)
app.include_router(detections.router)
app.include_router(cases.router)
app.include_router(appeals.router)
app.include_router(notifications.router)
app.include_router(reports.router)
app.include_router(internal.router)
app.include_router(media.internal_router)
app.include_router(media.router)


@app.get("/healthz", include_in_schema=False)
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


asgi_app = socketio.ASGIApp(sio, other_asgi_app=app)
