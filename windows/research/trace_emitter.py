"""Observe real emitter SET payloads and GET replies in the owned native test."""
import hashlib
import json
from pathlib import Path
import sys
import threading

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE.parent/'reverse_tools'))
import frida

driver = BASE.parent/'openni_runtime/OpenNI2/Drivers/orbbec.dll'
if hashlib.sha256(driver.read_bytes()).hexdigest() != 'bd08e87378eba3342f892c5d9cf00af1dfbf674ef46cec3812ebec0d669d1245':
    raise RuntimeError('Unexpected driver version')
source = r'''
const observer=Process.attachModuleObserver({onAdded(m) {
  if(m.name.toLowerCase()!=='orbbec.dll') return;
  Interceptor.attach(m.base.add(0x25e00), {
    onEnter(a) {
      const context=a[0], opcode=a[3].toUInt32()&65535;
      this.kind=opcode===context.add(0x15c).readU16() ? 'set' : opcode===context.add(0x17c).readU16() ? 'get' : null;
      if(!this.kind) return;
      this.opcode=opcode; this.reply=a[4]; this.words=a[5];
      this.request=this.kind==='set' ? a[1].add(context.add(0x110).readU16()).readU16() : null;
    },
    onLeave(r) {
      if(!this.kind) return;
      const status=r.toUInt32();
      const words=status===0 ? this.words.readU16() : 0;
      const reply=this.kind==='get' && status===0 ? this.reply.readPointer() : ptr(0);
      send({kind:this.kind,opcode:this.opcode,request:this.request,status,words,
            raw:words===2 && !reply.isNull() ? reply.readU32() : null});
    }
  });
}});
'''
device = frida.get_local_device()
mode = '--lighting-state' if '--lighting-state' in sys.argv else '--lighting-delayed'
pid = device.spawn([str(BASE/'driver/build/test_capture.exe'), mode], stdio='pipe')
done = threading.Event()
session = None
try:
    session = device.attach(pid)
    session.on('detached', lambda *args: done.set())
    output = BASE/('emitter_state_wire_trace.jsonl' if mode == '--lighting-state' else 'emitter_wire_trace.jsonl')
    with output.open('w', encoding='utf-8') as log:
        def receive(message, data):
            log.write(json.dumps(message)+'\n')
            log.flush()
        script = session.create_script(source)
        script.on('message', receive)
        script.load()
        device.resume(pid)
        if not done.wait(20):
            device.kill(pid)
            raise TimeoutError('Owned native test exceeded 20 seconds')
finally:
    if session:
        try:
            session.detach()
        except frida.InvalidOperationError:
            pass
events = [json.loads(line) for line in output.read_text().splitlines()]
assert events and not any(x['type']=='error' for x in events)
print(json.dumps(events[-12:], indent=2))
