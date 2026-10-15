"""Read D2 lighting capabilities without changing device settings."""
import ctypes as c
import json
from pathlib import Path
import sys
import time

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE.parent))
import probe_openni as runtime

sdk = runtime.sdk
P = c.c_void_p
for name, parameters, result in [
    ('oniDeviceOpen', [c.c_char_p, c.POINTER(P)], c.c_int),
    ('oniDeviceClose', [P], c.c_int),
    ('oniDeviceGetProperty', [P, c.c_int, P, c.POINTER(c.c_int)], c.c_int),
    ('oniDeviceIsPropertySupported', [P, c.c_int], c.c_int),
]:
    function = getattr(sdk, name)
    function.argtypes, function.restype = parameters, result

def check(status):
    if status:
        raise RuntimeError((status, sdk.oniGetExtendedError()))

check(sdk.oniInitialize(2003))
devices, count, device = c.POINTER(runtime.DeviceInfo)(), c.c_int(), P()
properties = {}
try:
    check(sdk.oniGetDeviceList(c.byref(devices), c.byref(count)))
    matches = [devices[i] for i in range(count.value)
               if devices[i].vid == 0x2bc5 and devices[i].pid == 0x060d]
    if len(matches) != 1:
        raise RuntimeError(f'Expected one D2, found {len(matches)}')
    check(sdk.oniDeviceOpen(matches[0].uri, c.byref(device)))
    for name, prop in [
        ('laser_enable', 15), ('emitter_state', 0x1080e007),
        ('emitter_state_v1', 0x1080ffbf), ('flood_state', 0x1080ff94),
        ('ir_gain', 0x1080ff95), ('ir_exposure', 0x1080ff96),
        ('flood_level', 0x1080ffca),
        ('depth_ir_mode', 0x1080fff0),
    ]:
        attempts = []
        for width in (1, 2, 4, 8, 16, 64):
            value, size = c.create_string_buffer(width), c.c_int(width)
            start = time.perf_counter()
            status = sdk.oniDeviceGetProperty(device, prop, value, c.byref(size))
            attempts.append(dict(status=status, size=size.value,
                elapsed_ms=(time.perf_counter()-start)*1000,
                value=int.from_bytes(value.raw[:size.value], 'little') if status == 0 and 0 < size.value <= width else None))
        properties[name] = dict(id=hex(prop),
            advertised=bool(sdk.oniDeviceIsPropertySupported(device, prop)), attempts=attempts)
    result = dict(scope='read-only public OpenNI properties', properties=properties)
    (BASE/'lighting_capabilities.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result, indent=2))
finally:
    if device:
        sdk.oniDeviceClose(device)
    if devices:
        sdk.oniReleaseDeviceList(devices)
    sdk.oniShutdown()
