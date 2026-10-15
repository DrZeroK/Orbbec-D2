"""Pinned D2 depth/IR worker with explicit factory-experimental or measured mode.

SDK operations belong only in the bounded face child, never the HTTP process.
"""
import ctypes as c
from collections import deque
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re
import struct
import sys
import threading
import time

P = c.c_void_p
POLICY = 'd2-ir-depth-v1'
SDK_FILES = {
    'lib/libd2sdk.so': '2bc3a8130e4fac62871d914ffea327cdd5834e3568f7ab6a2bc69d76573008fc',
    'lib/libOpenNI2.so': 'e5cc7f0246a8251ac887ac56e667301210388b1fcd038d99fae22738dabb58b7',
    'lib/OpenNI.ini': '3896e8f831c6a56576e9e93a2e5b3e1d3fa72041e7d01e1d7f23b7cd907e7eff',
    'lib/OpenNI2/Drivers/libOniFile.so': '847beadad9fc2e3ab4dab81b18a7cfdfc420d83091fa5ce07be2e349bdf33334',
    'lib/OpenNI2/Drivers/liborbbec.so': '4df458c5cec9a5795d0998ee035eb4fde67641a4ebde7d9c7565e9359866704f',
    'lib/OpenNI2/Drivers/OniFile.ini': 'f50a20ca76350f8e5e81b50477714f9a1b1db9b49047f5089b90644526ba9505',
    'lib/OpenNI2/Drivers/orbbec.ini': 'b6a1cc4ed8ee62c7c4b2596e43727362ee489bd1733f59633794b005224d1e9b',
}
DRIVER_HASH = SDK_FILES['lib/OpenNI2/Drivers/liborbbec.so']
SDK_ROOT = Path.home()/'wheelchair/models/d2-sdk-v0.2.0'
FACTORY_SERIAL = 'D2_SAMPLE_SERIAL'
FACTORY_DIGEST = '5c8ac26a8878b22833cfc343a1a427f3db19f8949c8618525d3053a86503da97'


def factory_profile(runtime):
    source = Path(runtime)/'factory_activation.json'
    if not source.exists():
        return None
    require(not source.is_symlink() and source.stat().st_size <= 4096, 'D2 出厂启用配置无效')
    value = json.loads(source.read_text(encoding='utf8'))
    require(isinstance(value, dict) and value.get('schema') == 'd2-factory-activation/1'
            and value.get('enabled') is True and value.get('experimental') is True
            and value.get('serial') == FACTORY_SERIAL
            and value.get('driver_sha256') == DRIVER_HASH, 'D2 出厂启用配置不匹配')
    encoded = value.get('factory_raw_hex')
    require(isinstance(encoded,str) and re.fullmatch('[a-f0-9]{240}',encoded), 'D2 出厂参数编码无效')
    raw = bytes.fromhex(encoded)
    require(len(raw) == 120 and hashlib.sha256(raw).hexdigest() == FACTORY_DIGEST,
            'D2 出厂参数校验失败')
    params = struct.unpack('<30f', raw)
    require(all(math.isfinite(x) for x in params), 'D2 出厂参数无效')
    fx, fy, cx, cy = params[:4]
    k1, k2, p1, p2, k3 = params[20:25]
    # Factory left coordinates precede the driver's CW90 depth-output rotation.
    return {'source':'device-factory-experimental', 'serial':FACTORY_SERIAL,
            'intrinsics':[fy,fx,639-cy,cx], 'distortion':[k1,k2,p2,-p1,k3],
            'depth_request':[100,400,640,30], 'ir_request':[203,640,400,30],
            'verified':False, 'timing_verified':False}


def require(value, reason):
    if not value:
        raise RuntimeError(reason)


def usb_identity(sysfs=Path('/sys/bus/usb/devices'), nodes=Path('/dev/bus/usb')):
    matches = []
    for entry in sysfs.iterdir():
        try:
            if ((entry/'idVendor').read_text().strip(), (entry/'idProduct').read_text().strip()) != ('2bc5', '060d'):
                continue
            bus, number = int((entry/'busnum').read_text()), int((entry/'devnum').read_text())
            require(1 <= bus <= 999 and 1 <= number <= 999, 'D2 USB 编号无效')
            serial = (entry/'serial').read_text().strip() if (entry/'serial').exists() else ''
            matches.append((nodes/f'{bus:03d}'/f'{number:03d}', '2bc5:060d:'+(serial or 'port:'+entry.name)))
        except FileNotFoundError:
            continue
    require(len(matches) == 1, '未找到唯一的 D2 深度设备，请使用 PIN')
    return matches[0]


