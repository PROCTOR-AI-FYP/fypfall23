-- ProctorAI backend schema: users (Google sign-in via Supabase Auth),
-- classrooms, exam sessions and seat maps, detections, cases, penalties,
-- appeals, notifications, detection thresholds and the append-only audit log.
--
-- Idempotent and migrating: every statement is safe to re-run, and changes to
-- existing tables are ALTERs, so applying it to a database created by an
-- earlier version upgrades that database in place. Apply with the
-- superuser/owner connection (DATABASE_ADMIN_URL), e.g.:
--   psql "$DATABASE_ADMIN_URL" -f db/schema.sql
-- or: python scripts/apply_schema.py

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
-- classrooms — exam halls, each with one ceiling camera and an optional seat
-- polygon map (JSON array of {seat_number, vertices:[{x,y}]} in the camera
-- frame's pixel space).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS classrooms (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name           TEXT NOT NULL UNIQUE,
    building       TEXT NOT NULL,
    capacity       INTEGER NOT NULL CHECK (capacity BETWEEN 1 AND 1000),
    camera_id      TEXT,
    camera_status  TEXT NOT NULL DEFAULT 'offline' CHECK (camera_status IN ('online', 'offline', 'maintenance')),
    seat_map       JSONB,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- exam_sessions — one scheduled exam in one room. The Exam Controller
-- schedules it (status 'scheduled') and assigns an invigilator; the teacher
-- starts it ('in_progress') and ends it ('completed').
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
ALTER TABLE exam_sessions ADD COLUMN IF NOT EXISTS course_name TEXT NOT NULL DEFAULT '';
ALTER TABLE exam_sessions ADD COLUMN IF NOT EXISTS department TEXT NOT NULL DEFAULT '';
-- `room` keeps the classroom's name as it was when the exam was scheduled
-- (it is also the MQTT topic slug and the room printed on notices).
ALTER TABLE exam_sessions ADD COLUMN IF NOT EXISTS classroom_id UUID REFERENCES classrooms(id) ON DELETE SET NULL;
ALTER TABLE exam_sessions ADD COLUMN IF NOT EXISTS scheduled_date DATE;
ALTER TABLE exam_sessions ADD COLUMN IF NOT EXISTS start_time TIME;
ALTER TABLE exam_sessions ADD COLUMN IF NOT EXISTS end_time TIME;
ALTER TABLE exam_sessions ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ;
ALTER TABLE exam_sessions ADD COLUMN IF NOT EXISTS ended_at TIMESTAMPTZ;
ALTER TABLE exam_sessions DROP CONSTRAINT IF EXISTS exam_sessions_time_order;
ALTER TABLE exam_sessions ADD CONSTRAINT exam_sessions_time_order
    CHECK (start_time IS NULL OR end_time IS NULL OR end_time > start_time);
CREATE INDEX IF NOT EXISTS exam_sessions_schedule_idx ON exam_sessions (scheduled_date, classroom_id);

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

-- Each detection carries its own snapshot, so the path identifies it: a
-- worker retrying a POST after a timeout gets 409 instead of opening a
-- second case against the same student for the same moment.
CREATE UNIQUE INDEX IF NOT EXISTS detection_events_snapshot_unique ON detection_events (snapshot_path);
-- Alert triage by the invigilator: first look at the evidence, and the
-- "confirm as case" decision that forwards the case to the HOD.
ALTER TABLE detection_events ADD COLUMN IF NOT EXISTS reviewed_at TIMESTAMPTZ;
ALTER TABLE detection_events ADD COLUMN IF NOT EXISTS teacher_confirmed_at TIMESTAMPTZ;
ALTER TABLE detection_events ADD COLUMN IF NOT EXISTS teacher_confirmed_by UUID REFERENCES users(id) ON DELETE SET NULL;

ALTER TABLE cases ADD COLUMN IF NOT EXISTS detection_event_id UUID REFERENCES detection_events(id) ON DELETE SET NULL;
ALTER TABLE cases ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();
-- The invigilator's note for the HOD, written when confirming the alert.
ALTER TABLE cases ADD COLUMN IF NOT EXISTS teacher_note TEXT;
ALTER TABLE cases ADD COLUMN IF NOT EXISTS teacher_note_by UUID REFERENCES users(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS cases_session_idx ON cases (session_id);
CREATE INDEX IF NOT EXISTS cases_student_idx ON cases (student_id);

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

-- Set when an appeal against the case is accepted; the row is kept as record.
ALTER TABLE penalties ADD COLUMN IF NOT EXISTS revoked_at TIMESTAMPTZ;
ALTER TABLE penalties ADD COLUMN IF NOT EXISTS revoked_by UUID REFERENCES users(id) ON DELETE SET NULL;

-- ---------------------------------------------------------------------------
-- appeals — a student's appeal against an issued penalty, resolved by the HOD.
-- At most one OPEN appeal per case, enforced here; the HOD's decision is final
-- (a second appeal after resolution is refused in the API).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS appeals (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id          UUID NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    student_id       UUID NOT NULL REFERENCES users(id),
    statement        TEXT NOT NULL CHECK (length(statement) BETWEEN 1 AND 5000),
    supporting_info  TEXT CHECK (supporting_info IS NULL OR length(supporting_info) <= 1000),
    status           TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'accepted', 'rejected')),
    reviewed_by      UUID REFERENCES users(id) ON DELETE SET NULL,
    review_note      TEXT,
    submitted_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at      TIMESTAMPTZ,
    CONSTRAINT appeals_resolution_consistent CHECK ((status = 'open') = (resolved_at IS NULL))
);
CREATE UNIQUE INDEX IF NOT EXISTS appeals_one_open_per_case ON appeals (case_id) WHERE status = 'open';
CREATE INDEX IF NOT EXISTS appeals_case_idx ON appeals (case_id);

