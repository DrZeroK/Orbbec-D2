"""Trust-boundary tests; no camera, model inference, or real face data."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from face_engine import FaceEngine, checked_embedding, RECOGNITION_HASH


class FaceEngineTests(unittest.TestCase):
    def test_reject_malformed_features(self):
        for value in [None, [], [0.0]*128, [True]+[0.0]*127,
                      [float('nan')]+[0.0]*127, [float('inf')]+[0.0]*127]:
            with self.subTest(value=str(value)[:30]), self.assertRaises(ValueError):
                checked_embedding(value)

    def test_private_template_and_model_binding(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = FaceEngine(directory)
            old_ir = Path(directory)/'screen_face_ir.json'
            old_ir.write_text('original-ir-template')
            with patch.object(engine, '_run', return_value={'embedding':[1.0]+[0.0]*127, 'samples':5}):
                self.assertEqual(engine.enroll(), {'samples':5})
            self.assertEqual(engine.template.name, 'screen_face.json')
            self.assertEqual(old_ir.read_text(), 'original-ir-template')
            self.assertEqual(engine._template()[0], 1.0)
            if hasattr(__import__('os'), 'getuid'):
                self.assertEqual(engine.template.stat().st_mode & 0o777, 0o600)
            record = json.loads(engine.template.read_text())
            self.assertEqual(record['model'], RECOGNITION_HASH)
            record['model'] = 'wrong-model'
            engine.template.write_text(json.dumps(record))
            with self.assertRaises(ValueError):
                engine._template()

    def test_broken_enrollment_preserves_existing_template(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = FaceEngine(directory)
            engine.template.write_text('existing-private-data')
            with patch.object(engine, '_run', return_value={'embedding':[0.0]*128, 'samples':5}):
                with self.assertRaises(ValueError):
                    engine.enroll()
            self.assertEqual(engine.template.read_text(), 'existing-private-data')

    def test_bad_template_can_be_reenrolled_after_pin(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = FaceEngine(directory, directory)
            engine.template.write_text('broken-template')
            from face_engine import MODELS
            for name in MODELS:
                (Path(directory)/name).write_text('model-presence-only')
            with patch('face_engine.rgb_device', return_value='/dev/mock-d2'):
                state = engine.status()
            self.assertFalse(state['enrolled'])
            self.assertTrue(state['available'])
            self.assertTrue(state['error'])

    def test_rgb_status_is_independent_of_depth_sdk(self):
        import sys
        from face_engine import MODELS
        with tempfile.TemporaryDirectory() as directory:
            engine = FaceEngine(directory, directory)
            for name in MODELS:
                (Path(directory)/name).write_text('model-presence-only')
            engine.template.write_text(json.dumps({'version': 1, 'model': RECOGNITION_HASH,
                                                  'embedding': [1.0]+[0.0]*127}))
            with patch.dict(sys.modules, {'d2_camera': None, 'face_pad': None}), \
                    patch('face_engine.rgb_device', return_value='/dev/mock-d2'):
                state = engine.status()
            self.assertTrue(state['available'])
            self.assertTrue(state['enrolled'])
            self.assertEqual(state['error'], '')

    def test_invalid_sample_counts_cannot_replace_existing_rgb_template(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = FaceEngine(directory)
            engine.template.write_text('existing-private-data')
            for count in (True, '5', None, 4, 81, float('nan')):
                with self.subTest(count=count), patch.object(engine, '_run', return_value={
                        'embedding': [1.0]+[0.0]*127, 'samples': count}):
                    with self.assertRaises(RuntimeError):
                        engine.enroll()
                self.assertEqual(engine.template.read_text(), 'existing-private-data')

    def test_bad_worker_and_timeout_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = FaceEngine(directory)
            with patch('face_engine.subprocess.run', return_value=subprocess.CompletedProcess([], 0, '[]', '')):
                with self.assertRaises(RuntimeError):
                    engine._run('enroll')
            with patch('face_engine.subprocess.run', side_effect=subprocess.TimeoutExpired([], 18)):
                with self.assertRaisesRegex(RuntimeError, '超时'):
                    engine._run('enroll')


if __name__ == '__main__':
    unittest.main()
