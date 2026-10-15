"""Experimental D2 geometric presentation screening; not a liveness guarantee.

Caller binds factory geometry, device identity, fresh host delivery timestamps,
one face and consecutive identity matches. Factory registration/exposure remain experimental.
Inputs use the unrotated IR grid and
its matching intrinsics. IR is native D2 10-bit (0..1023) in a 16-bit container.
Thresholds below are deliberately strict and await real-person/attack testing.
"""
import numpy as np


def evaluate_face(depth_mm, ir_gray16, face15, intrinsics, distortion=None):
    """Return {accepted, reason (Chinese), metrics (finite numeric values)}.

    face15 is YuNet's [x,y,w,h, eye1xy,eye2xy,nosexy,mouth1xy,mouth2xy,score]
    in the SAME IR pixel grid. Never resize depth or fill missing depth here.
    """
    metrics = {}

    def reject(reason):
        safe = {name: float(value) for name, value in metrics.items() if np.isfinite(value)}
        return {"accepted": False, "reason": reason, "metrics": safe}

    try:
        depth, ir = np.asarray(depth_mm), np.asarray(ir_gray16)
        face, camera = np.asarray(face15, dtype=float), np.asarray(intrinsics, dtype=float)
        if (depth.ndim != 2 or depth.shape != ir.shape or min(depth.shape) < 80
                or depth.size > 4000000 or depth.dtype.kind not in "uif"
                or ir.dtype.kind not in "uif" or face.shape != (15,)
                or camera.shape != (4,) or not np.isfinite(face).all()
                or not np.isfinite(camera).all() or not np.isfinite(depth).all()
                or not np.isfinite(ir).all()):
            return reject("深度、红外或人脸数据格式无效")
        fx, fy, cx, cy = camera
        height, width = depth.shape
        if min(fx, fy) <= 0 or not (0 <= cx < width and 0 <= cy < height):
            return reject("相机内参无效")
        x, y, w, h = face[:4]
        landmarks = face[4:14].reshape(5, 2)
        if (min(w, h) < 75 or x < 0 or y < 0 or x+w > width or y+h > height
                or not .90 <= face[14] <= 1
                or not ((landmarks[:, 0] >= x) & (landmarks[:, 0] < x+w)
                        & (landmarks[:, 1] >= y) & (landmarks[:, 1] < y+h)).all()):
            return reject("人脸过小、越界或定位不可靠")
        eyes = landmarks[:2][np.argsort(landmarks[:2, 0])]
        eye_mid, nose, mouth = eyes.mean(axis=0), landmarks[2], landmarks[3:].mean(axis=0)
        eye_vector = eyes[1]-eyes[0]
        scale = float(np.linalg.norm(eye_vector))
        if scale < 25 or abs(eye_vector[1]) > .26*scale:
            return reject("请正对镜头并保持头部平正")
        right = eye_vector/scale
        down = np.array([-right[1], right[0]])
        nose_pos, mouth_pos = (nose-eye_mid)/scale, (mouth-eye_mid)/scale
        if (abs(nose_pos @ right) > .22 or not .30 < nose_pos @ down < 1.0
                or abs(mouth_pos @ right) > .20 or not .85 < mouth_pos @ down < 1.8):
            return reject("人脸关键点或正面姿态不符合要求")

        # Work only inside a landmark-bound inner face, never the box/background.
        yy, xx = np.mgrid[max(0, int(y)):min(height, int(np.ceil(y+h))),
                          max(0, int(x)):min(width, int(np.ceil(x+w)))]
        offset = np.stack((xx-nose[0], yy-nose[1]), axis=-1)/scale
        u, v = offset @ right, offset @ down
        core = (u/.80)**2 + ((v+.02)/1.03)**2 <= 1
        z, light = depth[yy, xx].astype(float), ir[yy, xx].astype(float)
        valid = (z >= 400) & (z <= 1000)
        if core.sum() < 500:
            return reject("人脸有效区域过小")
        metrics["depth_coverage"] = float(valid[core].mean())
        if metrics["depth_coverage"] < .90:
            return reject("人脸深度缺失或距离不在40至100厘米实验范围")
        values = z[core & valid]
        metrics["depth_span_mm"] = float(np.percentile(values, 95)-np.percentile(values, 5))
        if metrics["depth_span_mm"] > 130:
            return reject("人脸区域深度跨度异常，可能混入背景")
        eye_mm = float(scale*float(np.median(values))/fx)
        metrics["eye_spacing_mm"] = eye_mm
        if not 38 <= eye_mm <= 90:
            return reject("人脸尺寸与深度不一致")
        pixels = light[core]
        metrics["ir_saturation_fraction"] = float((pixels >= 1000).mean())
        metrics["ir_contrast"] = float(np.percentile(pixels, 90)-np.percentile(pixels, 10))
        if (pixels.min() < 0 or pixels.max() > 1023
                or metrics["ir_saturation_fraction"] > .10 or metrics["ir_contrast"] < 24):
            return reject("红外过曝、过暗或纹理不足")
        inner_pairs = core[:, 1:] & core[:, :-1]
        metrics["ir_gradient"] = float(np.median(np.abs(np.diff(light, axis=1))[inner_pairs]))
        if metrics["ir_gradient"] < 1.5:
            return reject("红外纹理不足")

        patches = {"nose": (0, 0, .15), "left": (-.54, .02, .16),
                   "right": (.54, .02, .16), "forehead": (0, -.80, .14),
                   "lower": (0, .74, .14)}
        masks = {}
        for name, (pu, pv, radius) in patches.items():
            patch = core & ((u-pu)**2+(v-pv)**2 <= radius**2)
            if patch.sum() < 20 or valid[patch].mean() < .90:
                return reject("鼻部或面部锚点缺少可靠深度")
            masks[name] = patch & valid
            metrics[name+"_depth_mm"] = float(np.median(z[masks[name]]))
        # Abrupt depth edges inside the face cannot be used as a nose contour.
        jumps = []
        for axis in (0, 1):
            first = (slice(1, None), slice(None)) if axis == 0 else (slice(None), slice(1, None))
            last = (slice(None, -1), slice(None)) if axis == 0 else (slice(None), slice(None, -1))
            pairs = core[first] & core[last] & valid[first] & valid[last]
            jumps.append(np.abs(z[first]-z[last])[pairs] > 20)
        metrics["depth_edge_fraction"] = float(np.concatenate(jumps).mean())
        if metrics["depth_edge_fraction"] > .02:
            return reject("人脸深度不连续或背景边缘混入")

        # Plane fitting in actual camera XYZ rejects tilted flat photographs.
        anchors = core & valid & ~((np.abs(u) < .31) & (np.abs(v) < .43))
        if distortion is None:
            px = (xx-cx)*z/fx
            py = (yy-cy)*z/fy
        else:
            import cv2
            coefficients = np.asarray(distortion, dtype=float)
            if coefficients.shape != (5,) or not np.isfinite(coefficients).all():
                return reject('出厂畸变参数无效')
            K = np.array([[fx,0,cx],[0,fy,cy],[0,0,1.]])
            points = np.stack((xx,yy),axis=-1).astype(np.float64).reshape(-1,1,2)
            rays = cv2.undistortPoints(points,K,coefficients).reshape(*xx.shape,2)
            px, py = rays[...,0]*z, rays[...,1]*z
        xyz = np.column_stack((px[anchors], py[anchors], z[anchors]))
        origin = xyz.mean(axis=0)
        _, _, axes = np.linalg.svd(xyz-origin, full_matrices=False)
        normal = axes[-1]
        if normal[2] < 0:
            normal = -normal
        nose_xyz = np.column_stack((px[masks["nose"]], py[masks["nose"]], z[masks["nose"]]))
        metrics["nose_plane_prominence_mm"] = float(np.median(-(nose_xyz-origin) @ normal))
        if not 10 <= metrics["nose_plane_prominence_mm"] <= 65:
            return reject("未检测到足够的局部鼻部立体凸起")

        # shortcut: sculpted 3D faces are outside this geometric screen; validated PAD needs a separate detector.
        # Remove smooth bending first; a bowed paper's global depth range is not a nose.
        terms = np.stack((np.ones_like(u), u, v, u*u, u*v, v*v), axis=-1)
        design, inverse_z = terms[anchors], 1/z[anchors]
        coefficients, _, rank, _ = np.linalg.lstsq(design, inverse_z, rcond=None)
        if rank != 6:
            return reject("面部曲面拟合失败")
        inverse_prediction = terms @ coefficients
        if (inverse_prediction[core] <= 0).any():
            return reject("面部曲面预测无效")
        residual = 1/np.maximum(inverse_prediction, 1e-9)-z
        nose_bump = float(np.median(residual[masks["nose"]]))
        metrics["nose_local_prominence_mm"] = nose_bump
        if not 6 <= nose_bump <= 45:
            return reject("鼻部局部几何不足，可能为平面或弯曲载体")
        for axis, points in (("horizontal", [(-.33, 0), (.33, 0)]),
                             ("vertical", [(0, -.40), (0, .40)])):
            surround = []
            for pu, pv in points:
                patch = core & ((u-pu)**2+(v-pv)**2 <= .11**2)
                if patch.sum() < 15 or valid[patch].mean() < .90:
                    return reject("鼻部周边缺少可靠深度")
                surround.append(float(np.median(residual[patch & valid])))
            metrics[axis+"_nose_locality_mm"] = nose_bump-max(surround)
            if metrics[axis+"_nose_locality_mm"] < 4:
                return reject("鼻部形状呈连续弯折或脊线，无法确认局部凸起")
        if not all(np.isfinite(value) for value in metrics.values()):
            return reject("几何计算产生无效结果")
        return {"accepted": True, "reason": "实验性几何筛查通过", "metrics": metrics}
    except (TypeError, ValueError, IndexError, OverflowError, np.linalg.LinAlgError):
        return reject("深度、红外或几何计算无效")
