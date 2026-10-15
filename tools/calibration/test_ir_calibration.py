"""Synthetic calibration checks only; no camera, images on disk or face data."""
import copy
import json
import unittest

import cv2
import numpy as np

from ir_calibration import (SPEC, analyze, assess_novelty, detect_observation,
                            normalized_rays, object_points, observation_from_points)


class CalibrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cv2.setNumThreads(1)
        cls.K = np.array([[632., 0, 307.], [0, 478., 186.], [0, 0, 1.]])
        cls.dist = np.array([-.045, .012, .0008, -.0005, .002])
        cls.rays = normalized_rays(cls.K, cls.dist)
        cls.obj = object_points()
        cls.rng = np.random.default_rng(431)
        cls.views = []
        for i in range(20):
            pitch = [-24, -12, 5, 16, 26][i % 5]
            yaw = [-22, 9, 25][i // 5] if i < 15 else [-24, 17, -8, 26, 5][i % 5]
            z = [560, 650, 770, 880, 720][(i*3) % 5]
            # A distinct 5x4 image-position grid keeps ALL training/holdout poses
            # separate even where a yaw change alone moves corners by <3 pixels.
            centre = (210+(i % 5)*55, 125+(i//5)*50)
            cls.views.append(cls.make_view(pitch, yaw, z, centre))

    @classmethod
    def make_view(cls, pitch, yaw, z, centre, noise=.06, roll=0):
        rx = cv2.Rodrigues(np.array([np.deg2rad(pitch), 0., 0.]))[0]
        ry = cv2.Rodrigues(np.array([0., np.deg2rad(yaw), 0.]))[0]
        rz = cv2.Rodrigues(np.array([0., 0., np.deg2rad(roll)]))[0]
        rotation = rz @ ry @ rx
        rv = cv2.Rodrigues(rotation)[0]
        tv = np.array([(centre[0]-cls.K[0, 2])*z/cls.K[0, 0],
                       (centre[1]-cls.K[1, 2])*z/cls.K[1, 1], z])
        corners = cv2.projectPoints(cls.obj, rv, tv, cls.K, cls.dist)[0].reshape(88, 2)
        corners += cls.rng.normal(0, noise, corners.shape)
        normal = rotation[:, 2]
        depth = float(normal @ tv)/(cls.rays @ normal)
        depth += cls.rng.normal(0, .3, depth.shape)
        return observation_from_points(corners, depth)

    def test_restore_non_square_focal_off_centre_and_nonzero_distortion(self):
        for index, view in enumerate(self.views):
            novelty = assess_novelty(view, self.views[:index])
            self.assertTrue(novelty['accepted'], (index, novelty))
            if index:
                self.assertGreater(novelty['closest_rms_px'], 10)
        result = analyze(self.views[:15], self.views[15:])
        self.assertTrue(result['intrinsics_verified'], result)
        self.assertFalse(result['verified'], 'An IR fit must not enable the entire unlock profile')
        fitted = np.array(result['K'])
        np.testing.assert_allclose(np.diag(fitted)[:2], np.diag(self.K)[:2], atol=4)
        np.testing.assert_allclose(fitted[:2, 2], self.K[:2, 2], atol=4)
        self.assertGreater(abs(fitted[0, 0]-fitted[1, 1]), 100)
        self.assertGreater(abs(fitted[0, 2]-320), 7)
        self.assertLess(abs(result['dist'][0]-self.dist[0]), .02)
        self.assertLess(max(v['rms_px'] for v in result['holdout']), .2)
        self.assertLess(max(v['depth']['p95_mm'] for v in result['holdout']), 5)
        json.dumps(result, allow_nan=False)

    def test_repeated_pose_rejected_even_with_many_records(self):
        duplicate = copy.deepcopy(self.views[0])
        duplicate['corners'] = (np.array(duplicate['corners'])+.2).tolist()
        self.assertFalse(assess_novelty(duplicate, [self.views[0]])['accepted'])
        reversed_order = copy.deepcopy(self.views[0])
        reversed_order['corners'].reverse()
        self.assertFalse(assess_novelty(reversed_order, [self.views[0]])['accepted'])
        result = analyze([self.views[0]]*15, self.views[15:])
        self.assertFalse(result['intrinsics_verified'])
        self.assertTrue(any('重复' in r for r in result['reasons']), result)

    def test_front_parallel_translations_do_not_count_as_tilt_coverage(self):
        views = []
        for i in range(20):
            views.append(self.make_view(0, 0, [580, 680, 800, 900][i//5],
                                        (205+(i % 5)*55, 140+((i*3) % 5)*30), noise=.02))
        result = analyze(views[:15], views[15:])
        self.assertFalse(result['intrinsics_verified'], result)
        self.assertTrue(result['reasons'])

    def test_low_training_error_cannot_hide_bad_holdout(self):
        held = copy.deepcopy(self.views[15:])
        offsets = np.zeros((88, 2))
        offsets[::2, 0] = 4
        offsets[1::2, 0] = -4
        for view in held:
            view['corners'] = (np.array(view['corners'])+offsets).tolist()
        result = analyze(self.views[:15], held)
        self.assertIn('training_rms_px', result, result)
        self.assertLess(result['training_rms_px'], .5)
        self.assertFalse(result['intrinsics_verified'], result)
        self.assertTrue(any('留出重投影' in r for r in result['reasons']), result)

    def test_low_error_but_limited_frame_coverage_rejected(self):
        views = []
        for i in range(20):
            views.append(self.make_view(-24+(i % 5)*12, -20+(i//5)*14,
                                        [580, 680, 780, 880, 720][i % 5], (320, 200), roll=i*11))
        result = analyze(views[:15], views[15:])
        self.assertFalse(result['intrinsics_verified'], result)
        self.assertTrue(any('画面位置' in r for r in result['reasons']), result)

    def test_bad_depth_scale_holes_and_nonfinite_fail_closed(self):
        for kind in ('scale', 'holes', 'nonfinite'):
            held = copy.deepcopy(self.views[15:])
            for view in held:
                if kind == 'scale':
                    view['depth_mm'] = [v*1.08 for v in view['depth_mm']]
                elif kind == 'holes':
                    view['depth_mm'][:20] = [None]*20
                    view['depth_patch_coverage'][:20] = [0.]*20
                else:
                    view['depth_mm'][0] = float('nan')
            result = analyze(self.views[:15], held)
            self.assertFalse(result['intrinsics_verified'], (kind, result))
            if kind != 'nonfinite':
                self.assertIn('training_rms_px', result, (kind, result))
                self.assertTrue(any('留出深度' in reason for reason in result['reasons']), (kind, result))

    def test_ray_projection_round_trip_and_depth_not_resampled(self):
        pixels = np.array([[0., 0.], [639, 399], [307, 186], [120, 290]])
        rays = self.rays[pixels[:, 1].astype(int), pixels[:, 0].astype(int)]
        projected = cv2.projectPoints(rays*700, np.zeros(3), np.zeros(3), self.K, self.dist)[0]
        np.testing.assert_allclose(projected.reshape(-1, 2), pixels, atol=1e-6)
        self.assertEqual(self.rays.shape, (400, 640, 3))
        np.testing.assert_array_equal(self.rays[..., 2], np.ones((400, 640)))
        depth = np.full((400, 640), 650., dtype=np.float64)
        depth[10, 10] = 0
        original = depth.copy()
        _ = depth[..., None]*self.rays
        np.testing.assert_array_equal(depth, original)
        self.assertEqual(float(depth[10, 10]), 0)

    def test_detect_rendered_chessboard_only_in_ram(self):
        ir = np.full((400, 640), 300, np.uint16)
        for row in range(12):
            for col in range(9):
                ir[80+row*20:100+row*20, 230+col*20:250+col*20] = 900 if (row+col) % 2 else 30
        original = ir.copy()
        result = detect_observation(ir, np.full((400, 640), 650, np.uint16))
        self.assertEqual(np.array(result['corners']).shape, (88, 2))
        self.assertEqual(result['image_size'], [640, 400])
        np.testing.assert_array_equal(ir, original)

    def test_projected_dots_preserve_native_corner_accuracy(self):
        ir = np.full((400,640), 12, np.float32)
        cell,x0,y0 = 14,240,90
        for row in range(12):
            for col in range(9):
                ir[y0+row*cell:y0+(row+1)*cell, x0+col*cell:x0+(col+1)*cell] = 80 if (row+col)%2 else 3
        yy,xx = np.indices(ir.shape)
        spots = (((xx+2*(yy//13))%6 == 0) & (yy%6 == 0)).astype(np.float32)
        spots = cv2.GaussianBlur(spots,(3,3),.5)
        ir += spots*(ir*7+30)
        ir = np.uint16(np.clip(ir+np.random.default_rng(19).normal(0,1,ir.shape),0,1023))
        original = ir.copy()
        result = detect_observation(ir,np.full((400,640),800,np.uint16))
        self.assertEqual(result['corner_detector'],'median5-native-sb')
        actual = np.array(result['corners'])
        expected = np.mgrid[1:9,1:12].T.reshape(-1,2)*cell+[x0-.5,y0-.5]
        rms = min(np.sqrt(np.mean(np.sum((actual-p)**2,axis=1))) for p in (expected,expected[::-1]))
        self.assertLess(rms,.3)
        np.testing.assert_array_equal(ir,original)

    def test_format_size_spec_and_missing_views_rejected(self):
        depth = np.full((400, 640), 650, np.uint16)
        for ir in (None, np.zeros((640, 400), np.uint16), np.zeros((400, 640), np.uint8),
                   np.full((400, 640), 65535, np.uint16), np.zeros((400, 640), np.uint16)):
            with self.assertRaises(ValueError):
                detect_observation(ir, depth)
        for bad in (np.zeros((640, 400)), np.full((400, 640), np.nan), np.ones((400, 640), bool)):
            with self.assertRaises(ValueError):
                observation_from_points(self.views[0]['corners'], bad)
        spec = copy.deepcopy(SPEC)
        spec['inner_corners'] = [8, 6]
        with self.assertRaises(ValueError):
            object_points(spec)
        for camera, dist in ((np.eye(2), self.dist), (self.K, [np.nan]*5),
                              (self.K, [0.]*4)):
            with self.assertRaises(ValueError):
                normalized_rays(camera, dist)
        self.assertFalse(analyze(self.views[:14], self.views[15:])['intrinsics_verified'])
        bad = copy.deepcopy(self.views[:15])
        bad[0]['corners'][0][0] = float('inf')
        self.assertFalse(analyze(bad, self.views[15:])['intrinsics_verified'])


if __name__ == '__main__':
    unittest.main()
