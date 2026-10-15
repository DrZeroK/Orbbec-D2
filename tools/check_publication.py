"""Offline release checks: syntax, local Markdown links, forbidden private artifacts."""
import ast
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
SKIP = {'.git', '.venv', '__pycache__', 'build', 'downloads', 'local', 'openni_runtime'}
BAD_NAMES = {'credentials.json', 'screen_auth.json', 'screen_face.json', 'screen_face_ir.json',
             'factory_activation.json', '.vision_env'}
BINARY = {'.dll', '.so', '.exe', '.onnx', '.pgm', '.raw', '.npy', '.npz', '.pem', '.key'}


def check():
    errors, count = [], 0
    for file in ROOT.rglob('*'):
        rel = file.relative_to(ROOT)
        if any(part in SKIP for part in rel.parts) or not file.is_file():
            continue
        count += 1
        if file.name in BAD_NAMES or file.suffix in BINARY:
            errors.append(str(rel) + ': private/vendor artifact')
        if file.stat().st_size > 5 * 1024 * 1024:
            errors.append(str(rel) + ': unexpected large file')
        if file.suffix not in {'.py', '.md', '.json', '.cpp', '.h', '.cmd', '.ps1', '.txt', '.qml'}:
            continue
        text = file.read_text(encoding='utf-8-sig')
        if file.suffix == '.py':
            ast.parse(text, filename=str(rel))
        if file.suffix == '.json':
            json.loads(text)
        # Only recognizable credential signatures; synthetic test PINs are intentionally allowed.
        if re.search(r'gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|-----BEGIN (?:RSA |OPENSSH )?PRIVATE KEY-----', text):
            errors.append(str(rel) + ': possible credential')
        if file.suffix == '.md':
            for target in re.findall(r'\]\(([^)\s]+)\)', text):
                if target.startswith(('https://', 'http://', '#', 'mailto:')):
                    continue
                target = target.split('#', 1)[0]
                if target and not (file.parent / target).exists():
                    errors.append(str(rel) + ': broken local link ' + target)
    if errors:
        raise SystemExit('\n'.join(errors))
    print(json.dumps({'publication_checks': 'passed', 'files': count, 'hardware_access': False}))


if __name__ == '__main__':
    check()
