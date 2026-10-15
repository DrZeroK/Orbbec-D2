"""Observe the documented DepthIrMode GET only; never set a camera property."""
import ctypes as c
import hashlib
import json
from pathlib import Path
import sys
import threading
from datetime import datetime

BASE = Path(__file__).resolve().parent
EXPECTED = 'bd08e87378eba3342f892c5d9cf00af1dfbf674ef46cec3812ebec0d669d1245'
DRIVER = BASE.parent / 'openni_runtime/OpenNI2/Drivers/orbbec.dll'


def child_get():
    sys.path.insert(0, str(BASE.parent))
    import probe_openni as runtime
    sdk = runtime.sdk
    pointer = c.c_void_p
    sdk.oniDeviceOpen.argtypes = [c.c_char_p, c.POINTER(pointer)]
    sdk.oniDeviceOpen.restype = c.c_int
    sdk.oniDeviceClose.argtypes = [pointer]
    sdk.oniDeviceClose.restype = c.c_int
    sdk.oniDeviceGetProperty.argtypes = [pointer, c.c_int, pointer, c.POINTER(c.c_int)]
    sdk.oniDeviceGetProperty.restype = c.c_int
    if sdk.oniInitialize(2003):
        raise RuntimeError('OpenNI initialization failed')
    devices, count, device = c.POINTER(runtime.DeviceInfo)(), c.c_int(), pointer()
    try:
        if sdk.oniGetDeviceList(c.byref(devices), c.byref(count)):
            raise RuntimeError('Enumeration failed')
        if not 0 <= count.value <= 100:
            raise RuntimeError('Invalid enumeration count')
        matches = [devices[i] for i in range(count.value)
                   if devices[i].vid == 0x2bc5 and devices[i].pid == 0x060d]
        if len(matches) != 1 or sdk.oniDeviceOpen(matches[0].uri, c.byref(device)):
            raise RuntimeError('Expected exactly one available D2')
        value, size = c.c_uint64(), c.c_int(8)
        status = sdk.oniDeviceGetProperty(device, 0x1080fff0, c.byref(value), c.byref(size))
        print(json.dumps({'property': '0x1080fff0', 'status': status, 'size': size.value,
                          'value': value.value if status == 0 else None}))
    finally:
        if device:
            sdk.oniDeviceClose(device)
        if devices:
            sdk.oniReleaseDeviceList(devices)
        sdk.oniShutdown()


def trace_get():
    if hashlib.sha256(DRIVER.read_bytes()).hexdigest() != EXPECTED:
        raise RuntimeError('Unexpected driver version; no process spawned')
    sys.path.insert(0, str(BASE.parent / 'reverse_tools'))
    import frida
    source = r'''
const active = new Map();
Process.attachModuleObserver({onAdded(m) {
  if (m.name.toLowerCase() !== 'orbbec.dll') return;
  Interceptor.attach(m.base.add(0x301c0), {
    onEnter(a) {
      this.thread = Process.getCurrentThreadId();
      this.out = a[1];
      const context = a[0];
      active.set(this.thread, context);
      send({kind:'depth_ir_get_enter',context:context.toString(),
            set_opcode:context.add(0x1c0).readU16(),get_opcode:context.add(0x1c2).readU16(),
            header_bytes:context.add(0x110).readU16()});
    },
    onLeave(r) {
      send({kind:'depth_ir_get_leave',status:r.toUInt32(),
            raw_mode:r.toUInt32()===0 ? this.out.readU32() : null});
      active.delete(this.thread);
    }
  });
  Interceptor.attach(m.base.add(0x25e00), {
    onEnter(a) {
      const context = active.get(Process.getCurrentThreadId());
      this.watch = context !== undefined && context.equals(a[0]);
      if (!this.watch) return;
      this.reply = a[4]; this.words = a[5];
      send({kind:'depth_ir_sender_enter',opcode:a[3].toUInt32()&65535,
            request_bytes:a[2].toUInt32()&65535,
            request_hex:Array.from(new Uint8Array(a[1].readByteArray(a[2].toUInt32()&65535)))
              .map(x=>x.toString(16).padStart(2,'0')).join('')});
    },
    onLeave(r) {
      if (!this.watch) return;
      const status=r.toUInt32(), words=status===0 ? this.words.readU16() : null;
      const reply=status===0 && !this.reply.isNull() ? this.reply.readPointer() : ptr(0);
      send({kind:'depth_ir_sender_leave',status,reply_words:words,
            raw_mode:words===2 && !reply.isNull() ? reply.readU32() : null});
    }
  });
}});
'''
    local = frida.get_local_device()
    pid = local.spawn([sys.executable, str(Path(__file__).resolve()), '--child', '--d2'], stdio='pipe')
    session = None
    done = threading.Event()
    output = BASE / ('depth_ir_mode_trace_' + datetime.now().strftime('%Y%m%d_%H%M%S_%f') + '.jsonl')
    try:
        session = local.attach(pid)
        session.on('detached', lambda *unused: done.set())
        with output.open('w', encoding='utf-8') as log:
            script = session.create_script(source)
            def receive(message, data):
                log.write(json.dumps(message) + '\n')
                log.flush()
            script.on('message', receive)
            script.load()
            local.resume(pid)
            if not done.wait(30):
                local.kill(pid)
                raise TimeoutError('Owned GET probe exceeded 30 seconds')
    finally:
        if session:
            try:
                session.detach()
            except frida.InvalidOperationError:
                pass
    events = [json.loads(line) for line in output.read_text(encoding='utf-8').splitlines()]
    if not events or any(event['type'] == 'error' for event in events):
        raise RuntimeError('No complete trace; inspect ' + str(output))
    if not any(event.get('payload', {}).get('kind') == 'depth_ir_get_leave' for event in events):
        raise RuntimeError('Expected getter was not reached; inspect ' + str(output))
    print(json.dumps({'trace': str(output), 'events': events}, indent=2))


if __name__ == '__main__':
    child_get() if '--child' in sys.argv else trace_get()
