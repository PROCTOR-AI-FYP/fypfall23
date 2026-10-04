# Realtime update

## Latest website correction (2026-10-04)

The fresh website failure exposed exact-label rejection: a recognised phone
returned `a cell phone a` and was silently dropped. Grounding classes now use
their noun-token probabilities instead of decoded phrase equality, retaining
fabric competition and rejecting close competing scores. The thresholds
remain 0.50/0.60. A captured failing phone frame now produces a 0.509 detection;
the two recorded negative scenes still produce no confirmed events.

Slow results can outlive the eight-second image history. They now reconcile
directly against current-image evidence, up to an absolute 30-second result
age, and their track lifetime starts after successful reconciliation. This
does not retain a box without appearance evidence. Tighter contained boxes
replace the prior track instead of producing duplicates.

The real website/physical-webcam test confirmed both objects and saved a
combined alert in session 6; checks reached phone 0.827/book 0.776. Indicators
cleared after removal. The final restarted session 7 also detected the physical
phone (0.878) and saved its alert. Preview was about 15 FPS, while AI checks
took roughly 3–5 seconds. 66 regressions and the frontend build pass. Evidence
is in `validation-output/live-website-failure/`; see
`../backend/LOCAL_CAMERA_DEMO.md`. Earlier measurements below are historical.

The accurate blocking detector is preserved in the verified
`checkpoints/accurate-detection-2026-10-04.zip`. The source checksums and model
SHA256 are recorded alongside it. The original Grounding DINO weights remain
unchanged. The synchronous path is still available with `--sync`.

## Correction after the live failure report

The live default is now **640**, preserving the accurate checkpoint's input
size. The earlier 480-pixel measurements below describe the first speed update.
A subsequent 24-second physical phone/book diagnostic confirmed both objects
for 47 frames, but exposed confidence loss and tracking failures during motion.
On three clearly visible new frames, 640 increased book confidence to
0.780, 0.823 and 0.795 (480: 0.399, 0.730 and 0.594). These results are in
`validation-output/realtime-diagnosis-comparison.json`. Recognition remains in
the background, so restoring image detail does not block the camera loop.

Tracking now attempts current-image template reacquisition after optical-flow
failure. It requires correlation >= 0.75 and valid corners; absence or an
unrelated textured object still drops the track. Confirmation thresholds and
the two-observation alert requirement are unchanged. **50 regressions pass**.
The first correction run still rejected many recognized objects. The final
motion fix adds ORB descriptor matching with at least six consistent geometric
inliers, and directly checks the present image when a blurred history frame
breaks alignment. Two genuine semantic observations survive visual-track
reinitialization; a single observation cannot count twice.

Final live results are in `validation-output/realtime-corrected-live-v3.json`.
The trace confirmed both actual phones/books together at 15.3 seconds, following
strong recognitions at 12.3 and 15.3 seconds, and retained both through confidence
drops at 18.3 and 21.4 seconds. Captured close-range movement frames that previously
failed to reconcile now recover both phone and book boxes through rotation/scale.
The actual camera view contained the test objects in this final pass. This
40-second pass processed 656 frames at **16.4 fps**, with both confirmed in
**155 frames**; median current-frame work was 7.9 ms and p95 was 24.4 ms.
Objects were not consistently confirmed through the entire pass: rotation,
blur and weak classification still interrupted some tracks. This is an observed
remaining limit. Ordinary AI checks were about 3.0 seconds.
Very blurred/partly hidden frames in the diagnostic defeated even larger inputs;
those frames remain an observed limit, not a claimed successful detection.

## Earlier speed update

- Camera display, current-frame tracking, AI inference and HTTP dispatch no
  longer run in one blocking sequence.
- One background AI worker consumes the latest frame. Its input and output
  each occupy one slot; slower inference cannot create a growing frame queue.
- Optical flow and an appearance check follow each object on current frames.
  Before accepting a delayed detection, the engine moves its coordinates
  through a bounded frame history. Old boxes cannot simply land on new images.
- Confirmation follows the visually tracked object. Two strong AI checks are
  still required, even if the slow semantic detector assigns different IDs
  after movement. Weak second observations cannot confirm a provisional track.
- Lost image features, changed appearance and expired semantic verification
  remove a track. Gray "Checking" boxes are provisional and do not emit alerts.
- The live default uses a 480-pixel AI input, which retained phones, books,
  the blurred book track and the synthetic half-size test in the saved frames.
  The 640-pixel accurate synchronous path is unchanged.
- The full demo samples current tracking/head pose at 6 fps and dispatches
  backend requests outside the camera thread.

## Measured results on this CPU

| Test | Result |
|---|---|
| Regressions, including motion and async cases | 44 passed |
| 24-second live camera pass | 713 frames; 29.7 fps |
| Live processing time (empty inspected camera view) | Median 2.7 ms; p95 7.2 ms |
| 18-second controlled replay with phone/book movement and removal | 390 frames; 21.6 fps |
| Replay current-frame processing | Median 11.1 ms; p95 23.0 ms |
| Replay first confirmation of both objects after model loading | 3.8 seconds |
| Replay frames with both confirmed objects | 279 |
| Replay after switching to the recorded negative image | No final object events; no resurrection by delayed results |
| Semantic AI check | Typically 1.8–2.0 seconds; focused crops can take longer |
| 480-pixel saved-frame recognition | Both signals retained through the five positive frames after confirmation; both confirmed in the half-size test; recorded negative checks emitted no events |

Results are in `validation-output/realtime-live-benchmark-v2.json`,
`validation-output/realtime-benchmark-v2.json` and
`validation-output/live-test/fast-480-check.json`.

The latest inspected live camera snapshot showed an empty chair and no test
objects, so the live pass establishes camera responsiveness, not moving-phone
and book accuracy. Object movement was verified using the captured image replay
and deterministic motion/removal tests. The replay applies controlled scene
translation, not a new independent physical demonstration.

## Limits

This solves the frozen preview and lagging coordinates by doing current-image
tracking between recognition checks. It does not make the neural model itself
run at 30 fps. Newly introduced objects still need several seconds for two AI
checks, and difficult book crops may cost more time. The UI displays live FPS
and the last AI-check duration separately.

Tracking is image evidence, not fresh neural classification on every frame.
Occlusion, abrupt changes and extreme motion can drop a track; new confirmation
may then be required. Eight seconds without verification is the maximum track
age, and feature/appearance failure can remove it sooner. Independent live
positive tests in different conditions are still needed before deployment.
