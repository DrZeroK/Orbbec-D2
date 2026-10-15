"""Mocked worker integration; never opens USB, saves faces or runs a face model."""
from contextlib import ExitStack
import hashlib
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import numpy as np
try:
    import cv2
except ImportError:
    cv2 = None
import face_engine as engine


@unittest.skipUnless(cv2 is not None and sys.platform == 'linux', 'Uses target Linux OpenCV; all camera/model calls mocked')
class CaptureWiringTests(unittest.TestCase):
    def run_worker(self, geometry=True, stale=False, reference=None, reject_every=0,
                   tick=.05, operation='verify', inference_delay=0, rotated=False, no_face=False):
        clock_value = [1000.0]
        def clock():
            clock_value[0] += tick
            return clock_value[0]

        yy, xx = np.indices((400,640))
        ir = (80+(xx+3*yy)%100).astype(np.uint16)
        depth = np.full((400,640), 700, dtype=np.uint16)
        class Camera:
            intrinsics = (480,400,319.5,199.5)
            distortion = (0,0,0,0,0)
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self):
                return depth, ir, {'received_at':clock()-(1 if stale else 0)}

        recognizer = Mock()
        recognizer.alignCrop.return_value = np.zeros((112,112,3), dtype=np.uint8)
        def feature(*args):
            clock_value[0] += inference_delay
            return np.array([[1.0]+[0.0]*127], dtype=np.float32)
        recognizer.feature.side_effect = feature
        face = np.array([150,80,200,250,210,150,290,150,250,195,225,230,275,230,.99])
        self.preview_shapes = []
        class Preview:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def publish(inner, image):
                self.preview_shapes.append(image.shape[:2])
                self.last_preview = image.copy()

        def detection(detector, image):
            return face if not no_face and (not rotated or image.shape[:2] == (640,400)) else None
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            root = Path(directory)
            (root/'detector.onnx').write_bytes(b'synthetic-model-placeholder')
            models = {'detector.onnx':hashlib.sha256(b'synthetic-model-placeholder').hexdigest()}
            real_open = os.open
            def private_lease(path, flags, mode=0o777):
                return real_open(root/'lease', flags, mode)
            stack.enter_context(patch.dict(engine.MODELS, models, clear=True))
            stack.enter_context(patch('face_engine.D2Camera', Camera))
            stack.enter_context(patch('face_engine.time.monotonic', clock))
            stack.enter_context(patch('face_engine.os.open', side_effect=private_lease))
            stack.enter_context(patch('face_engine.detect_one', side_effect=detection))
            stack.enter_context(patch('face_engine.PreviewPublisher', Preview))
            stack.enter_context(patch('cv2.FaceDetectorYN_create', return_value=Mock()))
            stack.enter_context(patch('cv2.FaceRecognizerSF_create', return_value=recognizer))
            stack.enter_context(patch('cv2.Laplacian', return_value=np.array([[0,100],[100,0]])))
            judgments = [0]
            def judge_frame(*args):
                judgments[0] += 1
                accepted = geometry and (not reject_every or judgments[0] % reject_every != 0)
                return {'accepted':accepted, 'reason':'synthetic screening result'}
            judge = stack.enter_context(patch('face_pad.evaluate_face', side_effect=judge_frame))
            if stale:
                with self.assertRaisesRegex(RuntimeError, '过期'):
                    engine.capture('verify', root, {'embedding':reference or [1.0]+[0.0]*127})
                self.assertEqual(recognizer.feature.call_count, 0)
                return None
            result = engine.capture(operation, root, {'embedding':reference or [1.0]+[0.0]*127})
            if geometry:
                args = judge.call_args.args
                self.assertIs(args[0], depth)
                self.assertIs(args[1], ir)
            return result, recognizer.feature.call_count

    def test_only_joint_identity_and_geometry_generate_pad_proof(self):
        result, calls = self.run_worker()
        self.assertTrue(result['matched'])
        self.assertTrue(result['pad_passed'])
        self.assertEqual(result['policy'], engine.POLICY)
        self.assertGreaterEqual(result['samples'], 5)
        self.assertGreaterEqual(calls, 5)

    def test_enrollment_framing_keeps_time_for_a_continuous_sample_streak(self):
        result, calls = self.run_worker(operation='enroll', tick=.005)
        self.assertTrue(result['pad_passed'])
        self.assertGreaterEqual(result['samples'], 5)
        self.assertLessEqual(result['samples'], 80)
        self.assertGreater(calls, 80)

    def test_geometry_rejection_never_runs_identity_or_unlocks(self):
        result, calls = self.run_worker(geometry=False)
        self.assertFalse(result['matched'])
        self.assertFalse(result['pad_passed'])
        self.assertEqual(calls, 0)

    def test_geometry_pass_cannot_override_wrong_identity(self):
        result, _ = self.run_worker(reference=[0.0,1.0]+[0.0]*126)
        self.assertFalse(result['matched'])
        self.assertFalse(result['pad_passed'])

    def test_rejected_frame_resets_streak_instead_of_adding_good_frames(self):
        result, calls = self.run_worker(reject_every=4)
        self.assertGreater(calls, 5)
        self.assertFalse(result['matched'])
        self.assertFalse(result['pad_passed'])

    def test_many_good_frames_inside_half_second_do_not_unlock(self):
        result, calls = self.run_worker(tick=.00001)
        self.assertGreater(calls, 5)
        self.assertFalse(result['matched'])
        self.assertFalse(result['pad_passed'])

    def test_stale_pair_is_not_counted_as_a_new_first_sample(self):
        self.run_worker(stale=True)

    def test_inference_timeout_does_not_count_an_expired_sample(self):
        result, calls = self.run_worker(tick=.005, inference_delay=.30)
        self.assertGreater(calls, 5)
        self.assertFalse(result['matched'])
        self.assertFalse(result['pad_passed'])

    def test_preview_orientation_is_corrected_even_when_geometry_rejects(self):
        result, calls = self.run_worker(geometry=False, rotated=True)
        self.assertFalse(result['pad_passed'])
        self.assertEqual(calls, 0)
        self.assertGreater(len(self.preview_shapes), 1)
        self.assertEqual(self.preview_shapes[-1], (640,400))

    def test_mount_preview_is_upright_before_any_face_is_detected(self):
        result, calls = self.run_worker(geometry=False, no_face=True)
        self.assertFalse(result['pad_passed'])
        self.assertEqual(calls, 0)
        yy, xx = np.indices((400,640))
        ir = (80+(xx+3*yy)%100).astype(np.uint16)
        image = engine.ir_identity_image(ir, cv2.createCLAHE(clipLimit=2, tileGridSize=(8,8)))
        np.testing.assert_array_equal(self.last_preview, np.rot90(image,1))


if __name__ == '__main__':
    unittest.main()
