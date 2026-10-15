"""Bounded, numeric-only checker capture; never reads face/PIN records."""
import ctypes as c
from collections import Counter
import fcntl
import json
import os
from pathlib import Path
import re
import resource
import stat
import sys
import time

import cv2
import numpy as np
import d2_camera as d2
from timing_probe import frame_hash
from ir_calibration import detect_observation, assess_novelty, SPEC, object_points

RUNTIME = Path('/home/USER/wheelchair/models/d2-sdk-v0.2.0')
LOCK = Path('/run/user/1000/wheelchair-face-camera.lock')


def choose_pair(latest, now):
    if set(latest) != {1, 3}:
        return None
    ir, depth = latest[1], latest[3]
    if (abs(ir[1]-depth[1]) > 18_000 or abs(ir[3]-depth[3]) > .08
            or not 0 <= now-min(ir[3], depth[3]) <= .25):
        return None
    return depth, ir


def save(path, value):
    with path.open('x', encoding='utf8') as stream:
        json.dump(value, stream, ensure_ascii=False, allow_nan=False, indent=2)


def capture(work, label, group, nominal_mm):
    assert os.geteuid() == 0, 'Isolated diagnostic needs raw USB access'
    root = Path('/home/USER/wheelchair/tests').resolve(strict=True)
    work = work.resolve(strict=True)
    assert work.parent == root and work.name.startswith('d2-calibration-live-')
    assert re.fullmatch('[a-z0-9_-]{1,40}', label) and group in ('check', 'train', 'holdout')
    assert 350 <= nominal_mm <= 1000
    destination = work/(label+'.json')
    assert not destination.exists(), 'Result label already exists'
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_AS, (2*1024**3, 2*1024**3))
    resource.setrlimit(resource.RLIMIT_FSIZE, (32*1024**2, 32*1024**2))
    cv2.setNumThreads(2)
    telemetry = os.dup(1)
    def emit(value):
        os.write(telemetry, (json.dumps(value, ensure_ascii=False)+'\n').encode())
    lease = os.open(LOCK, os.O_RDWR | os.O_NOFOLLOW)
    sdk, device, pairs = None, d2.P(), []
    counts, flag_counts, latest, previous = Counter(), Counter(), {}, {}
    started = None
    try:
        info = os.fstat(lease)
        assert stat.S_ISREG(info.st_mode) and info.st_uid == 1000 and stat.S_IMODE(info.st_mode) == 0o600
        fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        node, key = d2.usb_identity()
        assert os.access(node, os.R_OK | os.W_OK)
        native = os.open(work/(label+'-native.log'), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.dup2(native, 1); os.dup2(native, 2); os.close(native)
        os.chdir(RUNTIME/'lib')
        sdk = d2.load_sdk(RUNTIME)
        def check(rc):
            if rc != 0:
                raise RuntimeError('D2 SDK status '+str(rc))
        check(sdk.d2_open(c.byref(device)))
        check(sdk.d2_configure(device, 3, 100, 640, 400, 30))
        check(sdk.d2_configure(device, 1, 203, 640, 400, 30))
        check(sdk.d2_start(device))
        started = time.monotonic()
        next_sample = .6
        while time.monotonic()-started < 3.2:
            frame = d2.Frame()
            rc = sdk.d2_read(device, 1000, c.byref(frame))
            if rc == 1:
                counts['timeouts'] += 1
                continue
            check(rc)
            frame_hash(frame)  # Native dimensions, request, format, buffer and depth mask.
            sensor = int(frame.sensor)
            stamp, index = int(frame.sdk_timestamp_us), int(frame.frame_index)
            if stamp == 0 or index == 0:
                assert sensor not in previous, 'Frame clock/counter reset after startup'
                counts['startup_zero_metadata'] += 1
                emit({'event':'startup_frame_skipped','sensor':sensor,'sdk_us':stamp,'index':index})
                latest.clear()
                continue
            assert index > 0, 'Invalid frame counter'
            before = previous.get(sensor)
            assert before is None or (stamp > before[0] and index > before[1]), 'Frame clock/counter regression'
            previous[sensor] = stamp, index
            counts[str(sensor)] += 1
            flag_counts[str(sensor)+':'+str(frame.flags)] += 1
            if frame.flags != (97 if sensor == 3 else 1):
                latest.clear()
                continue
            arrival = frame.host_received_ns/1e9
            assert 0 <= time.monotonic()-arrival <= .25, 'Stale host delivery'
            pixels = np.frombuffer(c.string_at(frame.data, frame.bytes), dtype='<u2').reshape(400, 640).copy()
            latest[sensor] = pixels, stamp, index, arrival
            now = time.monotonic()
            pair = choose_pair(latest, now)
            if pair is not None and now-started >= next_sample:
                pairs.append(pair)
                latest.clear()
                next_sample += .8
                if len(pairs) >= 3:
                    break
    finally:
        if sdk is not None and device:
            sdk.d2_close(device)
        os.close(lease)
    capture_seconds = time.monotonic()-started
    analysis_started = time.monotonic()
    emit({'event':'capture_complete', 'paired_snapshots':len(pairs), 'images_saved':False,
          'message':'Board can be relaxed; analysis uses RAM snapshots only.'})
    observations, failures = [], []
    preview_requested = os.environ.get('D2_SHOW_BOARD_PREVIEW') == '1'
    for depth, ir in ([] if preview_requested else pairs):
        try:
            value = detect_observation(ir[0], depth[0])
            value['timing'] = {'depth_us':depth[1], 'ir_us':ir[1],
                               'depth_index':depth[2], 'ir_index':ir[2],
                               'host_delivery_skew_ms':(ir[3]-depth[3])*1000}
            observations.append(value)
        except ValueError as error:
            failures.append(str(error))
    corners = [np.asarray(o['corners']) for o in observations]
    differences = []
    if corners:
        for points in corners[1:]:
            differences.append(min(float(np.sqrt(np.mean(np.sum((points-p)**2, axis=1))))
                                   for p in (corners[0], corners[0][::-1])))
    stable = len(observations) == 3 and max(differences, default=0) <= 1.0
    selected = observations[1] if stable else None
    result = {'label':label,'group':group,'nominal_distance_mm':nominal_mm,'measured_distance_mm':None,
              'pattern':SPEC,'device_key':key,'sdk_files':d2.SDK_FILES,
              'capture_s':capture_seconds,'analysis_s':time.monotonic()-analysis_started,'frame_counts':dict(counts),
              'flag_counts':dict(flag_counts),'paired_snapshots':len(pairs),
              'detections':len(observations),'corner_jitter_rms_px':differences,
              'stable':stable,'failures':failures,'observation':selected,
              'diagnostic_observations':observations,
              'images_saved':False,'verified':False,'timing_verified':False}
    if selected:
        values = [z for z in selected['depth_mm'] if z is not None]
        result['corner_depth_coverage'] = len(values)/88
        result['corner_depth_median_mm'] = float(np.median(values)) if values else None
        result['corner_bbox_xyxy'] = np.r_[np.min(corners[1],axis=0),np.max(corners[1],axis=0)].tolist()
    if not observations and pairs and not preview_requested:
        from checker_diagnostics import diagnose
        diagnostics = diagnose(pairs[len(pairs)//2][1][0],pairs[len(pairs)//2][0][0])
        result['diagnostics'] = diagnostics
    if preview_requested:
        import base64
        from board_preview import render
        middle = pairs[len(pairs)//2]
        jpeg,meta = render(middle[1][0],middle[0][0],nominal_mm)
        result['preview'] = meta
        emit({'event':'board_preview','jpeg_base64':base64.b64encode(jpeg).decode('ascii'),'metadata':meta})
    save(destination, result)
    emit({k:v for k,v in result.items() if k not in ('observation','diagnostic_observations','device_key','sdk_files')})
    os.close(telemetry)


def self_test():
    pixels = np.zeros((400,640),np.uint16)
    one = (pixels,1_000_000,1,10.0)
    two = (pixels,1_009_000,1,10.01)
    assert choose_pair({3:one,1:two},10.02) is not None
    assert choose_pair({3:one},10.02) is None
    assert choose_pair({3:one,1:two},11.0) is None
    assert choose_pair({3:one,1:(pixels,1_030_000,1,10.01)},10.02) is None
    points = object_points()
    assert np.isclose(SPEC['square_mm'],19.2)
    assert np.allclose(np.linalg.norm(np.diff(points[:8],axis=0),axis=1),19.2)
    assert assess_novelty({'corners':np.full((88,2),100).tolist()},[])['accepted']
    print(json.dumps({'self_test':True,'assertions':7,'camera_access':False}))


if __name__ == '__main__':
    if sys.argv[1:] == ['--self-test']:
        self_test()
    else:
        assert len(sys.argv) == 5
        capture(Path(sys.argv[1]),sys.argv[2],sys.argv[3],float(sys.argv[4]))
