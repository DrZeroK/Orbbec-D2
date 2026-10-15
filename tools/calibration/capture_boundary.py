"""Use the existing bounded capture and retain only measured boundary statistics."""
import hashlib
import json
from pathlib import Path
import sys
WORK = Path('/home/USER/wheelchair/tests/d2-calibration-live-20261015-1920')
sys.path.insert(0,str(WORK))
import capture_checker as capture
import board_boundary


if __name__ == '__main__':
    if sys.argv[1:] == ['--self-test']:
        board_boundary.self_test()
    else:
        assert len(sys.argv) == 3
        label,distance = sys.argv[1],int(sys.argv[2])
        frames = []
        detector = capture.detect_observation
        def inspect(ir,depth):
            observation = detector(ir,depth)
            try:
                result = board_boundary.evaluate(ir,depth,observation)
            except AssertionError as error:
                result = {'frame_boundary_passed':False,'reason':str(error)}
            frames.append(result)
            return observation
        capture.detect_observation = inspect
        capture.capture(WORK,label,'check',distance)
        source = WORK/(label+'.json')
        sample = json.loads(source.read_text())
        passed = sample['stable'] and len(frames) == 3 and all(f['frame_boundary_passed'] for f in frames)
        result = {'label':label,'capture_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
            'board_mm':[226,324],'checker_margin_left_top_mm':[27,42],
            'frames':frames,'static_pose_boundary_passed':passed,
            'global_alignment_verified':False,'timing_verified':False,'verified':False,'images_saved':False}
        with (Path(__file__).parent/(label+'-boundary.json')).open('x') as stream:
            json.dump(result,stream,allow_nan=False,indent=2)
