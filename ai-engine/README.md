# Phone and book detection

The local website now includes this detector. Run `./scripts/start-local.ps1`
from the project root and open http://127.0.0.1:5173/. The camera panel streams
annotated frames and sends sustained confirmed phone/book alerts to the saved
inbox. See `../backend/LOCAL_CAMERA_DEMO.md` for controls, data flow and validation.

The default detector recognises **phones and books**. Books emit
`UNAUTHORISED_OBJECT`; phones emit `PHONE_DETECTED`. The composite scorer gives
them weights 0.75 and 0.90 respectively. Other objects are outside this policy.

## Run from the project root (PowerShell)

The existing `venv` has the tested dependencies and downloaded model.

```powershell
.\venv\Scripts\python.exe ai-engine/phone_detector.py
```

Press **q** or close the camera window to exit. The default now shows a live
camera feed while the AI runs in a background worker. Gray "Checking" boxes
mark provisional objects; coloured boxes and alerts require two strong AI
observations of the same motion-tracked object. Optical flow keeps boxes
on the current image between AI checks. If flow loses abrupt movement, a
strong current-frame template or geometrically verified feature match can recover
the track, including rotation and scale changes. Feature loss, appearance mismatch or
expired verification removes a track. Separate objects have separate IDs.

The original accurate version was saved and verified before the speed changes:
`checkpoints/accurate-detection-2026-10-04.zip`. Its model checksum and source
checksums are in the adjacent JSON file. Model weights are retained in place.
To compare the original synchronous detector path:

```powershell
.\venv\Scripts\python.exe ai-engine/phone_detector.py --sync
```

To run the existing demo pipeline with head pose and backend alerts:

```powershell
.\venv\Scripts\python.exe ai-engine/main_pipeline.py
```

The demo pipeline posts to `http://localhost:8000/detection-event` and uses
session 1, as before. Start that demo backend separately. This change does not
connect the separate full platform backend to the camera pipeline.

## Setup on another machine

Install dependencies into a virtual environment, then explicitly download the
model once. Its weights are about 689 MB. Camera inference loads local files
only; no camera images are sent to a model service.

```powershell
python -m pip install -r ai-engine/requirements.txt
python ai-engine/prepare_models.py
```

The checkpoint is the official
[Grounding DINO Tiny](https://huggingface.co/IDEA-Research/grounding-dino-tiny),
pinned to revision `a2bb814dd30d776dcf7e30523b00659f4f141c71`. It recognised
the upright book that the tested YOLO and Faster R-CNN models missed. Fixed
text queries include fabric as a competing background class, but only phones
and books can become events. Ambiguous labels are discarded.

Default confirmation thresholds are 0.50 for phones and 0.60 for books, with
0.15 candidates for maintaining confirmed tracks. Small, uncertain books get
one additional native crop check. That check must recognise a book at the same
location above the normal threshold; it cannot promote an unrelated detection.

## Camera and performance

The camera setup requests 1920x1080 and reports what the device actually
provides. The tested webcam provided **1280x720**. More pixels and better light
help smaller objects; enlarging a frame cannot recover missing detail.

The corrected 640-pixel physical phone/book test reached **16.4 fps** over
40 seconds, with both objects confirmed in 155 frames. Current-frame processing
was a median 7.9 ms and p95 24.4 ms. Blur, rotation and weak recognition still
interrupted some tracks. AI recognition takes about 3 seconds per ordinary check.

The earlier 480-pixel live-camera pass reached **29.7 fps** with an empty camera
view. A controlled replay of the captured phone/book image, with movement and
removal, reached **21.6 fps**, and confirmed both objects after about **3.8 s**
once the model was loaded. Current-frame work took a median **11 ms** in that
replay, with a 95th percentile of **23 ms**.

The default live AI input is restored to **640 pixels**. A live failure report
revealed that the 480-pixel speed setting weakened recognition on new frames.
On three clear new frames, 640 gave book confidence 0.78–0.82, compared with
0.40–0.73 at 480. Ordinary 640 checks take about **2.9 s** on this CPU; focused
crops can take longer. `--imgsz 480` is an optional speed/accuracy tradeoff. Camera display and
motion tracking keep running during those checks, and pending work always
uses the latest frame instead of building a queue. Delayed AI boxes are aligned
through a short frame history before appearing on the live image. Two strong
AI confirmations still precede alerts. This is real-time visual tracking with
periodic AI recognition, not 30 new neural detections per second. A newly
introduced object takes several seconds to confirm.

The demo pipeline samples current tracking and head pose at 6 fps and sends
HTTP alerts in a worker so backend delays cannot freeze the camera. Synchronous
mode uses the original 640-pixel input and remains available with `--sync`.

For a supported CUDA GPU:

```powershell
.\venv\Scripts\python.exe ai-engine/phone_detector.py --device auto
```

For smaller objects, try `--imgsz 800` or `--imgsz 960`; these cost more time.
Use `--source 1` for another camera, or `--source path/to/recording.mp4` for video.

An optional faster YOLO path is available, with overlapping native-resolution
tiles. It detected the phone in the captured test but missed the upright book,
so it is not the default for this exam demo:

```powershell
python ai-engine/prepare_models.py --yolo
.\venv\Scripts\python.exe ai-engine/phone_detector.py --model ai-engine/models/yolo11s.pt --phone-threshold 0.35 --book-threshold 0.40
```

## Validation

```powershell
.\venv\Scripts\python.exe -m pytest ai-engine/test_phone_detector.py ai-engine/test_composite_scorer.py ai-engine/test_grounding_detector.py ai-engine/test_realtime.py -q -p no:cacheprovider
```

50 tests cover class mapping, crop coordinates, duplicate boxes, confirmation,
confidence dips, independent tracks, missing objects, track expiry, annotation
without repeating analysis, book alerts, time-based smoothing and crop checks.
They also cover delayed box alignment, latest-frame queuing, appearance-based
removal, motion-aware two-check confirmation, weak-observation rejection and
worker initialization errors, abrupt movement recovery and rejection of
unrelated textured objects, rotation/scale recovery and confirmation surviving
visual reinitialization without double-counting an observation.

The final model kept both tracks through the five captured positive frames,
including a blurred book. Synthetic 75% and 50% pixel-size tests confirmed both
objects. Three repeated checks of the captured negative frame emitted no events.
These are local regression results, not proof of perfect detection or a measured
physical-distance limit. Images from different rooms, books, phone orientations,
lighting conditions and distances are still needed for deployment validation.

`validate_objects.py` evaluates manually labelled local images with IoU >= 0.5
and saves overlays and JSON results. Include positive and negative images from
independent sessions. Example manifest:

```json
[
  {"image":"test.jpg","objects":[{"label":"phone","box":[100,100,180,250]}]},
  {"image":"negative.jpg","objects":[]}
]
```

```powershell
python ai-engine/validate_objects.py path/to/manifest.json
```

Local webcam captures and reports are in ignored `validation-output/`. Models,
runtime settings and downloaded test data are also ignored. `benchmark_models.py`
can reproduce the earlier YOLO comparisons using COCO128. COCO128 is a training
smoke dataset; it is not an independent classroom evaluation.

For repeatable speed measurements (the replay uses local captured images):

```powershell
.\venv\Scripts\python.exe ai-engine/benchmark_realtime.py --seconds 18
.\venv\Scripts\python.exe ai-engine/benchmark_realtime.py --camera 0 --seconds 24 --show
```

See `REALTIME_VALIDATION.md` for the current measurements and their limits.
