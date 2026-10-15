"""Local D2 RGB identity comparison; camera/inference live in a bounded child.

This convenience application lock does not claim depth liveness or OS security.
"""
import hashlib
import json
import math
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time

from face_preview import FacePreview, PreviewPublisher

MODELS = {
    'face_detection_yunet_2023mar.onnx': '8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4',
    'face_recognition_sface_2021dec.onnx': '0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79',
}
RECOGNITION_HASH = MODELS['face_recognition_sface_2021dec.onnx']
# Experimental threshold; validate false accepts/rejects with the actual rider.
MATCH_THRESHOLD = 0.60
SAMPLES = 5


def rgb_device():
    """Choose the physical 2bc5:0505 capture endpoint, never a numeric fallback."""
    found = []
    for item in Path('/sys/class/video4linux').glob('video*'):
        try:
            if (item/'index').read_text().strip() != '0':
                continue
            parent = (item/'device').resolve()
            for candidate in (parent, *parent.parents):
                if not (candidate/'idVendor').is_file():
                    continue
                if ((candidate/'idVendor').read_text().strip(),
                    (candidate/'idProduct').read_text().strip()) == ('2bc5', '0505'):
                    found.append('/dev/'+item.name)
                break
        except OSError:
            continue
    if len(found) != 1:
        raise RuntimeError('未找到唯一的 D2 彩色相机，请检查 USB 连接')
    return found[0]


class FaceCaptureError(RuntimeError):
    """Bounded camera-worker failure suitable for the local PIN-gated UI."""


def valid_samples(result):
    return (isinstance(result, dict) and type(result.get('samples')) is int
            and SAMPLES <= result['samples'] <= 80)


def checked_embedding(value):
    if not isinstance(value, list) or len(value) != 128:
        raise ValueError('人脸资料格式错误，请用 PIN 解锁后重新录入')
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in value):
        raise ValueError('人脸资料数值错误，请重新录入')
    norm = math.sqrt(sum(v*v for v in value))
    if not 0.98 <= norm <= 1.02:
        raise ValueError('人脸资料无效，请重新录入')
    return value


class FaceEngine:
    def __init__(self, data_dir, models_dir=None):
        self.preview = FacePreview()
        self.template = Path(data_dir)/'screen_face.json'
        self.models = Path(models_dir) if models_dir else Path.home()/'wheelchair/models/screen-face'

    def _template(self):
        if self.template.stat().st_size > 8192:
            raise ValueError('人脸资料过大，请重新录入')
        value = json.loads(self.template.read_text(encoding='utf8'))
        if not isinstance(value, dict) or value.get('version') != 1 or value.get('model') != RECOGNITION_HASH:
            raise ValueError('人脸模型或资料版本不匹配，请重新录入')
        return checked_embedding(value.get('embedding'))

    def status(self):
        result = {'available': False, 'enrolled': False, 'error': ''}
        try:
            if self.template.exists():
                self._template()
                result['enrolled'] = True
        except (OSError, ValueError, RuntimeError) as exc:
            result['error'] = str(exc)[:160]
        try:
            if not all((self.models/name).is_file() for name in MODELS):
                raise RuntimeError('本地人脸模型尚未就绪，PIN 仍可使用')
            rgb_device()
            result['available'] = True
        except (OSError, ValueError, RuntimeError) as exc:
            result['error'] = str(exc)[:160]
        return result

    def _run(self, operation, embedding=None):
        payload = {'embedding': embedding} if embedding is not None else {}
        try:
            with self.preview.channel(operation == 'enroll') as preview_options:
                completed = subprocess.run(
                    [sys.executable, str(Path(__file__).resolve()), '--capture', operation, str(self.models)],
                    input=json.dumps(payload), text=True, encoding='utf8', capture_output=True,
                    timeout=18, check=False, **preview_options)
        except subprocess.TimeoutExpired as exc:
            raise FaceCaptureError('相机取图超时，请使用 PIN，稍后重试') from exc
        except OSError as exc:
            raise FaceCaptureError('人脸识别进程无法启动，请使用 PIN') from exc
        if len(completed.stdout) > 16384:
            raise FaceCaptureError('人脸识别进程返回异常')
        try:
            result = json.loads(completed.stdout)
        except ValueError as exc:
            raise FaceCaptureError('人脸识别进程异常，请使用 PIN') from exc
        if not isinstance(result, dict):
            raise FaceCaptureError('人脸识别进程返回异常')
        if completed.returncode or result.get('error'):
            raise FaceCaptureError(str(result.get('error', '人脸识别进程异常'))[:160])
        return result

    def enroll(self):
        result = self._run('enroll')
        embedding = checked_embedding(result.get('embedding'))
        if not valid_samples(result):
            raise RuntimeError('人脸采样不足，未更改原资料')
        record = {'version': 1, 'model': RECOGNITION_HASH, 'embedding': embedding}
        self.template.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.template.with_name('.screen_face-'+secrets.token_hex(12))
        descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, 'w', encoding='utf8') as stream:
            json.dump(record, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, self.template)
        return {'samples': result['samples']}

    def verify(self):
        result = self._run('verify', self._template())
        matched = result.get('matched') is True and valid_samples(result)
        return {'matched': matched, 'samples': result.get('samples', 0),
                'reason': result.get('reason', '未识别到已录入的人脸，请重试或使用 PIN')}


