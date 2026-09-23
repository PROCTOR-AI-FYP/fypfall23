-- ProctorAI backend — Phase 2b schema.
-- This is the FIRST schema in this repo; it is written as the full minimal
-- schema this auth spec depends on (users + auth support + just enough of
-- exam_sessions/seat_assignments/cases/audit_log to prove the seat-map
-- linkage and RLS cross-visibility check end to end). Apply with a
-- superuser/owner connection (DATABASE_ADMIN_URL), e.g.:
--   psql "$DATABASE_ADMIN_URL" -f db/schema.sql
--
-- Rollback for the whole feature = delete the backend/ directory; nothing
-- outside it is touched. To roll back just this schema in an existing
-- database, `DROP DATABASE proctorai;` (or drop the objects below).

CREATE EXTENSION IF NOT EXISTS pgcrypto; -- gen_random_uuid()

-- ---------------------------------------------------------------------------
-- Application role: the API connects as this role, NOT as the owner/
-- superuser, so that Row-Level Security on `cases` actually applies to it.
-- (Postgres exempts the table owner and superusers from RLS unless FORCE
-- ROW LEVEL SECURITY is used — we set FORCE too, belt and suspenders, but
-- the primary defense is simply never connecting as the owner in prod.)
-- ---------------------------------------------------------------------------
-- The password below is a local-development default only. On Supabase, run
-- once after applying this file:  ALTER ROLE app_user PASSWORD '<random>';
-- The app refuses to start with APP_ENV=production while DATABASE_URL still
-- carries the development password.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_user') THEN
    CREATE ROLE app_user LOGIN PASSWORD 'app_password';
  END IF;
END
$$;

-- ---------------------------------------------------------------------------
-- users
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    full_name                   TEXT NOT NULL,
    email                       TEXT NOT NULL UNIQUE,
    password_hash               TEXT,
    role                        TEXT NOT NULL CHECK (role IN ('admin', 'hod', 'teacher', 'exam_controller', 'student')),
    registration_or_employee_no TEXT NOT NULL,
    status                      TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'disabled')),
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE users DROP CONSTRAINT IF EXISTS users_reg_no_unique;
ALTER TABLE users ADD CONSTRAINT users_reg_no_unique UNIQUE (registration_or_employee_no);

-- Google sign-in via Supabase Auth (migration from password auth).
-- supabase_user_id is the verified token's `sub`, set on first sign-in
-- ("activation"). It is deliberately NOT a foreign key to auth.users: that
-- would need cross-schema grants for app_user, and matching the verified
-- `sub` is all the linkage needs. password_hash is kept (nullable) only so
-- existing rows migrate in place; no code reads or writes it.
ALTER TABLE users ALTER COLUMN password_hash DROP NOT NULL;
ALTER TABLE users ADD COLUMN IF NOT EXISTS supabase_user_id UUID UNIQUE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS auth_provider TEXT NOT NULL DEFAULT 'google'
    CHECK (auth_provider IN ('google', 'legacy_password'));
ALTER TABLE users ADD COLUMN IF NOT EXISTS department TEXT NOT NULL DEFAULT '';
-- Soft delete: rows referenced by cases, penalties and the audit trail are
-- never physically removed.
ALTER TABLE users ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;
-- Google owns email verification now; "activated" (supabase_user_id set)
-- replaces this flag.
ALTER TABLE users DROP COLUMN IF EXISTS email_verified;
-- Sign-in matches on the verified email case-insensitively.
CREATE UNIQUE INDEX IF NOT EXISTS users_email_lower_idx ON users (lower(email));

DROP TABLE IF EXISTS email_verifications;

