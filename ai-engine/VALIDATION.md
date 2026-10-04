# Detection fix: local validation

This describes the saved accuracy checkpoint. The current live pipeline and
speed measurements are documented in `REALTIME_VALIDATION.md`.

## What changed

The previous class filter excluded books, and the scorer had no book weight.
Phone detection relied on one high confidence threshold and cropped views;
annotation repeated model inference. The tested small YOLO checkpoints could
locate the visible phone but consistently missed the upright novel cover.

The default now uses the official, pinned Grounding DINO Tiny checkpoint.
Only phones and books emit events. Fabric is a competing model query, not a
prohibited class. A focused crop verifies uncertain small books at the same
location. Two strong observations confirm a track; weaker matching observations
maintain it. Missing objects emit no events, and expired tracks need confirmation
again. Drawing uses cached results.

Camera setup preserves the available resolution. The demo scorer uses a
three-second observation window and still applies weighted-max scoring. It
requires current evidence and at least two real observations. API latency is
bounded to avoid unnecessarily delaying the next observation.

## Checks completed

| Check | Result |
|---|---|
| Unit/regression suite | 35 passed |
| Five captured webcam frames | Phone and book tracks retained after two-frame confirmation; both events in the remaining four frames |
| Blurred final book frame | Same book track retained with a matching weaker observation |
| Synthetic 75% scene size | Both objects confirmed |
| Synthetic 50% scene size | Phone confirmed; focused crop confirmed the small book |
| Recorded negative image, repeated three times | No confirmed object events |
| Local manually labelled positive/negative images | Both boxes matched IoU > 0.8; no false confirmed event on the negative image |
| Isolated demo FastAPI + temporary SQLite database | Phone and book events each created a review case |
| Existing head-pose detector | Initialized successfully |
| Dependency consistency | `pip check` reported no broken requirements |
| Model preparation / CLI / syntax | Local preparation, help command and compilation passed |

The final annotated image is `validation-output/live-test/final-45.jpg`.
The final sequence, tracks, scores and measured timings are in
`validation-output/live-test/final-sequence.json`. Captures and diagnostic
outputs stay local and are ignored by Git.

The final checks used the already captured webcam frames. No additional live
positive test was performed after the final model change. The five frames are
correlated observations from one camera setup, not five independent trials.
The size tests reduce image pixels; they do not establish a distance in metres.

## Remaining limits

The tested webcam provided 1280x720. CPU inference was about 2.6 seconds per
frame; the small-book refinement increased that to about 4.4 seconds. The
scope's 6-fps requirement is not met on this CPU. CUDA is supported but was
not available for local validation. The camera display updates at inference
speed, and initial confirmation/alerting takes several seconds.

This fixes the supplied phone/book failure case. It does not establish perfect
accuracy across classrooms, different books/phones, camera angles, occlusion,
blur or poor lighting. Independent positive and negative recordings are needed
to measure precision, recall and false-alert rate before deployment. Paper,
calculators and other objects are outside the agreed policy.
