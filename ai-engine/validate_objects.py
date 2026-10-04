"""Evaluate local annotated images without using the camera or posting alerts.

Manifest: [{"image": "relative.jpg", "objects": [{"label": "phone",
"box": [x1,y1,x2,y2]}]}]. Paths are relative to the manifest.
Use negatives (objects: []) as well as positive images from separate sessions.
"""
import argparse
import json
from pathlib import Path

import cv2

from benchmark_models import iou
from phone_detector import PhoneDetector


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('--model', type=Path)
    parser.add_argument('--output', type=Path, default=Path(__file__).parent / 'validation-output/local')
    args = parser.parse_args()
    detector = PhoneDetector(model_path=args.model)
    args.output.mkdir(parents=True, exist_ok=True)
    counts = {label: dict(tp=0, fp=0, fn=0) for label in ('phone', 'book')}
    rows = []
    for index, item in enumerate(json.loads(args.manifest.read_text())):
        image_path = args.manifest.parent / item['image']
        image = cv2.imread(str(image_path))
        if image is None:
            raise ValueError(f'Cannot read {image_path}')
        truth = item['objects']
        matched = set()
        # Repetition tests confirmation, not additional independent observations.
        detector.reset()
        detector.process_frame(image, 0)
        events = detector.process_frame(image, 0.1)
        found = []
        for event in events:
            candidates = [(iou(event.box, target['box']), k) for k, target in enumerate(truth)
                          if k not in matched and target['label'] == event.label]
            quality, match = max(candidates, default=(0, -1))
            valid = quality >= 0.5
            counts[event.label]['tp' if valid else 'fp'] += 1
            if valid:
                matched.add(match)
            found.append(dict(label=event.label, confidence=event.confidence, box=event.box,
                              matched=valid, iou=quality))
        for k, target in enumerate(truth):
            if k not in matched:
                counts[target['label']]['fn'] += 1
        cv2.imwrite(str(args.output / f'{index:04d}.jpg'), detector.annotate_frame(image))
        rows.append(dict(image=str(image_path), truth=truth, detections=found,
                         inference_seconds=detector.last_inference_seconds))
    result = dict(images=len(rows), matching='IoU >= 0.5, confirmed events', counts=counts, details=rows)
    (args.output / 'results.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(dict(images=len(rows), counts=counts), indent=2))


if __name__ == '__main__':
    main()
