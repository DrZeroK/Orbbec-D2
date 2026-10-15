"""Use the scene daemon's native RGB frames while it owns the UVC device."""
import json
import math
import os
from pathlib import Path
import socket
import time


class RGBCamera:
    def __init__(self, device, backend):
        import cv2
        self.native = self.connection = self.reader = None
        path = Path('/run/user')/str(os.getuid())/'scene-describe/scene.sock'
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        connection.settimeout(5)
        try:
            connection.connect(str(path))
        except (FileNotFoundError, ConnectionRefusedError):
            connection.close()
            self.native = cv2.VideoCapture(device, backend)
            return
        self.connection = connection
        try:
            connection.sendall(b'{"camera_test":{"width":640,"height":480,"fps":30}}\n')
            self.reader = connection.makefile('rb')
        except BaseException:
            self.release()
            raise

    def isOpened(self):
        return self.native.isOpened() if self.native is not None else self.reader is not None

    def set(self, key, value):
        return self.native.set(key, value) if self.native is not None else True

    def read(self):
        if self.native is not None:
            return self.native.read()
        import cv2
        import numpy as np
        try:
            for _ in range(32):
                header = json.loads(self.reader.readline(4097))
                length, stamp = header.get('length'), header.get('frame_at')
                if (type(length) is not int or not 0 < length <= 2*1024*1024
                        or type(stamp) not in (int, float) or not math.isfinite(stamp)
                        or (header.get('width'), header.get('height')) != (640, 480)):
                    return False, None
                jpeg = self.reader.read(length)
                if len(jpeg) != length:
                    return False, None
                # Slow inference must drain queued frames instead of recognizing an old face.
                if not 0 <= time.monotonic()-stamp <= .75:
                    continue
                image = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
                if image is None or image.shape != (480, 640, 3):
                    return False, None
                return True, image
        except (OSError, ValueError, TypeError, cv2.error):
            pass
        return False, None

    def release(self):
        if self.native is not None:
            self.native.release()
        if self.reader is not None:
            self.reader.close()
            self.reader = None
        if self.connection is not None:
            self.connection.close()
            self.connection = None
