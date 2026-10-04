"""
camera_check.py — sanity check that the webcam is accessible before
building anything else on top of it.

Run: python camera_check.py
Press 'q' in the video window to quit.
"""

import sys
import time

import cv2
from camera import open_camera


def main() -> None:
    cap = open_camera(0)

    if not cap.isOpened():
        print(
            "ERROR: Could not open webcam (index 0).\n"
            "  - Check that a webcam is physically connected.\n"
            "  - Check that no other application (Zoom, Teams, another "
            "Python process) is currently holding the camera.\n"
            "  - On Windows, check Settings > Privacy > Camera access is "
            "enabled for desktop apps.\n"
            "  - If you have multiple cameras, try index 1 or 2 instead "
            "of 0 in cv2.VideoCapture(...)."
        )
        sys.exit(1)

    print("Webcam opened successfully. Press 'q' in the window to quit.")

    prev_time = time.time()
    fps = 0.0

    while True:
        ret, frame = cap.read()
        if not ret:
            print("ERROR: Failed to read frame from webcam (camera may "
                  "have disconnected).")
            break

        now = time.time()
        elapsed = now - prev_time
        prev_time = now
        if elapsed > 0:
            # simple exponential smoothing so the FPS number doesn't jitter
            instant_fps = 1.0 / elapsed
            fps = fps * 0.9 + instant_fps * 0.1 if fps else instant_fps

        cv2.putText(
            frame,
            f"FPS: {fps:.1f}",
            (10, 30),
            cv2.FONT_HERSHEY_SIMPLEX,
            1,
            (0, 255, 0),
            2,
        )

        cv2.imshow("Camera Check - press q to quit", frame)

        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
