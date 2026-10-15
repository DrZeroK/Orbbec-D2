"""Minimal Python consumer of the native SDK; no in-memory driver patch or saved images."""
import ctypes as c
import json
from pathlib import Path
import sys
import time

class Frame(c.Structure):
    _fields_=[('data',c.c_void_p),('bytes',c.c_size_t),
        *[(name,c.c_int) for name in ('sensor','format','width','height','stride',
            'requested_width','requested_height','reported_fps','mirroring','frame_index')],
        ('sdk_timestamp_us',c.c_uint64),('host_received_ns',c.c_uint64),('flags',c.c_uint32)]

def main():
    if len(sys.argv)!=3:
        raise SystemExit('Usage: python3 capture.py /path/to/d2-package seconds')
    seconds=int(sys.argv[2])
    if not 1<=seconds<=60:
        raise SystemExit('seconds must be 1..60')
    assert c.sizeof(Frame)==80 and Frame.sdk_timestamp_us.offset==56
    sdk=c.CDLL(str(Path(sys.argv[1]).resolve()/'lib/libd2sdk.so'))
    pointer=c.c_void_p
    for name,args,result in [('d2_open',[c.POINTER(pointer)],c.c_int),
        ('d2_configure',[pointer]+[c.c_int]*5,c.c_int),('d2_start',[pointer],c.c_int),
        ('d2_read',[pointer,c.c_int,c.POINTER(Frame)],c.c_int),('d2_close',[pointer],None),
        ('d2_error',[pointer],c.c_char_p)]:
        fn=getattr(sdk,name);fn.argtypes=args;fn.restype=result
    def check(rc):
        if rc!=0:
            raise RuntimeError((sdk.d2_error(device) or b'native SDK error').decode(errors='replace'))
    device=pointer()
    check(sdk.d2_open(c.byref(device)))
    try:
        check(sdk.d2_configure(device,3,100,640,400,30))
        check(sdk.d2_configure(device,1,203,640,400,30))
        check(sdk.d2_start(device))
        end=time.monotonic()+seconds
        counts={1:0,3:0}
        while time.monotonic()<end:
            frame=Frame();check(sdk.d2_read(device,3000,c.byref(frame)))
            counts[frame.sensor]+=1
            if counts[frame.sensor]==1:
                print(json.dumps({'sensor':frame.sensor,'shape':[frame.height,frame.width],
                    'flags':frame.flags,'sdk_clock_verified':False}),flush=True)
        print(json.dumps({'counts':counts,'images_saved':False,'python_memory_patch':False}))
    finally:
        sdk.d2_close(device)

if __name__=='__main__':
    main()
