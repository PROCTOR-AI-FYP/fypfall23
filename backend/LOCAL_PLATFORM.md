# Local role-based camera integration

Run `scripts/start-local.ps1` from the repository. The website is
http://127.0.0.1:5173, with the full FastAPI application on loopback port 8000.
Configure the existing PostgreSQL, Redis and Supabase Google sign-in settings
in `backend/.env` and the frontend environment. The launcher preserves configured
origins and adds the exact localhost/127.0.0.1 browser origins. It never seeds or
resets the configured database. Secrets remain in ignored environment files.

## Workflow

1. Admin provisions the real staff accounts, classrooms and detection policy.
   Staff roles come from Admin provisioning; Google sign-in cannot claim a role.
2. Exam Controller schedules an exam for today and assigns its Teacher.
3. Students sign in with their institutional registration emails. The Teacher
   uploads a CSV with `seat_number,student_reg_no`; every monitored seat must
   resolve to an active, registered student.
4. Teacher starts the scheduled exam, opens Live Monitor, selects the student
   seat and starts this PC's webcam. Close other programs using the camera.
5. Phones and books appear in the feed. Set neutral head pose while facing
   forward in normal exam posture and holding still for two seconds.
6. Stable object detections above the configured review thresholds save an
   annotated image, detection and pending case. Head pose alone is a warning;
   sustained head movement can accompany an object alert as context.
7. Teacher reviews or dismisses an alert. HOD handles confirmation, penalties
   and appeals. Students see only their own case records and may appeal a penalty.
   Controller sees scheduling/history/statistics; Admin sees users/configuration/audit.
   Students can download their active decision notice as a text document. Accepted
   appeals show the penalty as revoked and prevent downloading it as an active notice.

Role and object access checks apply on the API, camera feed and evidence image.
The capture stops if the exam ends, its invigilator changes, the selected student
changes or becomes inactive, or the policy/session check loses connectivity.
The selected student is checked again in the transaction before saving evidence;
the live alert is emitted after the case has committed.

## CSV setup imports

Use **CSV Imports** in the Admin or Exam Controller sidebar. Download the blank
templates, fill them with real records, select the files and preview the batch.
Admins can import student rosters, classroom inventory, exam schedules and
invigilator assignments together. Exam Controllers can import schedules and
assignments for existing classrooms. Teachers retain the session seat-assignment
workflow; HODs and Students do not have setup-import access.

The importer connects rooms by name and invigilators by registered teacher email.
Assignments match course code, date, start/end times and room. New rooms and exams
in the same batch are resolved automatically. Use UTF-8 CSV, YYYY-MM-DD dates and
24-hour HH:MM times; preserve leading zeroes in six-digit student registrations.
Each file supports up to 1,000 rows and 256 KB.

Preview changes no records. Exact existing matches are skipped; different existing
details, duplicate rows, invalid student emails, missing links, room clashes and
teacher clashes block the complete batch. Commit revalidates the preview against
current records and saves records, audits and assignment notifications in one
transaction. A failure rolls back the complete import. Existing roles and account
activation are never changed by a CSV. Imported students still complete Google
sign-in; camera seat polygons still need alignment with the real camera view.

The endpoints are `POST /api/imports/preview` and `POST /api/imports/commit`.
Both require an authenticated permitted role and the normal CSRF header. Submit
files under `student_roster`, `classroom_inventory`, `exam_schedule` and/or
`invigilator_assignments`; commit also includes the preview's `preview_hash`.

## Live synchronization

Socket.IO delivers detection alerts to authorized session/invigilator rooms.
Successful mutations publish an empty change notification; each role fetches its
own permitted records through REST. Students never receive the staff alert payload.
Role changes and account removal disconnect the affected sockets. Reconnection
refreshes the UI; a five-second refresh runs when the socket is disconnected.
Background refreshes preserve open forms and do not replace errors with mock data.

Teacher sidebar links list actual assigned sessions, rather than demo IDs.
Selecting an alerted seat opens its matching review panel. Notification badges,
case lists, appeals, reports and dashboard counts read persisted data.

