"""Bundle the tested local object detector for the backend Docker build."""
from pathlib import Path

root = Path(__file__).resolve().parents[1]
target = root / 'backend/app/vision'
target.mkdir(exist_ok=True)
(target / '__init__.py').write_text('', encoding='utf-8')
phone = (root / 'ai-engine/phone_detector.py').read_text(encoding='utf-8')
phone = phone.replace('from grounding_detector import GroundingModel', 'from .grounding import GroundingModel')
(target / 'phone.py').write_text(phone, encoding='utf-8')
ground = (root / 'ai-engine/grounding_detector.py').read_text(encoding='utf-8')
ground = ground.replace('        from torchvision.ops import box_iou', '''        def box_iou(a, b):
            intersection = (torch.minimum(a[:, None, 2:], b[None, :, 2:]) -
                            torch.maximum(a[:, None, :2], b[None, :, :2])).clamp(min=0).prod(-1)
            areas_a = (a[:, 2:] - a[:, :2]).prod(-1)
            areas_b = (b[:, 2:] - b[:, :2]).prod(-1)
            return intersection / (areas_a[:, None] + areas_b[None, :] - intersection).clamp(min=1e-9)''')
(target / 'grounding.py').write_text(ground, encoding='utf-8')
