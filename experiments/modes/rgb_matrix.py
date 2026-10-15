import fcntl,json,os,pathlib,re,subprocess,sys
root=pathlib.Path(__file__).resolve().parent
lock=os.open('/run/user/1000/wheelchair-face-camera.lock',os.O_RDWR|os.O_NOFOLLOW)
def ctl(*args):return subprocess.check_output(['v4l2-ctl','-d','/dev/video0',*args],text=True,timeout=5)
with os.fdopen(lock,'w') as f:
 fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
 busy=subprocess.run(['sudo','-n','fuser','/dev/video0','/dev/video1','/dev/bus/usb/001/009'],capture_output=True,text=True)
 assert not busy.stdout.strip(),busy.stdout
 initial=ctl('--get-fmt-video','--get-parm');controls=ctl('--get-ctrl=auto_exposure,exposure_time_absolute,exposure_dynamic_framerate')
 size=re.search(r'Width/Height\s*:\s*(\d+)/(\d+)',initial);pixel=re.search(r"Pixel Format\s*:\s*'([^']+)'",initial);rate=re.search(r'Frames per second:\s*([\d.]+)',initial)
 assert size and pixel and rate,initial
 (root/'rgb-before.json').write_text(json.dumps({'format':initial,'controls':controls}))
 rows=[]
 try:
  for fmt in ('MJPG','YUYV'):
   for w,h,fps in [(2048,1536,15),(928,696,30),(1024,768,30),(640,480,30),(320,240,30)]:
    name=f'rgb-{fmt}-{w}-{h}';print(json.dumps({'starting':name}),flush=True)
    p=subprocess.run([sys.executable,'-B',str(root/'rgb_worker.py'),'--width',str(w),'--height',str(h),'--fourcc',fmt,'--fps',str(fps),'--frames','24','--threads','2'],capture_output=True,text=True,timeout=25)
    (root/(name+'.log')).write_text(p.stdout+p.stderr)
    row={'case':name,'target_fps':fps,'exit':p.returncode}
    for line in p.stdout.splitlines():
     try:v=json.loads(line)
     except ValueError:continue
     if 'host_fps' in v:row.update(v)
    rows.append(row);(root/'rgb-results.json').write_text(json.dumps(rows,indent=2));print(json.dumps(row),flush=True)
 finally:
  ctl('--set-fmt-video=width='+size[1]+',height='+size[2]+',pixelformat='+pixel[1]);ctl('--set-parm='+rate[1])
  after=ctl('--get-fmt-video','--get-parm');after_controls=ctl('--get-ctrl=auto_exposure,exposure_time_absolute,exposure_dynamic_framerate')
  assert controls==after_controls,'RGB controls changed'
  (root/'rgb-after.json').write_text(json.dumps({'format':after,'controls':after_controls,'controls_unchanged':True}))