def alignment_profile(runtime, device_key):
    """No guessed rotation/resize: only a physically measured same-imager profile."""
    selected = factory_profile(runtime)
    if selected is not None:
        return selected
    source = Path(runtime)/'alignment.json'
    try:
        require(source.stat().st_size <= 4096, 'D2 对齐记录过大')
        value = json.loads(source.read_text(encoding='utf8'))
    except (OSError, ValueError) as exc:
        raise RuntimeError('深度与红外对齐尚未验收，请使用 PIN') from exc
    require(isinstance(value, dict) and value.get('schema') == 'd2-ir-alignment/1'
            and value.get('verified') is True and value.get('timing_verified') is True,
            '深度与红外对齐或时序尚未验收，请使用 PIN')
    require(value.get('device_key') == device_key and value.get('driver_sha256') == DRIVER_HASH,
            'D2 设备或驱动与对齐记录不符，请使用 PIN')
    require(value.get('depth_request') == [100, 400, 640, 30]
            and value.get('ir_request') == [203, 640, 400, 30]
            and value.get('actual_shape') == [400, 640]
            and value.get('mirroring') is False and value.get('depth_to_ir') == 'identity'
            and value.get('method') == 'physical-target-depth-ir'
            and isinstance(value.get('evidence_sha256'), str)
            and re.fullmatch('[a-f0-9]{64}', value['evidence_sha256']),
            'D2 对齐条件未经确认，请使用 PIN')
    intrinsics = value.get('intrinsics')
    require(isinstance(intrinsics, list) and len(intrinsics) == 4
            and all(type(x) in (int, float) and math.isfinite(x) for x in intrinsics)
            and 100 <= intrinsics[0] <= 2000 and 100 <= intrinsics[1] <= 2000
            and 0 <= intrinsics[2] < 640 and 0 <= intrinsics[3] < 400,
            'D2 内参未通过校验，请使用 PIN')
    return value


def readiness(runtime=SDK_ROOT):
    node, key = usb_identity()
    profile = alignment_profile(runtime, key)
    require(all((Path(runtime)/name).is_file() for name in SDK_FILES), 'D2 深度运行库未就绪，请使用 PIN')
    # This SDK can crash instead of returning an error when USB write access is denied.
    require(os.access(node, os.R_OK | os.W_OK), 'D2 深度 USB 权限未就绪，请使用 PIN')
    return profile


class Frame(c.Structure):
    _fields_ = [('data', P), ('bytes', c.c_size_t),
                *[(name, c.c_int) for name in ('sensor','format','width','height','stride',
                   'requested_width','requested_height','reported_fps','mirroring','frame_index')],
                ('sdk_timestamp_us', c.c_uint64), ('host_received_ns', c.c_uint64), ('flags', c.c_uint32)]


class DeviceInfo(c.Structure):
    _fields_ = [('uri',c.c_char*256),('vendor',c.c_char*256),('name',c.c_char*256),
                ('serial',c.c_char*256),('vid',c.c_uint16),('pid',c.c_uint16)]


def verify_factory_device(runtime, expected_serial):
    """Known read-only serial getter, inside the bounded camera child only."""
    require(c.sizeof(DeviceInfo) == 1028, 'OpenNI 设备 ABI 不匹配')
    sdk = c.CDLL(str(Path(runtime)/'lib/libOpenNI2.so'))
    for name,args,ret in [
        ('oniInitialize',[c.c_int],c.c_int),('oniShutdown',[],None),
        ('oniGetDeviceList',[c.POINTER(c.POINTER(DeviceInfo)),c.POINTER(c.c_int)],c.c_int),
        ('oniReleaseDeviceList',[c.POINTER(DeviceInfo)],None),
        ('oniDeviceOpen',[c.c_char_p,c.POINTER(P)],c.c_int),('oniDeviceClose',[P],c.c_int),
        ('oniDeviceGetProperty',[P,c.c_int,P,c.POINTER(c.c_int)],c.c_int)]:
        getattr(sdk,name).argtypes,getattr(sdk,name).restype = args,ret
    devices, count, device, initialized = c.POINTER(DeviceInfo)(),c.c_int(),P(),False
    try:
        require(sdk.oniInitialize(2003) == 0, 'D2 设备身份初始化失败')
        initialized = True
        require(sdk.oniGetDeviceList(c.byref(devices),c.byref(count)) == 0
                and 0 < count.value <= 16, 'D2 设备枚举失败')
        matches = [devices[i] for i in range(count.value)
                   if (devices[i].vid,devices[i].pid) == (0x2bc5,0x060d)]
        require(len(matches) == 1, 'D2 设备不唯一')
        require(sdk.oniDeviceOpen(matches[0].uri,c.byref(device)) == 0, 'D2 身份检查打开失败')
        buffer, length = (c.c_char*256)(),c.c_int(256)
        require(sdk.oniDeviceGetProperty(device,3,buffer,c.byref(length)) == 0
                and 0 < length.value <= 256, 'D2 设备序列号读取失败')
        require(bytes(buffer[:length.value]).split(b'\0')[0].decode('ascii') == expected_serial,
                'D2 序列号与出厂参数不匹配，请使用 PIN')
    finally:
        if device:
            sdk.oniDeviceClose(device)
        if devices:
            sdk.oniReleaseDeviceList(devices)
        if initialized:
            sdk.oniShutdown()


