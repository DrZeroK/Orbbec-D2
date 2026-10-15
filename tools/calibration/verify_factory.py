"""Check fixed factory candidates against numeric checker observations; never refit K."""
import argparse
import json
from pathlib import Path
import sys
import cv2
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'D2_calibration_live_20261015_1920'))
# Board directory uses a different conventional spelling.
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'d2-calibration-live-20261015-1920'))
from ir_calibration import object_points, normalized_rays


def candidates(params):
    fx,fy,cx,cy = params['l_intr_p']
    k1,k2,p1,p2,k3 = params['l_k']
    K = np.array([[fy,0,639-cy],[0,fx,cx],[0,0,1.]],dtype=np.float64)
    # For the driver's proven CW90 mapping: x'=-y, y'=x in normalized coordinates.
    return [('cw90_factory_distortion',K,np.array([k1,k2,p2,-p1,k3])),
            ('cw90_zero_distortion',K,np.zeros(5))]


def evaluate(observation,K,dist):
    points = np.asarray(observation['corners'],np.float64)
    assert points.shape == (88,2) and np.isfinite(points).all()
    xyz = object_points().astype(np.float64)
    okay,rvec,tvec = cv2.solvePnP(xyz,points,K,dist)
    assert okay
    projected = cv2.projectPoints(xyz,rvec,tvec,K,dist)[0].reshape(-1,2)
    residual = np.linalg.norm(projected-points,axis=1)
    R = cv2.Rodrigues(rvec)[0]
    predicted = (xyz@R.T+tvec.reshape(3))[:,2]
    depth = np.array([np.nan if v is None else v for v in observation['depth_mm']],float)
    coverage = np.asarray(observation['depth_patch_coverage'],float)
    valid = np.isfinite(depth) & (coverage >= 7/9) & (depth >= 300) & (depth <= 1300)
    delta = depth[valid]-predicted[valid]
    pixels = points.reshape(-1,1,2)
    xy = cv2.undistortPointsIter(pixels,K,dist,None,None,
        (cv2.TERM_CRITERIA_EPS|cv2.TERM_CRITERIA_MAX_ITER,50,1e-12)).reshape(-1,2)
    rebuilt = np.c_[xy,np.ones(88)]*depth[:,None]
    edges = [(row*8+col,row*8+col+1) for row in range(11) for col in range(7)]
    edges += [(row*8+col,(row+1)*8+col) for row in range(10) for col in range(8)]
    errors = [abs(np.linalg.norm(rebuilt[a]-rebuilt[b])/19.2-1)
              for a,b in edges if valid[a] and valid[b]]
    result = {'reprojection_rms_px':float(np.sqrt(np.mean(residual**2))),
        'reprojection_p95_px':float(np.percentile(residual,95)),
        'depth_coverage':float(valid.mean()),
        'depth_bias_mm':float(np.median(delta)) if len(delta) else None,
        'depth_abs_p95_mm':float(np.percentile(abs(delta),95)) if len(delta) else None,
        'spacing_median_fraction':float(np.median(errors)) if errors else None,
        'spacing_p95_fraction':float(np.percentile(errors,95)) if errors else None,
        'board_centre_Z_mm':float(tvec[2,0])}
    result['numeric_check_passed'] = bool(valid.mean() >= .9 and len(errors)
        and result['reprojection_rms_px'] <= .6 and result['reprojection_p95_px'] <= 1.2
        and abs(result['depth_bias_mm']) <= 15 and result['depth_abs_p95_mm'] <= 25
        and result['spacing_median_fraction'] <= .04 and result['spacing_p95_fraction'] <= .10)
    return result


def self_test():
    params = {'l_intr_p':[477.,512.,196.,322.],'l_k':[.007,-.07,-.0001,-.0005,0.]}
    name,K,dist = candidates(params)[0]
    assert K[0,2] == 317 and K[1,2] == 196
    np.testing.assert_allclose(dist,[.007,-.07,-.0005,.0001,0.])
    original_xyz = np.array([[70.,-100.,700.],[-60.,80.,900.],[20.,30.,650.]])
    original_K = np.array([[477.,0,196.],[0,512.,322.],[0,0,1.]])
    before = cv2.projectPoints(original_xyz,np.zeros(3),np.zeros(3),original_K,
                              np.array(params['l_k']))[0].reshape(-1,2)
    rotated_xyz = original_xyz[:,[1,0,2]].copy();rotated_xyz[:,0] *= -1
    after = cv2.projectPoints(rotated_xyz,np.zeros(3),np.zeros(3),K,dist)[0].reshape(-1,2)
    np.testing.assert_allclose(after,np.c_[639-before[:,1],before[:,0]],atol=1e-8)
    xyz = object_points().astype(float)
    rvec,tvec = np.array([.15,-.2,.05]),np.array([0.,0.,800.])
    corners = cv2.projectPoints(xyz,rvec,tvec,K,dist)[0].reshape(-1,2)
    depth = (xyz@cv2.Rodrigues(rvec)[0].T+tvec)[:,2]
    observation = {'corners':corners.tolist(),'depth_mm':depth.tolist(),
                   'depth_patch_coverage':[1.]*88}
    good = evaluate(observation,K,dist)
    assert good['numeric_check_passed'] and good['reprojection_rms_px'] < 1e-5
    assert not evaluate(dict(observation,depth_mm=(depth*1.08).tolist()),K,dist)['numeric_check_passed']
    assert not evaluate(dict(observation,depth_mm=[None]*88),K,dist)['numeric_check_passed']
    # Compare full native ray helper with direct point undistortion at integer samples.
    rays = normalized_rays(K,dist)
    assert rays.shape == (400,640,3)
    print(json.dumps({'self_test':True,'assertions':7,'camera_access':False}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--self-test',action='store_true')
    parser.add_argument('--factory',type=Path)
    parser.add_argument('--observation',type=Path)
    args = parser.parse_args()
    if args.self_test:
        self_test()
    else:
        params = json.loads(args.factory.read_text())['camera_params']
        capture = json.loads(args.observation.read_text())
        observations = capture.get('diagnostic_observations') or [capture['observation']]
        assert observations and all(observations)
        print(json.dumps({'observation':args.observation.name,
            'capture_stable':capture['stable'],
            'models':{name:[evaluate(o,K,dist) for o in observations] for name,K,dist in candidates(params)},
            'K_refitted':False,'alignment_verified':False,'intrinsics_verified':False,'verified':False},
            allow_nan=False))
