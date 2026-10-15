"""Synthetic RGB lease/freshness checks; no model, template or USB device."""
import io
import json
import time
import unittest
from unittest.mock import Mock, patch

from PIL import Image
from face_rgb_stream import RGBCamera


class RGBStreamTests(unittest.TestCase):
    def camera(self, packets):
        stream = io.BytesIO()
        for changes in packets:
            jpeg = io.BytesIO(); Image.new('RGB', (640,480), 'green').save(jpeg,format='JPEG')
            header = {'length':len(jpeg.getvalue()), 'width':640, 'height':480,
                      'frame_at':time.monotonic(), **changes}
            stream.write(json.dumps(header).encode()+b'\n'+jpeg.getvalue())
        stream.seek(0)
        connection = Mock()
        connection.makefile.return_value = stream
        with patch('face_rgb_stream.socket.socket', return_value=connection):
            return RGBCamera('/synthetic', 0), connection

    def test_fresh_native_rgb_is_decoded_and_lease_released(self):
        camera, connection = self.camera([{}])
        try:
            okay, image = camera.read()
            self.assertTrue(okay)
            self.assertEqual(image.shape, (480,640,3))
            self.assertIn(b'camera_test', connection.sendall.call_args.args[0])
        finally:camera.release()
        connection.close.assert_called_once()

    def test_stale_frame_is_drained_and_invalid_metadata_fails_closed(self):
        camera, _ = self.camera([{'frame_at':0}, {}])
        try:self.assertTrue(camera.read()[0])
        finally:camera.release()
        for changes in ({'frame_at':float('nan')}, {'frame_at':time.monotonic()+10},
                        {'width':1}, {'length':2**30}, {'length':True}):
            camera, _ = self.camera([changes])
            try:self.assertFalse(camera.read()[0])
            finally:camera.release()

    def test_daemon_absence_keeps_standalone_native_capture(self):
        import cv2
        connection = Mock()
        connection.connect.side_effect = FileNotFoundError()
        with patch('face_rgb_stream.socket.socket', return_value=connection), \
             patch('cv2.VideoCapture') as capture:
            camera = RGBCamera('/synthetic', cv2.CAP_V4L2)
            camera.read()
            camera.release()
            capture.assert_called_once_with('/synthetic', cv2.CAP_V4L2)
            capture.return_value.read.assert_called_once()
            capture.return_value.release.assert_called_once()