-- ---------------------------------------------------------------------------
-- exam_sessions (minimal — full scheduling lives outside this spec's scope)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS exam_sessions (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    course_code TEXT NOT NULL,
    room        TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'scheduled'
                CHECK (status IN ('scheduled', 'in_progress', 'completed', 'cancelled')),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE exam_sessions ADD COLUMN IF NOT EXISTS invigilator_id UUID REFERENCES users(id) ON DELETE SET NULL;
ALTER TABLE exam_sessions ADD COLUMN IF NOT EXISTS silent_mode BOOLEAN NOT NULL DEFAULT false;

-- ---------------------------------------------------------------------------
-- seat_assignments — the join between a signed-up student and a seat,
-- resolved from the seat-map CSV (seat_number,student_reg_no).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS seat_assignments (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id      UUID NOT NULL REFERENCES exam_sessions(id) ON DELETE CASCADE,
    seat_number     INTEGER NOT NULL,
    student_reg_no  TEXT NOT NULL,
    student_id      UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (session_id, seat_number)
);

-- ---------------------------------------------------------------------------
-- cases — minimal shape; RLS enforced below.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS cases (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id    UUID NOT NULL REFERENCES exam_sessions(id) ON DELETE CASCADE,
    seat_number   INTEGER NOT NULL,
    student_id    UUID REFERENCES users(id) ON DELETE SET NULL,
    reference_no  TEXT NOT NULL UNIQUE, -- e.g. AU-CS-INT-2026-014
    status        TEXT NOT NULL DEFAULT 'pending_review'
                  CHECK (status IN ('pending_review', 'confirmed', 'dismissed', 'escalated')),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- detection_events — one row per alert the detection worker confirms, in
-- the AGENTS.md detection event shape. Snapshots live in Supabase Storage;
-- snapshot_purged_at records when the purge job deleted the object.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS detection_events (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id          UUID NOT NULL REFERENCES exam_sessions(id) ON DELETE CASCADE,
    seat_number         INTEGER NOT NULL,
    behaviour_types     TEXT[] NOT NULL,
    per_signal          JSONB NOT NULL,
    composite_score     NUMERIC(4, 3) NOT NULL CHECK (composite_score BETWEEN 0 AND 1),
    snapshot_path       TEXT NOT NULL,
    snapshot_purged_at  TIMESTAMPTZ,
    detected_at         TIMESTAMPTZ NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS detection_events_purge_idx
    ON detection_events (created_at) WHERE snapshot_purged_at IS NULL;

-- Evidence clip lifecycle: the compressed clip lives in Supabase Storage
-- (never in the database) until the review is final, then it is deleted and
-- record_image_path (a contact-sheet JPEG made from the clip) remains.
ALTER TABLE detection_events ADD COLUMN IF NOT EXISTS clip_path TEXT;
ALTER TABLE detection_events ADD COLUMN IF NOT EXISTS clip_bytes INTEGER;
ALTER TABLE detection_events ADD COLUMN IF NOT EXISTS clip_duration_seconds NUMERIC(6, 2);
ALTER TABLE detection_events ADD COLUMN IF NOT EXISTS clip_uploaded_at TIMESTAMPTZ;
ALTER TABLE detection_events ADD COLUMN IF NOT EXISTS clip_purged_at TIMESTAMPTZ;
ALTER TABLE detection_events ADD COLUMN IF NOT EXISTS record_image_path TEXT;

CREATE INDEX IF NOT EXISTS detection_events_clip_purge_idx
    ON detection_events (id) WHERE clip_path IS NOT NULL AND clip_purged_at IS NULL;

ALTER TABLE cases ADD COLUMN IF NOT EXISTS detection_event_id UUID REFERENCES detection_events(id) ON DELETE SET NULL;
ALTER TABLE cases ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();

-- Not owned by a column, so TRUNCATE ... RESTART IDENTITY leaves it alone and
-- reference numbers are never reissued.
CREATE SEQUENCE IF NOT EXISTS case_reference_seq START WITH 100;

-- ---------------------------------------------------------------------------
-- penalties — at most one per case (UNIQUE), which is also what guarantees
-- the notice document is generated at most once per issuance.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS penalties (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id           UUID NOT NULL UNIQUE REFERENCES cases(id) ON DELETE CASCADE,
    penalty_type      TEXT NOT NULL CHECK (penalty_type IN (
                          'formal_warning', 'mark_deduction', 'exam_voidance',
                          'disciplinary_referral', 'suspension', 'other')),
    description       TEXT NOT NULL,
    issued_by         UUID NOT NULL REFERENCES users(id),
    notice_reference  TEXT NOT NULL,
    notice_document   TEXT,
    notice_source     TEXT CHECK (notice_source IN ('anthropic', 'template')),
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Row-Level Security: a student may only ever see rows where they are the
-- accused student. Non-student roles pass through unfiltered (full case
-- management for HOD/Teacher/etc. is out of scope for this spec, but this
-- policy already allows it). The GUCs read here are set per-request by
-- app/db.py::acquire_rls_connection from the JWT — see that file's
-- docstring for the exact mechanism.
ALTER TABLE cases ENABLE ROW LEVEL SECURITY;
ALTER TABLE cases FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS cases_student_isolation ON cases;
CREATE POLICY cases_student_isolation ON cases
    USING (
        current_setting('app.current_role', true) IS DISTINCT FROM 'student'
        OR student_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid
    );

-- ---------------------------------------------------------------------------
-- audit_log
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS audit_log (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    actor_id    UUID REFERENCES users(id) ON DELETE SET NULL,
    action      TEXT NOT NULL,
    target      TEXT NOT NULL,
    new_value   JSONB NOT NULL DEFAULT '{}'::jsonb,
    ip_address  TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Append-only: the app role cannot UPDATE/DELETE (grants below), and this
-- trigger also blocks the owner. TRUNCATE (used only by the test harness)
-- fires no row triggers.
CREATE OR REPLACE FUNCTION audit_log_reject_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'audit_log is append-only';
END
$$;

DROP TRIGGER IF EXISTS audit_log_append_only ON audit_log;
CREATE TRIGGER audit_log_append_only
    BEFORE UPDATE OR DELETE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION audit_log_reject_mutation();

-- ---------------------------------------------------------------------------
-- Grants for the non-superuser application role.
-- ---------------------------------------------------------------------------
GRANT SELECT, INSERT, UPDATE, DELETE ON
    users, exam_sessions, seat_assignments, cases,
    detection_events, penalties
    TO app_user;
REVOKE UPDATE, DELETE ON audit_log FROM app_user;
GRANT SELECT, INSERT ON audit_log TO app_user;
GRANT USAGE ON SEQUENCE case_reference_seq TO app_user;

-- Supabase exposes the public schema through its Data API as the anon and
-- authenticated roles, and grants them access to new tables by default. This
-- backend never uses that API, so strip every grant: otherwise the public
-- anon key could read users.password_hash over REST. (No-op on plain Postgres.)
DO $$
DECLARE
  api_role TEXT;
BEGIN
  FOREACH api_role IN ARRAY ARRAY['anon', 'authenticated'] LOOP
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = api_role) THEN
      EXECUTE format(
        'REVOKE ALL ON users, exam_sessions, seat_assignments, '
        'cases, detection_events, penalties, audit_log FROM %I', api_role);
      EXECUTE format('REVOKE ALL ON SEQUENCE case_reference_seq FROM %I', api_role);
    END IF;
  END LOOP;
END
$$;
