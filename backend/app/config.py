"""Centralized application configuration.

All environment-driven values live here so nothing else in the codebase
reads os.environ directly. `validate_for_production()` is called at startup
and refuses to boot a production process with insecure transport or
placeholder secrets.
"""
from __future__ import annotations

from typing import Literal
from urllib.parse import urlparse

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_JWT_SECRET = "dev-only-jwt-secret-change-me-before-deploying"
DEV_DB_PASSWORD_MARKER = ":app_password@"
MIN_PRODUCTION_SECRET_LENGTH = 32


class InsecureConfigurationError(RuntimeError):
    """Raised at startup when production settings would weaken security."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: Literal["development", "test", "production"] = "development"

    # --- Core institutional rule ---
    allowed_email_domain: str = "students.au.edu.pk"

    # --- Database (Supabase Postgres in production) ---
    database_url: str = "postgresql://app_user:app_password@localhost:5432/proctorai"
    # Owner DSN, used only for applying schema.sql / seed.sql.
    database_admin_url: str = "postgresql://postgres:postgres@localhost:5432/proctorai"
    # Supabase's transaction-mode pooler (port 6543) does not support prepared
    # statements; set to 0 there. Session mode (port 5432) can keep the default.
    db_statement_cache_size: int = 100
    db_pool_max_size: int = 10

    # --- Supabase Storage (detection snapshots) ---
    supabase_url: str = ""
    supabase_service_role_key: str = ""
    supabase_snapshot_bucket: str = "snapshots"
    supabase_clip_bucket: str = "evidence-clips"
    # Evidence of dismissed cases (snapshot + record image) is deleted after this.
    snapshot_retention_days: int = 30
    snapshot_purge_interval_seconds: int = 3600

    # --- Evidence clips ---
    clip_max_upload_bytes: int = 50 * 1024 * 1024
    clip_min_seconds: float = 1.0
    clip_max_seconds: float = 30.0
    clip_max_width: int = 640
    clip_fps: int = 10
    clip_crf: int = 30
    clip_transcode_timeout_seconds: float = 120.0
    clip_max_concurrent_transcodes: int = 2
    # A clip is deleted (record image kept) once review is final: dismissed for
    # this long, or a penalty issued and the appeal window closed.
    clip_grace_hours_after_dismissal: int = 24
    appeal_window_days: int = 14
    media_url_ttl_seconds: int = 300

    # --- Redis (Upstash in production) ---
    redis_url: str = "redis://localhost:6379/0"
    require_redis_tls: bool = False

    # --- MQTT (HiveMQ Cloud in production) ---
    mqtt_enabled: bool = False
    mqtt_host: str = ""
    mqtt_port: int = 8883
    mqtt_use_tls: bool = True
    mqtt_username: str = ""
    mqtt_password: str = ""
    mqtt_startup_connect_timeout_seconds: float = 10.0

    # --- JWT ---
    jwt_secret: str = DEV_JWT_SECRET
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60

    # --- Service-to-service auth for the AI detection worker ---
    internal_api_key: str = ""

    # --- HTTP edge ---
    frontend_url: str = "http://localhost:5173"
    # Comma-separated exact origins. Wildcards are rejected at startup.
    cors_allowed_origins: str = ""
    # Number of reverse proxies in front of the app that append to
    # X-Forwarded-For. Railway's edge is 1. 0 = ignore the header entirely.
    trusted_proxy_hops: int = 0

    # --- Email ---
    email_backend: Literal["console", "smtp"] = "console"
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = Field(default="", validation_alias=AliasChoices("SMTP_PASSWORD", "GMAIL_APP_PASSWORD"))
    smtp_from_address: str = "no-reply@proctorai.local"

    # --- Penalty notice generation ---
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-opus-5"
    anthropic_effort: Literal["low", "medium", "high"] = "medium"
    anthropic_timeout_seconds: float = 120.0

    # --- Password hashing ---
    bcrypt_rounds: int = 12

    # --- Rate limiting ---
    signup_ip_limit: int = 5
    signup_email_limit: int = 3
    signup_rate_limit_window_seconds: int = 3600

    # --- Verification tokens ---
    verification_token_bytes: int = 32
    verification_token_ttl_hours: int = 24

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip().rstrip("/") for origin in self.cors_allowed_origins.split(",") if origin.strip()]

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


def _validate_cors_origins(origins: list[str], *, production: bool) -> None:
    for origin in origins:
        if "*" in origin:
            raise InsecureConfigurationError(f"CORS origin {origin!r} contains a wildcard; list exact origins.")
        parsed = urlparse(origin)
        if parsed.scheme not in {"https", "http"} or not parsed.netloc or parsed.path:
            raise InsecureConfigurationError(f"CORS origin {origin!r} must be scheme://host[:port] with no path.")
        if production and parsed.scheme != "https":
            raise InsecureConfigurationError(f"CORS origin {origin!r} must use https in production.")


def validate_settings(config: Settings) -> None:
    """Fail fast on configuration that would silently weaken security."""
    _validate_cors_origins(config.cors_origins, production=config.is_production)

    if not config.is_production:
        return

    problems: list[str] = []
    if not config.cors_origins:
        problems.append("CORS_ALLOWED_ORIGINS must list the deployed frontend origin(s).")
    if config.jwt_secret == DEV_JWT_SECRET or len(config.jwt_secret) < MIN_PRODUCTION_SECRET_LENGTH:
        problems.append(f"JWT_SECRET must be a random value of at least {MIN_PRODUCTION_SECRET_LENGTH} characters.")
    if len(config.internal_api_key) < MIN_PRODUCTION_SECRET_LENGTH:
        problems.append(f"INTERNAL_API_KEY must be at least {MIN_PRODUCTION_SECRET_LENGTH} characters.")
    if DEV_DB_PASSWORD_MARKER in config.database_url:
        problems.append("DATABASE_URL still uses the development app_user password; run ALTER ROLE app_user PASSWORD.")
    if not config.redis_url.startswith("rediss://") or not config.require_redis_tls:
        problems.append("REDIS_URL must be a rediss:// URL and REQUIRE_REDIS_TLS must be true.")
    if config.mqtt_enabled and (not config.mqtt_use_tls or config.mqtt_port != 8883):
        problems.append("MQTT must use TLS on port 8883 (MQTT_USE_TLS=true, MQTT_PORT=8883).")
    if config.trusted_proxy_hops < 1:
        problems.append("TRUSTED_PROXY_HOPS must be >= 1 behind Railway's proxy, or per-IP rate limits see the proxy IP.")

    if problems:
        raise InsecureConfigurationError("Refusing to start in production:\n- " + "\n- ".join(problems))


settings = Settings()
