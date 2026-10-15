"""Isolated numeric-only D2 timing diagnostic. Never grants alignment approval."""
import argparse
import bisect
import configparser
import ctypes as c
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import statistics
import subprocess
import sys
import time

RUNTIME = Path('/home/USER/wheelchair/models/d2-sdk-v0.2.0')
LOCK = Path('/run/user/1000/wheelchair-face-camera.lock')
DURATION = 110.0
PAUSES = ((15.0, .5), (45.0, 1.0))
PINNED = {
    'lib/libd2sdk.so': '2bc3a8130e4fac62871d914ffea327cdd5834e3568f7ab6a2bc69d76573008fc',
    'lib/libOpenNI2.so': 'e5cc7f0246a8251ac887ac56e667301210388b1fcd038d99fae22738dabb58b7',
    'lib/OpenNI.ini': '3896e8f831c6a56576e9e93a2e5b3e1d3fa72041e7d01e1d7f23b7cd907e7eff',
    'lib/OpenNI2/Drivers/libOniFile.so': '847beadad9fc2e3ab4dab81b18a7cfdfc420d83091fa5ce07be2e349bdf33334',
    'lib/OpenNI2/Drivers/liborbbec.so': '4df458c5cec9a5795d0998ee035eb4fde67641a4ebde7d9c7565e9359866704f',
    'lib/OpenNI2/Drivers/OniFile.ini': 'f50a20ca76350f8e5e81b50477714f9a1b1db9b49047f5089b90644526ba9505',
    'lib/OpenNI2/Drivers/orbbec.ini': 'b6a1cc4ed8ee62c7c4b2596e43727362ee489bd1733f59633794b005224d1e9b',
}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def write_json(path, value):
    with Path(path).open('x', encoding='utf8') as stream:
        json.dump(value, stream, ensure_ascii=False, allow_nan=False, indent=2)


def distribution(values):
    ordered = sorted(values)
    if not ordered:
        return {'n': 0}
    return {'n': len(ordered), 'min': ordered[0], 'p50': statistics.median(ordered),
            'p95': ordered[round((len(ordered)-1)*.95)],
            'p99': ordered[round((len(ordered)-1)*.99)], 'max': ordered[-1]}


def regression(rows):
    """SDK seconds per host second; excludes nothing, including flagged frames."""
    if len(rows) < 3:
        return {'n': len(rows)}
    x = [r['host_s'] for r in rows]
    y = [r['sdk_us']/1e6 for r in rows]
    mx, my = statistics.mean(x), statistics.mean(y)
    variance = sum((v-mx)**2 for v in x)
    if variance <= 0:
        return {'n': len(rows)}
    slope = sum((a-mx)*(b-my) for a, b in zip(x, y))/variance
    intercept = my-slope*mx
    residual = [b-(slope*a+intercept) for a, b in zip(x, y)]
    return {'n': len(rows), 'sdk_seconds_per_host_second': slope,
            'intercept_s': intercept,
            'residual_rms_ms': math.sqrt(statistics.mean(v*v for v in residual))*1000}


