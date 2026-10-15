"""Measured board outline versus independently observed valid depth steps."""
import cv2
import numpy as np

SQUARE = 19.2
WIDTH,HEIGHT,LEFT,TOP = 226.,324.,27.,42.


def outline(ir,corners):
    points = np.asarray(corners,float).reshape(88,2)
    xy = np.mgrid[1:9,1:12].T.reshape(-1,2).astype(float)*SQUARE
    H,_ = cv2.findHomography(xy,points,0)
    assert H is not None
    centres = (np.mgrid[0:9,0:12].T.reshape(-1,2)+.5)*SQUARE
    pixels = cv2.perspectiveTransform(centres.reshape(-1,1,2),H).reshape(12,9,2)
    cleaned = cv2.medianBlur(ir,5)
    levels = np.zeros((12,9))
    for row in range(12):
        for col in range(9):
            x,y = np.rint(pixels[row,col]).astype(int)
            assert 2 <= x < 638 and 2 <= y < 398, 'Outer pattern cropped'
            levels[row,col] = np.median(cleaned[y-1:y+2,x-1:x+2])
    white = np.indices((12,9)).sum(axis=0)%2 == 0
    contrast = []
    for row in range(12):
        for col in range(9):
            for dr,dc in ((0,1),(1,0)):
                if row+dr < 12 and col+dc < 9:
                    delta = levels[row,col]-levels[row+dr,col+dc]
                    contrast.append(delta if white[row,col] else -delta)
    contrast = np.array(contrast)
    median = float(np.median(contrast))
    assert abs(median) >= 8, 'Cannot identify printed checker orientation in IR'
    agreement = float(np.mean(contrast*np.sign(median) > 0))
    assert agreement >= .8, 'Checker orientation ambiguous'
    # PDF rows were drawn bottom-up: physical top-left square is white.
    if median < 0:
        points = points[::-1]
        H,_ = cv2.findHomography(xy,points,0)
    board = np.array([[-LEFT,-TOP],[WIDTH-LEFT,-TOP],
                      [WIDTH-LEFT,HEIGHT-TOP],[-LEFT,HEIGHT-TOP]],float)
    polygon = cv2.perspectiveTransform(board.reshape(-1,1,2),H).reshape(4,2)
    assert ((polygon >= [8,8]) & (polygon <= [631,391])).all(), 'Backing board cropped'
    return polygon,{'orientation_reversed':bool(median < 0),
                    'orientation_contrast':abs(median),'orientation_agreement':agreement}


def depth_edges(depth,target):
    z = depth.astype(float)
    valid = (z >= 300)&(z <= 1300)
    points = []
    for axis in (0,1):
        if axis == 0:
            a,b = z[:-1],z[1:]
            allowed = valid[:-1]&valid[1:]
        else:
            a,b = z[:,:-1],z[:,1:]
            allowed = valid[:,:-1]&valid[:,1:]
        allowed &= (np.minimum(a,b) >= target-80)&(np.minimum(a,b) <= target+80)
        allowed &= np.maximum(a,b)-np.minimum(a,b) >= 150
        y,x = np.nonzero(allowed)
        points.append(np.c_[x+(.5 if axis == 1 else 0),y+(.5 if axis == 0 else 0)])
    return np.concatenate(points)


def evaluate(ir,depth,observation):
    assert ir.shape == depth.shape == (400,640) and ir.dtype == depth.dtype == np.uint16
    polygon,orientation = outline(ir,observation['corners'])
    values = [z for z in observation['depth_mm'] if z is not None]
    assert len(values) >= 80
    target = float(np.median(values))
    edges = depth_edges(depth,target)
    sides = []
    for i in range(4):
        a,b = polygon[i],polygon[(i+1)%4]
        errors = []
        for t in np.linspace(.1,.9,25):
            p = a+t*(b-a)
            error = float(np.min(np.linalg.norm(edges-p,axis=1))) if len(edges) else float('inf')
            if error <= 12:
                errors.append(error)
        coverage = len(errors)/25
        sides.append({'side':i,'observed_fraction':coverage,
                      'median_error_px':float(np.median(errors)) if errors else None,
                      'p95_error_px':float(np.percentile(errors,95)) if errors else None,
                      'passed':bool(coverage >= .8 and np.median(errors) <= 2
                                    and np.percentile(errors,95) <= 4) if errors else False})
    return {'polygon_xy':polygon.tolist(),'orientation':orientation,'target_depth_mm':target,
            'valid_depth_step_points':len(edges),'sides':sides,
            'frame_boundary_passed':all(s['passed'] for s in sides),
            'verified':False,'images_saved':False,
            'note':'Zero depth is unknown, never background; requires valid foreground/background >=150mm step.'}


def self_test():
    # Object coordinates here use the grid's physical top-left outer edge.
    xy = np.mgrid[1:9,1:12].T.reshape(-1,2).astype(float)*SQUARE
    pixel = lambda p: p*477/700+[250.,110.]
    corners = pixel(xy)
    ir = np.full((400,640),80,np.uint16)
    polygon = pixel(np.array([[-LEFT,-TOP],[WIDTH-LEFT,-TOP],
                             [WIDTH-LEFT,HEIGHT-TOP],[-LEFT,HEIGHT-TOP]]))
    depth = np.full((400,640),1100,np.uint16)
    mask = np.zeros((400,640),np.uint8)
    cv2.fillConvexPoly(mask,np.rint(polygon).astype(np.int32),1)
    depth[mask.astype(bool)] = 700
    for row in range(12):
        for col in range(9):
            box = pixel(np.array([[col,row],[col+1,row],[col+1,row+1],[col,row+1]])*SQUARE)
            cv2.fillConvexPoly(ir,np.rint(box).astype(np.int32),800 if (row+col)%2 == 0 else 30)
    observation = {'corners':corners.tolist(),'depth_mm':[700.]*88}
    normal = evaluate(ir,depth,observation)
    assert normal['frame_boundary_passed'],normal
    reversed_result = evaluate(ir,depth,dict(observation,corners=corners[::-1].tolist()))
    assert reversed_result['frame_boundary_passed']
    np.testing.assert_allclose(normal['polygon_xy'],reversed_result['polygon_xy'],atol=1e-4)
    assert reversed_result['orientation']['orientation_reversed']
    shifted = np.roll(depth,8,axis=1)
    assert not evaluate(ir,shifted,observation)['frame_boundary_passed']
    missing = depth.copy();missing[missing == 1100] = 0
    assert not evaluate(ir,missing,observation)['frame_boundary_passed']
    try:
        outline(np.full_like(ir,80),corners)
    except AssertionError:
        pass
    else:
        raise AssertionError('Ambiguous orientation accepted')
    print({'self_test':True,'assertions':6,'camera_access':False})


if __name__ == '__main__':
    self_test()
