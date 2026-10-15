"""Factory-mode authorization and continuous acquisition without camera hardware."""
import copy
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import numpy as np
import d2_camera as d2


class FactoryActivationTests(unittest.TestCase):
    def test_factory_mode_is_explicit_bound_and_does_not_claim_verification(self):
        config = json.loads((Path(__file__).parent/'factory_activation_fixture.json').read_text())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'factory_activation.json'
            self.assertIsNone(d2.factory_profile(directory))
            path.write_text(json.dumps(config))
            value = d2.factory_profile(directory)
            np.testing.assert_allclose(value['intrinsics'],[476.959442,476.959442,316.939148,196.459702],atol=1e-5)
            self.assertFalse(value['verified'])
            self.assertFalse(value['timing_verified'])
            for change in ({'enabled':False},{'enabled':1},{'experimental':False},
                           {'serial':'another-device'},{'driver_sha256':'wrong'},
                           {'factory_raw_hex':('0' if config['factory_raw_hex'][0] != '0' else '1')+config['factory_raw_hex'][1:]},
                           {'factory_raw_hex':True},{'factory_raw_hex':''}):
                with self.subTest(change=change):
                    path.write_text(json.dumps({**config,**change}))
                    with self.assertRaises(RuntimeError):
                        d2.factory_profile(directory)

    def test_one_future_stream_is_rejected(self):
        for depth_arrival,ir_arrival in ((1.,1.02),(1.02,1.)):
            pairer = d2.Pairer()
            pairer.add(3,np.array([700]),100000,1,depth_arrival)
            pairer.add(1,np.array([150]),109000,1,ir_arrival)
            self.assertIsNone(pairer.take(1.01))

    def test_pump_keeps_draining_and_delivers_distinct_latest_pairs(self):
        class Camera(d2.D2Camera):
            def _read_pair(self):
                time.sleep(.004)
                self.counter += 1
                return self.counter,None,{'received_at':time.monotonic()}
        camera = Camera('/never-native')
        camera.counter = 0
        camera._start_pump()
        try:
            first = camera.read()[0]
            time.sleep(.12)
            second = camera.read()[0]
            self.assertGreaterEqual(second-first,10)
            third = camera.read()[0]
            self.assertGreater(third,second)
        finally:
            camera.__exit__()
        self.assertFalse(camera._thread.is_alive())
        with self.assertRaises(RuntimeError):
            camera.read()

    def test_pump_error_cannot_return_cached_data(self):
        camera = d2.D2Camera('/never-native')
        with patch.object(camera,'_read_pair',side_effect=RuntimeError('synthetic SDK failure')):
            camera._start_pump()
            try:
                with self.assertRaisesRegex(RuntimeError,'连续取流'):
                    camera.read()
            finally:
                camera.__exit__()

    def test_distortion_rotates_with_coordinates(self):
        import cv2
        from face_engine import rotated_intrinsics,rotated_distortion
        camera = [510.,470.,310.,190.]
        dist = [.01,-.02,.001,-.002,.003]
        xyz = np.array([[20.,30.,650.],[-70.,50.,800.]])
        K = np.array([[camera[0],0,camera[2]],[0,camera[1],camera[3]],[0,0,1.]])
        before = cv2.projectPoints(xyz,np.zeros(3),np.zeros(3),K,np.array(dist))[0].reshape(-1,2)
        changed = xyz[:,[1,0,2]].copy();changed[:,1] *= -1
        fx,fy,cx,cy = rotated_intrinsics(camera,(400,640),1)
        newK = np.array([[fx,0,cx],[0,fy,cy],[0,0,1.]])
        after = cv2.projectPoints(changed,np.zeros(3),np.zeros(3),newK,
                                 np.array(rotated_distortion(dist,1)))[0].reshape(-1,2)
        np.testing.assert_allclose(after,np.c_[before[:,1],639-before[:,0]],atol=1e-7)


if __name__ == '__main__':
    unittest.main()
