# ProctorAI Backend

FastAPI service for ProctorAI: authentication and role derivation, case
workflow, the detection pipeline (rolling buffers, cooldowns, live alerts),
penalty notices, and snapshot lifecycle. It runs as one always-on container on
Railway, using managed services only:

| Concern | Service | Notes |
|---|---|---|
| Postgres + snapshot storage | Supabase | App connects as the non-owner `app_user` role so RLS applies |
| Redis (rate limits, buffers, cooldowns, Socket.IO pub/sub, MQTT outbox) | Upstash | TLS (`rediss://`), verified at startup |
| MQTT (room devices) | HiveMQ Cloud | TLS on 8883, verified on every connection |
| API hosting | Railway | Dockerfile build, 1 replica, never sleeps, auto-deploy from GitHub |
| Frontend | Vercel | Separate; only its origin is allowed by CORS |

Nothing here needs a laptop, PC, or self-managed VM to stay on. The only
machine that must be powered during an exam is the detection worker driving the
camera, which is outside this repo.

## Rollback

- **Whole backend:** delete `backend/`. Nothing outside it depends on it.
- **Before evidence clips:** unzip `../.backups/backend-2026-09-23-pre-clips.zip`
  over `backend/` (and `../.backups/frontend-src-2026-09-23-pre-clips.zip` over `src/`).
- **Back to the pre-migration backend** (auth-only, local Redis): unzip
  `../.backups/backend-phase2b-2026-09-23.zip` over `backend/`.
- **Database:** every schema change is additive (`ADD COLUMN IF NOT EXISTS`,
  new tables), so the previous code still runs against the new schema.

## Layout

```
app/
  main.py            FastAPI app + lifespan; asgi_app wraps it with Socket.IO
  config.py          all settings; production refuses insecure config at startup
  sockets.py         Socket.IO server (JWT auth, per-session room authorization)
  routers/           auth, admin_users, sessions (seat map), cases, internal (worker)
  services/
    detection.py     pipelined rolling buffers, triggering, cooldowns
    mqtt.py          HiveMQ connection, heartbeat validation, Redis outbox
    snapshots.py     hourly purge of long-dismissed snapshots from Supabase Storage
    notices.py       penalty notice via the Claude API (one call) + template fallback
    case_workflow.py case status state machine
db/schema.sql        idempotent schema (apply with the owner role)
scripts/             verify_deployment.py (live checks), dev_redis_server.py (tests without Docker)
```

## Endpoints

| Method | Path | Who |
|---|---|---|
| POST | `/api/auth/signup`, `/verify-email`, `/resend-verification`, `/login` | public |
| POST | `/api/admin/users` | Admin |
| POST | `/api/sessions/{id}/seatmap` | Admin, Exam Controller |
| GET | `/api/cases` | students: own cases; teachers: their sessions; others: all |
| POST | `/api/cases/{id}/transitions` | Teacher (own session, pending) / HOD |
| POST, GET | `/api/cases/{id}/penalty` | HOD |
| POST | `/internal/frames`, `/internal/detections` | detection worker (`X-Internal-Api-Key`) |
| POST | `/internal/cases/{id}/clip` | detection worker; raw video body (`Content-Type: video/mp4`) |
| GET | `/api/cases/{id}/media`, `/api/detections/{id}/media` | HOD; Teacher who invigilated the session |
| GET | `/healthz` | public, returns `{"status":"ok"}` only |
| WS | `/socket.io/` | staff with a JWT; emit `join_session` to receive `detection:new` |

## Evidence clips

1. After `POST /internal/detections` returns the case, the worker sends the
   clip as the raw request body to `POST /internal/cases/{case_id}/clip`
   (MP4/MOV/MKV/WebM/AVI, 1–30 s, up to 50 MB).
2. The backend re-encodes it with ffmpeg to H.264, at most 640 px wide, 10 fps,
   no audio, no metadata, streamable MP4: typically a few hundred KB for 10
   seconds. It also makes a 2x2 contact-sheet JPEG from the clip, the **record
   image**. The clip goes to the private `evidence-clips` bucket and the record
   image to `snapshots`; only the paths go in Postgres.
3. The HOD and the invigilating teacher get 5-minute signed URLs from
   `GET /api/cases/{id}/media`. Video streams straight from Supabase's CDN,
   not through Railway, and every view is audit-logged.
4. Once the review is final, the hourly retention job deletes the clip and
   keeps the record image. Final means dismissed for 24 h, or a penalty issued
   and the 14-day appeal window closed. Pending, escalated, and
   confirmed-without-penalty cases keep their clip. The rule is one SQL
   predicate, `REVIEW_FINAL_SQL` in `app/services/retention.py`.

