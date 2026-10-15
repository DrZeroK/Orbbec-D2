"""Observe only the owned OpenNI probe process; no on-disk SDK changes."""
import hashlib
import json
from pathlib import Path
import sys
import threading

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE / 'reverse_tools'))
import frida

dll = BASE / 'openni_runtime/OpenNI2/Drivers/orbbec.dll'
assert hashlib.sha256(dll.read_bytes()).hexdigest() == 'bd08e87378eba3342f892c5d9cf00af1dfbf674ef46cec3812ebec0d669d1245'
source = r'''
const observer = Process.attachModuleObserver({onAdded(m) {
  if (m.name.toLowerCase() !== 'orbbec.dll') return;
  send({event:'module',name:m.name,base:m.base.toString()});
  Interceptor.attach(m.base.add(0x56b30), {
    onEnter(a) { this.vid=a[0].toUInt32()&65535; this.pid=a[1].toUInt32()&65535; this.count=a[3]; },
    onLeave(r) { send({event:'enumerate_usb',vid:this.vid,pid:this.pid,status:r.toUInt32(),count:this.count.readU32()}); }
  });
}});
'''
done = threading.Event()
output = BASE / 'openni_enum_trace.jsonl'
device = frida.get_local_device()
pid = device.spawn([sys.executable, str(BASE / 'probe_openni.py')], stdio='pipe')
session = None
try:
    session = device.attach(pid)
    session.on('detached', lambda *args: done.set())
    with output.open('w', encoding='utf-8') as log:
        def receive(message, data):
            log.write(json.dumps(message) + '\n')
            log.flush()
            print(json.dumps(message), flush=True)
        script = session.create_script(source)
        script.on('message', receive)
        script.load()
        device.resume(pid)
        if not done.wait(20):
            device.kill(pid)
            raise TimeoutError('Owned probe exceeded 20 seconds')
finally:
    if session:
        try:
            session.detach()
        except frida.InvalidOperationError:
            pass
