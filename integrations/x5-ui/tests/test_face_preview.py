"""Synthetic frames only; no camera, enrollment record or image file is used."""
import base64
import os
import socket
import struct
import sys
import time
import unittest
from unittest.mock import patch

from face_preview import FacePreview, PreviewPublisher, MAX_PACKET


@unittest.skipUnless(sys.platform == 'linux', 'Target Linux inherited socket transport')
class PreviewTests(unittest.TestCase):
    def test_latest_fresh_frame_expires_and_end_clears_memory(self):
        preview = FacePreview()
        jpeg = b'\xff\xd8synthetic\xff\xd9'
        with preview.channel(True) as options:
            sender = socket.socket(fileno=os.dup(options['pass_fds'][0]))
            with sender, patch('face_preview.time.monotonic', return_value=100):
                for packet in (b'bad', b'x'*(MAX_PACKET+1),
                               struct.pack('!d', float('nan'))+jpeg,
                               struct.pack('!d', 99)+jpeg,
                               struct.pack('!d', 100)+b'not-jpeg'):
                    sender.send(packet)
                    self.assertEqual(preview.snapshot()['image'], '')
                sender.send(struct.pack('!d', 100)+jpeg)
                expected = 'data:image/jpeg;base64,'+base64.b64encode(jpeg).decode()
                self.assertEqual(preview.snapshot()['image'], expected)
                self.assertEqual(preview.snapshot()['image'], expected)
            with patch('face_preview.time.monotonic', return_value=101):
                self.assertEqual(preview.snapshot()['image'], '')
        self.assertEqual(preview.snapshot(), {'active': False, 'image': ''})
        self.assertIsNone(preview.latest)

    def test_channel_closes_on_failure_and_verify_has_no_channel(self):
        preview = FacePreview()
        with self.assertRaises(TimeoutError):
            with preview.channel(True):
                raise TimeoutError('synthetic child timeout')
        self.assertFalse(preview.snapshot()['active'])
        with preview.channel(False) as options:
            self.assertEqual(options, {})
            self.assertIsNone(preview.reader)

    def test_slow_preview_consumer_never_blocks_capture(self):
        import cv2
        import numpy as np
        preview = FacePreview()
        image = np.random.default_rng(1).integers(0, 256, (480, 640, 3), dtype=np.uint8)
        with preview.channel(True) as options, patch.dict(os.environ, options['env']):
            # Dup models the separate descriptor table in an exec'ed child.
            os.environ['FACE_PREVIEW_FD'] = str(os.dup(options['pass_fds'][0]))
            with PreviewPublisher() as publisher:
                started = time.monotonic()
                for _ in range(30):
                    publisher.last = 0
                    publisher.publish(image)
                self.assertLess(time.monotonic()-started, 3)
                result = preview.snapshot()
                self.assertTrue(result['image'].startswith('data:image/jpeg;base64,'))
                decoded = cv2.imdecode(np.frombuffer(base64.b64decode(result['image'].split(',')[1]), np.uint8), cv2.IMREAD_COLOR)
                self.assertEqual(decoded.shape, (360, 480, 3))
            self.assertIsNone(publisher.socket)


if __name__ == '__main__':
    unittest.main()
