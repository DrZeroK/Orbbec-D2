"""Enumerate using the archived official SDK without installing system drivers."""
import ctypes as c
import json
import os
import sys
import hashlib
from pathlib import Path
import zipfile

BASE = Path(__file__).resolve().parent
ARCHIVE = Path(os.environ.get("D2_OPENNI_ZIP", str(BASE.parents[1] / "downloads" / "OpenNI_2.3.0.86_202210111950_4c8f5aa4_beta6_windows_x64.zip")))
RUNTIME = Path(os.environ.get('D2_OPENNI_RUNTIME', str(BASE / 'openni_runtime'))).resolve()
if hashlib.sha256(ARCHIVE.read_bytes()).hexdigest() != '8b95c8392e6ce75affacafc6fc007544f1757ae499e2e23401166e66a9486035':
    raise RuntimeError('Unrecognized official SDK archive; extraction/loading refused')
RUNTIME.mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile(ARCHIVE) as archive:
    for entry in archive.infolist():
        marker = '/Win64-Release/sdk/libs/'
        if marker not in entry.filename or entry.is_dir():
            continue
        relative = entry.filename.split(marker, 1)[1]
        target = (RUNTIME / relative).resolve()
        assert target.is_relative_to(RUNTIME), relative
        data = archive.read(entry)
        if target.exists():
            assert target.read_bytes() == data, f'Existing runtime differs: {target}'
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)

class DeviceInfo(c.Structure):
    _fields_ = [('uri', c.c_char * 256), ('vendor', c.c_char * 256),
                ('name', c.c_char * 256), ('serial', c.c_char * 256),
                ('vid', c.c_uint16), ('pid', c.c_uint16)]

# Layout and API version are taken from this SDK's OniCTypes.h and OniVersion.h.
assert c.sizeof(DeviceInfo) == 1028
assert c.sizeof(c.c_void_p) == 8
os.chdir(RUNTIME)
# Reuse Microsoft's installed runtime in this process only; do not alter system DLLs.
CRT = Path(os.environ.get('D2_VC120_DIR', str(Path(os.environ['SystemRoot']) / 'System32')))
crt_handles = []
for name in ('msvcr120.dll', 'msvcp120.dll'):
    data = (CRT / name).read_bytes()
    pe = int.from_bytes(data[60:64], 'little')
    assert int.from_bytes(data[pe + 4:pe + 6], 'little') == 0x8664
    crt_handles.append(c.CDLL(str(CRT / name)))
with os.add_dll_directory(str(RUNTIME)):
    sdk = c.CDLL(str(RUNTIME / 'OpenNI2.dll'))
    if '--d2' in sys.argv:
        # This pinned SDK omits 060d from enumeration despite containing TornadoD2 support.
        driver_path = RUNTIME / 'OpenNI2/Drivers/orbbec.dll'
        if hashlib.sha256(driver_path.read_bytes()).hexdigest() != 'bd08e87378eba3342f892c5d9cf00af1dfbf674ef46cec3812ebec0d669d1245':
            raise RuntimeError('D2 fix requires the exact verified Orbbec DLL')
        d2_driver = c.CDLL(str(driver_path))
        first_pair = (c.c_uint16 * 2).from_address(d2_driver._handle + 0x9f590)
        if list(first_pair) != [0x2bc5, 0x0300]:
            raise RuntimeError('Unexpected enumeration table; no memory was changed')
        first_pair[1] = 0x060d
        assert list(first_pair) == [0x2bc5, 0x060d]
    sdk.oniInitialize.argtypes = [c.c_int]
    sdk.oniInitialize.restype = c.c_int
    sdk.oniGetExtendedError.restype = c.c_char_p
    sdk.oniGetDeviceList.argtypes = [c.POINTER(c.POINTER(DeviceInfo)), c.POINTER(c.c_int)]
    sdk.oniGetDeviceList.restype = c.c_int
    sdk.oniReleaseDeviceList.argtypes = [c.POINTER(DeviceInfo)]
    sdk.oniShutdown.restype = None
    status = sdk.oniInitialize(2003)
    if status != 0:
        raise RuntimeError((status, sdk.oniGetExtendedError()))
    devices = c.POINTER(DeviceInfo)()
    count = c.c_int()
    try:
        status = sdk.oniGetDeviceList(c.byref(devices), c.byref(count))
        if status != 0:
            raise RuntimeError((status, sdk.oniGetExtendedError()))
        assert 0 <= count.value < 100
        kernel = c.WinDLL('kernel32', use_last_error=True)
        kernel.GetModuleHandleW.argtypes = [c.c_wchar_p]
        kernel.GetModuleHandleW.restype = c.c_void_p
        driver_loaded = bool(kernel.GetModuleHandleW('orbbec.dll'))
        assert driver_loaded, 'OpenNI did not load the Orbbec device plugin'
        print(json.dumps({'sdk': '2.3.0.86-beta6', 'd2_process_allowlist_fix': '--d2' in sys.argv, 'status': status, 'count': count.value,
                          'orbbec_driver_loaded': driver_loaded,
                          'sdk_detail': (sdk.oniGetExtendedError() or b'').decode(errors='replace'),
                          'devices': [{'name': devices[i].name.decode(errors='replace'),
                                       'vid': hex(devices[i].vid), 'pid': hex(devices[i].pid)}
                                      for i in range(count.value)]}, ensure_ascii=True))
    finally:
        if devices:
            sdk.oniReleaseDeviceList(devices)
        sdk.oniShutdown()
