"""Real-AI website validation fixture, exclusively using a disposable DB.

Served on a separate port. Camera input is a clearly documented replay of the
locally captured scene, with controlled translation and later object removal.
The detector, smoothing, SQLite writes, socket events and website are real.
"""
import math
import os
import sys
import time
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
database = os.environ.get('PROCTORAI_DEMO_DATABASE_URL', '')
if not database.startswith('sqlite:///') or not database.endswith('/web-replay-test.db'):
    raise RuntimeError('Replay fixture requires a disposable SQLite web-replay-test.db.')

from backend import main as demo
from backend.object_monitor import ObjectMonitor, runtime_factory

loaded_runtime = None


def real_runtime():
    global loaded_runtime
    loaded_runtime = runtime_factory()
    return loaded_runtime


class RecordedCamera:
    def __init__(self):
        root = ROOT/'ai-engine/validation-output'
        self.positive = cv2.imread(str(root/'live-test/frame-45.jpg'))
        self.negative = cv2.imread(str(root/'webcam-moderate.jpg'))
        if self.positive is None or self.negative is None:
            raise RuntimeError('The recorded validation images are missing.')
        self.first_ready = None

    def read(self):
        time.sleep(1/30)
        now = time.monotonic()
        if loaded_runtime is not None and loaded_runtime.ready and self.first_ready is None:
            self.first_ready = now
        elapsed = now-self.first_ready if self.first_ready is not None else 0
        if elapsed > 32:
            return True, self.negative.copy()
        dx,dy = round(24*math.sin(elapsed*.4)),round(8*math.sin(elapsed*.4))
        return True, cv2.warpAffine(self.positive,np.float32([[1,0,dx],[0,1,dy]]),
                                    (self.positive.shape[1],self.positive.shape[0]))

    def release(self):
        pass


demo.monitor = ObjectMonitor(demo.camera_alert_sink,camera=RecordedCamera,runtime=real_runtime)
app = demo.app
