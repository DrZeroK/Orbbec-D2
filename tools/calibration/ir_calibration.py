"""RAM-only IR calibration analysis. No camera access, image files or configuration writes.

All acceptance limits are engineering starting values, not biometric/security
certification. `intrinsics_verified` covers this IR fit only; `verified` remains
False because depth/IR boundary registration and timing require separate checks.
"""
import cv2
import numpy as np


IMAGE_SIZE = (640, 400)
PATTERN_ID = "d2-a4-9x12-measured19p2-inner8x11-v1"
SPEC = {"squares": [9, 12], "inner_corners": [8, 11], "square_mm": 19.2,
        "paper_mm": [210.0, 297.0], "object_origin": "checkerboard-centre", "pattern_top_left_on_paper_mm": None}
LIMITS = {"training_poses": 15, "holdout_poses": 5, "duplicate_rms_px": 3.0,
          "center_span_x": .25, "center_span_y": .18, "corner_hull_fraction": .25,
          "normal_span": .25, "minor_tilt_std": .07, "distance_ratio": 1.20,
          "training_rms_px": .50, "training_view_max_px": .80,
          "holdout_rms_px": .60, "holdout_p95_px": 1.20,
          "holdout_normal_span": .15, "holdout_distance_ratio": 1.10,
          "focal_std_fraction": .03, "principal_std_px": 5.0,
          "depth_coverage": .90, "depth_bias_mm": 15.0, "depth_p95_mm": 25.0,
          "spacing_median_fraction": .04, "spacing_p95_fraction": .10}


def _check_spec(spec):
    if spec != SPEC:
        raise ValueError("棋盘规格必须与已打印的9×12个实测19.2毫米方格一致")


def object_points(spec=SPEC):
    """88 inner corners, millimetres, origin at the checkerboard centre."""
    _check_spec(spec)
    points = np.zeros((88, 3), np.float32)
    grid = np.mgrid[1:9, 1:12].T.reshape(-1, 2)
    points[:, :2] = (grid-np.array([4.5, 6.0]))*SPEC["square_mm"]
    return points


def _depth_array(depth_mm):
    depth = np.asarray(depth_mm)
    if (depth.shape != (400, 640) or depth.dtype.kind not in "uif"
            or not np.isfinite(depth).all() or (depth < 0).any() or (depth > 65535).any()):
        raise ValueError("深度必须是640×400、有限非负毫米数组")
    return depth


def _points(corners):
    raw = np.asarray(corners)
    if raw.dtype.kind not in "uif":
        raise ValueError("棋盘角点必须是实数")
    points = raw.astype(np.float64)
    if points.shape != (88, 2) or not np.isfinite(points).all():
        raise ValueError("必须提供88个有限棋盘角点")
    if not ((points >= [4, 4]) & (points <= [635, 395])).all():
        raise ValueError("棋盘角点越界或距图像边缘太近")
    return points


def observation_from_points(corners, depth_mm, spec=SPEC):
    """Create JSON-safe numeric observations; depth is sampled, never filled."""
    _check_spec(spec)
    points, depth = _points(corners), _depth_array(depth_mm)
    samples, coverage = [], []
    for x, y in np.rint(points).astype(int):
        patch = depth[y-1:y+2, x-1:x+2]
        valid = (patch >= 300) & (patch <= 1300)
        coverage.append(float(valid.mean()))
        samples.append(float(np.median(patch[valid])) if valid.sum() >= 7 else None)
    return {"pattern_id": PATTERN_ID, "image_size": list(IMAGE_SIZE),
            "corners": points.tolist(), "depth_mm": samples, "depth_patch_coverage": coverage}


