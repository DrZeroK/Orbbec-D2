"""Capture depth with the archived OpenNI SDK; save measurements beside this script."""
import argparse
import ctypes as c
from datetime import datetime
import json
import time

import numpy as np
import probe_openni as runtime

parser = argparse.ArgumentParser()
parser.add_argument('--frames', type=int, default=90)
parser.add_argument('--d2', action='store_true')
parser.add_argument('--ir', action='store_true', help='Capture 16-bit infrared instead of depth')
parser.add_argument('--high-resolution', action='store_true')
parser.add_argument('--preview', action='store_true')
parser.add_argument('--save-frame', action='store_true', help='Explicitly save the last raw frame (may contain personal data)')
args = parser.parse_args()
assert 1 <= args.frames <= 18000
sdk = runtime.sdk


class VideoMode(c.Structure):
    _fields_ = [('format', c.c_int), ('width', c.c_int),
                ('height', c.c_int), ('fps', c.c_int)]


class SensorInfo(c.Structure):
    _fields_ = [('type', c.c_int), ('count', c.c_int),
                ('modes', c.POINTER(VideoMode))]


class Frame(c.Structure):
    _fields_ = [('size', c.c_int), ('data', c.c_void_p), ('sensor', c.c_int),
                ('timestamp', c.c_uint64), ('index', c.c_int),
                ('width', c.c_int), ('height', c.c_int), ('mode', VideoMode),
                ('cropping', c.c_int), ('crop_x', c.c_int), ('crop_y', c.c_int),
                ('stride', c.c_int)]


# ABI checks against the bundled Win64 OniCTypes.h, including pointer alignment.
assert c.sizeof(VideoMode) == 16 and c.sizeof(SensorInfo) == 16
assert c.sizeof(Frame) == 80 and Frame.timestamp.offset == 24
P = c.c_void_p
for name, parameters, result in [
    ('oniDeviceOpen', [c.c_char_p, c.POINTER(P)], c.c_int),
    ('oniDeviceClose', [P], c.c_int),
    ('oniDeviceGetSensorInfo', [P, c.c_int], c.POINTER(SensorInfo)),
    ('oniDeviceCreateStream', [P, c.c_int, c.POINTER(P)], c.c_int),
    ('oniStreamSetProperty', [P, c.c_int, P, c.c_int], c.c_int),
    ('oniStreamGetProperty', [P, c.c_int, P, c.POINTER(c.c_int)], c.c_int),
    ('oniStreamStart', [P], c.c_int),
    ('oniStreamStop', [P], None), ('oniStreamDestroy', [P], None),
    ('oniWaitForAnyStream', [c.POINTER(P), c.c_int, c.POINTER(c.c_int), c.c_int], c.c_int),
    ('oniStreamReadFrame', [P, c.POINTER(c.POINTER(Frame))], c.c_int),
    ('oniFrameRelease', [c.POINTER(Frame)], None),
]:
    function = getattr(sdk, name)
    function.argtypes, function.restype = parameters, result


def check(status):
    if status:
        raise RuntimeError((status, (sdk.oniGetExtendedError() or b'').decode(errors='replace')))


