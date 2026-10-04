"""Offline Grounding DINO adapter for the phone/book detector.

Text queries are fixed to the exam policy. No images leave this computer.
Uses the official, unmodified 900-query checkpoint; smaller image inputs
reduce CPU cost without changing the learned query embeddings.
"""
from pathlib import Path
from types import SimpleNamespace

import cv2
import torch

PROMPT = 'a cell phone. a book. fabric.'
CLASS_PHRASES = ('cell phone', 'book', 'fabric')


def decode_classes(outputs, token_spans, shape, threshold):
    """Score noun tokens per class instead of comparing generated sentences.

    The processor can join an article from another phrase to a correctly
    recognised phone. Articles and punctuation must neither veto that phone
    nor supply confidence to a class whose noun was not recognised.
    """
    probabilities = outputs.logits[0].sigmoid()
    scores = torch.stack([probabilities[:, indices].amax(dim=-1)
                          for indices in token_spans], dim=-1)
    ranked, classes = scores.topk(2, dim=-1)
    # Include fabric in competition, and reject genuinely ambiguous classes.
    keep = (classes[:, 0] < 2) & (ranked[:, 0] >= threshold) & (ranked[:, 0]-ranked[:, 1] >= .05)
    selected = outputs.pred_boxes[0][keep]
    centers, sizes = selected[:, :2], selected[:, 2:]
    boxes = torch.cat((centers-sizes/2, centers+sizes/2), dim=-1)
    h, w = shape[:2]
    boxes = boxes * boxes.new_tensor([w, h, w, h])
    return [(box.detach().cpu(), int(cls), float(score))
            for box, cls, score in zip(boxes, classes[keep, 0], ranked[keep, 0])]


class GroundingModel:
    names = {0: 'cell phone', 1: 'book'}
    supports_tiling = False

    def __init__(self, path, device='cpu', book_threshold=0.60):
        from transformers import AutoConfig, AutoModelForZeroShotObjectDetection, AutoProcessor
        path = Path(path)
        required = ['config.json', 'model.safetensors', 'preprocessor_config.json', 'tokenizer.json']
        if not all((path / name).is_file() for name in required):
            raise FileNotFoundError(f'Incomplete model in {path}. Run python ai-engine/prepare_models.py')
        if device == 'auto':
            device = 'cuda' if torch.cuda.is_available() else 'cpu'
        self.device = device
        self.book_threshold = book_threshold
        if device == 'cpu':
            torch.set_num_threads(min(8, torch.get_num_threads()))
        config = AutoConfig.from_pretrained(str(path), local_files_only=True)
        config.disable_custom_kernels = True  # portable CPU implementation; no compiler/download
        self.processor = AutoProcessor.from_pretrained(str(path), local_files_only=True)
        offsets = self.processor.tokenizer(PROMPT, return_offsets_mapping=True)['offset_mapping']
        self.token_spans = []
        for phrase in CLASS_PHRASES:
            start = PROMPT.index(phrase)
            end = start + len(phrase)
            indices = [i for i, (left, right) in enumerate(offsets)
                       if right > left and left >= start and right <= end]
            if not indices:
                raise ValueError(f'No model tokens for {phrase}')
            self.token_spans.append(indices)
        self.network = AutoModelForZeroShotObjectDetection.from_pretrained(
            str(path), config=config, local_files_only=True).to(device).eval()

    def _infer(self, frame, conf, imgsz):
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        # Fabric supplies a competing label for curtains/cloth, rather than
        # forcing every rectangle into one of the two prohibited classes.
        inputs = self.processor(images=rgb, text=PROMPT,
                                size={'shortest_edge': round(imgsz * 0.6), 'longest_edge': imgsz},
                                return_tensors='pt').to(self.device)
        with torch.inference_mode():
            outputs = self.network(**inputs)
        return decode_classes(outputs, self.token_spans, frame.shape, conf)

    def predict(self, images, *, conf, classes, imgsz, **kwargs):
        from torchvision.ops import box_iou
        results = []
        for frame in images:
            rows = self._infer(frame, conf, imgsz)
            books = [row for row in rows if row[1] == 1]
            if books:
                box, _, score = max(books, key=lambda row: row[2])
                # Recheck an uncertain SMALL book in a native-resolution crop.
                # A second view must recognise the same location at the normal
                # confirmation threshold; a weak crop cannot create an alert.
                if 0.25 <= score < self.book_threshold and max(float(box[2]-box[0]), float(box[3]-box[1])) <= 128:
                    h, w = frame.shape[:2]
                    side = min(320, h, w)
                    x = max(0, min(w-side, round(float((box[0]+box[2]-side)/2))))
                    y = max(0, min(h-side, round(float((box[1]+box[3]-side)/2))))
                    for refined, cls, confidence in self._infer(frame[y:y+side, x:x+side], conf, imgsz):
                        refined = refined + torch.tensor([x, y, x, y])
                        if cls == 1 and confidence >= self.book_threshold and float(box_iou(box[None], refined[None])[0, 0]) >= 0.3:
                            rows.append((refined, cls, confidence))
            selected = [row for row in rows if row[1] in classes]
            boxes, ids, scores = ([row[k] for row in selected] for k in range(3))
            results.append(SimpleNamespace(boxes=SimpleNamespace(
                xyxy=torch.stack(boxes) if boxes else torch.empty((0, 4)),
                cls=torch.tensor(ids), conf=torch.tensor(scores))))
        return results
