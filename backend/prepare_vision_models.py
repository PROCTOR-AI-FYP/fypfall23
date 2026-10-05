"""Download the pinned, public object model during the image build, never camera images."""
from pathlib import Path
from urllib.request import urlretrieve

REVISION = 'a2bb814dd30d776dcf7e30523b00659f4f141c71'
FILES = ['added_tokens.json', 'config.json', 'model.safetensors', 'preprocessor_config.json',
         'special_tokens_map.json', 'tokenizer.json', 'tokenizer_config.json', 'vocab.txt']
root = Path('/opt/proctorai/grounding-dino-tiny')
root.mkdir(parents=True, exist_ok=True)
for name in FILES:
    urlretrieve(f'https://huggingface.co/IDEA-Research/grounding-dino-tiny/resolve/{REVISION}/{name}', root / name)
    print(f'Prepared {name}', flush=True)
