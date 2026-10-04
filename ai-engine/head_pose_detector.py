"""
head_pose_detector.py — detects sustained head-turn/tilt (looking away
from screen) using MediaPipe FaceMesh landmarks + OpenCV solvePnP.

IMPORTANT — read before trusting this:
solvePnP is the single most likely place for a plausible-but-wrong
result. Run this in DEBUG mode, physically turn your head to a KNOWN
angle (e.g. turn to look at something ~30-40 degrees to your side,
or ask someone to check with a phone compass/protractor app), and
confirm the printed yaw number is in a sane range for that turn. If the
number reads near 0 when you're clearly turned, or near 90 when you're
barely turned, the 3D model correspondence points or axis convention
below need fixing before you trust this for anything else.
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from collections import deque

import cv2
import numpy as np
import mediapipe as mp
import urllib.request
from pathlib import Path

# --------------------------------------------------------------------------
# Tunable constants
# --------------------------------------------------------------------------

YAW_THRESHOLD_DEG = 30.0      # fires if |yaw| exceeds this
PITCH_THRESHOLD_DEG = -20.0   # fires if pitch drops BELOW this (looking down)
SUSTAINED_SECONDS = 2.0       # must persist this long before firing

# MediaPipe FaceMesh landmark indices for the 6 points we use.
# These correspond to: nose tip, chin, left eye outer corner,
# right eye outer corner, left mouth corner, right mouth corner.
# (MediaPipe's own face is mirrored in image space, i.e. landmark "left"
# corresponds to the subject's own right side as seen on screen — this
# doesn't matter for pose math as long as the 3D model points below use
# the SAME left/right convention consistently.)
LANDMARK_IDS = {
    "nose_tip": 1,
    "chin": 152,
    "right_eye_outer": 33,   # MediaPipe landmark 33 = subject's RIGHT eye
    "left_eye_outer": 263,   # MediaPipe landmark 263 = subject's LEFT eye
    "right_mouth": 61,       # MediaPipe landmark 61 = subject's RIGHT mouth corner
    "left_mouth": 291,       # MediaPipe landmark 291 = subject's LEFT mouth corner
}

# Generic 3D face model points (arbitrary units, roughly millimeters),
# in the SAME order as LANDMARK_IDS above. This is a standard reference
# model widely used for solvePnP head-pose demos, centered near the nose.
# NOTE: order below is nose, chin, RIGHT eye, LEFT eye, RIGHT mouth,
# LEFT mouth — matching LANDMARK_IDS exactly. X-axis convention:
# positive X = subject's left (screen-right when facing camera), so the
# subject's right-side points get NEGATIVE X, left-side points get
# POSITIVE X.
MODEL_POINTS_3D = np.array(
    [
        (0.0, 0.0, 0.0),          # nose tip
        (0.0, -330.0, -65.0),     # chin
        (-225.0, 170.0, -135.0), # right eye outer corner (subject's right = -X)
        (225.0, 170.0, -135.0),  # left eye outer corner (subject's left = +X)
        (-150.0, -150.0, -125.0),# right mouth corner
        (150.0, -150.0, -125.0), # left mouth corner
    ],
    dtype=np.float64,
)


@dataclass
class DetectionEvent:
    type: str
    confidence: float
    timestamp: float


@dataclass
class PoseResult:
    yaw: float
    pitch: float
    roll: float


class HeadPoseDetector:
    def __init__(
        self,
        yaw_threshold: float = YAW_THRESHOLD_DEG,
        pitch_threshold: float = PITCH_THRESHOLD_DEG,
        sustained_seconds: float = SUSTAINED_SECONDS,
        debug: bool = False,
    ):
        self.yaw_threshold = yaw_threshold
        self.pitch_threshold = pitch_threshold
        self.sustained_seconds = sustained_seconds
        self.debug = debug

        _MODEL_PATH = Path(__file__).parent / "models" / "face_landmarker.task"
        if not _MODEL_PATH.exists():
            _MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
            print("Downloading FaceLandmarker model...")
            url = "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task"
            urllib.request.urlretrieve(url, str(_MODEL_PATH))

        BaseOptions = mp.tasks.BaseOptions
        FaceLandmarker = mp.tasks.vision.FaceLandmarker
        FaceLandmarkerOptions = mp.tasks.vision.FaceLandmarkerOptions
        VisionRunningMode = mp.tasks.vision.RunningMode

        options = FaceLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(_MODEL_PATH)),
            running_mode=VisionRunningMode.IMAGE,
            num_faces=1,
            min_face_detection_confidence=0.5,
            min_face_presence_confidence=0.5,
            min_tracking_confidence=0.5
        )
        self.face_mesh = FaceLandmarker.create_from_options(options)

        # Tracks how long we've been continuously in violation, so we can
        # require it to be SUSTAINED rather than firing on a single noisy
        # frame.
        self._violation_start_time: float | None = None
        self._last_pose: PoseResult | None = None

    def _estimate_pose(self, frame) -> PoseResult | None:
        h, w = frame.shape[:2]
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        results = self.face_mesh.detect(mp_image)

        if not results.face_landmarks:
            return None

        landmarks = results.face_landmarks[0]

        image_points = np.array(
            [
                (landmarks[LANDMARK_IDS["nose_tip"]].x * w,
                 landmarks[LANDMARK_IDS["nose_tip"]].y * h),
                (landmarks[LANDMARK_IDS["chin"]].x * w,
                 landmarks[LANDMARK_IDS["chin"]].y * h),
                (landmarks[LANDMARK_IDS["right_eye_outer"]].x * w,
                 landmarks[LANDMARK_IDS["right_eye_outer"]].y * h),
                (landmarks[LANDMARK_IDS["left_eye_outer"]].x * w,
                 landmarks[LANDMARK_IDS["left_eye_outer"]].y * h),
                (landmarks[LANDMARK_IDS["right_mouth"]].x * w,
                 landmarks[LANDMARK_IDS["right_mouth"]].y * h),
                (landmarks[LANDMARK_IDS["left_mouth"]].x * w,
                 landmarks[LANDMARK_IDS["left_mouth"]].y * h),
            ],
            dtype=np.float64,
        )

        focal_length = w
        center = (w / 2, h / 2)
        camera_matrix = np.array(
            [
                [focal_length, 0, center[0]],
                [0, focal_length, center[1]],
                [0, 0, 1],
            ],
            dtype=np.float64,
        )
        dist_coeffs = np.zeros((4, 1))  # assume no lens distortion

        success, rotation_vec, _translation_vec = cv2.solvePnP(
            MODEL_POINTS_3D,
            image_points,
            camera_matrix,
            dist_coeffs,
            flags=cv2.SOLVEPNP_EPNP,
        )

        if not success:
            return None

        rotation_mat, _ = cv2.Rodrigues(rotation_vec)

        # Decompose rotation matrix into Euler angles (yaw, pitch, roll)
        # using the standard sy/singular-check approach.
        sy = np.sqrt(rotation_mat[0, 0] ** 2 + rotation_mat[1, 0] ** 2)
        singular = sy < 1e-6

        if not singular:
            pitch = np.degrees(np.arctan2(-rotation_mat[2, 0], sy))
            yaw = np.degrees(np.arctan2(rotation_mat[1, 0], rotation_mat[0, 0]))
            roll = np.degrees(np.arctan2(rotation_mat[2, 1], rotation_mat[2, 2]))
        else:
            pitch = np.degrees(np.arctan2(-rotation_mat[2, 0], sy))
            yaw = 0.0
            roll = np.degrees(np.arctan2(-rotation_mat[1, 2], rotation_mat[1, 1]))

        return PoseResult(yaw=yaw, pitch=pitch, roll=roll)

    def process_frame(self, frame) -> DetectionEvent | None:
        """
        Returns a DetectionEvent only once the violation has been
        sustained for self.sustained_seconds. Returns None otherwise,
        including on every frame before the sustain threshold is met.
        """
        pose = self._estimate_pose(frame)
        now = time.time()

        if pose is None:
            # No face found this frame — reset the sustain timer. We do
            # NOT fire on "no face detected", since that's ambiguous
            # (could be a tracking blip), not a confirmed violation.
            self._violation_start_time = None
            self._last_pose = None
            return None

        self._last_pose = pose

        is_violating = (
            abs(pose.yaw) > self.yaw_threshold
            or pose.pitch < self.pitch_threshold
        )

        if not is_violating:
            self._violation_start_time = None
            return None

        if self._violation_start_time is None:
            self._violation_start_time = now
            return None

        elapsed = now - self._violation_start_time
        if elapsed < self.sustained_seconds:
            return None

        # Confidence scales with how far past threshold we are, capped at 1.0
        yaw_excess = max(0.0, abs(pose.yaw) - self.yaw_threshold)
        pitch_excess = max(0.0, self.pitch_threshold - pose.pitch)
        excess = max(yaw_excess, pitch_excess)
        confidence = min(1.0, 0.5 + excess / 60.0)

        return DetectionEvent(
            type="HEAD_POSE_VIOLATION",
            confidence=confidence,
            timestamp=now,
        )

    def annotate_frame(self, frame):
        """Overlays computed yaw/pitch/roll as text, for debug mode."""
        annotated = frame.copy()
        if self._last_pose is None:
            cv2.putText(
                annotated, "No face detected", (10, 60),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2,
            )
            return annotated

        pose = self._last_pose
        violating = (
            abs(pose.yaw) > self.yaw_threshold
            or pose.pitch < self.pitch_threshold
        )
        color = (0, 0, 255) if violating else (0, 255, 0)

        cv2.putText(
            annotated, f"yaw: {pose.yaw:+.1f} deg", (10, 60),
            cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2,
        )
        cv2.putText(
            annotated, f"pitch: {pose.pitch:+.1f} deg", (10, 90),
            cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2,
        )
        cv2.putText(
            annotated, f"roll: {pose.roll:+.1f} deg", (10, 120),
            cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2,
        )
        return annotated


def main() -> None:
    detector = HeadPoseDetector(debug=True)

    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("ERROR: Could not open webcam. Run camera_check.py first.")
        sys.exit(1)

    print(
        "Running live in DEBUG mode. Turn your head to a KNOWN angle and "
        "verify the printed yaw/pitch looks correct BEFORE trusting this. "
        "Press 'q' to quit."
    )

    while True:
        ret, frame = cap.read()
        if not ret:
            print("ERROR: Failed to read frame from webcam.")
            break

        event = detector.process_frame(frame)
        if event:
            print(
                f"ALERT: {event.type} "
                f"conf={event.confidence:.2f} "
                f"t={event.timestamp:.1f}"
            )

        annotated = detector.annotate_frame(frame)
        cv2.imshow("Head Pose Detector (debug) - press q to quit", annotated)

        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