def detect_observation(ir_gray16, depth_mm, spec=SPEC):
    """Detect the complete pattern in a native 10-bit uint16 IR frame in RAM."""
    _check_spec(spec)
    _depth_array(depth_mm)
    ir = np.asarray(ir_gray16)
    if ir.shape != (400, 640) or ir.dtype != np.uint16 or ir.max() > 1023:
        raise ValueError("红外必须是原始640×400、0至1023的uint16数组")
    lo, hi = np.percentile(ir, [1, 99])
    if hi-lo < 32:
        raise ValueError("红外对比度不足，请确认打印图案在红外下可见")
    image = np.uint8(np.clip((ir.astype(float)-lo)*255/(hi-lo), 0, 255))
    # Suppress projector dots before clipping; keep SB's own subpixel positions.
    native = cv2.medianBlur(ir, 5)
    low, high = np.percentile(native, [1, 99])
    found, corners, refinement = False, None, None
    method = 'median5-native-sb'
    if high-low >= 8 and hasattr(cv2, 'findChessboardCornersSB'):
        cleaned = np.uint8(np.clip((native.astype(float)-low)*255/(high-low), 0, 255))
        found, corners = cv2.findChessboardCornersSB(
            cleaned, (8, 11), cv2.CALIB_CB_NORMALIZE_IMAGE | cv2.CALIB_CB_EXHAUSTIVE | cv2.CALIB_CB_ACCURACY)
    if not found:
        cleaned = cv2.GaussianBlur(cv2.medianBlur(image, 5), (5, 5), 1.5)
        found, corners = cv2.findChessboardCorners(
            cleaned, (8, 11), cv2.CALIB_CB_ADAPTIVE_THRESH | cv2.CALIB_CB_NORMALIZE_IMAGE)
        method, refinement = 'median5-gaussian5-classic', cleaned
    if not found:
        image = cv2.GaussianBlur(image, (3, 3), 0)
        if hasattr(cv2, 'findChessboardCornersSB'):
            found, corners = cv2.findChessboardCornersSB(
                image, (8, 11), cv2.CALIB_CB_NORMALIZE_IMAGE | cv2.CALIB_CB_EXHAUSTIVE | cv2.CALIB_CB_ACCURACY)
            method = 'gaussian3-sb'
        if not found:
            found, corners = cv2.findChessboardCorners(
                image, (8, 11), cv2.CALIB_CB_ADAPTIVE_THRESH | cv2.CALIB_CB_NORMALIZE_IMAGE)
            method = 'gaussian3-classic'
        refinement = image
    if not found:
        raise ValueError("未找到完整的8×11内角点棋盘")
    if refinement is not None:
        corners = cv2.cornerSubPix(refinement, corners, (4, 4), (-1, -1),
                                  (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_MAX_ITER, 50, 1e-4))
    result = observation_from_points(corners.reshape(88, 2), depth_mm, spec)
    result['corner_detector'] = method
    return result


def assess_novelty(candidate, existing):
    """Reject repeated image poses, allowing the detector's 180-degree ambiguity."""
    points = _points(candidate["corners"])
    closest = float("inf")
    for other in existing:
        previous = _points(other["corners"])
        closest = min(closest, *(float(np.sqrt(np.mean(np.sum((points-p)**2, axis=1))))
                                 for p in (previous, previous[::-1])))
    return {"accepted": closest >= LIMITS["duplicate_rms_px"],
            "closest_rms_px": closest if np.isfinite(closest) else None}


def _camera(K, dist):
    raw_matrix, raw_dist = np.asarray(K), np.asarray(dist)
    if raw_matrix.dtype.kind not in "uif" or raw_dist.dtype.kind not in "uif":
        raise ValueError("内参与畸变必须是实数")
    matrix, distortion = raw_matrix.astype(float), raw_dist.astype(float).reshape(-1)
    if (matrix.shape != (3, 3) or distortion.shape != (5,) or not np.isfinite(matrix).all()
            or not np.isfinite(distortion).all() or min(matrix[0, 0], matrix[1, 1]) <= 0
            or not np.allclose(matrix[2], [0, 0, 1]) or abs(matrix[0, 1])+abs(matrix[1, 0]) > 1e-9):
        raise ValueError("相机矩阵或五项畸变参数无效")
    return matrix, distortion


def normalized_rays(K, dist):
    """400×640×3 rays with Z=1: XYZ_mm = raw_depth_Z_mm[...,None] * rays.

    This undistorts pixel coordinates only; it does not resample/fill depth.
    Invalid depth stays invalid and must be masked by the caller.
    """
    matrix, distortion = _camera(K, dist)
    yy, xx = np.mgrid[:400, :640]
    pixels = np.stack((xx, yy), axis=-1).astype(np.float64).reshape(-1, 1, 2)
    xy = cv2.undistortPointsIter(pixels, matrix, distortion, None, None,
                              (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_MAX_ITER, 50, 1e-12))
    rays = np.concatenate((xy.reshape(400, 640, 2), np.ones((400, 640, 1))), axis=2)
    if not np.isfinite(rays).all():
        raise ValueError("去畸变射线包含无效值")
    return rays


