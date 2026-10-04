# Head-pose notebook review — 2026-10-05

Reviewed all five cells of `C:\Users\ahmar\Downloads\headpose.ipynb` without
executing its Colab, installation or webcam cells. Verification used previously
saved camera frames, real MediaPipe inference, known 3D rotations and disposable
web integration fixtures. No webcam was opened for this review.

## Decision

Retain the calibrated canonical-face rotation estimator. The notebook uses the
same MediaPipe Face Landmarker model, not a better trained head-pose model.
Its horizontal image reflection was useful as a recovery technique; its angle
and student attribution code should not replace the existing estimator.

Problems in the notebook:

- `RQDecomp3x3` already returns degrees. Multiplication by 360 inflated known
  10°, 30° and 45° yaw rotations to 3,600°, 10,800° and 16,200°.
- Its six `solvePnP` object points mix image-pixel X/Y coordinates with normalized
  landmark depth. They are not a consistent 3D face model. Synthetic projections
  at ±40° produced incorrect directions and magnitudes; removing the degree
  multiplier alone cannot correct this construction.
- Face-list indices become student IDs and warning timers. List order does not
  establish identity and can change between frames.
- Its maximum-angle rule combines pitch, yaw and roll, without normal-posture
  calibration. A tilted head can therefore become a sideways-looking warning.
- The webcam loop uses IMAGE inference; it does not provide temporal tracking,
  seat binding or the project's authorized review workflow.

## Changes adopted

When the normal VIDEO pass finds no face, try a horizontally reflected view
using the same confidence limits and two-face ambiguity check. Track in the
successful view on subsequent frames, avoiding a second inference on every
valid frame. Original camera images, object detection and website feed are
unchanged. Recovered boxes are mapped back with `x = 1 - x`; rotations are
mapped back with `S R S`, where `S = diag(-1, 1, 1)`. This preserves proper
handedness and the project's yaw, pitch and roll conventions.

Invalidate the neutral reference after prolonged face loss, a long capture gap,
clock reversal or a multiple-face observation. Angles and warning timers clear
immediately when tracking is unavailable. The existing website reports the
state and offers **Set neutral pose**; no API or review-policy changes were needed.

## Evidence and limits

| Check | Result |
| --- | --- |
| Independent known rotations and head/source regressions | 47 passed |
| Full AI and web integration suite | 115 passed |
| Saved neutral frame | Calibration completed without warnings |
| Saved sideways frame | Old source: 0/8 detections; recovery source: 8/8 |
| Recovery performance in direct source replay | Initial recovery about 24 ms; subsequent valid samples about 13–17 ms |
| Saved right/down frames | No reliable face at existing confidence limits; no angles or warnings fabricated |
| Recorded pipeline after prolonged face loss | Reference cleared; neutral return required calibration; recalibration passed |

Tests also check both yaw directions, downward pitch, roll isolation, continuous
two-second warning timing, mirrored box alignment, unmodified input images,
strictly increasing VIDEO timestamps and rejection of ambiguous/reflected
transforms. Web regressions check calibration status, teardown, saved cases and
the existing combined phone/head policy.

The saved images contain existing overlays and are still frames replayed at
simulated timestamps, not fresh video or physical-angle ground truth. The saved
sideways frame measures below the 30° relative yaw threshold; recovery does not
justify lowering that threshold to force a warning. Increasing input size from
640 to 960 did not recover the right/down frames. The previous physical downward
test remains unconfirmed. No new live accuracy or whole-class monitoring claim
is made; one registered student is monitored per camera view.

Private inputs and detailed traces remain Git-excluded under
`validation-output/head-pose-live/` and `.runtime/headpose-notebook-review/`.

Primary references:

- [OpenCV calibration reference: RQDecomp3x3 and solvePnP](https://docs.opencv.org/4.13.0/d9/d0c/group__calib3d.html)
- [MediaPipe Face Landmarker Python guide](https://developers.google.com/edge/mediapipe/solutions/vision/face_landmarker/python)
