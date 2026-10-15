"""Bounded same-frame corner detector comparison, numeric output only."""
import json
from pathlib import Path
import sys
import cv2
import numpy as np
WORK = Path('/home/USER/wheelchair/tests/d2-calibration-live-20261015-1920')
sys.path.insert(0,str(WORK))
import capture_checker as capture
from ir_calibration import object_points,observation_from_points
from verify_factory import candidates,evaluate


def normalize(image):
    lo,hi = np.percentile(image,[1,99])
    assert hi-lo >= 8
    return np.uint8(np.clip((image.astype(float)-lo)*255/(hi-lo),0,255))


def variants(ir):
    gray = normalize(ir)
    native = cv2.GaussianBlur(cv2.medianBlur(ir,5),(5,5),1.5)
    return {
        'clip_then_denoise':cv2.GaussianBlur(cv2.medianBlur(gray,5),(5,5),1.5),
        'native_denoise_then_clip':normalize(native),
        'native_median_only':normalize(cv2.medianBlur(ir,5)),
        'sqrt_native_denoise':np.uint8(np.sqrt(np.clip(native.astype(float)/1023,0,1))*255),
    }


def compare(ir,depth,factory):
    rows = []
    for name,image in variants(ir).items():
        for algorithm in (('classic','sb') if name == 'native_median_only' else ('classic',)):
            if algorithm == 'classic':
                found,corners = cv2.findChessboardCorners(image,(8,11),
                    cv2.CALIB_CB_ADAPTIVE_THRESH|cv2.CALIB_CB_NORMALIZE_IMAGE)
                if found:
                    corners = cv2.cornerSubPix(image,corners,(4,4),(-1,-1),
                        (cv2.TERM_CRITERIA_EPS|cv2.TERM_CRITERIA_MAX_ITER,50,1e-4))
            else:
                found,corners = cv2.findChessboardCornersSB(image,(8,11),
                    cv2.CALIB_CB_NORMALIZE_IMAGE|cv2.CALIB_CB_EXHAUSTIVE|cv2.CALIB_CB_ACCURACY)
            row = {'filter':name,'algorithm':algorithm,'found':bool(found)}
            if found:
                points = corners.reshape(88,2).astype(float)
                observation = observation_from_points(points,depth)
                xy = object_points()[:,:2].astype(float)
                H,_ = cv2.findHomography(xy,points,0)
                residual = cv2.perspectiveTransform(xy.reshape(-1,1,2),H).reshape(88,2)-points
                row['planar_rms_px'] = float(np.sqrt(np.mean(np.sum(residual**2,axis=1))))
                row['fixed_factory_checks'] = {label:evaluate(observation,K,dist)
                                              for label,K,dist in candidates(factory)}
            rows.append(row)
    return rows


if __name__ == '__main__':
    if sys.argv[1:] == ['--self-test']:
        image = np.full((400,640),300,np.uint16)
        for row in range(12):
            for col in range(9):
                image[80+row*20:100+row*20,230+col*20:250+col*20] = 900 if (row+col)%2 else 30
        original = image.copy()
        params = {'l_intr_p':[477.,477.,196.,322.],'l_k':[0.]*5}
        results = compare(image,np.full((400,640),650,np.uint16),params)
        print(json.dumps({'self_test_paths':[{k:v for k,v in r.items() if k != 'fixed_factory_checks'} for r in results]}))
        assert all(r['found'] for r in results)
        assert max(r['planar_rms_px'] for r in results) < .2
        np.testing.assert_array_equal(image,original)
        print(json.dumps({'self_test':True,'detector_paths':len(results),'camera_access':False}))
    else:
        params = json.loads((Path(__file__).parent/'factory-current.json').read_text())['camera_params']
        original = capture.detect_observation
        results = []
        def with_comparison(ir,depth):
            observation = original(ir,depth)
            if not results:
                results.extend(compare(ir,depth,params))
            return observation
        capture.detect_observation = with_comparison
        capture.capture(WORK,'factory_algorithm_compare','check',600)
        result = {'label':'factory_algorithm_compare','results':results,'verified':False,
                  'images_saved':False,'K_refitted':False}
        with (Path(__file__).parent/'detector-comparison.json').open('x') as stream:
            json.dump(result,stream,allow_nan=False)
        print(json.dumps({'event':'algorithm_compare_complete','paths':len(results),'images_saved':False}),flush=True)