Clips are kept in object storage rather than in Postgres. Video in a database
bloats backups and costs roughly 6× more per GB on Supabase. Object storage
also serves range requests, which is what lets a browser seek inside a video.

## Deploying

### 1. Supabase

1. Create the project. In **Settings → Data API**, turn the Data API off; this
   backend never uses it. (`schema.sql` also revokes every grant from `anon` and
   `authenticated` as a second layer.)
2. Apply the schema as the `postgres` user (SQL editor, or `psql` with the
   direct connection string):
   `psql "<owner connection string>" -f db/schema.sql`
3. Give the app role a real password: `ALTER ROLE app_user PASSWORD '<random 32+ chars>';`
4. `DATABASE_URL` = the **Session pooler** string with user `app_user.<project-ref>`
   and that password. (If you use the Transaction pooler on port 6543, also set
   `DB_STATEMENT_CACHE_SIZE=0`.)
5. Storage: create two **private** buckets, `snapshots` and `evidence-clips`.
   The worker uploads trigger snapshots to `snapshots/<session_id>/<file>.jpg`;
   the backend writes clips and record images itself.
6. Free-tier Supabase projects pause after a period of inactivity. For a live
   pilot, use a paid plan or confirm the pause policy; a paused database takes
   the whole system down.

### 2. Upstash

Create one Redis database in the region closest to the Railway service. Use the
**Fixed 250MB** plan, not pay-as-you-go: the detection buffers generate about 3,600
commands/s per 40-seat room during an exam, and pay-as-you-go bills every
pipelined command (~$78 per 3-hour exam). The fixed plan has no per-command
billing, with a 10,000 commands/s ceiling (one or two concurrent rooms). The full
reasoning is in `app/redis_client.py`. Copy the `rediss://` URL into `REDIS_URL`.

### 3. HiveMQ Cloud

Create a Serverless (free) cluster. The free tier allows 100 connections: this
system uses 1 (backend) + 1 per room device + ad hoc tooling. Credentials, one
permission each:

| Username | Permission | Topic filter |
|---|---|---|
| `proctorai_backend` | Publish and Subscribe | `proctorai/#` |
| `proctorai_esp32` (one per room is better) | Publish and Subscribe | `proctorai/rooms/<room-slug>/#` |

The free tier has no finer ACLs, so the backend treats everything it receives as
untrusted (see `app/services/mqtt.py`). The room slug is the session's room name,
lowercased, with non-alphanumerics replaced by `-` (`Hall A` → `hall-a`).

### 4. Railway

1. New service from the GitHub repo. Set **Root Directory** to `backend`. If
   Railway doesn't pick up `railway.json` automatically, set the config file path
   to `/backend/railway.json`.
2. `railway.json` fixes the Dockerfile build, `/healthz` health check,
   1 replica, `sleepApplication: false`, and restart on failure. In the dashboard,
   confirm **Serverless / App Sleeping** is off and replicas = 1.
3. Enable auto-deploy on pushes to `main`.
4. Set every variable from `.env.example` under **Variables**, including
   `APP_ENV=production`, `REQUIRE_REDIS_TLS=true`, `MQTT_ENABLED=true`,
   `TRUSTED_PROXY_HOPS=1`, and `CORS_ALLOWED_ORIGINS=<your Vercel production URL>`.
   Leave `DATABASE_ADMIN_URL` unset. With `APP_ENV=production`, the app refuses
   to start if any transport or secret is insecure. The deploy then fails its
   health check and the previous version keeps serving.
5. Check `TRUSTED_PROXY_HOPS=1` against reality once: make one failed login,
   then confirm the `ip_address` of that `login_attempt` row in `audit_log` is your
   public IP, not a Railway internal address.

### 5. Verify the live deployment

```
pip install -r requirements-dev.txt
set REDIS_URL=... & set MQTT_HOST=... & set MQTT_USERNAME=proctorai_backend & set MQTT_PASSWORD=...
set INTERNAL_API_KEY=... & set E2E_TEACHER_PASSWORD=...
python scripts/verify_deployment.py --base-url https://<service>.up.railway.app ^
    --allowed-origin https://<your-app>.vercel.app ^
    --e2e --teacher-email <teacher> --session-id <in-progress session> --room "<room>"
```

It checks that `/healthz` is public and minimal, that CORS rejects a foreign
origin, that Redis negotiates TLS, that MQTT uses TLS on 8883 and plaintext 1883
is refused, and (with `--e2e`) that a detection reaches a connected Socket.IO
client and an MQTT subscriber. `--e2e` creates one real case in the session you
name, so use a dedicated test session.