def load_sdk(runtime):
    require(sys.platform == 'linux' and platform.machine().lower() in ('aarch64', 'arm64')
            and c.sizeof(Frame) == 80 and Frame.sdk_timestamp_us.offset == 56, 'D2 SDK 平台或 ABI 不符')
    runtime = Path(runtime).resolve(strict=True)
    for name, expected in SDK_FILES.items():
        item = runtime/name
        require(not item.is_symlink() and item.resolve().is_relative_to(runtime)
                and hashlib.sha256(item.read_bytes()).hexdigest() == expected, 'D2 适配 SDK 校验失败')
    require({x.name for x in (runtime/'lib/OpenNI2/Drivers').glob('*.so')} == {'liborbbec.so', 'libOniFile.so'},
            'D2 SDK 出现未经校验的驱动')
    sdk = c.CDLL(str(runtime/'lib/libd2sdk.so'))
    for name, args, result in [
        ('d2_open', [c.POINTER(P)], c.c_int), ('d2_close', [P], None),
        ('d2_error', [P], c.c_char_p), ('d2_configure', [P]+[c.c_int]*5, c.c_int),
        ('d2_start', [P], c.c_int), ('d2_read', [P, c.c_int, c.POINTER(Frame)], c.c_int),
    ]:
        getattr(sdk, name).argtypes, getattr(sdk, name).restype = args, result
    return sdk


class Pairer:
    """Fresh distinct buffers/counters, bounded SDK skew and host delivery age."""
    def __init__(self):
        self.queues = {1: deque(maxlen=4), 3: deque(maxlen=4)}
        self.last = {}

    def add(self, sensor, pixels, timestamp, index, arrival):
        require(sensor in self.queues and type(timestamp) is int and timestamp >= 0
                and type(index) is int and index > 0 and math.isfinite(arrival), 'D2 帧元数据无效')
        fingerprint = hashlib.blake2s(pixels.tobytes()).digest()
        old = self.last.get(sensor)
        require(old is None or (timestamp > old[0] and index > old[1] and fingerprint != old[2]),
                'D2 帧重复、冻结或时钟倒退，请使用 PIN')
        self.last[sensor] = timestamp, index, fingerprint
        self.queues[sensor].append((pixels, timestamp, index, arrival))

    def take(self, now):
        for queue in self.queues.values():
            while queue and now-queue[0][3] > .25:
                queue.popleft()
        candidates = [(abs(ir[1]-depth[1]), ir, depth) for ir in self.queues[1] for depth in self.queues[3]
                      if abs(ir[1]-depth[1]) <= 18_000 and abs(ir[3]-depth[3]) <= .08
                      and all(0 <= now-frame[3] <= .25 for frame in (ir, depth))]
        if not candidates:
            return None
        _, ir, depth = min(candidates, key=lambda pair: pair[0])
        for sensor, used in ((1, ir), (3, depth)):
            while self.queues[sensor] and self.queues[sensor][0][2] <= used[2]:
                self.queues[sensor].popleft()
        return depth[0], ir[0], {'depth_us': depth[1], 'ir_us': ir[1], 'received_at': min(ir[3], depth[3])}


