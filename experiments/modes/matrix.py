import configparser,json,pathlib,shutil,subprocess,time
root=pathlib.Path(__file__).resolve().parent
source=pathlib.Path('/home/USER/wheelchair/tests/d2-sdk-20261015-1321/package-arm64')
busy=subprocess.run(['fuser','/dev/video0','/dev/video1','/dev/bus/usb/001/009'],capture_output=True,text=True)
assert not busy.stdout.strip(),busy.stdout
configs=[('default',None),('filter0',0),('filter1',1)]
results=[]
for label,filter_value in configs:
 target=root/('pkg-v3-'+label)
 assert not target.exists()
 shutil.copytree(source,target)
 cfgpath=target/'lib/OpenNI2/Drivers/orbbec.ini'
 text=(source/'lib/OpenNI2/Drivers/orbbec.ini').read_text()
 if filter_value is not None:
  assert text.count('SoftFilter=2')==1
  text=text.replace('SoftFilter=2','SoftFilter='+str(filter_value))
 cfgpath.write_text(text)
 cfgpath=target/'lib/OpenNI.ini'
 text=cfgpath.read_text().replace(';Verbosity=0','Verbosity=0').replace(';LogToConsole=1','LogToConsole=1')
 cfgpath.write_text(text)
 cmd=['g++','-std=c++17','-O2','-I'+str(source/'include/openni'),str(root/'raw_probe.cpp'),'-L'+str(target/'lib'),'-lOpenNI2','-Wl,-rpath,$ORIGIN/../lib','-o',str(target/'bin/raw_probe')]
 subprocess.run(cmd,check=True)
 cases=[(3,1,5,8)]
 if label=='default':cases=[(3,0,30,5),(3,1,5,8),(3,1,30,8),(1,1,5,8),(1,1,30,8)]
 for sensor,hd,fps,seconds in cases:
  name=f'{label}-{sensor}-{hd}-{fps}'
  print(json.dumps({'starting':name}),flush=True)
  proc=subprocess.run(['timeout','--kill-after=3s',str(seconds+12)+'s',str(target/'bin/raw_probe'),str(sensor),str(hd),str(fps),str(seconds)],cwd=str(root),capture_output=True,text=True)
  (root/(name+'.log')).write_text(proc.stdout+proc.stderr)
  values=[]
  for line in proc.stdout.splitlines():
   try:value=json.loads(line)
   except ValueError:continue
   if 'summary' in value or 'firmware_stage' in value or 'mode_rc' in value:values.append(value)
  row={'case':name,'exit':proc.returncode,'values':values};results.append(row)
  (root/'matrix-results.json').write_text(json.dumps(results,indent=2));print(json.dumps(row),flush=True)