## Running tests

The suite truncates every table and flushes Redis before each test, and refuses
to run against a non-local host (override with
`PROCTORAI_ALLOW_REMOTE_TEST_DB=1` only for a disposable instance).

```
docker compose --profile test run --rm tests      # full suite: Postgres 16, Redis 7, ffmpeg
docker compose --profile test down -v             # remove the throwaway containers
```

Without Docker, `pytest` also runs from a venv (`pip install -r requirements-dev.txt`)
against a local Postgres and `python scripts/dev_redis_server.py`. The ffmpeg
clip tests are skipped unless ffmpeg is installed.

What the new tests prove:

| Check | Test |
|---|---|
| A frame's buffer writes (40 seats × 5 signals) are one round trip | `test_detection_pipeline.py::test_frame_buffer_writes_are_one_round_trip_per_frame` |
| Trigger after a full window, then cooldown | `::test_frames_trigger_after_a_full_window_then_cool_down` |
| Detection → case linked via seat map → Socket.IO + MQTT (no student ID over MQTT) | `::test_detection_creates_linked_case_and_notifies_socket_and_mqtt` |
| Real server: JWT socket auth, room authorization, event delivered through Redis | `::test_end_to_end_detection_reaches_connected_socketio_client` |
| MQTT outbox queues on failure and replays in order | `::test_mqtt_publish_failure_queues_then_drains_in_order` |
| Only well-formed heartbeats accepted | `::test_only_well_formed_heartbeats_are_accepted` |
| Snapshot paths confined to the session folder | `::test_snapshot_path_must_stay_inside_the_session_folder` |
| Exactly one Claude API call per penalty; reads never call it | `test_case_workflow.py::test_penalty_generates_notice_with_exactly_one_api_call` |
| API failure/refusal → template, still one call; client has `max_retries=0` | `::test_failed_generation_falls_back_to_template_without_retrying`, `::test_claude_client_never_retries` |
| Case state machine + teacher object-level authorization | `::test_teacher_triages_own_session_case`, `::test_teacher_cannot_see_or_touch_other_sessions` |
| Purge deletes only long-dismissed snapshots, idempotently | `::test_purge_deletes_only_long_dismissed_snapshots` |
| Clips re-encoded (H.264, ≤640 px, 10 fps, no audio, >5× smaller) + JPEG record image | `test_evidence_clips.py::test_clip_is_compressed_and_a_record_image_is_made` |
| Playlists / non-video / undecodable uploads rejected before storage | `::test_non_video_and_playlist_uploads_are_rejected` |
| Duration, size (413) and auth limits on uploads | `::test_clip_duration_limits`, `::test_upload_limits_and_auth` |
| Only HOD + invigilating teacher get signed URLs; views audited | `::test_reviewers_get_signed_urls_and_others_do_not` |
| Clip deleted only when review is final; record image survives | `::test_clips_are_deleted_only_once_review_is_final` |
| Supabase Storage request shapes (upload, sign, delete) | `::test_storage_client_request_shapes` |
| CORS rejects unlisted origins; wildcards refused at startup | `test_infrastructure.py::test_cors_rejects_unlisted_origin_and_allows_configured_one` |
| Production refuses plaintext Redis/MQTT, weak secrets, dev DB password | `::test_production_refuses_insecure_configuration` |
| Plaintext Redis detected when TLS is required | `::test_plaintext_redis_is_detected_and_refused_when_tls_required` |
| Internal endpoints fail closed | `::test_internal_endpoints_reject_missing_wrong_or_unconfigured_key` |
| Spoofed X-Forwarded-For can't bypass the signup rate limit | `::test_spoofed_forwarded_for_cannot_bypass_signup_rate_limit` |
| audit_log is append-only for the app role and the owner | `::test_audit_log_is_append_only` |
| Supabase `anon`/`authenticated` grants are stripped | `::test_schema_strips_supabase_data_api_grants` |

The original auth-hardening checklist tests (`test_signup.py`, `test_login.py`,
`test_verify_email.py`, `test_admin_users.py`, `test_seatmap.py`,
`test_cases_rls.py`) run unmodified.

## Local development

`docker compose up backend` runs the API against whatever `.env` points at.
Without Docker: `uvicorn app.main:asgi_app --reload`. On Windows, MQTT
(`MQTT_ENABLED=true`) needs a selector event loop, because paho uses
`add_reader`. Keep it disabled locally unless you need it.