check(sdk.oniInitialize(2003))
devices = c.POINTER(runtime.DeviceInfo)()
count = c.c_int()
device, stream = P(), P()
records = []
window = None
closing = False
sensor_type, pixel_format = (1, 203) if args.ir else (3, 100)
unit = 'raw_ir' if args.ir else 'mm'
try:
    check(sdk.oniGetDeviceList(c.byref(devices), c.byref(count)))
    matches = [devices[i] for i in range(count.value)
               if devices[i].vid == 0x2bc5 and devices[i].pid == 0x060d]
    assert len(matches) == 1, f'Expected one attached 2bc5:060d, found {len(matches)}'
    info = matches[0]
    check(sdk.oniDeviceOpen(info.uri, c.byref(device)))
    sensor = sdk.oniDeviceGetSensorInfo(device, sensor_type)
    assert sensor and 0 < sensor.contents.count < 1000
    modes = [sensor.contents.modes[i] for i in range(sensor.contents.count)]
    mode_list = [dict(format=m.format, width=m.width, height=m.height, fps=m.fps) for m in modes]
    print(json.dumps({'sensor': sensor_type, 'modes': mode_list}), flush=True)
    usable = [m for m in modes if m.format == pixel_format]
    assert usable, 'Required 16-bit format is not advertised'
    preferred = (640, 400, 30) if args.ir else (400, 640, 30)
    mode = max(usable, key=lambda m: m.width * m.height) if args.high_resolution else next((m for m in usable if (m.width, m.height, m.fps) == preferred), usable[0])
    check(sdk.oniDeviceCreateStream(device, sensor_type, c.byref(stream)))
    check(sdk.oniStreamSetProperty(stream, 3, c.byref(mode), c.sizeof(mode)))
    input_format, property_size = c.c_uint64(), c.c_int(8)
    check(sdk.oniStreamGetProperty(stream, 0x10800001, c.byref(input_format), c.byref(property_size)))
    print(json.dumps({'input_format': input_format.value}), flush=True)
    if args.preview:
        import tkinter as tk
        from PIL import Image, ImageTk, ImageDraw
        window = tk.Tk()
        window.title('D2 infrared' if args.ir else 'D2 depth - centre distance (mm)')
        display = tk.Label(window)
        display.pack()
        caption = tk.Label(window, font=('Segoe UI', 14))
        caption.pack()
        def close_preview():
            global closing
            closing = True
        window.protocol('WM_DELETE_WINDOW', close_preview)
    check(sdk.oniStreamStart(stream))
    started = time.monotonic()
    last_timestamp = -1
    for n in range(args.frames):
        ready = c.c_int()
        check(sdk.oniWaitForAnyStream(c.byref(stream), 1, c.byref(ready), 5000))
        frame = c.POINTER(Frame)()
        check(sdk.oniStreamReadFrame(stream, c.byref(frame)))
        try:
            f = frame.contents
            assert f.sensor == sensor_type and f.mode.format == pixel_format
            assert 0 < f.width <= 4096 and 0 < f.height <= 4096
            assert f.data and f.stride >= f.width * 2 and f.stride % 2 == 0
            assert f.size >= f.height * f.stride
            assert f.timestamp > last_timestamp, 'Non-increasing frame timestamp'
            last_timestamp = f.timestamp
            pixels = (c.c_uint16 * (f.height * f.stride // 2)).from_address(f.data)
            depth = np.ctypeslib.as_array(pixels).reshape(f.height, f.stride // 2)[:, :f.width].copy()
            valid = depth[depth > 0]
            cy, cx = f.height // 2, f.width // 2
            center = depth[cy-10:cy+11, cx-10:cx+11]
            center_valid = center[center > 0]
            row = dict(frame=f.index, timestamp_us=f.timestamp,
                       valid_fraction=float(valid.size / depth.size),
                       center_valid_fraction=float(center_valid.size / center.size),
                       unit=unit,
                       **{('center_raw' if args.ir else 'center_mm'): float(np.median(center_valid)) if center_valid.size else None,
                          ('min_raw' if args.ir else 'min_mm'): int(valid.min()) if valid.size else None,
                          ('max_raw' if args.ir else 'max_mm'): int(valid.max()) if valid.size else None})
            records.append(row)
            if not args.ir:
                value = row['center_mm']
                row['center_status'] = ('no_data' if value is None else
                                        'in_nominal_range' if 300 <= value <= 1300 else 'out_of_range')
            if n % 15 == 0 or n == args.frames - 1:
                print(json.dumps(row), flush=True)
            if window:
                if args.ir:
                    upper = max(1, float(np.percentile(valid, 99))) if valid.size else 1
                    picture = Image.fromarray(np.clip(depth.astype(float) * 255 / upper, 0, 255).astype('uint8')).convert('RGB')
                else:
                    level = np.clip((depth.astype(float) - 300) / 1000, 0, 1)
                    rgb = np.stack([255*(1-level), 255*(1-np.abs(2*level-1)), 255*level], axis=-1).astype('uint8')
                    rgb[(depth < 300) | (depth > 1300)] = 0
                    picture = Image.fromarray(rgb)
                draw = ImageDraw.Draw(picture)
                draw.rectangle((cx-10, cy-10, cx+10, cy+10), outline='white', width=2)
                picture.thumbnail((800, 640))
                photo = ImageTk.PhotoImage(picture)
                display.configure(image=photo)
                display.image = photo
                value = row.get('center_raw' if args.ir else 'center_mm')
                status = '' if args.ir else f" | {row['center_status']} (300-1300 mm)"
                caption.configure(text=f'Centre: {value if value is not None else "invalid"} {unit} | {f.width}x{f.height}{status}')
                window.update()
        finally:
            sdk.oniFrameRelease(frame)
        if closing:
            break
    elapsed = time.monotonic() - started
    assert any(r['valid_fraction'] > 0 for r in records), 'All depth pixels were invalid'
    destination = runtime.BASE / (('ir_' if args.ir else 'depth_') + datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
    destination.mkdir()
    array_path = destination / ('last_ir_raw.npy' if args.ir else 'last_depth_mm.npy')
    if args.save_frame:
        np.save(array_path, depth, allow_pickle=False)
        assert np.array_equal(np.load(array_path, allow_pickle=False), depth)
    result = dict(device=info.name.decode(errors='replace'), vid='2bc5', pid='060d',
                  d2_process_allowlist_fix=args.d2, calibration='SDK millimetres; ruler verification recorded separately',
                  width=depth.shape[1], height=depth.shape[0], unit=unit,
                  input_format=input_format.value,
                  frames=len(records), elapsed_s=elapsed, modes=mode_list, readings=records)
    (destination / 'measurements.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps({'saved': str(destination), 'frames': len(records), 'elapsed_s': elapsed}), flush=True)
finally:
    if window:
        window.destroy()
    if stream:
        sdk.oniStreamStop(stream)
        sdk.oniStreamDestroy(stream)
    if device:
        sdk.oniDeviceClose(device)
    if devices:
        sdk.oniReleaseDeviceList(devices)
    sdk.oniShutdown()
