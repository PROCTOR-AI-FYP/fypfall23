"""Download pinned official Grounding DINO files once; detection runs offline."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import urllib.request
from pathlib import Path

REVISION = 'a2bb814dd30d776dcf7e30523b00659f4f141c71'
FILES = ['added_tokens.json', 'config.json', 'model.safetensors', 'preprocessor_config.json',
         'special_tokens_map.json', 'tokenizer.json', 'tokenizer_config.json', 'vocab.txt']


def download(url, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_file() and target.stat().st_size:
        print(f'Already present: {target.name}')
        return
    temporary = target.with_suffix(target.suffix + '.download')
    try:
        urllib.request.urlretrieve(url, temporary)
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    print(f'Downloaded: {target.name}', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--yolo', action='store_true', help='Also prepare the optional faster YOLO model')
    parser.add_argument('--face', action='store_true', help='Prepare only the head-pose face model')
    args = parser.parse_args()
    root = Path(__file__).parent / 'models'
    download('https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task',
             root / 'face_landmarker.task')
    if args.face:
        return
    def prepare(name):
        download(f'https://huggingface.co/IDEA-Research/grounding-dino-tiny/resolve/{REVISION}/{name}',
                 root / 'grounding-dino-tiny' / name)
    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(prepare, FILES))
    if args.yolo:
        download('https://github.com/ultralytics/assets/releases/download/v8.3.0/yolo11s.pt', root / 'yolo11s.pt')
    print('Ready. Live inference uses local files only.')


if __name__ == '__main__':
    main()
