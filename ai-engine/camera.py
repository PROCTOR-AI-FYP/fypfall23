"""Shared camera setup: preserve pixels needed to see phones across a room."""
import cv2
import sys


def open_camera(source=0, width=1920, height=1080):
    if isinstance(source, int) and sys.platform == 'win32':
        cap = cv2.VideoCapture(source, cv2.CAP_DSHOW)
        if not cap.isOpened():
            cap.release()
            cap = cv2.VideoCapture(source, cv2.CAP_MSMF)
    else:
        cap = cv2.VideoCapture(source)
    if isinstance(source, int):
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        cap.set(cv2.CAP_PROP_FPS, 30)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    if not cap.isOpened():
        cap.release()
        raise RuntimeError(f'Could not open camera/video {source}. Check camera access and other applications.')
    actual_width, actual_height = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    print(f'Capture resolution: {actual_width}x{actual_height}')
    if isinstance(source, int) and (actual_width < width or actual_height < height):
        print('WARNING: Camera did not provide 1080p. Small/distant objects have fewer usable pixels.')
    return cap
