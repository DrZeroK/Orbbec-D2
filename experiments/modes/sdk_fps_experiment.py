"""Compare temporary copies of documented SDK settings; preserve original runtime."""
import configparser
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parent
SOURCE=Path('/home/USER/wheelchair/tests/d2-20261015/runtime')
OLD=Path('/home/USER/wheelchair/tests/d2-mx6000-20261015-1108')


def configure(path,section,key,value):
    cfg=configparser.ConfigParser()
    cfg.optionxform=str
    cfg.read(path)
    cfg.set(section,key,str(value))
    with path.open('w') as out:
        cfg.write(out)


if len(sys.argv)>1:
    sys.path.insert(0,str(OLD))
    import probe
    probe.RUNTIME=ROOT/sys.argv[1]
    modes={'ir60':[[1,[203,320,240,60]]], 'depth_hd':[[3,[100,800,1280,5]]]}[sys.argv[2]]
    sys.argv=[__file__,'--modes',json.dumps(modes),'--seconds','12','--frames','60']
    probe.main()
else:
    # All writes are to fresh runtime copies under tests, never the pinned runtime.
    source_hashes={str(p.relative_to(SOURCE)):hashlib.sha256(p.read_bytes()).hexdigest()
        for p in SOURCE.rglob('*') if p.is_file()}
    fd=os.open('/run/user/1000/wheelchair-face-camera.lock',os.O_RDWR|os.O_NOFOLLOW)
    with os.fdopen(fd,'w') as lease:
        fcntl.flock(lease,fcntl.LOCK_EX|fcntl.LOCK_NB)
        busy=subprocess.run(['sudo','-n','fuser','/dev/bus/usb/001/009'],capture_output=True,text=True)
        assert not busy.stdout.strip(),busy.stdout
        configs=[('runtime_baseline',None),('runtime_no_filter',('Depth','SoftFilter','0')),
            ('runtime_ir60',('IR','FPS','60'))]
        for name,setting in configs:
            target=ROOT/name
            assert not target.exists(),'preserve prior experiment directory'
            shutil.copytree(SOURCE,target)
            if setting:
                configure(target/'OpenNI2/Drivers/orbbec.ini',*setting)
        results=[]
        for case,runtime,mode in [('hd_default','runtime_baseline','depth_hd'),
            ('hd_no_filter','runtime_no_filter','depth_hd'),('ir60_default','runtime_baseline','ir60'),
            ('ir60_ini60','runtime_ir60','ir60')]:
            print(json.dumps({'starting':case}),flush=True)
            cmd=['sudo','-n','timeout','--kill-after=3s','25s','python3','-B',__file__,runtime,mode]
            output=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
            (ROOT/(case+'.log')).write_text(output.stdout)
            row={'case':case,'exit':output.returncode}
            for line in output.stdout.splitlines():
                try:
                    value=json.loads(line)
                except ValueError:
                    continue
                if value.get('kind')=='capture_summary':
                    row['summary']=value
            results.append(row)
            print(json.dumps(row),flush=True)
        after={str(p.relative_to(SOURCE)):hashlib.sha256(p.read_bytes()).hexdigest()
            for p in SOURCE.rglob('*') if p.is_file()}
        assert source_hashes==after,'original SDK changed'
        (ROOT/'sdk_fps_results.json').write_text(json.dumps({'original_runtime_unchanged':True,'results':results},indent=2))