## Evidence and detector limits

New camera images stay under ignored `ai-engine/.runtime/platform-evidence/` on
this PC; only authorized evidence routes serve them. The database stores their
references. Local captures currently save an annotated **snapshot**; they do not
automatically record a video clip. The existing external-worker clip upload and
review pipeline remains available and requires FFmpeg and FFprobe.

This capture mode monitors one clearly visible student per webcam view, bound
explicitly to that student's registered seat. It does not locate every student
in a ceiling-camera hall. Head pose is movement context, not proof of misconduct.
Recognition depends on visibility, size, lighting and orientation; a visible box
may be below the institution's case threshold. Only phones and books are enabled
in the current object policy. Lip/gaze detectors and physical room devices are
outside this integration.

Inference runs in the background and the latest video frame remains independent
of neural inference. Model startup needs available memory; avoid running model
benchmarks and production builds simultaneously on a busy PC. Watch camera status
for initialization/errors rather than treating an empty preview as an all-clear.

## Verification

`backend/tests/test_camera.py` covers role gates, active-session and seat requirements,
head-only warnings, institution sensitivity, correct student attribution, snapshot
access, the teacher/HOD/penalty/student-appeal lifecycle, reassignment rejection,
evidence cleanup, path traversal and emission after database commit.

The full backend suite uses disposable PostgreSQL/Redis. Never run destructive
tests against the configured institutional database. For the isolated services
prepared on this PC:

```powershell
.\venv\Scripts\python.exe backend/scripts/test_local_platform.py -q -p no:cacheprovider
```

The launcher checks the fixture database and service ports, overrides cloud DSNs,
and places pytest temporary files under the ignored workspace runtime directory.
`backend/scripts/browser_platform_fixture.py` is a separate QA entry point: it
creates a new local database, fixture-only accounts/cookie and a recorded camera
scene with the real models. It is never imported by `app.main` and cannot sign into
the real platform. Its API uses port 8003; the QA frontend uses 5181 with
`PROCTORAI_API_PROXY_TARGET=http://127.0.0.1:8003`.

Before the live hierarchy can be used, Admin must provision a real HOD account.
No HOD identity is invented or assigned automatically by this integration.

## Recorded acceptance checks on this PC

The isolated browser used the same React pages, FastAPI routes, native head pose
detector and object models as the real website. Only the camera source and user
accounts were disposable fixtures. Recorded phone/book frames produced 93% phone
and 77% book confidence at approximately 10–14 preview FPS. The resulting alert
saved an authorized evidence image, entered the teacher inbox and opened from its
seat. HOD review showed the actual per-signal scores and audit trail.

The same captured case then passed the browser workflow: teacher confirmation,
HOD warning/notice, student appeal, HOD acceptance, dismissed case and revoked
penalty in the student view. The controller report showed six cases, one appeal
and 100% appeal success for this fixture. The student saw five own cases and
could not see the other student's case. No test penalties or fixture users were
added to the configured institutional database.

Recorded neutral head pose calibrated to zero without a warning. The annotated
sideways JPEG fixtures did not yield a visible face; the UI correctly reported
that condition. Direction, angle, calibration and sustained-warning behavior are
covered by the head-pose regression tests and earlier webcam validation. A fresh
integrated sideways webcam warning was not performed, at the user's request to
finish with recorded tests.

Proof images are saved locally under `ai-engine/validation-output/platform/`:
`real-model-monitor.png`, `head-neutral.png`, `evidence-review.png`,
`hod-case-review.png`, `student-appeal.png`, `student-resolution.png` and
`controller-statistics.png`. These images and exam runtime data remain ignored by Git.

The production build passes. Lint exits successfully with existing React/style
warnings; the decorative sign-in bundle still produces a size warning. The AI
and demo bridge regression suite passed 102 tests. The final complete backend run
passed 272 tests in 152.51 seconds, including notice ownership and revoked-notice checks.