def summarize(rows, events):
    answer = {'timing_verified': 0, 'absolute_exposure_age_proven': 0,
              'hardware_wrap_observed': 0, 'streams': {}, 'consumer_pauses': events}
    for sensor in (1, 3):
        stream = [r for r in rows if r['sensor'] == sensor]
        baseline = [r for r in stream if 5 <= r['host_s'] < 14]
        fit = regression(baseline)
        timestamp_bad = sum(b['sdk_us'] <= a['sdk_us'] for a, b in zip(stream, stream[1:]))
        counter_bad = sum(b['index'] <= a['index'] for a, b in zip(stream, stream[1:]))
        gaps = sum(max(0, b['index']-a['index']-1) for a, b in zip(stream, stream[1:]))
        repeated = sum(a['hash'] == b['hash'] for a, b in zip(stream, stream[1:]))
        result = {'frames': len(stream), 'timestamp_nonincreasing': timestamp_bad,
                  'counter_nonincreasing': counter_bad, 'counter_gap_frames': gaps,
                  'adjacent_identical_hashes': repeated, 'baseline_fit': fit,
                  'read_call_ms': distribution([r['read_ns']/1e6 for r in stream]),
                  'sdk_to_python_delivery_ms': distribution([r['post_read_ns']/1e6 for r in stream]),
                  'flag_counts': {str(bit): sum(bool(r['flags'] & bit) for r in stream)
                                  for bit in (1, 2, 4, 8, 16, 32, 64, 128)},
                  'unknown_flag_frames': sum(bool(r['flags'] & ~255) for r in stream),
                  'phases': {}}
        if stream:
            result['sdk_span_s'] = (stream[-1]['sdk_us']-stream[0]['sdk_us'])/1e6
            result['host_span_s'] = stream[-1]['host_s']-stream[0]['host_s']
            result['covers_85_9s_sdk_span'] = int(result['sdk_span_s'] > 85.9)
        # Relative to the fastest baseline delivery, NOT an absolute capture age.
        slope = fit.get('sdk_seconds_per_host_second', 0)
        lag_ok = bool(baseline and .95 < slope < 1.05 and not timestamp_bad)
        result['relative_lag_fit_valid'] = int(lag_ok)
        if lag_ok:
            offset = min(r['host_s']-r['sdk_us']/1e6/slope for r in baseline)
            for row in stream:
                row['excess_lag_ms'] = (row['host_s']-row['sdk_us']/1e6/slope-offset)*1000
            result['relative_excess_lag_ms'] = distribution([r['excess_lag_ms'] for r in stream])
            result['relative_lag_above_250ms'] = sum(r['excess_lag_ms'] > 250 for r in stream)
        for phase in range(6):
            selected = [r for r in stream if r['phase'] == phase]
            result['phases'][str(phase)] = {'fit': regression(selected),
                'relative_excess_lag_ms': distribution([r['excess_lag_ms'] for r in selected]) if lag_ok else {'n': 0}}
        result['pause_windows'] = []
        for event in events:
            before = [r for r in stream if r['host_s'] < event['start_s']]
            after = [r for r in stream if event['end_s'] <= r['host_s'] < event['end_s']+3]
            window = {'pause_start_s': event['start_s'], 'pause_end_s': event['end_s'], 'frames': len(after)}
            if before and after:
                window.update({'first_sdk_advance_ms': (after[0]['sdk_us']-before[-1]['sdk_us'])/1000,
                               'first_host_advance_ms': (after[0]['host_s']-before[-1]['host_s'])*1000,
                               'first_index_advance': after[0]['index']-before[-1]['index']})
            if lag_ok:
                window['relative_excess_lag_ms'] = distribution([r['excess_lag_ms'] for r in after])
            result['pause_windows'].append(window)
        answer['streams'][str(sensor)] = result
    # Nearest numeric timestamp difference only: not unique accepted identity pairs.
    depth_times = sorted(r['sdk_us'] for r in rows if r['sensor'] == 3)
    differences = []
    for row in rows:
        if row['sensor'] != 1 or not depth_times:
            continue
        pos = bisect.bisect_left(depth_times, row['sdk_us'])
        candidates = depth_times[max(0, pos-1):pos+1]
        differences.append(row['sdk_us']-min(candidates, key=lambda t: abs(t-row['sdk_us'])))
    answer['nearest_ir_minus_depth_us_not_pairing_proof'] = distribution(differences)
    return answer


def phase_at(elapsed):
    return 0 if elapsed < 5 else 1 if elapsed < 15 else 2 if elapsed < 20 else 3 if elapsed < 45 else 4 if elapsed < 51 else 5


def frame_hash(frame):
    expected = (400, 640) if frame.sensor == 3 else (640, 400)
    require(frame.sensor in (1, 3) and frame.format == (100 if frame.sensor == 3 else 203), 'invalid sensor/format')
    require((frame.width, frame.height, frame.stride, frame.bytes, frame.reported_fps) == (640, 400, 1280, 512000, 30), 'invalid frame layout')
    require((frame.requested_width, frame.requested_height) == expected and frame.mirroring == 0, 'unexpected native mode/mirror')
    require(bool(frame.data), 'null frame data')
    content = c.string_at(frame.data, frame.bytes)
    if frame.sensor == 3:
        require(content[:16] == bytes(16), 'depth invalid-pixel mask missing')
    digest = hashlib.blake2s(content, digest_size=16).digest()
    return [int.from_bytes(digest[:8], 'big'), int.from_bytes(digest[8:], 'big')]


