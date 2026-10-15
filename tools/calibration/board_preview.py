"""Render a board-only crop in RAM; caller must obtain permission before emitting it."""
import cv2
import numpy as np


def render(ir, depth, distance_mm):
    assert ir.shape == depth.shape == (400,640) and ir.dtype == depth.dtype == np.uint16
    mask = (np.abs(depth.astype(float)-distance_mm)<120).astype(np.uint8)
    count,labels,stats,centres = cv2.connectedComponentsWithStats(mask,8)
    candidates = [i for i in range(1,count) if 3000<=stats[i,4]<=160000
                  and stats[i,0]>0 and stats[i,1]>0
                  and stats[i,0]+stats[i,2]<640 and stats[i,1]+stats[i,3]<400]
    if not candidates:
        raise ValueError('No bounded board foreground at the expected distance; preview withheld')
    index = min(candidates,key=lambda i:np.linalg.norm(centres[i]-[320,200]))
    x,y,w,h,_ = map(int,stats[index])
    # Exclude the board perimeter and hands; never emit the surrounding full frame.
    dx,dy = round(w*.15),round(h*.15)
    x,y,w,h = x+dx,y+dy,w-2*dx,h-2*dy
    crop = ir[y:y+h,x:x+w]
    low,high = np.percentile(crop,[1,99])
    linear = np.uint8(np.clip((crop.astype(float)-low)*255/max(high-low,1),0,255))
    gamma = np.uint8(np.sqrt(np.clip(crop.astype(float)/1023,0,1))*255)
    contrast = cv2.createCLAHE(clipLimit=2,tileGridSize=(8,8)).apply(gamma)
    height = 220
    width = round(w*height/h)
    width = min(width,300)
    panels=[]
    for label,view in [('LINEAR',linear),('GAMMA + CLAHE',contrast)]:
        view=cv2.cvtColor(cv2.resize(view,(width,height)),cv2.COLOR_GRAY2BGR)
        view=cv2.copyMakeBorder(view,24,0,0,0,cv2.BORDER_CONSTANT,value=(0,0,0))
        cv2.putText(view,label,(5,17),cv2.FONT_HERSHEY_SIMPLEX,.45,(255,255,255),1)
        panels.append(view)
    okay,jpeg=cv2.imencode('.jpg',np.hstack(panels),[cv2.IMWRITE_JPEG_QUALITY,75])
    assert okay
    return jpeg.tobytes(),{'crop_xywh':[x,y,w,h],'ir_crop_percentiles':np.percentile(crop,[0,1,10,50,90,99,100]).tolist(),
                           'display':'linear and gamma/CLAHE; same IR crop','local_image_file_written':False}


if __name__=='__main__':
    depth=np.full((400,640),1200,np.uint16); depth[70:330,220:420]=800
    ir=np.full((400,640),100,np.uint16); ir[70:330,220:420]=600
    raw=ir.copy()
    jpeg,meta=render(ir,depth,800)
    assert jpeg.startswith(b'\xff\xd8') and len(jpeg)<20000
    x,y,w,h=meta['crop_xywh']
    assert x>220 and y>70 and x+w<420 and y+h<330
    np.testing.assert_array_equal(ir,raw)
    try: render(ir,np.zeros_like(depth),800)
    except ValueError: pass
    else: raise AssertionError('Missing target must not expose background')
    print({'preview_renderer_self_test':True,'synthetic_only':True,'crop_xywh':meta['crop_xywh']})
