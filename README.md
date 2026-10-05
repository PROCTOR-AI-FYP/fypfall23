# ProctorAI

Exam proctoring with Google sign-in and five institutional roles. The current
local camera integration detects phones and books and monitors calibrated head
pose. Alerts are attributed to a registered exam seat and enter the existing
teacher review → HOD decision → penalty → student appeal workflow.

## Current local website

The default website is the authenticated role-based platform. It runs
`app.main:asgi_app` from `backend/`, with the React frontend on port 5173.
The standalone SQLite camera milestone remains available in `backend/main.py`.

First-time Windows setup (tested with Node 24 and Python 3.14):

```powershell
npm ci
python -m venv venv
.\venv\Scripts\python.exe -m pip install -r ai-engine/requirements.txt -r backend/requirements.txt
.\venv\Scripts\python.exe ai-engine/prepare_models.py
# Configure backend/.env and frontend Supabase settings; see the guide below.
.\scripts\start-local.ps1
```

Open **http://127.0.0.1:5173/** and sign in with the institutional Google account.
The launcher enables the local camera and adds exact localhost/127.0.0.1 origins
without disabling CSRF protection. `/api` and `/socket.io` use the same-origin
Vite proxy; set `VITE_API_BASE_URL=` for local development.

A Controller schedules an exam and assigns its Teacher. Students must have
signed in; the Teacher uploads a resolved seat CSV, starts the exam, opens
**Live Monitor**, selects the registered student seat and starts the camera.
Set the neutral head pose in normal exam posture. The camera handles **one
clearly visible student at a time**, rather than automatic full-hall attribution.

**CSV Imports** automates setup from the supplied templates: Admins can upload
student rosters, classroom inventory, exam schedules and invigilator assignments
together. Exam Controllers can upload schedules and assignments. Preview checks
every row and its links; importing saves the entire valid batch together, skips
exact matches and refreshes the connected portals. Teachers keep the seat-map
upload workflow, with reusable templates and a seat generator on Session Setup.

See [the local platform guide](backend/LOCAL_PLATFORM.md) for roles, live updates,
evidence, operational limits and validation. Model weights, private captures,
local evidence, environments and checkpoints are excluded from Git.

## Platform architecture

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
#   VITE_API_BASE_URL=  (Vite's local proxy / Vercel rewrites)
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
# Local backend (same-origin Vite proxy)
VITE_API_BASE_URL=
# Optional when the local API uses another port:
# PROCTORAI_API_PROXY_TARGET=http://127.0.0.1:8001

# Staging on Railway
VITE_API_BASE_URL=https://proctorai-staging.up.railway.app

# Production via Vercel rewrites (cookie is first-party)
VITE_API_BASE_URL=
```

When `VITE_API_BASE_URL` is empty, the frontend uses same-origin requests (Vite
proxies them locally; Vercel rewrites them in production). Development also
routes older `http://localhost:8000` / `http://127.0.0.1:8000` settings through
Vite, preserving a custom API port. Production API addresses remain explicit.

If sign-in briefly shows a dashboard and returns to login, check that the
browser retains the app's httpOnly session cookie. Local setups should use
`VITE_API_BASE_URL=`, `SESSION_COOKIE_SECURE=false`,
`SESSION_COOKIE_SAMESITE=lax` and an empty `SESSION_COOKIE_DOMAIN`. Restart
services after environment changes and use one website address throughout the
Google round trip. Production requires its existing HTTPS cookie protections.
Sign-in now checks `/api/auth/me` before opening a role portal, so a rejected
cookie produces a sign-in error rather than a dashboard flash. During an OAuth
callback, an old account cookie is not used to open its previous portal while
the new sign-in is still being confirmed.

## Running tests

Run the frontend session-cookie, role confirmation and local API routing checks
with `npm run test:auth` (Node 24). These checks use test accounts and do not
connect to Google or modify the configured database.

The backend has a comprehensive `pytest` integration suite (including the camera integration checks) that
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

- **Frontend:** Vite · React 19 · TypeScript · Tailwind CSS · React Router ·
  React Three Fiber + drei · Recharts · Socket.IO client
- **Backend:** FastAPI · asyncpg · python-socketio · Pydantic
- **Infrastructure:** Supabase (Postgres + Auth + Storage) · Upstash (Redis) ·
  Railway (API hosting)
