"""Read known OpenNI serial/property14 only; no streaming or persistent device writes."""
import ctypes as c
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import struct
import sys

WORK = Path('/home/USER/wheelchair/tests/d2-factory-acceptance-20261015')
RUNTIME = Path('/home/USER/wheelchair/models/d2-sdk-v0.2.0')
P = c.c_void_p


class DeviceInfo(c.Structure):
    _fields_ = [('uri',c.c_char*256),('vendor',c.c_char*256),('name',c.c_char*256),
                ('serial',c.c_char*256),('vid',c.c_uint16),('pid',c.c_uint16)]


def decode(raw):
    assert len(raw) == 120
    values = struct.unpack('<30f',raw)
    assert all(math.isfinite(v) for v in values)
    assert all(100 < values[i] < 2000 for i in (0,1,4,5))
    R = [values[8+i*3:11+i*3] for i in range(3)]
    error = max(abs(sum(R[k][i]*R[k][j] for k in range(3))-(i == j))
                for i in range(3) for j in range(3))
    determinant = sum(R[0][i]*(R[1][(i+1)%3]*R[2][(i+2)%3]
                              -R[1][(i+2)%3]*R[2][(i+1)%3]) for i in range(3))
    assert error < .01 and abs(determinant-1) < .01
    return {'l_intr_p':values[:4],'r_intr_p':values[4:8],'r2l_r':R,'r2l_t':values[17:20],
            'l_k':values[20:25],'r_k':values[25:30],
            'rotation_orthogonality_max_error':error,'rotation_determinant':determinant,
            'raw_sha256':hashlib.sha256(raw).hexdigest(),'raw_hex':raw.hex(),
            'resolution_verified':False,'intrinsics_verified':False,'verified':False}


def run():
    import fcntl
    import resource
    assert os.geteuid() == 0 and c.sizeof(DeviceInfo) == 1028
    resource.setrlimit(resource.RLIMIT_CORE,(0,0))
    resource.setrlimit(resource.RLIMIT_AS,(1024**3,1024**3))
    resource.setrlimit(resource.RLIMIT_FSIZE,(4*1024**2,4*1024**2))
    sys.path.insert(0,str(WORK.parent/'d2-calibration-live-20261015-1920'))
    import d2_camera as helper
    lock = Path('/run/user/1000/wheelchair-face-camera.lock')
    fd = os.open(lock,os.O_RDWR|os.O_NOFOLLOW)
    device,devices,count,initialized,sdk = P(),c.POINTER(DeviceInfo)(),c.c_int(),False,None
    telemetry = os.dup(1)
    def emit(value):
        os.write(telemetry,(json.dumps(value)+'\n').encode())
    try:
        info = os.fstat(fd)
        assert stat.S_ISREG(info.st_mode) and info.st_uid == 1000 and stat.S_IMODE(info.st_mode) == 0o600
        fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        assert os.stat(lock).st_ino == info.st_ino
        node,key = helper.usb_identity()
        assert os.access(node,os.R_OK|os.W_OK)
        helper.load_sdk(RUNTIME)  # Verifies all seven pinned artifacts before native loading.
        os.chdir(RUNTIME/'lib')
        sdk = c.CDLL(str(RUNTIME/'lib/libOpenNI2.so'))
        for name,args,ret in [
            ('oniInitialize',[c.c_int],c.c_int),('oniShutdown',[],None),
            ('oniGetDeviceList',[c.POINTER(c.POINTER(DeviceInfo)),c.POINTER(c.c_int)],c.c_int),
            ('oniReleaseDeviceList',[c.POINTER(DeviceInfo)],None),
            ('oniDeviceOpen',[c.c_char_p,c.POINTER(P)],c.c_int),('oniDeviceClose',[P],c.c_int),
            ('oniDeviceGetProperty',[P,c.c_int,P,c.POINTER(c.c_int)],c.c_int)]:
            getattr(sdk,name).argtypes,getattr(sdk,name).restype = args,ret
        native = os.open(WORK/'factory-current-native.log',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        os.dup2(native,1);os.dup2(native,2);os.close(native)
        assert sdk.oniInitialize(2003) == 0
        initialized = True
        assert sdk.oniGetDeviceList(c.byref(devices),c.byref(count)) == 0 and 0 < count.value <= 16
        matches = [devices[i] for i in range(count.value) if (devices[i].vid,devices[i].pid) == (0x2bc5,0x060d)]
        assert len(matches) == 1
        assert sdk.oniDeviceOpen(matches[0].uri,c.byref(device)) == 0
        values = {}
        for prop,size in ((3,256),(14,120)):
            emit({'event':'before_known_getter','property':prop,'bytes':size})
            buffer = (c.c_ubyte*4096)(*([0xA5]*4096))
            length = c.c_int(size)
            rc = sdk.oniDeviceGetProperty(device,prop,buffer,c.byref(length))
            assert rc == 0 and 0 < length.value <= size
            assert bytes(buffer[size:]) == b'\xA5'*(4096-size)
            values[prop] = bytes(buffer[:length.value])
            emit({'event':'getter_complete','property':prop,'bytes':length.value,'rc':rc})
        serial = values[3].split(b'\0')[0].decode('ascii')
        assert serial == 'D2_SAMPLE_SERIAL', 'Camera identity differs from earlier factory record'
        result = {'serial':serial,'device_key':key,'sdk_files':helper.SDK_FILES,
                  'camera_params':decode(values[14]),'images_saved':False,
                  'persistent_device_writes':False,'properties_read':[3,14]}
        out = WORK/'factory-current.json'
        with out.open('x',encoding='utf8') as stream:
            json.dump(result,stream,indent=2,allow_nan=False)
        emit({'event':'factory_read_complete','serial':serial,'sha256':result['camera_params']['raw_sha256']})
    finally:
        if sdk and device:
            sdk.oniDeviceClose(device)
        if sdk and devices:
            sdk.oniReleaseDeviceList(devices)
        if sdk and initialized:
            sdk.oniShutdown()
        os.close(fd)
        os.close(telemetry)


if __name__ == '__main__':
    if sys.argv[1:] == ['--self-test']:
        sample = [476.,476.,196.,322.,477.,477.,210.,300.,1.,0.,0.,0.,1.,0.,0.,0.,1.]+[0.]*13
        assert decode(struct.pack('<30f',*sample))['rotation_determinant'] == 1
        for bad in (bytes(120),bytes(119),struct.pack('<30f',*([float('nan')]+sample[1:]))):
            try:
                decode(bad)
            except AssertionError:
                continue
            raise AssertionError('Invalid factory data accepted')
        print(json.dumps({'self_test':True,'assertions':4,'camera_access':False}))
    else:
        run()
