# ProctorAI

AI-powered exam proctoring platform for academic integrity. A ceiling-mounted
camera per exam hall detects five behaviours (gaze deviation, head-pose
violation, lip movement, phone detection, unauthorised objects), and confirmed
incidents follow a real academic-integrity workflow: teacher review → HOD
penalty → automated notice → student appeal.

## Architecture

```
┌─────────────────────────────────────────────┐
│  React + TypeScript + Tailwind (Vite)       │  ← frontend
│  Google Sign-In via Supabase Auth           │
│  Real-time alerts via Socket.IO             │
└───────────────┬─────────────────────────────┘
                │  REST + Socket.IO
┌───────────────▼─────────────────────────────┐
│  FastAPI backend on Railway                 │  ← backend/
│  JWT session cookies (httpOnly, Secure)     │
│  Supabase JWKS token verification           │
└───────────────┬──────────┬──────────────────┘
         ┌──────▼──┐  ┌────▼────┐  ┌──────────┐
         │ Postgres │  │ Redis   │  │ Supabase │
         │ (Supabase)│ │(Upstash)│  │ Storage  │
         └──────────┘  └─────────┘  └──────────┘
```

**Roles:** Admin · HOD · Teacher · Exam Controller · Student

## Login flow

1. User clicks **Sign in with Google** → `@supabase/supabase-js` redirects to
   Google's account picker with `hd` hint.
2. Google redirects back to `/login?code=...`; the Supabase client exchanges the
   PKCE code for an access token.
3. Frontend POSTs the Supabase access token to `POST /api/auth/session`.
4. Backend verifies the token's signature against Supabase's JWKS endpoint,
   checks the email domain server-side, looks up/provisions the user, and sets
   an `httpOnly` session cookie with the app's own JWT.
5. Subsequent requests use the cookie automatically. Session recovery on refresh
   uses `GET /api/auth/me`.

**Student auto-provisioning:** 6-digit local part → auto-created as student on
first sign-in. Staff accounts must be pre-created by an Admin.

## Quick start

### Prerequisites

- Node.js ≥ 18, Docker, Docker Compose

### Frontend

```bash
# Install dependencies
npm install

# Copy and fill in environment variables
cp .env.example .env.local
# Edit .env.local:
#   VITE_API_BASE_URL=http://localhost:8000  (or leave empty if using Vercel rewrites)
#   VITE_SUPABASE_URL=https://<project-ref>.supabase.co
#   VITE_SUPABASE_ANON_KEY=<your-anon-key>
#   VITE_ALLOWED_EMAIL_DOMAIN=students.au.edu.pk

# Start dev server
npm run dev
```

### Backend

```bash
cd backend

# Copy and fill in environment variables
cp .env.example .env

# Start all services (Postgres, Redis, API)
docker compose up -d

# Apply schema and seed data
docker compose exec api python -m app.cli db-migrate
docker compose exec api python -m app.cli db-seed

# API is now at http://localhost:8000
# Swagger docs at http://localhost:8000/docs
```

### Pointing the frontend at a different backend

Set `VITE_API_BASE_URL` in `.env.local`:

```bash
# Local backend
VITE_API_BASE_URL=http://localhost:8000

# Staging on Railway
VITE_API_BASE_URL=https://proctorai-staging.up.railway.app

# Production via Vercel rewrites (cookie is first-party)
VITE_API_BASE_URL=
```

When `VITE_API_BASE_URL` is empty, the frontend assumes same-origin (Vercel
rewrites `/api/*` and `/socket.io/*` to the backend).

## Running tests

The backend has a comprehensive `pytest` integration suite (252 tests) that
covers: authentication (Google token verification, auto-provisioning, staff
rejection, re-link prevention), the full case lifecycle (detection → triage →
confirmation → penalty → appeal), role-based access control for all five roles,
the detection pipeline with cooldowns, and evidence media compression/storage.

```bash
cd backend

# Run the full suite (uses a test database in Docker; no external API calls)
docker compose --profile test run --rm tests pytest -q

# Run a specific test file
docker compose --profile test run --rm tests pytest tests/test_case_workflow.py -v

# Run with coverage
docker compose --profile test run --rm tests pytest --cov=app --cov-report=term-missing
```

The Anthropic API call for penalty-notice generation is mocked in tests — the
suite is free and repeatable with no external dependencies.

## Available commands

| Command | Description |
|---|---|
| `npm install` | Install frontend dependencies |
| `npm run dev` | Start Vite dev server |
| `npm run build` | Production build |
| `npm run lint` | Run Oxlint |
| `docker compose up -d` | Start backend + infra |
| `docker compose --profile test run --rm tests pytest -q` | Run backend test suite |

## Tech stack

- **Frontend:** Vite · React 18 · TypeScript · Tailwind CSS · React Router ·
  React Three Fiber + drei · Recharts · Socket.IO client
- **Backend:** FastAPI · asyncpg · python-socketio · Pydantic
- **Infrastructure:** Supabase (Postgres + Auth + Storage) · Upstash (Redis) ·
  Railway (API hosting)