def _checked_observation(observation):
    if (not isinstance(observation, dict) or observation.get("pattern_id") != PATTERN_ID
            or observation.get("image_size") != list(IMAGE_SIZE)):
        raise ValueError("角点记录的打印规格或图像尺寸不匹配")
    points = _points(observation.get("corners"))
    depths = observation.get("depth_mm")
    fractions = np.asarray(observation.get("depth_patch_coverage"), float)
    if (not isinstance(depths, list) or len(depths) != 88 or fractions.shape != (88,)
            or not np.isfinite(fractions).all() or ((fractions < 0) | (fractions > 1)).any()
            or any(value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))
                                         or not np.isfinite(value) or not 300 <= value <= 1300)
                   for value in depths)):
        raise ValueError("角点深度或有效比例无效")
    return points


def _depth_metrics(observation, points, obj, K, dist, rvec, tvec):
    values = np.array([np.nan if value is None else value for value in observation["depth_mm"]])
    valid = np.isfinite(values) & (np.asarray(observation["depth_patch_coverage"]) >= 7/9)
    rotation = cv2.Rodrigues(rvec)[0]
    predicted = (obj @ rotation.T + tvec.reshape(3))[:, 2]
    errors = values[valid]-predicted[valid]
    result = {"coverage": float(valid.mean())}
    if valid.sum() < 2:
        return result
    result.update(bias_mm=float(np.median(errors)), p95_mm=float(np.percentile(np.abs(errors), 95)))
    rays = cv2.undistortPoints(points.reshape(-1, 1, 2), K, dist).reshape(-1, 2)
    xyz = np.column_stack((rays, np.ones(88)))*values[:, None]
    xyz, valid = xyz.reshape(11, 8, 3), valid.reshape(11, 8)
    spacing_errors = []
    for axis in (0, 1):
        adjacent = valid[1:] & valid[:-1] if axis == 0 else valid[:, 1:] & valid[:, :-1]
        length = np.linalg.norm(np.diff(xyz, axis=axis), axis=2)
        spacing_errors.extend(np.abs(length[adjacent]/SPEC["square_mm"]-1))
    if spacing_errors:
        result["spacing_median_fraction"] = float(np.median(spacing_errors))
        result["spacing_p95_fraction"] = float(np.percentile(spacing_errors, 95))
    return result