def child(out):
    import fcntl
    import resource
    import stat
    import d2_camera as helper
    require(sys.platform == 'linux' and os.geteuid() == 0, 'requires isolated root subprocess')
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_CPU, (125, 130))
    resource.setrlimit(resource.RLIMIT_AS, (2*1024**3, 2*1024**3))
    resource.setrlimit(resource.RLIMIT_FSIZE, (64*1024**2, 64*1024**2))
    def interrupted(signum, frame):
        raise RuntimeError('diagnostic interrupted')
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    require(LOCK.exists(), 'missing lock: sunrise must create the shared camera lock before this probe')
    fd = os.open(LOCK, os.O_RDWR | os.O_NOFOLLOW)  # Never O_CREAT, chmod or chown.
    sdk, device, rows, pauses, started, completed = None, c.c_void_p(), [], [], None, 0
    timeouts = 0
    telemetry = os.dup(1)
    def emit(value):
        os.write(telemetry, (json.dumps(value, allow_nan=False)+'\n').encode())
    try:
        lock_stat = os.fstat(fd)
        require(stat.S_ISREG(lock_stat.st_mode) and lock_stat.st_uid == 1000, 'lock must already be a sunrise-owned regular file')
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        current_lock = os.stat(LOCK, follow_symlinks=False)
        require((current_lock.st_dev, current_lock.st_ino) == (lock_stat.st_dev, lock_stat.st_ino), 'lock file changed')
        node, key = helper.usb_identity()
        require(os.access(node, os.R_OK | os.W_OK), 'USB permission unavailable')
        require(helper.SDK_FILES == PINNED, 'loader manifest differs from approved SDK')
        require(c.sizeof(helper.Frame) == 80 and helper.Frame.sdk_timestamp_us.offset == 56
                and helper.Frame.host_received_ns.offset == 64 and helper.Frame.flags.offset == 72, 'C ABI mismatch')
        # Pinned default constructor + pinned INI establish configured source, not observed exposure.
        for ini in ('lib/OpenNI.ini', 'lib/OpenNI2/Drivers/orbbec.ini'):
            config = configparser.ConfigParser(interpolation=None)
            config.read(RUNTIME/ini, encoding='utf8')
            for section in config.sections():
                require(not config.has_option(section, 'HostTimestamps') or config.getint(section, 'HostTimestamps') == 0,
                        'HostTimestamps enabled')
        manifest = {'expected_files': PINNED, 'helper_sha256': hashlib.sha256(Path(helper.__file__).read_bytes()).hexdigest(),
                    'device_key': key, 'host_timestamps_configured_default': 0,
                    'host_timestamps_runtime_getter_used': 0, 'duration_s': DURATION}
        write_json(out/'manifest.json', manifest)
        # Keep SDK diagnostics separate; stdout contains only our numeric JSON telemetry.
        native = os.open(out/'native.log', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.dup2(native, 1)
        os.dup2(native, 2)
        os.close(native)
        os.chdir(RUNTIME/'lib')
        sdk = helper.load_sdk(RUNTIME)
        def check(rc):
            require(rc == 0, 'SDK status '+str(rc))
        check(sdk.d2_open(c.byref(device)))
        check(sdk.d2_configure(device, 3, 100, 640, 400, 30))
        check(sdk.d2_configure(device, 1, 203, 640, 400, 30))
        check(sdk.d2_start(device))
        started = time.monotonic()
        next_progress, pause_index = 10.0, 0
        with (out/'frames.jsonl').open('x', encoding='utf8') as stream:
            while time.monotonic()-started < DURATION:
                elapsed = time.monotonic()-started
                if pause_index < len(PAUSES) and elapsed >= PAUSES[pause_index][0]:
                    before = time.monotonic()-started
                    emit({'event': 2, 'pause': pause_index, 'elapsed_s': before, 'requested_s': PAUSES[pause_index][1]})
                    time.sleep(PAUSES[pause_index][1])
                    pauses.append({'start_s': before, 'end_s': time.monotonic()-started,
                                   'requested_s': PAUSES[pause_index][1]})
                    pause_index += 1
                frame = helper.Frame()
                begin_ns = time.monotonic_ns()
                rc = sdk.d2_read(device, 1000, c.byref(frame))
                end_ns = time.monotonic_ns()
                if rc == 1:
                    timeouts += 1
                    stream.write(json.dumps({'event': 3, 'elapsed_s': time.monotonic()-started, 'rc': rc})+'\n')
                    stream.flush()
                    if time.monotonic()-started >= next_progress:
                        emit({'event': 4, 'elapsed_s': time.monotonic()-started, 'frames': len(rows), 'timeouts': timeouts})
                        next_progress += 10
                    continue
                check(rc)
                digest = frame_hash(frame)
                host_s = frame.host_received_ns/1e9-started
                require(abs(end_ns-frame.host_received_ns) < 5_000_000_000, 'host clock domains differ or severe delivery stall')
                row = {'event': 1, 'sensor': frame.sensor, 'host_s': host_s,
                       'host_received_ns': frame.host_received_ns, 'python_read_end_ns': end_ns,
                       'sdk_us': frame.sdk_timestamp_us, 'index': frame.frame_index,
                       'flags': frame.flags, 'read_ns': end_ns-begin_ns,
                       'post_read_ns': end_ns-frame.host_received_ns, 'phase': phase_at(host_s), 'hash': digest}
                rows.append(row)
                stream.write(json.dumps(row, separators=(',', ':'))+'\n')
                if time.monotonic()-started >= next_progress:
                    stream.flush()
                    emit({'event': 4, 'elapsed_s': time.monotonic()-started, 'frames': len(rows), 'sdk_us': frame.sdk_timestamp_us})
                    next_progress += 10
        completed = 1
    except Exception as exc:
        write_json(out/'error.json', {'error': str(exc), 'completed': 0})
        emit({'event': 9, 'completed': 0})
    finally:
        if sdk is not None and device:
            sdk.d2_close(device)
        result = summarize(rows, pauses)
        result['completed'] = completed
        result['timeouts'] = timeouts
        result['wall_s'] = time.monotonic()-started if started is not None else 0
        write_json(out/'summary.json', result)
        emit({'event': 5, 'completed': completed, 'frames': len(rows), 'wall_s': result['wall_s'], 'timing_verified': 0})
        os.close(telemetry)
        os.close(fd)
    return 0 if completed else 1


def run(out):
    require(sys.platform == 'linux' and os.geteuid() == 0, 'run through explicitly scoped sudo')
    out = out.resolve()
    out.mkdir(parents=False, exist_ok=False)
    # Bounded native child: a crash cannot leave its USB handles alive.
    process = subprocess.Popen([sys.executable, '-B', str(Path(__file__).resolve()), '--child', str(out)])
    timeout, interrupted = 0, 0
    def stop_child():
        process.terminate()
        try:
            return process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            return process.wait()
    def stop_requested(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop_requested)
    try:
        rc = process.wait(timeout=140)
    except subprocess.TimeoutExpired:
        timeout = 1
        rc = stop_child()
    except KeyboardInterrupt:
        interrupted = 1
        rc = stop_child()
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
    write_json(out/'supervisor.json', {'returncode': rc, 'timeout': timeout, 'interrupted': interrupted})
    return int(rc != 0 or timeout != 0 or interrupted != 0)


def self_test():
    rows = []
    for sensor in (1, 3):
        for i in range(200):
            host = 5+i/30
            rows.append({'sensor': sensor, 'host_s': host, 'sdk_us': round(host*1e6),
                         'index': i+1, 'hash': str(i), 'flags': 1, 'read_ns': 1000,
                         'post_read_ns': 100, 'phase': 1})
        for i in range(10):
            # Consumer wakes one second late; old SDK timestamps keep progressing.
            sdk_s = 5+(200+i)/30
            rows.append({'sensor': sensor, 'host_s': sdk_s+1, 'sdk_us': round(sdk_s*1e6),
                         'index': 201+i, 'hash': str(201+i), 'flags': 1, 'read_ns': 1000,
                         'post_read_ns': 100, 'phase': 2})
    # Baseline must exclude the synthetic pause, whose test starts before real t=15.
    for row in rows:
        if row['phase'] == 2:
            row['host_s'] += 10
            row['sdk_us'] += 10_000_000
    result = summarize(rows, [])
    assertions = 0
    for sensor in ('1', '3'):
        assert result['streams'][sensor]['relative_lag_above_250ms'] == 10
        assertions += 1
        assert abs(result['streams'][sensor]['baseline_fit']['sdk_seconds_per_host_second']-1) < 1e-6
        assertions += 1
    rows[-1]['sdk_us'] = 1
    bad = summarize(rows, [])
    assert bad['streams']['3']['timestamp_nonincreasing'] == 1
    assertions += 1
    assert bad['streams']['3']['relative_lag_fit_valid'] == 0
    assertions += 1
    assert bad['timing_verified'] == 0 and bad['absolute_exposure_age_proven'] == 0
    assertions += 1
    print(json.dumps({'self_test': 1, 'assertions': assertions, 'camera_access': 0, 'passed': 1}))
    return 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    choices = parser.add_mutually_exclusive_group(required=True)
    choices.add_argument('--self-test', action='store_true')
    choices.add_argument('--run', type=Path)
    choices.add_argument('--child', type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    try:
        status = self_test() if args.self_test else run(args.run) if args.run else child(args.child)
    except Exception as error:
        print(json.dumps({'event': 9, 'error': str(error), 'completed': 0}))
        status = 1
    raise SystemExit(status)
