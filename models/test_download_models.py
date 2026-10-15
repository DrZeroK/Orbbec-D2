import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('model_download', Path(__file__).with_name('download_models.py'))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ModelDownloadTests(unittest.TestCase):
    def manifest(self):
        return json.dumps({'models': [{'file': 'example.onnx', 'bytes': 3,
            'sha256': hashlib.sha256(b'abc').hexdigest(), 'download_url': 'https://example.invalid/model'}]})

    def test_reject_bad_download_before_writing_payload(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(Path, 'read_text', return_value=self.manifest()), \
             patch.object(module, 'urlopen') as request:
            request.return_value.__enter__.return_value.read.return_value = b'bad'
            with self.assertRaises(ValueError):
                module.download(Path(directory))
            self.assertFalse((Path(directory) / 'example.onnx').exists())

    def test_verified_existing_file_is_not_downloaded_or_overwritten(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(Path, 'read_text', return_value=self.manifest()), \
             patch.object(module, 'urlopen') as request:
            target = Path(directory) / 'example.onnx'
            target.write_bytes(b'abc')
            module.download(Path(directory))
            request.assert_not_called()
            self.assertEqual(target.read_bytes(), b'abc')

    def test_bad_existing_file_is_preserved_and_rejected(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(Path, 'read_text', return_value=self.manifest()), \
             patch.object(module, 'urlopen') as request:
            target = Path(directory) / 'example.onnx'
            target.write_bytes(b'bad')
            with self.assertRaises(ValueError):
                module.download(Path(directory))
            request.assert_not_called()
            self.assertEqual(target.read_bytes(), b'bad')


if __name__ == '__main__':
    unittest.main()
