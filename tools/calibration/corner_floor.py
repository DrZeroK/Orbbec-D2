"""Numeric-only planar residual diagnostic; a homography cannot certify intrinsics."""
import json
from pathlib import Path
import sys
import cv2
import numpy as np
sys.path.insert(0,str(Path.home()/'wheelchair/tests/d2-calibration-live-20261015-1920'))
from ir_calibration import object_points


def planar_error(points):
    xy = object_points()[:,:2].astype(np.float64)
    H,_ = cv2.findHomography(xy,points,0)
    assert H is not None and np.isfinite(H).all()
    predicted = cv2.perspectiveTransform(xy.reshape(-1,1,2),H).reshape(-1,2)
    vectors = points-predicted
    errors = np.linalg.norm(vectors,axis=1)
    return {'rms_px':float(np.sqrt(np.mean(errors**2))),
            'p95_px':float(np.percentile(errors,95))},vectors


results = []
for label in ('factory_centre_800_fixed','factory_centre_near_fixed'):
    path = Path.home()/'wheelchair/tests/d2-calibration-live-20261015-1920'/(label+'.json')
    capture = json.loads(path.read_text())
    frames = [np.array(o['corners'],float) for o in capture['diagnostic_observations']]
    for i in range(1,len(frames)):
        if np.linalg.norm(frames[i]-frames[0]) > np.linalg.norm(frames[i][::-1]-frames[0]):
            frames[i] = frames[i][::-1]
    per_frame = [planar_error(f) for f in frames]
    mean = np.mean(frames,axis=0)
    mean_error,_ = planar_error(mean)
    deviations = np.array(frames)-mean
    correlations = [float(np.corrcoef(per_frame[0][1].ravel(),r[1].ravel())[0,1])
                    for r in per_frame[1:]]
    results.append({'label':label,'frame_planar_errors':[r[0] for r in per_frame],
        'mean_corner_planar_error_diagnostic_only':mean_error,
        'temporal_corner_rms_px':float(np.sqrt(np.mean(np.sum(deviations**2,axis=2)))),
        'residual_vector_correlation_to_first':correlations})
print(json.dumps({'results':results,'K_fitted':False,'camera_access':False,'verified':False,
    'limit':'Planar residual includes distortion, board nonplanarity, printing and detector error; it does not isolate any one cause.'},allow_nan=False))
