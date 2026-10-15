"""Pinned OpenNI ARM64 D2 loader and bounded depth probe; no firmware writes."""
import argparse
import array
import ctypes as c
import hashlib
import json
import os
from pathlib import Path
import platform
import statistics
import sys
import time

SDK_SHA256 = 'e5cc7f0246a8251ac887ac56e667301210388b1fcd038d99fae22738dabb58b7'
DRIVER_SHA256 = '24e43298e83d74bb3ce8dcf3ca28979e6334603f9d0534542aa5891cc6764e4b'
PRODUCTS_RVA = 0x109DC0
PRODUCT_COUNT_RVA = 0x109DB0
P = c.c_void_p


class DeviceInfo(c.Structure):
    _fields_ = [('uri', c.c_char * 256), ('vendor', c.c_char * 256),
                ('name', c.c_char * 256), ('serial', c.c_char * 256),
                ('vid', c.c_uint16), ('pid', c.c_uint16)]


class VideoMode(c.Structure):
    _fields_ = [('format', c.c_int), ('width', c.c_int),
                ('height', c.c_int), ('fps', c.c_int)]


class SensorInfo(c.Structure):
    _fields_ = [('type', c.c_int), ('count', c.c_int), ('modes', c.POINTER(VideoMode))]


class Frame(c.Structure):
    _fields_ = [('size', c.c_int), ('data', P), ('sensor', c.c_int),
                ('timestamp', c.c_uint64), ('index', c.c_int),
                ('width', c.c_int), ('height', c.c_int), ('mode', VideoMode),
                ('cropping', c.c_int), ('crop_x', c.c_int), ('crop_y', c.c_int),
                ('stride', c.c_int)]


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def verify_file(path, expected):
    require(hashlib.sha256(path.read_bytes()).hexdigest() == expected,
            f'Unsupported or modified official SDK artifact: {path}')


def check_d2_usb_access(sysfs_root=Path('/sys/bus/usb/devices'),
                        device_root=Path('/dev/bus/usb')):
    """Fail before oniDeviceOpen: this SDK can segfault on inaccessible USB nodes."""
    matches = []
    for entry in Path(sysfs_root).iterdir():
        try:
            vendor = (entry / 'idVendor').read_text().strip().lower()
            product = (entry / 'idProduct').read_text().strip().lower()
            if (vendor, product) != ('2bc5', '060d'):
                continue
            bus = int((entry / 'busnum').read_text().strip(), 10)
            number = int((entry / 'devnum').read_text().strip(), 10)
        except FileNotFoundError:
            continue
        require(1 <= bus <= 999 and 1 <= number <= 999, 'Invalid D2 USB bus/device number')
        matches.append(Path(device_root) / f'{bus:03d}' / f'{number:03d}')
    require(len(matches) == 1, f'Expected one D2 USB device 2bc5:060d, found {len(matches)}')
    node = matches[0]
    if not os.access(node, os.R_OK | os.W_OK):
        raise PermissionError(f'D2 USB node requires read and write permission: {node}; '
                              'camera was not opened. Resolve device permissions before retrying.')
    return node


def mapped_library(path):
    """Return the offset-zero base and actual maps of this exact loaded inode."""
    stat = path.stat()
    mappings = []
    for line in Path('/proc/self/maps').read_text().splitlines():
        parts = line.split(None, 5)
        if len(parts) != 6 or parts[5] != str(path):
            continue
        require(int(parts[4]) == stat.st_ino, 'Loaded library inode changed')
        lo, hi = (int(x, 16) for x in parts[0].split('-'))
        mappings.append((lo, hi, parts[1], int(parts[2], 16)))
    bases = [lo for lo, hi, perm, offset in mappings if offset == 0]
    require(len(bases) == 1, 'Cannot establish loaded ELF base from /proc/self/maps')
    return bases[0], mappings


