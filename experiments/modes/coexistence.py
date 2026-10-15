"""Compare unchanged auto-exposure RGB formats while standard depth/IR are active."""
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys

import rgb_fps_experiment as rgb

ROOT=Path(__file__).resolve().parent
PROBE='/home/USER/wheelchair/tests/d2-mx6000-20261015-1108/probe.py'
DUAL=json.dumps([[3,[100,400,640,30]],[1,[203,640,400,30]]])
fd=os.open('/run/user/1000/wheelchair-face-camera.lock',os.O_RDWR|os.O_NOFOLLOW)
with os.fdopen(fd,'w') as lease:
    fcntl.flock(lease,fcntl.LOCK_EX|fcntl.LOCK_NB)
    busy=subprocess.run(['sudo','-n','fuser','/dev/video0','/dev/video1','/dev/bus/usb/001/009'],capture_output=True,text=True)
    assert not busy.stdout.strip(),busy.stdout
    initial=rgb.get_controls()
    assert initial['auto_exposure']==3,initial
    try:
        results=[]
        for fmt in ('MJPG','YUYV'):
            print(json.dumps({'starting':fmt}),flush=True)
            with (ROOT/('coexist_'+fmt+'_depth_ir.log')).open('w') as out:
                depth=subprocess.Popen(['sudo','-n','timeout','--kill-after=3s','40s','python3','-B',PROBE,'--modes',DUAL,'--seconds','30','--frames','10000'],stdout=out,stderr=subprocess.STDOUT)
                try:
                    result=subprocess.run(['timeout','--kill-after=3s','38s',sys.executable,'-B',str(ROOT/'rgb_fps_experiment.py'),'--worker',fmt,'--frames','120'],capture_output=True,text=True)
                    (ROOT/('coexist_'+fmt+'_rgb.log')).write_text(result.stdout+result.stderr)
                finally:
                    depth_rc=depth.wait(timeout=45)
                row={'format':fmt,'rgb_exit':result.returncode,'depth_ir_exit':depth_rc}
                for line in result.stdout.splitlines():
                    try:
                        value=json.loads(line)
                    except ValueError:
                        continue
                    if 'host_fps' in value:
                        row['rgb']=value
                results.append(row)
                print(json.dumps(row),flush=True)
        (ROOT/'coexistence_results.json').write_text(json.dumps(results,indent=2))
    finally:
        # Format negotiation is per test; restore the original idle RGB format.
        rgb.v4l('--set-fmt-video=width=640,height=480,pixelformat=MJPG','--set-parm=30')
        assert rgb.get_controls()==initial,'auto-exposure controls unexpectedly changed'