def capture(operation, models, payload):
    import fcntl
    import cv2
    import numpy as np

    if operation not in ('enroll', 'verify', 'probe'):
        raise ValueError('无效的人脸操作')
    reference = checked_embedding(payload.get('embedding')) if operation == 'verify' else None
    for name, expected in MODELS.items():
        if hashlib.sha256((models/name).read_bytes()).hexdigest() != expected:
            raise RuntimeError('本地模型校验失败，请使用 PIN')
    cv2.setNumThreads(4)
    detector = cv2.FaceDetectorYN_create(str(models/next(iter(MODELS))), '', (320, 320), .90, .30, 5000)
    recognizer = cv2.FaceRecognizerSF_create(str(models/'face_recognition_sface_2021dec.onnx'), '')
    runtime = Path('/run/user')/str(os.getuid())
    lock_path = runtime/'wheelchair-face-camera.lock'
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    with os.fdopen(descriptor, 'w') as lease:
        try:
            fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError('相机正在识别中，PIN 仍可使用') from exc
        device = rgb_device()
        preview = PreviewPublisher()
        from face_rgb_stream import RGBCamera
        camera = RGBCamera(device, cv2.CAP_V4L2)
        try:
            if not camera.isOpened():
                raise RuntimeError('D2 彩色相机暂不可用，请使用 PIN')
            camera.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
            camera.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            camera.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            features, selected_rotation = [], None
            started, first_sample, last_reason = time.monotonic(), None, '请单人正对相机并保持光线充足'
            reads = 0
            while time.monotonic()-started < 11 and reads < 80:
                okay, image = camera.read()
                reads += 1
                if not okay or image is None or image.ndim != 3 or image.shape[2] != 3:
                    raise RuntimeError('D2 图像读取中断，请使用 PIN')
                if reads <= 3:
                    continue
                preview.publish(np.rot90(image, selected_rotation).copy() if selected_rotation else image)
                feature = None
                rotations = [selected_rotation] if selected_rotation is not None else [0, 1, 2, 3]
                for rotation in rotations:
                    view = np.rot90(image, rotation).copy() if rotation else image
                    height, width = view.shape[:2]
                    scale = min(320/width, 320/height)
                    small = cv2.resize(view, (round(width*scale), round(height*scale)))
                    dy, dx = (320-small.shape[0])//2, (320-small.shape[1])//2
                    padded = np.zeros((320, 320, 3), dtype=np.uint8)
                    padded[dy:dy+small.shape[0], dx:dx+small.shape[1]] = small
                    _, faces = detector.detect(padded)
                    if faces is None:
                        continue
                    if len(faces) != 1:
                        last_reason = '画面中需要只有一人，请其他人暂时离开'
                        break
                    face = faces[0].copy()
                    face[0], face[1] = (face[0]-dx)/scale, (face[1]-dy)/scale
                    face[2:4] /= scale
                    for index in range(4, 14, 2):
                        face[index], face[index+1] = (face[index]-dx)/scale, (face[index+1]-dy)/scale
                    if min(face[2:4]) < 75 or face[0] < 0 or face[1] < 0 or face[0]+face[2] > width or face[1]+face[3] > height:
                        last_reason = '请靠近相机，并让整张脸位于画面内'
                        continue
                    aligned = recognizer.alignCrop(view, face)
                    if float(cv2.Laplacian(cv2.cvtColor(aligned, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var()) < 35:
                        last_reason = '画面模糊，请保持不动并改善照明'
                        continue
                    feature = recognizer.feature(aligned).reshape(-1).astype(np.float64)
                    feature /= max(float(np.linalg.norm(feature)), 1e-12)
                    checked_embedding(feature.tolist())
                    selected_rotation = rotation
                    break
                if feature is None:
                    features, first_sample = [], None
                    continue
                if features and float(np.dot(features[0], feature)) < .70:
                    features, first_sample = [], None
                if reference is not None and float(np.dot(reference, feature)) < MATCH_THRESHOLD:
                    features, first_sample = [], None
                    last_reason = '未识别到已录入的人脸，请重试或使用 PIN'
                    continue
                if operation == 'enroll' and time.monotonic()-started < 3:
                    time.sleep(.05)
                    continue
                first_sample = first_sample or time.monotonic()
                features.append(feature)
                if operation == 'probe':
                    return {'samples': 1, 'face_detected': True, 'rotation_quarters': selected_rotation,
                            'elapsed_s': time.monotonic()-started, 'images_saved': False}
                if len(features) >= SAMPLES and time.monotonic()-first_sample >= .5:
                    if reference is not None:
                        return {'matched': True, 'samples': len(features), 'reason': ''}
                    averaged = np.mean(features, axis=0)
                    averaged /= float(np.linalg.norm(averaged))
                    return {'embedding': averaged.tolist(), 'samples': len(features)}
                time.sleep(.13)
            if operation == 'probe':
                return {'samples': 0, 'face_detected': False, 'reason': last_reason,
                        'frames_read': reads, 'elapsed_s': time.monotonic()-started, 'images_saved': False}
            if operation == 'verify':
                return {'matched': False, 'samples': 0, 'reason': last_reason}
            raise RuntimeError(last_reason+'，未更改原资料')
        finally:
            camera.release()
            preview.close()


# Standalone diagnostic helpers are retained for existing callers; RGB authentication never calls them.
def rotated_intrinsics(intrinsics, shape, turns):
    fx, fy, cx, cy = intrinsics
    height, width = shape
    for _ in range(turns):
        fx, fy, cx, cy = fy, fx, cy, width-1-cx
        height, width = width, height
    return fx, fy, cx, cy


def rotated_distortion(distortion, turns):
    k1, k2, p1, p2, k3 = distortion
    for _ in range(turns):
        p1, p2 = -p2, p1
    return k1, k2, p1, p2, k3


def ir_identity_image(ir, contrast):
    import cv2
    import numpy as np
    if ir.ndim != 2 or ir.dtype != np.uint16 or not ir.size or int(ir.max()) > 1023:
        raise RuntimeError('D2 红外像素格式异常，请使用 PIN')
    # Global percentile stretching clipped bright facial detail in the D2 live trial.
    gray = (np.sqrt(ir.astype(np.float32)/1023)*255).astype(np.uint8)
    gray = cv2.GaussianBlur(contrast.apply(gray), (3, 3), 0)
    return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)


if __name__ == '__main__':
    try:
        if len(sys.argv) != 4 or sys.argv[1] != '--capture':
            raise ValueError('此模块只供本机认证进程调用')
        incoming = sys.stdin.read(8193)
        if len(incoming) > 8192:
            raise ValueError('无效的人脸资料大小')
        request = json.loads(incoming)
        if not isinstance(request, dict):
            raise ValueError('无效的人脸资料')
        print(json.dumps(capture(sys.argv[2], Path(sys.argv[3]), request), ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({'error': str(exc)[:160]}, ensure_ascii=False))
        raise SystemExit(1)