def load_sdk(runtime, apply_fix=True):
    """Use only in an isolated camera worker; sets its working directory to runtime."""
    require(sys.platform == 'linux' and platform.machine().lower() in ('aarch64', 'arm64'),
            'This loader requires native Linux ARM64')
    require(c.sizeof(P) == 8 and c.sizeof(Frame) == 80 and Frame.timestamp.offset == 24,
            'Unsupported OpenNI ABI')
    runtime = Path(runtime).resolve(strict=True)
    sdk_path = runtime / 'libOpenNI2.so'
    driver_path = (runtime / 'OpenNI2/Drivers/liborbbec.so').resolve(strict=True)
    verify_file(sdk_path, SDK_SHA256)
    verify_file(driver_path, DRIVER_SHA256)
    os.chdir(runtime)
    sdk = c.CDLL(str(sdk_path), mode=c.RTLD_GLOBAL)
    driver = c.CDLL(str(driver_path), mode=c.RTLD_GLOBAL)
    base, maps = mapped_library(driver_path)
    address = base + PRODUCTS_RVA
    require(any(lo <= base + PRODUCT_COUNT_RVA and address + 180 <= hi and 'rw' in perm
                for lo, hi, perm, offset in maps), 'Enumeration table is not fully readable/writable')
    require(c.c_uint32.from_address(base + PRODUCT_COUNT_RVA).value == 45,
            'Unexpected supported-product count')
    products = (c.c_uint16 * 90).from_address(address)
    pairs = list(zip(products[::2], products[1::2]))
    require(pairs[0] == (0x2BC5, 0x0300) and all(v == 0x2BC5 for v, p in pairs)
            and (0x2BC5, 0x060D) not in pairs, 'Unexpected original product table')
    if apply_fix:
        # Only the isolated process loses 0300 support; device identity stays 060d.
        products[1] = 0x060D
        require(products[0] == 0x2BC5 and products[1] == 0x060D, 'Process patch failed')
    sdk._d2_driver = driver
    sdk._d2_fix = apply_fix
    for name, parameters, result in [
        ('oniInitialize', [c.c_int], c.c_int),
        ('oniGetExtendedError', [], c.c_char_p),
        ('oniGetDeviceList', [c.POINTER(c.POINTER(DeviceInfo)), c.POINTER(c.c_int)], c.c_int),
        ('oniReleaseDeviceList', [c.POINTER(DeviceInfo)], None),
        ('oniShutdown', [], None),
        ('oniDeviceOpen', [c.c_char_p, c.POINTER(P)], c.c_int),
        ('oniDeviceClose', [P], c.c_int),
        ('oniDeviceGetSensorInfo', [P, c.c_int], c.POINTER(SensorInfo)),
        ('oniDeviceCreateStream', [P, c.c_int, c.POINTER(P)], c.c_int),
        ('oniStreamSetProperty', [P, c.c_int, P, c.c_int], c.c_int),
        ('oniStreamStart', [P], c.c_int),
        ('oniStreamStop', [P], None), ('oniStreamDestroy', [P], None),
        ('oniWaitForAnyStream', [c.POINTER(P), c.c_int, c.POINTER(c.c_int), c.c_int], c.c_int),
        ('oniStreamReadFrame', [P, c.POINTER(c.POINTER(Frame))], c.c_int),
        ('oniFrameRelease', [c.POINTER(Frame)], None),
    ]:
        function = getattr(sdk, name)
        function.argtypes, function.restype = parameters, result
    return sdk


def measure(data, width, height, stride):
    values = array.array('H')
    values.frombytes(data)
    require(sys.byteorder == 'little' and values.itemsize == 2, 'Unsupported host pixel encoding')
    step = stride // 2
    valid = sum(v != 0 for y in range(height) for v in values[y * step:y * step + width])
    cx, cy = width // 2, height // 2
    center = [values[y * step + x] for y in range(max(0, cy - 10), min(height, cy + 11))
              for x in range(max(0, cx - 10), min(width, cx + 11))]
    center_valid = [v for v in center if v]
    return {'valid_fraction': valid / (width * height),
            'center_valid_fraction': len(center_valid) / len(center),
            'center_mm': statistics.median(center_valid) if center_valid else None}


