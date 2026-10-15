"""Bounded, reversible D2 RGB FPS experiments. No service or source changes."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parent
NODE='/dev/video0'
CONTROLS=('auto_exposure','exposure_time_absolute','exposure_dynamic_framerate')


def v4l(*args):
    return subprocess.check_output(['v4l2-ctl','-d',NODE,*args],text=True,stderr=subprocess.STDOUT,timeout=8)


def get_controls():
    text=v4l('--get-ctrl='+','.join(CONTROLS))
    return parse_controls(text)


def parse_controls(text):
    values={k:int(v) for k,v in re.findall(r'^[ \t]*(\w+):[ \t]*(-?\d+)(?:[ \t]+\([^\r\n]*\))?[ \t]*$',text,re.M)}
    assert set(values)==set(CONTROLS),text
    return values


def set_controls(values):
    for name,value in values.items():
        v4l('--set-ctrl='+name+'='+str(value))


def fps(times):
    assert len(times)>=2 and all(b>a for a,b in zip(times,times[1:]))
    return (len(times)-1)/(times[-1]-times[0])


def worker(fmt,frames):
    import cv2
    cv2.setNumThreads(2)
    cap=cv2.VideoCapture(NODE,cv2.CAP_V4L2)
    try:
        assert cap.isOpened(),'camera open'
        settings={cv2.CAP_PROP_FOURCC:cv2.VideoWriter_fourcc(*fmt),
            cv2.CAP_PROP_FRAME_WIDTH:640,cv2.CAP_PROP_FRAME_HEIGHT:480,
            cv2.CAP_PROP_FPS:30,cv2.CAP_PROP_BUFFERSIZE:1}
        for key,value in settings.items():
            assert cap.set(key,value),('camera setting failed',key)
        controls_before=get_controls()
        times,means,stddev,hashes=[],[],[],[]
        for i in range(frames+12):
            ok,image=cap.read()
            assert ok and image is not None and image.shape==(480,640,3),'frame'
            if i<12:
                continue
            times.append(time.monotonic())
            sample=image[::8,::8]
            means.append(float(sample.mean()))
            stddev.append(float(sample.std()))
            hashes.append(hashlib.blake2s(image.tobytes()).hexdigest())
        result={'format':fmt,'frames':len(times),'host_fps':fps(times),
            'elapsed_s':times[-1]-times[0],'first_host':times[0],'last_host':times[-1],
            'reported_fps':cap.get(cv2.CAP_PROP_FPS),'mean':sum(means)/len(means),
            'mean_min':min(means),'mean_max':max(means),'last_stddev':stddev[-1],
            'max_gap_s':max(b-a for a,b in zip(times,times[1:])),
            'unique_full_frames':len(set(hashes)),
            'adjacent_identical_frames':sum(a==b for a,b in zip(hashes,hashes[1:])),
            'unique_frames_per_second':len(set(hashes))/(times[-1]-times[0]),
            'last_value_range':[int(image.min()),int(image.max())],
            'controls_before_capture':controls_before,'controls_after_capture':get_controls(),
            'images_saved':False}
        print(json.dumps(result),flush=True)
    finally:
        cap.release()


def parent(quality=False):
    # Check the exact USB parent before allowing any temporary control write.
    item=Path('/sys/class/video4linux/video0/device').resolve()
    usb=next(p for p in (item,*item.parents) if (p/'idVendor').exists())
    assert ((usb/'idVendor').read_text().strip(),(usb/'idProduct').read_text().strip())==('2bc5','0505')
    fd=os.open('/run/user/1000/wheelchair-face-camera.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as lease:
        fcntl.flock(lease,fcntl.LOCK_EX|fcntl.LOCK_NB)
        busy=subprocess.run(['sudo','-n','fuser',NODE,'/dev/video1'],capture_output=True,text=True)
        assert not busy.stdout.strip(),busy.stdout
        initial=get_controls()
        initial_format=v4l('--get-fmt-video','--get-parm')
        size=re.search(r'Width/Height\s*:\s*(\d+)/(\d+)',initial_format)
        pixel=re.search(r"Pixel Format\s*:\s*'([^']+)'",initial_format)
        rate=re.search(r'Frames per second:\s*([\d.]+)',initial_format)
        assert size and pixel and rate,initial_format
        baseline={'controls':initial,'format':initial_format}
        (ROOT/'rgb_controls_before.json').write_text(json.dumps(baseline,indent=2))
        rows=[]
        def interrupted(signum,frame):
            raise SystemExit('interrupted '+str(signum))
        signal.signal(signal.SIGTERM,interrupted)
        try:
            configs=[('original',{'auto_exposure':initial['auto_exposure'],'exposure_dynamic_framerate':initial['exposure_dynamic_framerate']}),('fixed_auto',{'auto_exposure':3,'exposure_dynamic_framerate':0}),
                ('manual_157',{'auto_exposure':1,'exposure_dynamic_framerate':0,'exposure_time_absolute':157}),
                ('manual_100',{'auto_exposure':1,'exposure_dynamic_framerate':0,'exposure_time_absolute':100})]
            if quality:
                configs=[configs[0]]+[(f'manual_{v}',{'auto_exposure':1,'exposure_dynamic_framerate':0,'exposure_time_absolute':v}) for v in (100,157,300,1000)]
            for fmt in (('YUYV',) if quality else ('MJPG','YUYV')):
                for label,values in configs:
                    # Make each comparison independent of the previous exposure mode.
                    set_controls({'auto_exposure':1})
                    set_controls({'exposure_time_absolute':initial['exposure_time_absolute'],
                        'exposure_dynamic_framerate':initial['exposure_dynamic_framerate']})
                    set_controls({'auto_exposure':initial['auto_exposure']})
                    set_controls(values)
                    print(json.dumps({'starting':fmt+'_'+label,'controls':get_controls()}),flush=True)
                    proc=subprocess.Popen([sys.executable,'-B',__file__,'--worker',fmt,'--frames','90'],
                        stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
                    try:
                        output,_=proc.communicate(timeout=40)
                    except subprocess.TimeoutExpired:
                        proc.kill(); output,_=proc.communicate()
                    finally:
                        if proc.poll() is None:
                            proc.kill();proc.wait()
                    prefix='quality_' if quality else ''
                    (ROOT/(prefix+fmt+'_'+label+'.log')).write_text(output)
                    row={'case':fmt+'_'+label,'exit':proc.returncode}
                    for line in output.splitlines():
                        try:
                            data=json.loads(line)
                        except ValueError:
                            continue
                        if 'host_fps' in data:
                            row.update(data)
                    rows.append(row)
                    (ROOT/(prefix+'rgb_exposure_results.json')).write_text(json.dumps(rows,indent=2))
                    print(json.dumps(row),flush=True)
        finally:
            set_controls({'auto_exposure':1})
            set_controls({'exposure_time_absolute':initial['exposure_time_absolute'],
                'exposure_dynamic_framerate':initial['exposure_dynamic_framerate']})
            set_controls({'auto_exposure':initial['auto_exposure']})
            v4l('--set-fmt-video=width='+size[1]+',height='+size[2]+',pixelformat='+pixel[1])
            v4l('--set-parm='+rate[1])
            restored=get_controls()
            result={'initial':initial,'restored':restored,'controls_restored':initial==restored,
                'restored_format':v4l('--get-fmt-video','--get-parm')}
            (ROOT/('quality_rgb_restore.json' if quality else 'rgb_restore.json')).write_text(json.dumps(result,indent=2))
            print(json.dumps(result),flush=True)
            assert initial==restored,'camera control restoration failed'


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--worker',choices=['MJPG','YUYV'])
    parser.add_argument('--frames',type=int,default=90)
    parser.add_argument('--self-test',action='store_true')
    parser.add_argument('--quality',action='store_true')
    args=parser.parse_args()
    assert 2<=args.frames<=1000
    if args.self_test:
        assert abs(fps([1,1+1/30,1+2/30])-30)<1e-9
        assert parse_controls('auto_exposure: 3 (Aperture Priority Mode)\nexposure_time_absolute: 157\nexposure_dynamic_framerate: 1\n')==dict(zip(CONTROLS,(3,157,1)))
        print('PASS: frame rate and V4L2 control parser')
    elif args.worker:
        worker(args.worker,args.frames)
    else:
        parent(args.quality)
