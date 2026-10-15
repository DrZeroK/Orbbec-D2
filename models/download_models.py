"""Download the two pinned OpenCV models; never install or start camera services."""
import argparse
import hashlib
import json
from pathlib import Path
from urllib.request import urlopen


def download(output):
    manifest = json.loads((Path(__file__).parent / 'manifest.json').read_text(encoding='utf8'))
    output.mkdir(parents=True, exist_ok=True)
    for model in manifest['models']:
        target = output / model['file']
        if target.exists():
            data = target.read_bytes()
        else:
            with urlopen(model['download_url'], timeout=60) as response:
                data = response.read(model['bytes'] + 1)
        if len(data) != model['bytes'] or hashlib.sha256(data).hexdigest() != model['sha256']:
            raise ValueError('Model size/SHA-256 mismatch: ' + model['file'])
        if not target.exists():
            with target.open('xb') as stream:
                stream.write(data)
        print(model['file'] + ': SHA-256 verified')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path, help='Private model directory, not a template directory')
    download(parser.parse_args().output)
