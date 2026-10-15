"""Bounded D2 UVC mode probe; no files or camera controls changed."""
import argparse
import hashlib
import json
from pathlib import Path
import time
import cv2

parser=argparse.ArgumentParser()
parser.add_argument('--width',type=int,default=640)
parser.add_argument('--height',type=int,default=480)
parser.add_argument('--fourcc',choices=['MJPG','YUYV'],default='MJPG')
parser.add_argument('--frames',type=int,default=20)
parser.add_argument('--threads',type=int,choices=[1,2])
parser.add_argument('--fps',type=int,default=30)
args=parser.parse_args()
assert 2<=args.frames<=1000
if args.threads is not None:
    cv2.setNumThreads(args.threads)
devices=[]
for item in Path('/sys/class/video4linux').glob('video*'):
    if (item/'index').read_text().strip()!='0':
        continue
    parent=(item/'device').resolve()
    for p in (parent,*parent.parents):
        if (p/'idVendor').exists() and (p/'idProduct').exists():
            if ((p/'idVendor').read_text().strip(),(p/'idProduct').read_text().strip())==('2bc5','0505'):
                devices.append('/dev/'+item.name)
            break
assert len(devices)==1,devices
cap=cv2.VideoCapture(devices[0],cv2.CAP_V4L2)
try:
    assert cap.isOpened(),'RGB open failed'
    cap.set(cv2.CAP_PROP_FOURCC,cv2.VideoWriter_fourcc(*args.fourcc))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH,args.width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT,args.height)
    cap.set(cv2.CAP_PROP_BUFFERSIZE,1)
    cap.set(cv2.CAP_PROP_FPS,args.fps)
    times,hashes,means=[],[],[]
    for number in range(args.frames+8):
        ok,image=cap.read()
        assert ok and image is not None,'RGB read failed'
        assert image.shape==(args.height,args.width,3),('unexpected shape',image.shape)
        if number<8:continue
        times.append(time.monotonic())
        hashes.append(hashlib.blake2s(image.tobytes()).hexdigest())
        means.append(float(image.mean()))
    fourcc=int(cap.get(cv2.CAP_PROP_FOURCC))
    actual=''.join(chr((fourcc>>(8*i))&255) for i in range(4))
    assert actual==args.fourcc,(actual,args.fourcc)
    result={'requested':[args.fourcc,args.width,args.height], 'actual_fourcc':actual,
        'frames':len(times),'shape':list(image.shape),'reported_fps':cap.get(cv2.CAP_PROP_FPS),
        'first_host':times[0],'last_host':times[-1],'opencv_threads':cv2.getNumThreads(),
        'host_fps':(len(times)-1)/(times[-1]-times[0]),'max_gap_s':max(b-a for a,b in zip(times,times[1:])),
        'mean_min':min(means),'mean_max':max(means),'last_stddev':float(image.std()),
        'duplicate_content_pairs':sum(a==b for a,b in zip(hashes,hashes[1:])),
        'images_saved':False,'identity_inference':False}
    print(json.dumps(result),flush=True)
finally:
    cap.release()
