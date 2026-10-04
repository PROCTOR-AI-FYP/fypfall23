"""Compare model recall/precision on labelled COCO images (not classroom validation)."""
import argparse
import json
import time
from pathlib import Path

import cv2
import numpy as np


def iou(a, b):
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    intersection = max(0, x2 - x1) * max(0, y2 - y1)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - intersection
    return intersection / union if union else 0.0


def samples(dataset, scale=1.0):
    for path in sorted((dataset / 'images/train2017').glob('*.jpg')):
        image = cv2.imread(str(path))
        h, w = image.shape[:2]
        truth = []
        label_path = dataset / 'labels/train2017' / (path.stem + '.txt')
        for line in (label_path.read_text().splitlines() if label_path.exists() else []):
            cls, x, y, bw, bh = map(float, line.split())
            if int(cls) in (67, 73):
                truth.append(('phone' if int(cls) == 67 else 'book',
                              [(x - bw / 2) * w, (y - bh / 2) * h,
                               (x + bw / 2) * w, (y + bh / 2) * h]))
        if scale != 1:
            # A controlled pixel-size stress test, not a claim about physical distance.
            resized = cv2.resize(image, (max(1, round(w * scale)), max(1, round(h * scale))))
            canvas = np.full((1080, 1920, 3), 114, dtype=np.uint8)
            rh, rw = resized.shape[:2]
            ox, oy = (1920 - rw) // 2, (1080 - rh) // 2
            canvas[oy:oy + rh, ox:ox + rw] = resized
            sx, sy = rw / w, rh / h
            truth = [(name, [b[0] * sx + ox, b[1] * sy + oy, b[2] * sx + ox, b[3] * sy + oy])
                     for name, b in truth]
            image = canvas
        yield path.name, image, truth


def evaluate(predict, dataset, scale, limit=None):
    counts = {name: {'tp': 0, 'fp': 0, 'fn': 0} for name in ('phone', 'book')}
    timings, details = [], []
    for index, (filename, image, truth) in enumerate(samples(dataset, scale)):
        if limit and index >= limit:
            break
        start = time.perf_counter()
        detections = predict(image)
        timings.append(time.perf_counter() - start)
        matched = set()
        for name, box, score in sorted(detections, key=lambda d: -d[2]):
            candidates = [(iou(box, target), i) for i, (label, target) in enumerate(truth)
                          if i not in matched and label == name]
            overlap, match = max(candidates, default=(0, -1))
            if overlap >= 0.5:
                counts[name]['tp'] += 1
                matched.add(match)
            else:
                counts[name]['fp'] += 1
        for i, (name, _) in enumerate(truth):
            if i not in matched:
                counts[name]['fn'] += 1
        details.append({'image': filename, 'ground_truth': truth,
                        'predictions': [(name, [float(v) for v in box], float(score))
                                        for name, box, score in detections]})
        if index % 20 == 0:
            print(f'  {index + 1} images', flush=True)
    for values in counts.values():
        tp, fp, fn = values['tp'], values['fp'], values['fn']
        values['precision'] = round(tp / (tp + fp), 3) if tp + fp else 0
        values['recall'] = round(tp / (tp + fn), 3) if tp + fn else 0
    return {'objects': counts, 'images': len(timings),
            'median_seconds': round(float(np.median(timings)), 3), 'details': details}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', type=Path, default=Path(__file__).parent / 'test-data/coco128')
    parser.add_argument('--output', type=Path, default=Path(__file__).parent / 'validation-output/benchmark.json')
    parser.add_argument('--scale', type=float, default=1)
    parser.add_argument('--limit', type=int)
    parser.add_argument('--mode', choices=['models', 'detector', 'baseline'], default='models')
    parser.add_argument('--phone-threshold', type=float, default=0.35)
    parser.add_argument('--book-threshold', type=float, default=0.40)
    parser.add_argument('--tile-size', type=int, default=640)
    parser.add_argument('--full-imgsz', type=int, default=960)
    parser.add_argument('--model', type=Path)
    args = parser.parse_args()
    results = {}
    if args.mode == 'models':
        from ultralytics import YOLO
        for filename in ('proctoring_yolov8n_best.pt', 'yolo11s.pt'):
            model = YOLO(Path(__file__).parent / 'models' / filename)
            classes = {i: 'phone' if name == 'cell phone' else 'book' for i, name in model.names.items()
                       if name in ('cell phone', 'book')}
            for threshold in (0.6, 0.35):
                def predict(image):
                    result = model.predict(image, classes=list(classes), conf=threshold, imgsz=960,
                                           verbose=False)[0]
                    return [(classes[int(c)], list(b), float(s)) for b, c, s in
                            zip(result.boxes.xyxy.cpu().numpy(), result.boxes.cls.cpu().numpy(),
                                result.boxes.conf.cpu().numpy())]
                key = f'{filename}@{threshold}'
                print(key, flush=True)
                results[key] = evaluate(predict, args.dataset, args.scale, args.limit)
                print({k: v for k, v in results[key].items() if k != 'details'}, flush=True)
    elif args.mode == 'baseline':
        from ultralytics import YOLO
        model = YOLO(Path(__file__).parent / 'models/proctoring_yolov8n_best.pt')
        def predict(image):
            h, w = image.shape[:2]
            tw, th = (w + int(w * 0.2)) // 2, (h + int(h * 0.2)) // 2
            boxes, scores = [], []
            for ox, oy in [(0, 0), (w - tw, 0), (0, h - th), (w - tw, h - th)]:
                result = model.predict(image[oy:oy + th, ox:ox + tw], conf=0.6, verbose=False)[0]
                for box, cls, score in zip(result.boxes.xyxy.cpu().numpy(), result.boxes.cls.cpu().numpy(),
                                           result.boxes.conf.cpu().numpy()):
                    if model.names[int(cls)] != 'cell phone':
                        continue  # the original code excludes books completely
                    x1, y1, x2, y2 = box
                    boxes.append([float(x1 + ox), float(y1 + oy), float(x2 - x1), float(y2 - y1)])
                    scores.append(float(score))
            indices = cv2.dnn.NMSBoxes(boxes, scores, 0.6, 0.45)
            return [('phone', [boxes[int(i)][0], boxes[int(i)][1],
                               boxes[int(i)][0] + boxes[int(i)][2], boxes[int(i)][1] + boxes[int(i)][3]],
                     scores[int(i)]) for i in np.asarray(indices).flatten()]
        results['original_detector'] = evaluate(predict, args.dataset, args.scale, args.limit)
        print({k: v for k, v in results['original_detector'].items() if k != 'details'}, flush=True)
    else:
        from phone_detector import PhoneDetector
        detector = PhoneDetector(args.phone_threshold, book_threshold=args.book_threshold,
                                 tile_size=args.tile_size, full_imgsz=args.full_imgsz, model_path=args.model)
        def predict(image):
            return [('phone' if d.type == 'PHONE_DETECTED' else 'book', d.box, d.confidence)
                    for d in detector.detect(image) if d.confidence >= detector.thresholds[d.type]]
        results['detector'] = evaluate(predict, args.dataset, args.scale, args.limit)
        print({k: v for k, v in results['detector'].items() if k != 'details'}, flush=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()
