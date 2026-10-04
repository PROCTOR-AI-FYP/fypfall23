# Local website: live phone and book detection

This connects the currently active `src/App.tsx` Live Alert Inbox to the local
SQLite backend (`backend.main:app`) and the corrected detector. The separate
authenticated platform in `backend/app/` is unchanged.

From the project root in PowerShell:

```powershell
.\scripts\start-local.ps1
```

Open **http://127.0.0.1:5173/** and click **Start monitoring**. **Stop monitoring**
releases the webcam. Close other camera applications, including the standalone
`phone_detector.py` window, before starting the website camera.

The launcher keeps the backend (port 8000) and Vite (5173) running in hidden
background processes. Logs and process IDs are in
`ai-engine/.runtime/local-web/`. Both services bind to this PC's loopback address.
This SQLite milestone has no authentication; use it locally.

The existing root `venv` and model are already installed and tested. On a new PC:

```powershell
.\venv\Scripts\python.exe -m pip install -r ai-engine/requirements.txt -r backend/requirements-demo.txt
.\venv\Scripts\python.exe ai-engine/prepare_models.py
```

## Data flow

1. The website starts one backend camera session. The backend owns the physical
   camera, avoiding browser/native camera contention.
2. Grounding DINO runs on original camera frames in a background worker at the
   accurate 640-pixel setting. Current-image tracking aligns the boxes.
3. The annotated latest frame streams to the browser as MJPEG. No growing
   frame queue is created. Transport images are at most 960 pixels wide.
4. Confirmed phones/books pass the existing three-second scorer sampled at
   6 fps. Phones use weight 0.90; books emit `UNAUTHORISED_OBJECT`, weight 0.75.
5. The backend saves a detection and pending review case in `proctoring.db`
   using the actual camera session ID, then emits `case_created` via Socket.IO.
6. The inbox updates immediately and reloads saved cases on reconnect.
   Confirm/Dismiss is shown as successful only after the backend accepts it.

Sustained alerts are limited to one per signal combination every 20 seconds;
failed saves retry after at least five seconds. Model/camera/save failures are
visible in the panel. Backend disconnects clear current object indicators.

The displayed **object confidence** is the neural score. The case's **Alert
score** is the weighted composite policy score. They are different values.

## Validation

```powershell
.\venv\Scripts\python.exe -m pytest ai-engine/test_phone_detector.py ai-engine/test_composite_scorer.py ai-engine/test_grounding_detector.py ai-engine/test_realtime.py ai-engine/test_web_integration.py -q -p no:cacheprovider
npm run build
```

66 tests passed, and the production frontend build passed. The web tests use a
disposable SQLite database and fake capture to verify policy, storage, delivery,
idempotent Start, Stop/release, failure reporting and review persistence. They
do not invoke the destructive Postgres/Redis test suite.

A separate real-AI browser check used the locally captured positive scene with
controlled movement, followed by its recorded negative image. It generated
combined phone/book cases through the real model, scorer, database and socket.
Both arrived in the browser without reloading. Confirm and Dismiss were checked
through the UI and persisted after reload. The real webcam feed, socket
connection and Start/Stop controls were also verified on the actual local site.

Replay evidence is in `ai-engine/validation-output/website-replay-result.json`
and `website-replay-verified.png`. The replay's cases live only in
`ai-engine/.runtime/local-web/web-replay-test.db`, separate from the real inbox.
Its fixture refuses to use any other database name. Test ports are 8001/5180;
the user-facing site uses 8000/5173 and the physical webcam.

### Correction after the live failure report

The model's decoded phrase could be `a cell phone a`, despite strong phone
tokens. Exact string matching silently discarded that recognition. Classes
now use their own noun-token scores, with fabric competing as a negative class
and a margin to reject ambiguous classes. Articles cannot inflate confidence.
Phone/book thresholds remain 0.50/0.60 and two semantic checks are required.

Inference taking over eight seconds previously exhausted the frame history
and rejected every result. Results up to 30 seconds old now require current
image reconciliation; the eight-second track lifetime begins at that verified
reconciliation. Removed objects still fail alignment. Tighter boxes replace
containing tracks of the same class, avoiding duplicate boxes.

The fresh physical-webcam run (session 6) confirmed both objects together,
saved a combined case, and delivered it to the actual website without reload.
Observed strong checks reached phone 0.827/book 0.776, with preview around
15 FPS. Indicators subsequently cleared after objects left view. Evidence:
`ai-engine/validation-output/live-website-failure/fixed-live-trace.json`,
`fixed-ai-results.json`, and `website-fixed-live.png`. Recognition still takes
seconds and confidence varies with the view; this is not a claim of perfect
or instantaneous recognition.

Recognition limitations remain: new objects require several seconds; blur,
orientation and occlusion can interrupt detections. Connecting the website
does not increase neural detection accuracy. See `ai-engine/REALTIME_VALIDATION.md`.

The pre-integration source checkpoint is
`ai-engine/checkpoints/local-website-before-integration-2026-10-04.zip`.
