"""Offline Grounding DINO adapter for the phone/book detector.

Text queries are fixed to the exam policy. Inference is local to this backend; images are not sent to external AI providers.
Uses the official, unmodified 900-query checkpoint; smaller image inputs
reduce CPU cost without changing the learned query embeddings.
"""
import logging
import os
from pathlib import Path, PurePosixPath
from types import SimpleNamespace

import cv2
import torch

PROMPT = 'a cell phone. a book. fabric.'
CLASS_PHRASES = ('cell phone', 'book', 'fabric')


def cpu_thread_budget(existing_threads, *, cpu_count=None, affinity_count=None, reader=None):
    """Honor CPU allocation while preserving the existing eight-thread cap.

    Inputs/readers can be supplied to test this without depending on the host.
    Cgroup metadata is optional: Windows and inaccessible/incomplete mounts
    safely fall back to the process affinity and reported processor count.
    """
    if cpu_count is None:
        cpu_count = os.cpu_count() or 1
    if affinity_count is None:
        try:
            affinity_count = len(os.sched_getaffinity(0))
        except (AttributeError, OSError):
            affinity_count = 0
    limits = [8, max(1, int(existing_threads)), max(1, int(cpu_count))]
    if affinity_count > 0:
        limits.append(int(affinity_count))
    if reader is None:
        reader = lambda path: Path(path).read_text(encoding='ascii')
    cache = {}

    def read(path):
        path = str(path)
        if path not in cache:
            try:
                cache[path] = reader(path).strip()
            except (OSError, ValueError, TypeError):
                cache[path] = ''
        return cache[path]

    def quota_limit(quota, period):
        try:
            quota, period = int(quota), int(period)
        except (TypeError, ValueError):
            return None
        # Negative/unlimited quotas and invalid/partial metadata impose no cap.
        return max(1, (quota + period - 1) // period) if quota > 0 and period > 0 else None

    memberships = {}
    for line in read('/proc/self/cgroup').splitlines():
        parts = line.split(':', 2)
        if len(parts) != 3:
            continue
        _, controllers, relative = parts
        path = PurePosixPath(relative)
        if not relative.startswith('/') or '..' in path.parts or len(path.parts) > 17:
            continue
        if controllers == '':
            memberships['v2'] = str(path).lstrip('/')
        elif 'cpu' in controllers.split(','):
            memberships['v1'] = str(path).lstrip('/')

    def directories(root, kind):
        # Process membership can be nested; the smallest ancestor allocation
        # wins. Four common mounted roots and at most sixteen ancestors bound
        # all reads, including containers whose mount hides the host prefix.
        root = PurePosixPath(root)
        candidate = root / memberships.get(kind, '')
        result = []
        for _ in range(17):
            result.append(candidate)
            if candidate == root:
                break
            candidate = candidate.parent
        if root not in result:
            result.append(root)
        return result

    for directory in directories('/sys/fs/cgroup', 'v2'):
        fields = read(directory / 'cpu.max').split()
        limit = quota_limit(*fields) if len(fields) == 2 else None
        if limit is not None:
            limits.append(limit)
    for root in ('/sys/fs/cgroup/cpu', '/sys/fs/cgroup/cpu,cpuacct', '/sys/fs/cgroup/cpuacct,cpu'):
        for directory in directories(root, 'v1'):
            limit = quota_limit(read(directory / 'cpu.cfs_quota_us'), read(directory / 'cpu.cfs_period_us'))
            if limit is not None:
                limits.append(limit)
    return max(1, min(limits))



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
            threads = cpu_thread_budget(torch.get_num_threads())
            torch.set_num_threads(threads)
            logging.getLogger('proctorai.grounding').info('Grounding DINO CPU inference uses %s PyTorch threads', threads)
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
        def box_iou(a, b):
            intersection = (torch.minimum(a[:, None, 2:], b[None, :, 2:]) -
                            torch.maximum(a[:, None, :2], b[None, :, :2])).clamp(min=0).prod(-1)
            areas_a = (a[:, 2:] - a[:, :2]).prod(-1)
            areas_b = (b[:, 2:] - b[:, :2]).prod(-1)
            return intersection / (areas_a[:, None] + areas_b[None, :] - intersection).clamp(min=1e-9)
        results = []
        for frame in images:
            rows = self._infer(frame, conf, imgsz)
            scene_rows = list(rows)
            context_phones = []
            context_checked = False
            # One student is framed centrally. When the scene has only weak
            # object candidates, preserve native detail in a bounded lower-centre
            # context view before attempting a phone close-up. No image upscaling
            # or lower confirmation threshold is used to manufacture a result.
            verified = any(score >= (.50 if cls == 0 else self.book_threshold)
                           for _,cls,score in rows)
            if not verified and any(score >= .25 for _,_,score in rows) and min(frame.shape[:2]) > 512:
                h,w = frame.shape[:2]
                side = 512
                x,y = (w-side)//2,h-side
                context_checked = True
                for refined,cls,confidence in self._infer(frame[y:y+side,x:x+side],conf,imgsz):
                    refined = refined + torch.tensor([x,y,x,y])
                    if cls == 1 and confidence >= self.book_threshold and any(
                            original_cls == 1 and float(box_iou(original[None],refined[None])[0,0]) >= .3
                            for original,original_cls,_ in scene_rows):
                        rows.append((refined,cls,confidence))
                    elif cls == 0 and confidence >= .25:
                        context_phones.append((refined,cls,confidence))
            books = [row for row in rows if row[1] == 1]
            if books and not context_checked:
                box, _, score = max(books, key=lambda row: row[2])
                # Recheck an uncertain SMALL book in a native-resolution crop.
                # A second view must recognise the same location at the normal
                # confirmation threshold; a weak crop cannot create an alert.
                if 0.25 <= score < self.book_threshold and max(float(box[2]-box[0]), float(box[3]-box[1])) <= 192:
                    h, w = frame.shape[:2]
                    side = min(512, h, w)
                    x = max(0, min(w-side, round(float((box[0]+box[2]-side)/2))))
                    y = max(0, min(h-side, round(float((box[1]+box[3]-side)/2))))
                    for refined, cls, confidence in self._infer(frame[y:y+side, x:x+side], conf, imgsz):
                        refined = refined + torch.tensor([x, y, x, y])
                        if cls == 1 and confidence >= self.book_threshold and float(box_iou(box[None], refined[None])[0, 0]) >= 0.3:
                            rows.append((refined, cls, confidence))
                        elif cls == 0 and .25 <= confidence < .50:
                            # Preserve a newly resolved small phone candidate for
                            # a separate, same-location verification below.
                            rows.append((refined,cls,confidence))
            # Small phones need native-resolution verification. Keep scene/fabric
            # competition and never promote a different location or a known book.
            verified_books = [box for box,cls,score in rows if cls == 1 and score >= self.book_threshold]
            candidates = [row for row in rows if row[1] == 0 and .25 <= row[2] < .50] + context_phones
            phones = [row for row in candidates
                      if not any(float(box_iou(row[0][None],book[None])[0,0]) >= .3 for book in verified_books)]
            if phones:
                box, _, _ = max(phones,key=lambda row:row[2])
                if max(float(box[2]-box[0]),float(box[3]-box[1])) <= 192:
                    h,w = frame.shape[:2]
                    side = min(320,h,w)
                    x = max(0,min(w-side,round(float((box[0]+box[2]-side)/2))))
                    y = max(0,min(h-side,round(float((box[1]+box[3]-side)/2))))
                    for refined,cls,confidence in self._infer(frame[y:y+side,x:x+side],conf,imgsz):
                        refined = refined + torch.tensor([x,y,x,y])
                        if cls == 0 and confidence >= .50 and float(box_iou(box[None],refined[None])[0,0]) >= .3:
                            rows.append((refined,cls,confidence))
            selected = [row for row in rows if row[1] in classes]
            boxes, ids, scores = ([row[k] for row in selected] for k in range(3))
            results.append(SimpleNamespace(boxes=SimpleNamespace(
                xyxy=torch.stack(boxes) if boxes else torch.empty((0, 4)),
                cls=torch.tensor(ids), conf=torch.tensor(scores))))
        return results
