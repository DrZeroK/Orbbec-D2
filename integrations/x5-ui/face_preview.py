"""Enrollment-only preview over an inherited, bounded in-memory socket pair."""
import base64
from contextlib import contextmanager
import math
import os
import socket
import struct
import threading
import time

MAX_PACKET = 100_000


class FacePreview:
    def __init__(self):
        self.reader = None
        self.latest = None
        self.lock = threading.Lock()

    @contextmanager
    def channel(self, enabled):
        if not enabled:
            yield {}
            return
        reader, writer = socket.socketpair(socket.AF_UNIX, socket.SOCK_DGRAM)
        for endpoint in (reader, writer):
            endpoint.setblocking(False)
            endpoint.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 65_536)
            endpoint.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 65_536)
        with self.lock:
            self.reader = reader
            self.latest = None
        try:
            yield {'pass_fds': (writer.fileno(),),
                   'env': {**os.environ, 'FACE_PREVIEW_FD': str(writer.fileno())}}
        finally:
            with self.lock:
                self.reader = None
                self.latest = None
                reader.close()
            writer.close()

    def snapshot(self):
        latest = None
        with self.lock:
            if self.reader is None:
                return {'active': False, 'image': ''}
            # A full queue drops previews, never blocks camera capture.
            for _ in range(32):
                try:
                    packet = self.reader.recv(MAX_PACKET + 1)
                except BlockingIOError:
                    break
                if not 12 <= len(packet) <= MAX_PACKET:
                    continue
                stamp = struct.unpack('!d', packet[:8])[0]
                jpeg = packet[8:]
                if (math.isfinite(stamp) and 0 <= time.monotonic()-stamp <= .75
                        and jpeg.startswith(b'\xff\xd8') and jpeg.endswith(b'\xff\xd9')):
                    self.latest = (stamp, jpeg)
            if self.latest and 0 <= time.monotonic()-self.latest[0] <= .75:
                latest = self.latest[1]
            else:
                self.latest = None
        return {'active': True, 'image': ('data:image/jpeg;base64,' +
                base64.b64encode(latest).decode('ascii')) if latest else ''}


class PreviewPublisher:
    def __init__(self):
        descriptor = os.environ.get('FACE_PREVIEW_FD')
        self.socket = socket.socket(fileno=int(descriptor)) if descriptor is not None else None
        if self.socket is not None:
            self.socket.setblocking(False)
        self.last = 0.0

    def publish(self, image):
        now = time.monotonic()
        if self.socket is None or now-self.last < .25:
            return
        self.last = now
        import cv2
        height, width = image.shape[:2]
        scale = min(1, 480/max(height, width))
        small = cv2.resize(image, (round(width*scale), round(height*scale)))
        okay, encoded = cv2.imencode('.jpg', small, [cv2.IMWRITE_JPEG_QUALITY, 70])
        if not okay or encoded.nbytes + 8 > MAX_PACKET:
            return
        try:
            self.socket.send(struct.pack('!d', now) + encoded.tobytes())
        except BlockingIOError:
            pass
        except OSError:
            self.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def close(self):
        if self.socket is not None:
            self.socket.close()
            self.socket = None