def probe(runtime, frames, apply_fix=True):
    sdk = load_sdk(runtime, apply_fix)

    def check(status):
        if status:
            raise RuntimeError(f'OpenNI status {status}: {(sdk.oniGetExtendedError() or b"").decode(errors="replace")}')

    check(sdk.oniInitialize(2003))
    devices, count = c.POINTER(DeviceInfo)(), c.c_int()
    device, stream = P(), P()
    records = []
    try:
        check(sdk.oniGetDeviceList(c.byref(devices), c.byref(count)))
        require(0 <= count.value < 100, 'Invalid device count')
        print(json.dumps({'device_count': count.value, 'd2_process_allowlist_fix': apply_fix}), flush=True)
        matches = [devices[i] for i in range(count.value)
                   if devices[i].vid == 0x2BC5 and devices[i].pid == 0x060D]
        require(len(matches) == 1, f'Expected one D2 2bc5:060d, found {len(matches)}')
        check_d2_usb_access()
        check(sdk.oniDeviceOpen(matches[0].uri, c.byref(device)))
        sensor = sdk.oniDeviceGetSensorInfo(device, 3)
        require(bool(sensor) and 0 < sensor.contents.count < 1000, 'Missing depth sensor/modes')
        modes = [sensor.contents.modes[i] for i in range(sensor.contents.count)]
        modes_mm = [m for m in modes if m.format == 100]
        require(bool(modes_mm), 'No advertised millimeter depth mode')
        mode = next((m for m in modes_mm if (m.width, m.height, m.fps) == (400, 640, 30)), modes_mm[0])
        print(json.dumps({'mode': [mode.width, mode.height, mode.fps], 'format': mode.format}), flush=True)
        check(sdk.oniDeviceCreateStream(device, 3, c.byref(stream)))
        check(sdk.oniStreamSetProperty(stream, 3, c.byref(mode), c.sizeof(mode)))
        check(sdk.oniStreamStart(stream))
        last = -1
        started = time.monotonic()
        for n in range(frames):
            ready, frame = c.c_int(), c.POINTER(Frame)()
            check(sdk.oniWaitForAnyStream(c.byref(stream), 1, c.byref(ready), 5000))
            check(sdk.oniStreamReadFrame(stream, c.byref(frame)))
            require(bool(frame), 'SDK returned null frame')
            try:
                f = frame.contents
                require(f.sensor == 3 and f.mode.format == 100, 'Unexpected frame format')
                require(0 < f.width <= 4096 and 0 < f.height <= 4096, 'Invalid dimensions')
                require(f.data and f.width * 2 <= f.stride <= 65536 and f.stride % 2 == 0,
                        'Invalid pixel buffer or stride')
                require(f.height * f.stride <= f.size <= 128 * 1024 * 1024, 'Invalid frame byte count')
                require(f.timestamp > last, 'Non-increasing timestamp')
                last = f.timestamp
                pixels = c.string_at(f.data, f.height * f.stride)
                row = {'index': f.index, 'timestamp_us': f.timestamp,
                       **measure(pixels, f.width, f.height, f.stride)}
                records.append(row)
                if n % 15 == 0 or n == frames - 1:
                    print(json.dumps(row), flush=True)
            finally:
                sdk.oniFrameRelease(frame)
        require(any(r['valid_fraction'] > 0 for r in records), 'All pixels invalid')
        result = {'frames': len(records), 'elapsed_s': time.monotonic() - started,
                  'unit': 'mm', 'd2_process_allowlist_fix': apply_fix,
                  'calibration': 'SDK depth values; physical ruler comparison not performed', 'readings': records}
        print(json.dumps(result), flush=True)
        return result
    finally:
        if stream:
            sdk.oniStreamStop(stream)
            sdk.oniStreamDestroy(stream)
        if device:
            sdk.oniDeviceClose(device)
        if devices:
            sdk.oniReleaseDeviceList(devices)
        sdk.oniShutdown()


def self_test():
    require(c.sizeof(DeviceInfo) == 1028 and c.sizeof(VideoMode) == 16
            and c.sizeof(SensorInfo) == 16 and c.sizeof(Frame) == 80, 'ABI layout test failed')
    require(Frame.mode.offset == 44 and Frame.stride.offset == 72, 'ABI offsets failed')
    pixels = array.array('H', [1000, 0, 1200, 65535, 1100, 900, 0, 65535])
    result = measure(pixels.tobytes(), 3, 2, 8)
    require(result['center_mm'] == 1050 and result['valid_fraction'] == 4 / 6,
            'Padded-row, zero-depth and millimeter median test failed')
    print('PASS: ABI, padded rows, zero-depth rejection and millimeter median; no SDK loaded')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', type=Path, help='Directory containing libOpenNI2.so and OpenNI2/Drivers')
    parser.add_argument('--frames', type=int, default=90)
    parser.add_argument('--no-fix', action='store_true', help='Run an unmodified-process baseline')
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args()
    if args.self_test:
        self_test()
    else:
        require(args.runtime is not None and 1 <= args.frames <= 18000, 'Provide --runtime and 1..18000 frames')
        probe(args.runtime, args.frames, not args.no_fix)
