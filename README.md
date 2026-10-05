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

# Production via vercel.mjs rewrites (cookie is first-party)
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

### Hosted website and localhost development

The frontend is a Vercel Vite project at the repository root. The FastAPI API
is a separate Railway service built from `/backend` using its Dockerfile.
Keep both services connected to `PROCTOR-AI-FYP/fypfall23`, branch `main`, for
automatic updates. The backend's watch pattern is `/backend/**`, so frontend
changes do not rebuild its Docker image. Railway settings define the root
directory, Dockerfile, health check `/healthz`, and sleeping disabled; the
older `backend/railway.json` is retained for existing setups.

In Vercel Production and Preview, set `PROCTORAI_BACKEND_URL` to the deployed
API's HTTPS origin, leave `VITE_API_BASE_URL` empty, and configure
`VITE_SUPABASE_URL` and `VITE_SUPABASE_ANON_KEY` for the existing Supabase
project. `vercel.mjs` forwards API and Socket.IO paths before the SPA fallback.
The production client uses Socket.IO HTTP long-polling because the external
Vercel rewrite does not preserve WebSocket upgrades. Events are delivered as
they arrive, with the same secure first-party session cookie. Local Vite
development uses WebSocket with polling fallback. Keep the Railway API at one
replica for this setup; multiple replicas require sticky routing for polling.
Authenticated responses are not cached. The configuration refuses an absent,
local, or insecure hosted API target. Private worker endpoints are not proxied
through the website. `.vercelignore` excludes Python services, private files,
local environments, and deliverables from frontend CLI uploads.

In Supabase Authentication URL Configuration, use the canonical hosted origin
as Site URL and add its exact `/login` address, plus
`http://localhost:5173/login` and `http://127.0.0.1:5173/login`, as allowed
redirects. Keep the Google OAuth client's redirect URI pointing to Supabase's
`/auth/v1/callback`. A trusted preview that needs sign-in must have its exact
origin added to the backend's CORS allowlist and its `/login` URL added to
Supabase; building a preview alone does not grant production API access.

The hosted backend uses `APP_ENV=production`, secure host-only cookies with
`SESSION_COOKIE_SAMESITE=lax`, an exact HTTPS CORS origin list, independent
random JWT/internal API secrets, and TLS Redis. Store private database, Redis,
and Supabase service-role credentials only in the backend service. Local
`.env.local` and `backend/.env` remain independent and are never committed.
Continue running `start-local.ps1` for the local camera-enabled platform.

Cloud containers do not have the exam PC's webcam. Keep `LOCAL_CAMERA_ENABLED`
false on the hosted backend. The website now captures the viewing device's
camera with `getUserMedia` over HTTPS (or localhost). Open **Camera check** in
the user menu to try it; all signed-in roles can run this personal check, which
does not save exam evidence or create cases. Allow camera access, face forward,
and click **Set neutral pose**. Recalibrate after a camera change or prolonged
loss of the face. A missing or uncertain face is reported without inventing
angles. Head pose indicates orientation, not eye gaze or proof of cheating.

An assigned teacher can use the same camera in **Live Monitor** during an
active exam after selecting a registered student seat. One student is monitored
per device-camera view. Head pose runs in a browser worker; the preview continues
independently while sampled JPEGs are checked for phones and books by the
existing Grounding DINO detector on Railway. Object boxes are tracked between
server checks for display only. Object checks take seconds on a CPU; this is not
full-frame-rate object inference or a multi-camera classroom deployment.

The authenticated `/api/device-camera/*` routes accept bounded JPEG samples,
verify current role, session and student attribution, and require repeated
server detections before writing private Supabase snapshots into the existing
case, notification and review workflow. Exam head pose is independently verified
by MediaPipe on the server; after neutral calibration, a sustained sideways turn
over 30 degrees or downward tilt over 20 degrees can create its own review alert.
A browser boolean cannot create head evidence. Hold neutral until both browser
and exam verification finish calibrating. Ending the exam, hiding
the tab or stopping the camera releases capture. No microphone is requested.
Runs expire after 90 seconds of inactivity. The current single-replica CPU
backend accepts one model inference at a time; competing cameras retry without
blocking their local previews.

Phone and book boxes retain raw model confidence. Repeated recognitions at the
detector's verified class thresholds (phone .50, book .60) map to a review signal
score of .80; administrators control review sensitivity on that policy scale.
This score is not the probability that a student cheated. Three consecutive
recognitions spanning at least three seconds are required, with gaps up to 30
seconds allowed for hosted CPU inference. Missing recognitions reset the window.
Head and object alerts have independent 30-second cooldowns. Evidence storage
failures are displayed and retried rather than silently discarding detections.

The single API process delivers live events directly to authenticated sockets.
Only assigned teachers and HOD reviewers receive detailed detection events.
All portals reconcile their authorized data every five seconds even if a proxy
leaves a stale socket connected. Admin configures users and policies; Controllers
schedule exams and see reports; Teachers triage their assigned exams; HODs decide
cases and appeals; Students see and appeal only their own cases.

`npm ci` and `npm run build` prepare the same-origin MediaPipe worker and WASM
assets automatically. `public/vision/face_landmarker.task` is the public Google
MediaPipe model; its WASM files come from the pinned `@mediapipe/tasks-vision`
package. The Railway image installs CPU vision dependencies and downloads
`IDEA-Research/grounding-dino-tiny` at revision
`a2bb814dd30d776dcf7e30523b00659f4f141c71` during the build, so the first vision
deployment takes longer. `DEVICE_CAMERA_ENABLED=false` disables browser sample
processing if needed. `DEVICE_CAMERA_MODEL_PATH` can override the model folder;
local development also finds the existing `ai-engine/models/grounding-dino-tiny`
folder automatically. `scripts/prepare-hosted-vision.py` reproduces the bundled
backend detector from the tested local sources. Neither captured images nor
private credentials are committed.

Model and runtime references: [MediaPipe Face Landmarker](https://ai.google.dev/edge/mediapipe/solutions/vision/face_landmarker/web_js),
[MediaPipe license](https://github.com/google-ai-edge/mediapipe/blob/master/LICENSE),
[Grounding DINO model](https://huggingface.co/IDEA-Research/grounding-dino-tiny),
and [Grounding DINO license](https://github.com/IDEA-Research/GroundingDINO/blob/main/LICENSE).

Run `npm run test:vision` for rotation, calibration, sustained-warning and
tracking-loss checks. `backend/tests/test_device_camera.py` exercises capture
permissions, uploads and evidence attribution against disposable test services.

Run `npm run test:deployment` to check hosted API routing and cache policy.

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
