"""D2 appearance processing must preserve the native depth/IR coordinate grid."""
import unittest
try:
    import cv2
    import numpy as np
except ImportError:
    cv2 = None

from face_engine import ir_identity_image


@unittest.skipUnless(cv2 is not None, 'Needs target OpenCV')
class IRIdentityImageTests(unittest.TestCase):
    def test_appearance_does_not_resize_or_modify_raw_measurements(self):
        yy, xx = np.indices((400, 640))
        raw = ((xx+yy) % 256*4).astype(np.uint16)
        previous = raw.copy()
        image = ir_identity_image(raw, cv2.createCLAHE(clipLimit=2, tileGridSize=(8, 8)))
        self.assertEqual(image.shape, (400, 640, 3))
        self.assertEqual(image.dtype, np.uint8)
        self.assertTrue(np.array_equal(raw, previous))
        self.assertTrue(np.array_equal(image[:, :, 0], image[:, :, 1]))
        self.assertTrue(np.array_equal(image[:, :, 1], image[:, :, 2]))
        self.assertGreater(int(image.max())-int(image.min()), 100)

    def test_bad_native_pixels_are_rejected_before_contrast_processing(self):
        from unittest.mock import Mock
        contrast = Mock()
        for raw in (np.full((400, 640), 1024, np.uint16),
                    np.zeros((400, 640), np.uint8),
                    np.zeros((400, 640, 3), np.uint16),
                    np.empty((0, 640), np.uint16)):
            with self.subTest(shape=raw.shape, dtype=str(raw.dtype)), self.assertRaises(RuntimeError):
                ir_identity_image(raw, contrast)
        contrast.apply.assert_not_called()


if __name__ == '__main__':
    unittest.main()