def frame_pixels(frame, sensor):
    import numpy as np
    expected_request = (400, 640) if sensor == 3 else (640, 400)
    expected_flags = 97 if sensor == 3 else 1
    require(sensor in (1, 3) and frame.sensor == sensor and frame.format == (100 if sensor == 3 else 203)
            and (frame.width, frame.height, frame.reported_fps) == (640, 400, 30)
            and (frame.requested_width, frame.requested_height) == expected_request
            and frame.mirroring == 0 and frame.flags == expected_flags, 'D2 帧模式或完整性检查失败，请使用 PIN')
    require(frame.data and frame.stride == 1280 and frame.bytes == 512000, 'D2 帧缓冲区无效')
    pixels = np.frombuffer(c.string_at(frame.data, frame.bytes), dtype='<u2').reshape(400, 640).copy()
    if sensor == 3:
        require(bool((pixels.ravel()[:8] == 0).all()), 'D2 无效像素屏蔽未生效，请使用 PIN')
    return pixels


class D2Camera:
    def __init__(self, runtime=SDK_ROOT):
        self.runtime = Path(runtime)
        self.device, self.sdk = P(), None
        self.pairer = Pairer()
        self._condition = threading.Condition()
        self._stop = threading.Event()
        self._thread = None
        self._latest, self._failure = None, None
        self._generation = self._consumed = 0

    def check(self, status):
        if status != 0:
            error = self.sdk.d2_error(self.device) if self.sdk else None
            raise RuntimeError('D2 深度/红外 SDK 错误，请使用 PIN：'+(error or b'unknown').decode(errors='replace')[:120])

    def __enter__(self):
        # Validate the selected mode and permissions before native loading.
        self.profile = readiness(self.runtime)
        self.intrinsics = self.profile['intrinsics']
        self.distortion = self.profile.get('distortion', [0.]*5)
        try:
            self.sdk = load_sdk(self.runtime)
            if self.profile.get('source') == 'device-factory-experimental':
                verify_factory_device(self.runtime, self.profile['serial'])
            self.check(self.sdk.d2_open(c.byref(self.device)))
            for sensor, key in ((3, 'depth_request'), (1, 'ir_request')):
                requested = self.profile[key]
                self.check(self.sdk.d2_configure(self.device, sensor, requested[0], 640, 400, requested[3]))
            self.check(self.sdk.d2_start(self.device))
            self._start_pump()
            return self
        except Exception:
            self.__exit__(None, None, None)
            raise

    def _read_pair(self):
        deadline = time.monotonic()+3
        while time.monotonic() < deadline:
            frame = Frame()
            status = self.sdk.d2_read(self.device, 1000, c.byref(frame))
            if status == 1:
                continue
            self.check(status)
            pixels = frame_pixels(frame, frame.sensor)
            self.pairer.add(frame.sensor, pixels, int(frame.sdk_timestamp_us), int(frame.frame_index), frame.host_received_ns/1e9)
            pair = self.pairer.take(time.monotonic())
            if pair is not None:
                return pair
        raise RuntimeError('D2 深度/红外未取得新鲜配对，请使用 PIN')

    def _start_pump(self):
        def pump():
            try:
                while not self._stop.is_set():
                    pair = self._read_pair()
                    with self._condition:
                        self._latest = pair
                        self._generation += 1
                        self._condition.notify_all()
            except Exception as error:
                with self._condition:
                    self._failure = error
                    self._condition.notify_all()
        self._thread = threading.Thread(target=pump, name='d2-fresh-pairs', daemon=True)
        self._thread.start()

    def read(self):
        deadline = time.monotonic()+3
        with self._condition:
            while True:
                if self._failure is not None:
                    raise RuntimeError('D2 连续取流异常，请使用 PIN') from self._failure
                require(not self._stop.is_set(), 'D2 相机已关闭')
                if self._latest is not None and self._generation > self._consumed:
                    pair = self._latest
                    self._consumed = self._generation
                    require(0 <= time.monotonic()-pair[2]['received_at'] <= .25,
                            'D2 图像交付超时，请使用 PIN')
                    return pair
                remaining = deadline-time.monotonic()
                require(remaining > 0, 'D2 等待新帧超时，请使用 PIN')
                self._condition.wait(remaining)

    def __exit__(self, *args):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(4)
            # Never close a native handle concurrently with an outstanding read.
            require(not self._thread.is_alive(), 'D2 取流未退出，请使用 PIN')
        if self.sdk and self.device:
            self.sdk.d2_close(self.device)
            self.device = P()