def analyze(training, holdout, spec=SPEC):
    """Fit training poses and independently solve held-out poses with K/dist fixed.

    The full numeric observations may be JSON-saved by a collector; this module
    writes nothing. An IR-only pass never enables a depth/IR unlock profile.
    """
    result = {"intrinsics_verified": False, "verified": False, "scope": "ir_intrinsics_only",
              "reasons": [], "limits": dict(LIMITS), "pattern": dict(SPEC)}
    reasons = result["reasons"]
    try:
        _check_spec(spec)
        if len(training) < 15 or len(holdout) < 5:
            raise ValueError("至少需要15个训练姿态和5个独立留出姿态")
        observations = [*training, *holdout]
        points = [_checked_observation(item) for item in observations]
        for index, item in enumerate(observations):
            if not assess_novelty(item, observations[:index])["accepted"]:
                raise ValueError("存在重复或过于相近的姿态，不能作为独立样本")
        train_points = points[:len(training)]
        centres = np.array([p.mean(axis=0) for p in train_points])
        span = np.ptp(centres, axis=0)/np.array(IMAGE_SIZE)
        hull = cv2.convexHull(np.concatenate(train_points).astype(np.float32))
        hull_fraction = float(cv2.contourArea(hull)/(640*400))
        result["coverage"] = {"centre_span_x": float(span[0]), "centre_span_y": float(span[1]),
                              "corner_hull_fraction": hull_fraction}
        if span[0] < .25 or span[1] < .18 or hull_fraction < .25:
            reasons.append("训练姿态未覆盖足够的画面位置")
        obj = object_points(spec)
        rms, K, dist, rvecs, tvecs, std_i, _, view_errors = cv2.calibrateCameraExtended(
            [obj.copy() for _ in training], [p.astype(np.float32) for p in train_points],
            IMAGE_SIZE, None, None, flags=0,
            criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_MAX_ITER, 100, 1e-9))
        K, dist = _camera(K, dist)
        std_i = std_i.reshape(-1)
        if not np.isfinite(std_i).all() or not np.isfinite(view_errors).all() or not np.isfinite(rms):
            raise ValueError("标定或参数不确定度包含非有限值")
        result.update(K=K.tolist(), dist=dist.tolist(), training_rms_px=float(rms),
                      training_view_rms_px=view_errors.reshape(-1).tolist(),
                      parameter_std=std_i.tolist())
        if (not (100 < K[0, 0] < 2000 and 100 < K[1, 1] < 2000)
                or not (-64 < K[0, 2] < 704 and -40 < K[1, 2] < 440)):
            reasons.append("内参落在实验合理范围之外")
        if rms > .50 or view_errors.max() > .80:
            reasons.append("训练重投影误差过高")
        if max(std_i[0]/K[0, 0], std_i[1]/K[1, 1]) > .03 or max(std_i[2:4]) > 5:
            reasons.append("内参不确定度过大")
        normals = np.array([cv2.Rodrigues(rv)[0][:, 2] for rv in rvecs])
        if not np.isfinite(normals).all() or not all(np.isfinite(tv).all() for tv in tvecs):
            raise ValueError("训练姿态包含非有限值")
        tilt_xy = normals[:, :2]
        normal_span = np.ptp(tilt_xy, axis=0)
        minor_std = float(np.linalg.svd(tilt_xy-tilt_xy.mean(axis=0), compute_uv=False)[-1]/np.sqrt(len(training)))
        distances = np.array([tv.reshape(3)[2] for tv in tvecs])
        ratio = float(distances.max()/distances.min()) if distances.min() > 0 else 0.0
        result["pose_diversity"] = {"normal_span_x": float(normal_span[0]), "normal_span_y": float(normal_span[1]),
                                    "minor_tilt_std": minor_std, "distance_ratio": ratio}
        if normal_span.min() < .25 or minor_std < .07 or ratio < 1.20:
            reasons.append("姿态缺少双轴倾斜或近远变化，低RMS不能证明标定有效")
        held, held_normals, held_distances = [], [], []
        for item, p in zip(holdout, points[len(training):]):
            ok, rv, tv = cv2.solvePnP(obj, p, K, dist, flags=cv2.SOLVEPNP_ITERATIVE)
            if not ok or not np.isfinite(rv).all() or not np.isfinite(tv).all() or tv.reshape(3)[2] <= 0:
                raise ValueError("留出姿态求解失败")
            projected = cv2.projectPoints(obj, rv, tv, K, dist)[0].reshape(-1, 2)
            error = np.linalg.norm(projected-p, axis=1)
            depth = _depth_metrics(item, p, obj, K, dist, rv, tv)
            if not np.isfinite(error).all() or not all(np.isfinite(value) for value in depth.values()):
                raise ValueError("留出计算包含非有限值")
            held.append({"rms_px": float(np.sqrt(np.mean(error**2))),
                         "p95_px": float(np.percentile(error, 95)), "depth": depth})
            held_normals.append(cv2.Rodrigues(rv)[0][:2, 2])
            held_distances.append(float(tv.reshape(3)[2]))
        result["holdout"] = held
        held_span = np.ptp(held_normals, axis=0)
        held_ratio = max(held_distances)/min(held_distances)
        result["holdout_diversity"] = {"normal_span_x": float(held_span[0]),
                                       "normal_span_y": float(held_span[1]), "distance_ratio": held_ratio}
        if held_span.min() < .15 or held_ratio < 1.10:
            reasons.append("留出样本缺少双轴倾斜或近远变化")
        if any(v["rms_px"] > .60 or v["p95_px"] > 1.20 for v in held):
            reasons.append("独立留出重投影误差过高")
        if any(v["depth"].get("coverage", 0) < .90 or abs(v["depth"].get("bias_mm", 1e9)) > 15
               or v["depth"].get("p95_mm", 1e9) > 25
               or v["depth"].get("spacing_median_fraction", 1e9) > .04
               or v["depth"].get("spacing_p95_fraction", 1e9) > .10 for v in held):
            reasons.append("留出深度平面、已知实测方格尺度或深度覆盖检验未通过")
        result["intrinsics_verified"] = not reasons
        result["pending"] = ["深度与红外在真实纸边/背景台阶处的配准验收", "双流时序验收", "真人和呈现攻击验收"]
    except (TypeError, ValueError, KeyError, IndexError, cv2.error, np.linalg.LinAlgError) as exc:
        reasons.append(str(exc) if isinstance(exc, ValueError) else "输入或标定计算失败")
    return result
