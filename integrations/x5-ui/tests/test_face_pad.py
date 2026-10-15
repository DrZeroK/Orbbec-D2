"""Synthetic geometry regressions only: no proof of camera registration or liveness."""
import unittest

import numpy as np

from face_pad import evaluate_face


class FacePadTests(unittest.TestCase):
    def setUp(self):
        self.yy, self.xx = np.mgrid[:400, :640]
        self.u, self.v = (self.xx-320)/60, (self.yy-190)/60
        self.face = [240, 100, 160, 190, 290, 155, 350, 155,
                     320, 190, 299, 226, 341, 226, .99]
        self.camera = (500, 500, 320, 200)
        # Fixed high-frequency texture, including on the spoof surfaces.
        self.ir = (300 + 50*np.sin(self.xx*1.4) + 40*np.cos(self.yy*.9)).astype(np.uint16)

    def face_depth(self):
        smooth = 650 + 14*self.u**2 + 10*self.v**2
        nose = 25*np.exp(-((self.u/.19)**2+(self.v/.25)**2)/2)
        return smooth-nose

    def check_reject(self, depth, ir=None, face=None, camera=None):
        result = evaluate_face(depth, self.ir if ir is None else ir,
                               self.face if face is None else face,
                               self.camera if camera is None else camera)
        self.assertFalse(result['accepted'], result)
        self.assertTrue(result['reason'])
        self.assertTrue(all(np.isfinite(v) for v in result['metrics'].values()), result)
        return result

    def test_synthetic_face_positive_is_geometry_only(self):
        result = evaluate_face(self.face_depth(), self.ir, self.face, self.camera)
        self.assertTrue(result['accepted'], result)
        self.assertGreater(result['metrics']['nose_local_prominence_mm'], 6)

    def test_quantized_noisy_positive_and_inputs_unchanged(self):
        noise = np.random.default_rng(4).normal(0, 1, self.xx.shape)
        depth = (self.face_depth()+noise).astype(np.uint16)
        original, original_ir = depth.copy(), self.ir.copy()
        result = evaluate_face(depth, self.ir, self.face, self.camera)
        self.assertTrue(result['accepted'], result)
        np.testing.assert_array_equal(depth, original)
        np.testing.assert_array_equal(self.ir, original_ir)

    def test_flat_and_tilted_planes_even_with_large_depth_range(self):
        self.check_reject(np.full((400, 640), 650, dtype=np.uint16))
        # Perspective-correct oblique physical plane, not merely z=a*x+b*y.
        tilted = 650/(1+.11*(self.xx-320)/500+.08*(self.yy-200)/500)
        self.check_reject(tilted)

    def test_bowed_paper_and_continuous_fold(self):
        self.check_reject(650+20*self.u**2+12*self.v**2)
        # Strong bow passes the plane-prominence gate; the local curved fit must reject it.
        result = self.check_reject(650+45*self.u**2+30*self.v**2)
        self.assertIn('nose_local_prominence_mm', result['metrics'])
        self.check_reject(650+25*self.u**2-15*np.exp(-(self.u/.19)**2/2))
        self.check_reject(650+20*np.abs(self.u))

    def test_photo_with_three_dimensional_background(self):
        depth = self.face_depth()+180*np.sin(self.xx*.02)**2
        interior = (self.u/.90)**2+(self.v/1.15)**2 <= 1
        depth[interior] = 650
        self.check_reject(depth)

    def test_missing_nose_and_background_in_nose(self):
        patch = self.u**2+self.v**2 < .18**2
        for value in (0, 990, 1300):
            depth = self.face_depth()
            depth[patch] = value
            self.check_reject(depth)

    def test_excess_span_and_face_edge_background(self):
        depth = self.face_depth()
        depth[(self.u > .35) & (np.abs(self.v) < .75)] = 950
        self.check_reject(depth)
        depth = self.face_depth()
        depth[(self.xx % 11) == 0] += 80
        self.check_reject(depth)

    def test_ir_invalid_saturated_and_low_texture(self):
        for ir in (np.zeros((400, 640)), np.full((400, 640), 1023),
                   np.full((400, 640), 400), np.full((400, 640), 65535)):
            self.check_reject(self.face_depth(), ir)
        smooth = 300+self.xx*.3
        self.check_reject(self.face_depth(), smooth)

    def test_nonfinite_malformed_and_mismatched_inputs(self):
        for value in (np.nan, np.inf, -np.inf):
            depth = self.face_depth()
            depth[190, 320] = value
            self.check_reject(depth)
            ir = self.ir.astype(float)
            ir[190, 320] = value
            self.check_reject(self.face_depth(), ir)
        for depth in (None, [], np.zeros((4, 4)), np.zeros((400, 640), dtype=bool)):
            self.check_reject(depth)
        self.check_reject(self.face_depth(), self.ir.T)
        for face in ([1, 2], [np.nan]*15, [True]*15):
            self.check_reject(self.face_depth(), face=face)
        for camera in ((0, 500, 320, 200), (500, 500, -1, 200), (np.inf,)*4):
            self.check_reject(self.face_depth(), camera=camera)

    def test_missing_face_landmarks_and_wrong_distance(self):
        face = list(self.face)
        face[8] = 280
        self.check_reject(self.face_depth(), face=face)
        self.check_reject(np.full((400, 640), 300))
        self.check_reject(np.full((400, 640), 1100))


if __name__ == '__main__':
    unittest.main()