-- ---------------------------------------------------------------------------
-- notifications — per-user inbox behind the header bell.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS notifications (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    type            TEXT NOT NULL CHECK (type IN ('alert', 'case_update', 'penalty', 'appeal', 'system')),
    title           TEXT NOT NULL,
    message         TEXT NOT NULL,
    reference_type  TEXT CHECK (reference_type IN ('case', 'appeal', 'session')),
    reference_id    UUID,
    read_at         TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS notifications_user_idx ON notifications (user_id, created_at DESC);

-- ---------------------------------------------------------------------------
-- detection_thresholds — Admin-configured sensitivity and composite weight
-- per behaviour. The detection pipeline reads these (app/services/detection.py):
-- a signal counts as over threshold at score >= 1 - sensitivity/100.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS detection_thresholds (
    behaviour_type  TEXT PRIMARY KEY CHECK (behaviour_type IN (
                        'GAZE_DEVIATION', 'HEAD_POSE_VIOLATION', 'LIP_MOVEMENT',
                        'PHONE_DETECTED', 'UNAUTHORISED_OBJECT')),
    sensitivity     INTEGER NOT NULL CHECK (sensitivity BETWEEN 0 AND 100),
    weight          NUMERIC(4, 3) NOT NULL CHECK (weight BETWEEN 0 AND 1),
    updated_by      UUID REFERENCES users(id) ON DELETE SET NULL,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- Defaults reproduce the pipeline's original fixed thresholds (0.70/0.70/0.75/0.80/0.80).
-- BEGIN default thresholds (tests re-apply this block between cases)
INSERT INTO detection_thresholds (behaviour_type, sensitivity, weight) VALUES
    ('GAZE_DEVIATION', 30, 0.20),
    ('HEAD_POSE_VIOLATION', 30, 0.20),
    ('LIP_MOVEMENT', 25, 0.15),
    ('PHONE_DETECTED', 20, 0.25),
    ('UNAUTHORISED_OBJECT', 20, 0.20)
ON CONFLICT (behaviour_type) DO NOTHING;
-- END default thresholds

-- ---------------------------------------------------------------------------
-- Row-Level Security. The GUCs are set per request by deps.get_rls_db from
-- the authenticated user as re-read from the database (see app/db.py).
--   cases, penalties, appeals: a student sees only their own; staff pass.
--   notifications: every role sees only its own rows (inserts are open, so
--   system events can notify anyone).
-- ---------------------------------------------------------------------------
ALTER TABLE cases ENABLE ROW LEVEL SECURITY;
ALTER TABLE cases FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS cases_student_isolation ON cases;
CREATE POLICY cases_student_isolation ON cases
    USING (
        current_setting('app.current_role', true) IS DISTINCT FROM 'student'
        OR student_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid
    );

ALTER TABLE penalties ENABLE ROW LEVEL SECURITY;
ALTER TABLE penalties FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS penalties_student_isolation ON penalties;
CREATE POLICY penalties_student_isolation ON penalties
    USING (
        current_setting('app.current_role', true) IS DISTINCT FROM 'student'
        OR EXISTS (
            SELECT 1 FROM cases c
            WHERE c.id = penalties.case_id
              AND c.student_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid
        )
    );

ALTER TABLE appeals ENABLE ROW LEVEL SECURITY;
ALTER TABLE appeals FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS appeals_student_isolation ON appeals;
CREATE POLICY appeals_student_isolation ON appeals
    USING (
        current_setting('app.current_role', true) IS DISTINCT FROM 'student'
        OR student_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid
    )
    WITH CHECK (
        current_setting('app.current_role', true) IS DISTINCT FROM 'student'
        OR student_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid
    );

ALTER TABLE notifications ENABLE ROW LEVEL SECURITY;
ALTER TABLE notifications FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS notifications_owner_read ON notifications;
CREATE POLICY notifications_owner_read ON notifications FOR SELECT
    USING (user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid);
DROP POLICY IF EXISTS notifications_owner_update ON notifications;
CREATE POLICY notifications_owner_update ON notifications FOR UPDATE
    USING (user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid);
DROP POLICY IF EXISTS notifications_insert ON notifications;
CREATE POLICY notifications_insert ON notifications FOR INSERT WITH CHECK (true);

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

ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_log FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS audit_log_insert ON audit_log;
CREATE POLICY audit_log_insert ON audit_log FOR INSERT WITH CHECK (true);
DROP POLICY IF EXISTS audit_log_select ON audit_log;
CREATE POLICY audit_log_select ON audit_log FOR SELECT USING (true);

-- clock_timestamp(), not now(): now() is the transaction's start time, so
-- several entries written by one request would share a timestamp and the
-- case timeline (read from this table) would have no reliable order.
ALTER TABLE audit_log ALTER COLUMN created_at SET DEFAULT clock_timestamp();

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
-- Grants for the non-superuser application role: exactly what the code does.
-- Records the app never deletes (users are soft-deleted; cases, penalties,
-- appeals and detections are evidence) get no DELETE.
-- ---------------------------------------------------------------------------
REVOKE ALL ON
    users, classrooms, exam_sessions, seat_assignments, cases, detection_events,
    penalties, appeals, notifications, detection_thresholds, audit_log
    FROM app_user;
-- An earlier scripts/apply_schema.py set blanket default privileges for
-- app_user on every future table; undo that so new tables start closed.
ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM app_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON SEQUENCES FROM app_user;
GRANT USAGE ON SCHEMA public TO app_user;
GRANT SELECT, INSERT, UPDATE ON
    users, exam_sessions, cases, detection_events, penalties, appeals, notifications, detection_thresholds
    TO app_user;
GRANT SELECT, INSERT, UPDATE, DELETE ON classrooms, seat_assignments TO app_user;
GRANT SELECT, INSERT ON audit_log TO app_user;
GRANT USAGE ON SEQUENCE case_reference_seq TO app_user;

-- Supabase exposes the public schema through its Data API as the anon and
-- authenticated roles and grants them access to new tables by default. This
-- backend never uses that API, and since Google sign-in the anon key ships in
-- the frontend and real `authenticated` tokens exist; so strip every grant on
-- every table in the schema, and on tables created later. (No-op on plain
-- Postgres, where those roles don't exist.)
DO $$
DECLARE
  api_role TEXT;
BEGIN
  FOREACH api_role IN ARRAY ARRAY['anon', 'authenticated'] LOOP
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = api_role) THEN
      EXECUTE format('REVOKE ALL ON ALL TABLES IN SCHEMA public FROM %I', api_role);
      EXECUTE format('REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM %I', api_role);
      EXECUTE format('REVOKE ALL ON ALL FUNCTIONS IN SCHEMA public FROM %I', api_role);
      EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM %I', api_role);
      EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON SEQUENCES FROM %I', api_role);
    END IF;
  END LOOP;
END
$$;
