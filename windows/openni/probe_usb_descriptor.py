"""Read USB descriptors using the libusb shipped with the official Orbbec SDK."""
import ctypes as c
import json
from pathlib import Path

root = Path(__file__).resolve().parents[2]
usb = c.CDLL(str(root / 'bin/d2_runtime/ob_usb.dll'))
P = c.c_void_p


class Descriptor(c.Structure):
    _fields_ = [('length', c.c_uint8), ('type', c.c_uint8), ('usb', c.c_uint16),
                ('cls', c.c_uint8), ('subclass', c.c_uint8), ('protocol', c.c_uint8),
                ('packet', c.c_uint8), ('vid', c.c_uint16), ('pid', c.c_uint16),
                ('release', c.c_uint16), ('manufacturer', c.c_uint8),
                ('product', c.c_uint8), ('serial', c.c_uint8), ('configs', c.c_uint8)]


assert c.sizeof(Descriptor) == 18 and Descriptor.vid.offset == 8
for name, params, result in [
    ('libusb_init', [c.POINTER(P)], c.c_int),
    ('libusb_exit', [P], None),
    ('libusb_get_device_list', [P, c.POINTER(c.POINTER(P))], c.c_ssize_t),
    ('libusb_free_device_list', [c.POINTER(P), c.c_int], None),
    ('libusb_get_device_descriptor', [P, c.POINTER(Descriptor)], c.c_int),
    ('libusb_get_device_speed', [P], c.c_int),
    ('libusb_open', [P, c.POINTER(P)], c.c_int),
    ('libusb_close', [P], None),
    ('libusb_get_string_descriptor_ascii', [P, c.c_uint8, P, c.c_int], c.c_int),
]:
    f = getattr(usb, name)
    f.argtypes, f.restype = params, result

ctx = P()
assert usb.libusb_init(c.byref(ctx)) == 0
devices = c.POINTER(P)()
try:
    count = usb.libusb_get_device_list(ctx, c.byref(devices))
    assert 0 <= count < 1024, count
    print(json.dumps({'usb_count': count}), flush=True)
    for i in range(count):
        d = Descriptor()
        status = usb.libusb_get_device_descriptor(devices[i], c.byref(d))
        assert status == 0, status
        if d.vid != 0x2bc5:
            continue
        row = {'vid': hex(d.vid), 'pid': hex(d.pid), 'usb_bcd': hex(d.usb),
               'release_bcd': hex(d.release), 'speed': usb.libusb_get_device_speed(devices[i]),
               'class': d.cls, 'configs': d.configs}
        handle = P()
        row['open_status'] = usb.libusb_open(devices[i], c.byref(handle))
        try:
            if handle:
                for key in ('manufacturer', 'product', 'serial'):
                    index = getattr(d, key)
                    if not index:
                        row[key] = {'index': 0}
                        continue
                    buf = c.create_string_buffer(256)
                    result = usb.libusb_get_string_descriptor_ascii(handle, index, buf, len(buf))
                    row[key] = {'index': index, 'status': result,
                                'text': buf.raw[:result].decode(errors='replace') if result >= 0 else None}
        finally:
            if handle:
                usb.libusb_close(handle)
        print(json.dumps(row), flush=True)
finally:
    if devices:
        usb.libusb_free_device_list(devices, 1)
    usb.libusb_exit(ctx)
