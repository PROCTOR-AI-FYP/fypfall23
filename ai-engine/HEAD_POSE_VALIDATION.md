# Calibrated head pose

The earlier six-point EPNP path mixed the Euler axes and used an upside-down
generic model frame. One forward-facing capture returned yaw -6.2°, pitch
-31.6°, roll -175.5°. It falsely treated that view as looking down.

The replacement uses MediaPipe Face Landmarker's canonical-face transformation
matrix. Its 3×3 rotation is checked for finite values, proper handedness and
scale consistency, then orthonormalised with SVD. The transform follows
MediaPipe's right-handed space with camera looking along negative Z:

`R = Rz(roll) Ry(yaw) Rx(-pitch)`

Yaw is positive towards the right of an **unmirrored input image**, pitch is
negative down, and roll is positive counterclockwise in that image. Display
mirroring must not be applied before inference. Pitch is not yaw, and roll is
not the sideways-turn alert angle. Translation and uniform scale cannot
become head angles.

## Neutral posture and policy

On the local website, start monitoring and click **Set neutral pose**. Sit in
the normal working posture, including permitted desk reading for a paper
exam, and hold still for two seconds. Calibration requires at least eight
valid observations; movement over 5°, missing/multiple faces and long frame
gaps restart it. A head already turned over 35° cannot be set as neutral.

Neutral rotation is averaged on the rotation manifold. Each subsequent
orientation is relative to it (`Rneutral.T @ Rcurrent`), rather than subtracting
Euler numbers. This compensates for normal camera/posture offset. Recalibrate
after moving the camera, changing the monitored person or changing the exam
working posture. A camera resolution change invalidates the baseline.

Matrix smoothing has a 120 ms time constant. Yaw beyond ±30° or downward pitch
below -20° must remain continuously outside the limits for two seconds. A 3°
exit hysteresis reduces threshold chatter. Missing/unreliable faces, frame
gaps over 0.5 seconds and clock reversal reset the timer and clear the angles.
Roll is displayed, but does not independently become a sideways-turn signal.

The existing composite policy is preserved: head pose has weight 0.65 and
the review threshold is 0.75. A sustained head turn shows a warning on the
website. It combines with stronger object evidence in the existing scorer;
head pose alone does not manufacture a review case or a probability of guilt.

## Run and verify

```powershell
.\venv\Scripts\python.exe ai-engine/prepare_models.py --face
.\scripts\start-local.ps1
# Optional standalone preview: c calibrates, q exits
.\venv\Scripts\python.exe ai-engine/head_pose_detector.py
# Close the website camera before using the standalone preview.
.\venv\Scripts\python.exe -m pytest ai-engine/test_head_pose.py ai-engine/test_web_integration.py -q -p no:cacheprovider
```

Geometry tests independently construct known yaw/pitch/roll rotations using
Rodrigues axis-angle rotations, including combined rotations and a tilted
neutral camera. They also cover scale/translation, reflection/degeneracy,
timing, missing faces, calibration instability, recalibration and resolution
changes. Web tests cover calibration, teardown and the unchanged head-only
policy versus combined phone/head cases, using a disposable database.

The model was also checked on actual saved camera frames. The same forward
capture now produced approximately 8.7° yaw, -2.4° pitch and 6.6° roll. This
comparison removes the observed gross axis error; it is not measured physical
angle ground truth. Results are in the local, Git-excluded
`validation-output/head-pose-saved-frame-check.json`.

Guided physical webcam results are recorded through the actual backend by
`validate_head_pose_live.py` and saved locally under
`validation-output/head-pose-live/`. Frames and traces are excluded from Git.

The 2026-10-04 guided check used the real webcam, local backend and website:

| Check | Observed result |
| --- | --- |
| Normal posture after calibration | 45 valid samples, no sustained warning |
| Turn toward image left | Negative yaw; sustained warning in 31 samples |
| Upright turn toward image right | Median yaw +36.6°, range +33.9° to +40.4°; all 55 samples sustained |
| Partial opposite turn with tilt | About +24° yaw and −25° roll; no false sideways warning |

Preview speed was approximately 15 FPS, with typical head inference around
20–21 ms. These are measured head-pose checks; the separate phone/book model
still performs background checks taking several seconds.

The physical downward check did not establish a sustained warning: one
capture measured roughly −15° relative pitch; a repeat captured tilt and
intermittent face loss instead of a continuously tracked pitch below −20°.
This remains an unconfirmed live test, not a pass. Known-rotation tests cover
the negative pitch direction, the −20° threshold, continuous two-second timing
and clearing the warning on return to neutral. A final service restart loaded
the recovery fixes and reset the calibration; set neutral again before use.

The combined AI and local web regression suite passed **102 tests**. The
production frontend build also passed. Tests use disposable storage; they do
not run the platform test suite that clears the configured database.

## Deployment limits

This local monitor intentionally handles **one clear student face per view**.
It suppresses angle attribution when multiple faces are visible. Whole-class
deployment needs a tracked, seat-associated face crop and separate calibration
and timers per student. Applying one person's baseline to a room is incorrect.
Head orientation does not measure eye gaze, identify a person or prove cheating.

Monocular angles are estimates. Glasses, occlusion, profile views, small faces,
camera perspective and face-shape differences affect accuracy. The source
rejects faces smaller than 60×70 pixels in its at-most-640-pixel input. No
benchmark accuracy claim or guarantee of perfect measurement is made. A
classroom evaluation with independent physical-angle ground truth is still
required for the FYP's sensitivity and false-positive targets.

Primary references:
- [MediaPipe Face Landmarker Python guide](https://developers.google.com/edge/mediapipe/solutions/vision/face_landmarker/python)
- [MediaPipe face geometry coordinate conventions](https://github.com/google-ai-edge/mediapipe/blob/master/docs/solutions/face_mesh.md#metric-3d-space)

The previous implementation is preserved locally in
`checkpoints/head-pose-before-fix-2026-10-04.zip`.
