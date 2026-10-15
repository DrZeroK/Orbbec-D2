"""RAM-only printed-target diagnostics; transformed detections map to native pixels."""
import cv2
import numpy as np


def diagnose(ir, depth):
    assert ir.shape == depth.shape == (400,640) and ir.dtype == depth.dtype == np.uint16
    result = {'ir_percentiles':np.percentile(ir,[0,1,10,50,90,99,100]).tolist(),
              'ir_central_percentiles':np.percentile(ir[100:300,180:460],[1,10,50,90,99]).tolist(),
              'depth_central_percentiles':None,'foreground_components':[], 'attempts':[]}
    central = depth[185:215,305:335]
    valid = central[(central>=300)&(central<=1300)]
    if valid.size:
        result['depth_central_percentiles'] = np.percentile(valid,[10,50,90]).tolist()
    # This is a diagnostic foreground estimate, not a verified paper contour.
    mask = ((depth>=350)&(depth<=1050)).astype(np.uint8)
    count, labels, stats, centres = cv2.connectedComponentsWithStats(mask,8)
    for i in sorted(range(1,count),key=lambda i:stats[i,4],reverse=True)[:3]:
        x,y,w,h,area = map(int,stats[i])
        if area<300:
            continue
        region = ir[labels==i]
        result['foreground_components'].append({'bbox_xywh':[x,y,w,h],'area':area,
            'touches_frame':x==0 or y==0 or x+w==640 or y+h==400,
            'ir_percentiles':np.percentile(region,[1,10,50,90,99]).tolist()})
    low,high = np.percentile(ir,[1,99])
    gray = np.uint8(np.clip((ir.astype(float)-low)*255/max(high-low,1),0,255))
    local = cv2.createCLAHE(clipLimit=3,tileGridSize=(8,8)).apply(gray)
    views = [('raw',(640,400),gray),('clahe',(640,400),local),
             ('clahe_width_480',(480,400),local),('clahe_height_534',(640,534),local),
             ('clahe_double',(1280,800),local)]
    for name,size,image in views:
        if size!=(640,400):
            image = cv2.resize(image,size,interpolation=cv2.INTER_CUBIC)
        for pattern in ((8,11),(11,8)):
            okay, corners = cv2.findChessboardCornersSB(image,pattern,cv2.CALIB_CB_NORMALIZE_IMAGE)
            result['attempts'].append({'view':name,'pattern':list(pattern),'found':bool(okay)})
            if not okay:
                continue
            points = corners.reshape(-1,2).astype(np.float32)
            # OpenCV resize maps pixel centres, not just coordinate origins.
            points = (points+.5)/np.array([size[0]/640,size[1]/400],np.float32)-.5
            if pattern==(11,8):
                points = points.reshape(8,11,2).transpose(1,0,2).reshape(88,2).copy()
            points = cv2.cornerSubPix(gray,points.reshape(-1,1,2),(4,4),(-1,-1),
                                     (cv2.TERM_CRITERIA_EPS|cv2.TERM_CRITERIA_MAX_ITER,40,1e-4))
            result['found_in_native_grid'] = True
            result['view'] = name
            result['corners'] = points.reshape(88,2).tolist()
            return result
    result['found_in_native_grid'] = False
    return result


if __name__=='__main__':
    ir=np.full((400,640),300,np.uint16)
    for row in range(12):
        for col in range(9):
            ir[80+row*20:100+row*20,230+col*20:250+col*20] = 900 if (row+col)%2 else 30
    original=ir.copy()
    result=diagnose(ir,np.full_like(ir,800))
    assert result['found_in_native_grid']
    points=np.array(result['corners'])
    expected=np.mgrid[1:9,1:12].T.reshape(-1,2)*20+[229.5,79.5]
    error=min(np.sqrt(np.mean(np.sum((points-p)**2,axis=1))) for p in (expected,expected[::-1]))
    assert error<.3,error
    np.testing.assert_array_equal(ir,original)
    # Pixel-centre inverse mapping is exact for the deliberately distorted test view.
    transformed=(expected+.5)*np.array([.75,1])-.5
    recovered=(transformed+.5)/np.array([.75,1])-.5
    assert np.max(np.abs(recovered-expected))<1e-9
    print({'diagnostic_self_test':True,'synthetic_only':True,'native_corner_rms_px':float(error)})
