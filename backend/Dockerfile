# base: Python deps + ffmpeg (evidence clip compression)
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

# test: `docker compose --profile test run --rm tests`
FROM base AS test
COPY requirements-dev.txt .
RUN pip install -r requirements-dev.txt
COPY . .
CMD ["pytest", "-p", "no:cacheprovider"]

# runtime: what Railway builds (last stage)
FROM base AS runtime
COPY app ./app
COPY templates ./templates

RUN useradd --system --uid 10001 --no-create-home proctorai
USER proctorai

# Railway injects PORT. X-Forwarded-For is parsed by the app itself
# (TRUSTED_PROXY_HOPS), so uvicorn's own proxy-header handling stays off.
CMD ["sh", "-c", "exec uvicorn app.main:asgi_app --host 0.0.0.0 --port ${PORT:-8000} --no-server-header --no-proxy-headers"]
