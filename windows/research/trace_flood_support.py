"""Observe firmware capability queries in an owned read-only probe process."""
import hashlib
import json
from pathlib import Path
import sys
import threading

bypass = '--bypass-flood-read-gate' in sys.argv

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE.parent / 'reverse_tools'))
import frida

driver = BASE.parent / 'openni_runtime/OpenNI2/Drivers/orbbec.dll'
if hashlib.sha256(driver.read_bytes()).hexdigest() != 'bd08e87378eba3342f892c5d9cf00af1dfbf674ef46cec3812ebec0d669d1245':
    raise RuntimeError('Unexpected driver version')
source = r'''
const diagnosticBypass = BYPASS_VALUE;
const observer = Process.attachModuleObserver({onAdded(m) {
  if (m.name.toLowerCase() !== 'orbbec.dll') return;
  Interceptor.attach(m.base.add(0x2c200), {
    onEnter(a) { this.command=a[1].toUInt32(); this.sub=a[2].toUInt32(); this.output=a[3]; },
    onLeave(r) {
      if (this.command !== 0x96) return;
      const status=r.toUInt32();
      send({event:'flood_capability',command:this.command,sub:this.sub,status,
            flags:status===0 ? Array.from(new Uint8Array(this.output.readByteArray(16))) : null});
      // Diagnostic only: allow the official read opcode to run when discovery fails.
      if (diagnosticBypass && status !== 0 && this.sub === 0) {
        this.output.writeByteArray([1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0]);
        r.replace(0);
        send({event:'diagnostic_read_gate_bypass',not_a_hardware_capability:true});
      }
    }
  });
  Interceptor.attach(m.base.add(0x2eb90), {
    onEnter(a) {this.output=a[2];},
    onLeave(r) {const status=r.toUInt32(); send({event:'flood_get',status,value:status===0 ? this.output.readU32() : null});}
  });
  Interceptor.attach(m.base.add(0x25e00), {
    onEnter(a) {this.command=a[3].toUInt32()&65535; this.data=a[4]; this.size=a[5];},
    onLeave(r) {
      if (this.command !== 0x96) return;
      const status=r.toUInt32();
      const words=status===0 ? this.size.readU16() : 0;
      const data=status===0 ? this.data.readPointer() : ptr(0);
      send({event:'flood_read_wire_reply',status,words,
            bytes:words>0 && words<=16 && !data.isNull() ? Array.from(new Uint8Array(data.readByteArray(words*2))) : null});
    }
  });
}});
'''
source = source.replace('BYPASS_VALUE', 'true' if bypass else 'false')
device = frida.get_local_device()
pid = device.spawn([sys.executable, str(BASE/'probe_hello_properties.py'), '--d2'], stdio='pipe')
done = threading.Event()
session = None
try:
    session = device.attach(pid)
    session.on('detached', lambda *args: done.set())
    with (BASE/('flood_read_gate_bypass_trace.jsonl' if bypass else 'flood_firmware_trace.jsonl')).open('w', encoding='utf-8') as log:
        def receive(message, data):
            log.write(json.dumps(message)+'\n')
            log.flush()
            print(json.dumps(message), flush=True)
        script = session.create_script(source)
        script.on('message', receive)
        script.load()
        device.resume(pid)
        if not done.wait(20):
            device.kill(pid)
            raise TimeoutError('Owned read-only probe exceeded 20 seconds')
finally:
    if session:
        try:
            session.detach()
        except frida.InvalidOperationError:
            pass
