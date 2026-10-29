"""
Height & Weight - a normal DeepFit camera test (no separate program, no PyTorch).

HEIGHT
A camera cannot know centimetres unless something of known size is in the picture. The athlete
stands with heels, back and head against a wall, next to two references on that wall:
  * best:  the two DeepFit sheets - print /height/marker at 100 %: a 16.0 cm black-and-white code
           each (FLOOR = id 23, TOP = id 24). OpenCV finds their corners to a fraction of a pixel.
  * else:  two plain A4 sheets (21.0 x 29.7 cm), long side up, on a darker wall.
The FLOOR sheet stands on the floor: its bottom edge IS the floor line on the wall, exactly where the
heels stand - so the feet never have to be found. (Measuring to the toes would be wrong by several
cm: they stick out ~25 cm towards the camera and look lower than the floor.)
The TOP sheet goes anywhere above the head (no measuring). One sheet alone can't tell how much the
camera is tilted - a 2 degree tilt would add ~4 cm. With both, the mapping picture -> wall (cm) is
pinned at both ends of the body (a homography fitted to 8 corners: the floor sheet's place is known,
the top sheet's place is solved for), so tilt and turn are handled exactly.

The head top comes from the body cut-out (MediaPipe segmentation), refined to sub-pixel where the
soft mask crosses 50 %. The top of the head is ~8 cm in front of the wall, so its ray hits the wall
a little too high or low; the camera position (from the same mapping) corrects that parallax. Many frames are combined (median) and the test only
finishes when they agree within +/-0.5 cm.

Expected accuracy: about +/-1 cm (~99.4 % for a 165 cm person) with the camera 2-3 m away at chest
height, barefoot, no cap, hair flat. Error budget: marker corners ~0.3 cm, head-top depth ~0.4 cm,
hair/posture ~0.5 cm, lens distortion of wide webcams up to ~1 cm (keep the athlete in the middle
of the picture). No camera method can promise 99.99 % - that is +/-0.02 cm, finer than a school
stadiometer (+/-0.1-0.5 cm) or the change in a person's height between morning and evening (~1 cm).

NO SHEETS ("just stand")
Without the sheets the body itself is the ruler, as in the original DeepFit estimator: the spacing of the eyes
and the width of the shoulders have known average sizes (smaller for children, so they go by age). One person's
can be ~5 % off the average, so this is an ESTIMATE, typically within about +/-5-8 cm. Weight is then a typical
weight for that height and age - the camera cannot weigh - so no BMI is made from it.

WEIGHT
A camera cannot weigh. DeepFit reads the athlete's bathroom scale instead: a photo of the display
goes to a vision model (Muse Spark, or the Groq fallback - see llm.py) which reads the number, so
the value is as accurate as the scale (usually +/-0.1 kg). It can also be typed.
"""

import math
from collections import deque
from statistics import median
from typing import Dict, List, Optional

import cv2
import numpy as np

from exercise_engine import (Exercise, L_ANKLE, L_HEEL, L_FOOT, L_HIP, L_KNEE, L_SHOULDER, NOSE, R_ANKLE, R_HEEL,
                             R_FOOT, R_HIP, R_KNEE, R_SHOULDER, angle)

MARKER_DICT = cv2.aruco.DICT_4X4_50 if hasattr(cv2, "aruco") else None
MARKER_IDS = {"floor": 23, "top": 24}   # two printed codes: one on the floor, one anywhere above the head
MARKER_ID = MARKER_IDS["floor"]
MARKER_CM = 16.0           # leaves >= 2.5 cm of white paper round the code on A4 (the edge finder needs a clean white rim)
MARKER_GAP_CM = 3.0        # the FLOOR sheet is cut 3 cm below the code, so the code's bottom edge is 3 cm above the floor
A4_CM = (21.0, 29.7)
NEED_SAMPLES = 25
STABLE_CM = 0.5            # half the range of the middle samples must be within this
MAX_FIT_RMS_CM = 0.35      # the two sheets must fit one flat wall this well (cm), else one is mis-printed, bent or not on the wall


# ------------------------------------------------------------------ the two references on the wall

def _quad(kind: str, q: np.ndarray, role: Optional[str] = None) -> Dict:
    left, right = np.linalg.norm(q[3] - q[0]), np.linalg.norm(q[2] - q[1])
    top, bottom = np.linalg.norm(q[1] - q[0]), np.linalg.norm(q[2] - q[3])
    return {"kind": kind, "role": role, "corners": q.tolist(), "size_px": [round((top + bottom) / 2, 2), round((left + right) / 2, 2)],
            "center": q.mean(axis=0).tolist()}


def refine_quad(gray, q: np.ndarray) -> np.ndarray:
    """Corners to ~1/20 pixel: each edge is found at dozens of points (where the brightness is halfway
    between the dark and the bright side), a straight line is fitted through them, and neighbouring
    lines are intersected. Far steadier than refining the 4 corner pixels alone."""
    g = cv2.GaussianBlur(gray, (3, 3), 0).astype(np.float32)
    q = np.asarray(q, dtype=np.float64)
    c0 = q.mean(axis=0)
    size = float(np.mean([np.linalg.norm(q[(k + 1) % 4] - q[k]) for k in range(4)]))
    half = float(np.clip(size / 14, 1.5, 4.0))
    offs = np.arange(-half, half + 1e-6, 0.25)
    lines = []
    for k in range(4):
        a, b = q[k], q[(k + 1) % 4]
        d = b - a
        L = np.linalg.norm(d)
        t = d / L
        n = np.array([-t[1], t[0]])
        if n @ ((a + b) / 2 - c0) < 0:
            n = -n                                         # outward
        ss = np.linspace(0.15, 0.85, max(8, int(L * 0.35)))
        base = a[None, :] + ss[:, None] * d[None, :]
        P = base[:, None, :] + offs[None, :, None] * n[None, None, :]
        prof = cv2.remap(g, P[..., 0].astype(np.float32), P[..., 1].astype(np.float32), cv2.INTER_LINEAR)
        pts = []
        for i in range(len(ss)):
            pr = prof[i]
            lo, hi = float(pr.min()), float(pr.max())
            if hi - lo < 20:
                continue
            lvl = (lo + hi) / 2
            sgn = pr - lvl
            idx = np.nonzero(np.sign(sgn[:-1]) != np.sign(sgn[1:]))[0]
            if len(idx) == 0:
                continue
            j = idx[np.argmin(np.abs(offs[idx]))]           # the crossing nearest the rough edge
            f = sgn[j] / (sgn[j] - sgn[j + 1])
            pts.append(base[i] + (offs[j] + f * 0.25) * n)
        if len(pts) < 5:
            return q
        pts = np.array(pts)
        m = pts.mean(axis=0)
        _, _, vt = np.linalg.svd(pts - m)
        res = np.abs((pts - m) @ np.array([-vt[0][1], vt[0][0]]))
        keep = res <= max(0.3, 3 * np.median(res))          # drop points spoiled by a finger / shadow
        if keep.sum() >= 5:
            m = pts[keep].mean(axis=0)
            _, _, vt = np.linalg.svd(pts[keep] - m)
        lines.append((m, vt[0]))
    out = []
    for k in range(4):                                     # corner k joins edge k-1 and edge k
        (p1, d1), (p2, d2) = lines[k - 1], lines[k]
        A = np.array([d1, -d2]).T
        if abs(np.linalg.det(A)) < 1e-9:
            return q
        s1, _ = np.linalg.solve(A, p2 - p1)
        out.append(p1 + s1 * d1)
    out = np.array(out)
    return out if np.abs(out - q).max() < max(3.0, 0.1 * size) else q


def _aruco_params():
    p = cv2.aruco.DetectorParameters()
    p.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
    return p


def find_markers(gray) -> Dict[str, Dict]:
    """The printed DeepFit codes: id 23 = FLOOR sheet, id 24 = TOP sheet."""
    if MARKER_DICT is None:
        return {}
    det = cv2.aruco.ArucoDetector(cv2.aruco.getPredefinedDictionary(MARKER_DICT), _aruco_params())
    corners, ids, _ = det.detectMarkers(gray)
    out = {}
    if ids is None:
        # a mirrored picture (some front cameras) shows the codes back to front: read them from the flipped picture
        corners, ids, _ = det.detectMarkers(cv2.flip(gray, 1))
        if ids is None:
            return out
        w = gray.shape[1]
        corners = [np.stack([w - 1 - c[..., 0], c[..., 1]], axis=-1) for c in corners]
    for c, i in zip(corners, ids.flatten()):
        for role, mid in MARKER_IDS.items():
            if int(i) == mid:
                q = _order(c.reshape(4, 2).astype(np.float32)).astype(np.float64)   # tl, tr, br, bl as seen in the picture
                q = refine_quad(gray, q)
                if min(_quad("marker", q)["size_px"]) >= 12:
                    out[role] = _quad("marker", q, role)
    return out


def find_a4s(gray) -> List[Dict]:
    """Bright 21 x 29.7 cm rectangles (long side up) that stand out from the wall."""
    h, w = gray.shape[:2]
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.dilate(cv2.Canny(blur, 30, 90), np.ones((3, 3), np.uint8))
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    found = []
    for c in contours:
        area = cv2.contourArea(c)
        if not 0.0008 * w * h <= area <= 0.25 * w * h:
            continue
        ap = cv2.approxPolyDP(c, 0.02 * cv2.arcLength(c, True), True)
        if len(ap) != 4 or not cv2.isContourConvex(ap):
            continue
        q = _order(ap.reshape(4, 2).astype(np.float32))
        crit = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.01)
        q = cv2.cornerSubPix(blur, q.reshape(-1, 1, 2).copy(), (5, 5), (-1, -1), crit).reshape(4, 2).astype(np.float64)
        q = refine_quad(gray, q)
        info = _quad("a4", q)
        hh, v = info["size_px"]
        if not 1.28 <= v / max(hh, 1) <= 1.58:           # A4 is 1.414 tall:wide (some slack for perspective)
            continue
        m = np.zeros_like(gray); cv2.fillConvexPoly(m, q.astype(np.int32), 255)
        ring = cv2.dilate(m, np.ones((15, 15), np.uint8)) - m
        inside, outside = cv2.mean(gray, m)[0], cv2.mean(gray, ring)[0]
        if inside < outside + 25:                         # paper must be clearly brighter than the wall
            continue
        info["area"] = area
        found.append(info)
    found.sort(key=lambda r: -r["area"])
    sheets = []
    for r in found:                                       # the same sheet is often found twice (inner + outer edge)
        if all(np.linalg.norm(np.subtract(r["center"], k["center"])) > 0.5 * k["size_px"][0] for k in sheets):
            sheets.append(r)
    return sheets


def _order(p):
    s, d = p.sum(axis=1), np.diff(p, axis=1).ravel()
    return np.array([p[np.argmin(s)], p[np.argmin(d)], p[np.argmax(s)], p[np.argmax(d)]], dtype=np.float32)


def find_references(bgr) -> Dict:
    """{"kind": "marker"|"a4", "floor": quad or None, "top": quad or None} - {} when nothing is found."""
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY) if bgr.ndim == 3 else bgr
    m = find_markers(gray)
    if m:
        return {"kind": "marker", "floor": m.get("floor"), "top": m.get("top")}
    sheets = sorted(find_a4s(gray), key=lambda r: r["center"][1])
    if not sheets:
        return {}
    floor = dict(sheets[-1], role="floor")                # lowest in the picture
    top = None
    if len(sheets) > 1 and floor["center"][1] - sheets[0]["center"][1] > 2.5 * floor["size_px"][1]:
        top = dict(sheets[0], role="top")
    return {"kind": "a4", "floor": floor, "top": top}


def find_reference(bgr) -> Optional[Dict]:
    """The floor sheet only (kept for older callers)."""
    return find_references(bgr).get("floor")


# ------------------------------------------------------------------ picture -> wall (cm), from both sheets

def _apply(H: np.ndarray, pts: np.ndarray) -> np.ndarray:
    p = np.c_[pts, np.ones(len(pts))] @ H.T
    return p[:, :2] / p[:, 2:3]


def _rot(a: float) -> np.ndarray:
    return np.array([[math.cos(a), -math.sin(a)], [math.sin(a), math.cos(a)]])


def _place(template: np.ndarray, pts: np.ndarray):
    """Rotation + shift (no scale) that best puts the template on pts."""
    tc, pc = template.mean(0), pts.mean(0)
    a, b = template - tc, pts - pc
    ang = math.atan2((a[:, 0] * b[:, 1] - a[:, 1] * b[:, 0]).sum(), (a * b).sum())
    return ang, pc - _rot(ang) @ tc


def fit_wall(refs: Dict, w: int, h: int):
    """Homography picture -> wall (cm, y up, y = 0 on the floor under the FLOOR sheet).
    The floor sheet's place on the wall is known; the top sheet is somewhere above (unknown spot,
    may be a little rotated) but has the same known size. Both together pin the mapping over the
    whole body, so a tilted camera is handled exactly. Returns (H, rms_cm)."""
    W, Hh = (MARKER_CM, MARKER_CM) if refs["kind"] == "marker" else A4_CM
    g = MARKER_GAP_CM if refs["kind"] == "marker" else 0.0
    fl = np.array(refs["floor"]["corners"], dtype=np.float64)
    floor_wall = np.array([[0, g + Hh], [W, g + Hh], [W, g], [0, g]]) / 100.0       # metres keep the numbers tame
    s = 1.0 / max(w, h)
    T = np.array([[s, 0, -0.5 * w * s], [0, s, -0.5 * h * s], [0, 0, 1.0]])           # picture -> normalised
    U = np.diag([100.0, 100.0, 1.0])                                                   # metres -> cm
    A = _apply(T, fl)
    H0 = cv2.getPerspectiveTransform(A.astype(np.float32), floor_wall.astype(np.float32)).astype(np.float64)
    if not refs.get("top"):
        return U @ H0 @ T, 0.0
    tmpl = np.array([[0, Hh], [W, Hh], [W, 0], [0, 0]]) / 100.0
    B = _apply(T, np.array(refs["top"]["corners"], dtype=np.float64))
    ang, sh = _place(tmpl, _apply(H0, B))
    H1, _ = cv2.findHomography(np.vstack([A, B]), np.vstack([floor_wall, tmpl @ _rot(ang).T + sh]), 0)
    H1 = H1 / H1[2, 2]
    p = np.r_[H1.ravel()[:8], sh, ang]

    def resid(p):
        Hm = np.r_[p[:8], 1.0].reshape(3, 3)
        return np.r_[(_apply(Hm, A) - floor_wall).ravel(), (_apply(Hm, B) - (tmpl @ _rot(p[10]).T + p[8:10])).ravel()]

    r = resid(p)
    lam = 1e-3
    for _ in range(60):                                   # Levenberg-Marquardt, 11 unknowns, 16 equations
        J = np.empty((len(r), len(p)))
        for k in range(len(p)):
            d = np.zeros_like(p); d[k] = 1e-7
            J[:, k] = (resid(p + d) - r) / 1e-7
        JtJ, g_ = J.T @ J, J.T @ r
        step = np.linalg.solve(JtJ + lam * np.diag(np.diag(JtJ) + 1e-12), -g_)
        r2 = resid(p + step)
        if r2 @ r2 < r @ r:
            p, r, lam = p + step, r2, lam / 3
            if np.abs(step).max() < 1e-10:
                break
        else:
            lam *= 4
    Hm = np.r_[p[:8], 1.0].reshape(3, 3)
    return U @ Hm @ T, float(100 * math.sqrt((r @ r) / (len(r) / 2)))


# ------------------------------------------------------------------ head top and soles from the body cut-out

def _crossing(profile: np.ndarray, start: int, step: int) -> Optional[float]:
    """Walk from `start` in direction `step` over a 1-D mask profile; sub-pixel row where it first crosses 0.5."""
    n = len(profile)
    i = start
    while 0 <= i < n and profile[i] >= 0.5:
        i += step
    # i is the first row outside the person; interpolate between i - step (inside) and i
    j = i - step
    if not (0 <= i < n) or not (0 <= j < n):
        return None
    a, b = profile[j], profile[i]
    frac = (a - 0.5) / (a - b) if a != b else 0.5
    return j + step * frac


def head_top(mask: np.ndarray, lm, w: int, h: int):
    """(x, y) of the top of the head in the picture, y sub-pixel, from the person mask.
    Each column above the face is followed up to where the mask crosses 50 %; the top of the head is
    the highest of those (median of the 5 highest, so one stray hair or noisy pixel doesn't decide it)."""
    P = lambda i: (lm[i][0] * w, lm[i][1] * h)
    sw = abs(P(L_SHOULDER)[0] - P(R_SHOULDER)[0])
    nx, ny = P(NOSE)
    c0, c1 = int(max(0, nx - 0.35 * sw)), int(min(w, nx + 0.35 * sw + 1))
    r0 = int(min(h - 1, max(0, ny)))
    if c1 - c0 < 2 or mask[r0, c0:c1].max() < 0.5:
        return None
    tops = []
    for c in range(c0, c1):
        if mask[r0, c] < 0.5:
            continue
        t = _crossing(mask[:, c], r0, -1)
        if t is not None:
            tops.append((t, c))
    if len(tops) < 3:
        return None
    tops.sort()
    best = tops[:5]
    return float(median(c for _, c in best)), float(median(t for t, _ in best))


def body_extent(mask: np.ndarray, lm, w: int, h: int) -> Optional[Dict]:
    """Head-top and sole rows (sub-pixel) from the person mask, guided by the landmarks (diagnostics only:
    the height itself is measured from the floor line, not the soles)."""
    P = lambda i: (lm[i][0] * w, lm[i][1] * h)
    sw = abs(P(L_SHOULDER)[0] - P(R_SHOULDER)[0])
    nx, ny = P(NOSE)
    c0, c1 = int(max(0, nx - 0.3 * sw)), int(min(w, nx + 0.3 * sw + 1))
    if c1 - c0 < 2:
        return None
    head = mask[:, c0:c1].mean(axis=1)
    if head[int(min(h - 1, ny))] < 0.5:
        return None
    top = _crossing(head, int(ny), -1)
    soles = []
    for heel, toe, ank in ((L_HEEL, L_FOOT, L_ANKLE), (R_HEEL, R_FOOT, R_ANKLE)):
        xs = [P(heel)[0], P(toe)[0], P(ank)[0]]
        a0, a1 = int(max(0, min(xs) - 0.05 * sw)), int(min(w, max(xs) + 0.05 * sw + 1))
        ay = int(min(h - 1, P(ank)[1]))
        if a1 - a0 < 2:
            continue
        foot = mask[:, a0:a1].max(axis=1)                 # any person pixel in the foot columns
        if foot[ay] < 0.5:
            continue
        s = _crossing(foot, ay, +1)
        if s is not None:
            soles.append(s)
    if top is None or not soles:
        return None
    return {"top": top, "bottom": max(soles), "touches_edge": top <= 1 or max(soles) >= h - 2}


FOCAL_RATIO = 0.714        # focal length / long image side for a ~70 degree camera (webcams and phone main cameras)
HEAD_TOP_DEPTH = 0.05      # top of the head is ~5 % of height in front of the wall (back of head on the wall)
HEAD_RADIUS = 0.055        # curvature of the top of the head ~5.5 % of height: the outline's top is a tangent, a bit above the crown


def to_wall(Hiw: np.ndarray, x: float, y: float):
    p = Hiw @ np.array([x, y, 1.0])
    return p[0] / p[2], p[1] / p[2]


def camera_pose(Hiw: np.ndarray, w: int, h: int, focal: Optional[float] = None) -> Optional[Dict]:
    """Camera position in wall coordinates (cm) from the reference's corners (planar pose)."""
    f = focal or FOCAL_RATIO * max(w, h)
    K = np.array([[f, 0, w / 2], [0, f, h / 2], [0, 0, 1.0]])
    M = np.linalg.inv(K) @ np.linalg.inv(Hiw)            # wall -> camera rays
    n1, n2 = np.linalg.norm(M[:, 0]), np.linalg.norm(M[:, 1])
    if n1 < 1e-12 or n2 < 1e-12:
        return None
    lam = 2.0 / (n1 + n2)
    if M[2, 2] * lam < 0:                                 # the wall must be in front of the camera
        lam = -lam
    r1, r2, t = lam * M[:, 0], lam * M[:, 1], lam * M[:, 2]
    U, _, Vt = np.linalg.svd(np.column_stack([r1, r2, np.cross(r1, r2)]))
    R = U @ Vt
    C = -R.T @ t
    # a real camera sees the wall's x and y axes equally long (n1 = n2); sheets printed at different sizes don't fit that
    return {"x": float(C[0]), "y": float(C[1]), "dist": float(abs(C[2])), "focal": f, "aspect": float(n2 / n1)}


def measure(bgr, lm, mask: Optional[np.ndarray], refs: Optional[Dict] = None, focal: Optional[float] = None) -> Dict:
    """One frame. lm: 33 x (x, y, visibility), normalised. Returns {"height_cm", ...} or {"problem"}."""
    h, w = bgr.shape[:2]
    refs = refs if refs is not None else find_references(bgr)
    if not refs.get("floor"):
        return {"problem": "no_reference", "refs": refs}
    if lm is None:
        return {"problem": "no_person", "refs": refs}
    vis = lambda *ids: all(lm[i][2] >= 0.5 for i in ids)
    if not vis(NOSE, L_SHOULDER, R_SHOULDER, L_HIP, R_HIP, L_ANKLE, R_ANKLE):
        return {"problem": "not_whole_body", "refs": refs}
    P = lambda i: (lm[i][0] * w, lm[i][1] * h)
    if vis(L_KNEE, R_KNEE):
        knees = [angle(P(L_HIP), P(L_KNEE), P(L_ANKLE)), angle(P(R_HIP), P(R_KNEE), P(R_ANKLE))]
        if min(knees) < 165:
            return {"problem": "not_straight", "refs": refs}
    if not refs.get("top"):
        return {"problem": "no_top_reference", "refs": refs}
    if mask is None:
        return {"problem": "no_mask", "refs": refs}
    top = head_top(mask, lm, w, h)
    if top is None:
        return {"problem": "no_outline", "refs": refs}
    if top[1] <= 1:
        return {"problem": "not_whole_body", "refs": refs}
    Hiw, rms = fit_wall(refs, w, h)
    if rms > MAX_FIT_RMS_CM:
        return {"problem": "reference_mismatch", "refs": refs}
    # the FLOOR sheet must stand on the floor next to the heels: its bottom edge is the floor line
    feet = [P(i) for i in (L_HEEL, R_HEEL) if lm[i][2] >= 0.5] or [P(i) for i in (L_ANKLE, R_ANKLE)]
    foot_y = float(np.mean([to_wall(Hiw, x, y)[1] for x, y in feet]))
    if not -15 <= foot_y <= 30:
        return {"problem": "marker_not_on_floor", "refs": refs}
    cam = camera_pose(Hiw, w, h, focal)
    if cam is None:
        return {"problem": "no_reference", "refs": refs}
    _, y_wall = to_wall(Hiw, top[0], top[1])              # where the head-top ray meets the wall
    d = HEAD_TOP_DEPTH * y_wall                             # how far the head top is in front of the wall
    dist = max(cam["dist"], 50.0)
    height = y_wall + (cam["y"] - y_wall) * d / dist
    # seen from below (or above) the outline's top is where the line of sight grazes the round head, slightly above the crown
    tilt = math.atan2(abs(height - cam["y"]), dist - d)
    height -= HEAD_RADIUS * height * (1 / math.cos(tilt) - 1)
    return {"height_cm": float(height), "wall_cm": float(y_wall), "top": top[1], "camera": cam, "fit_rms_cm": rms,
            "refs": refs}


def stable_value(values: List[float]) -> Optional[Dict]:
    """Median of the recent samples if the middle ones agree within +/-STABLE_CM."""
    if len(values) < NEED_SAMPLES:
        return None
    v = sorted(values[-NEED_SAMPLES * 2:])
    k = len(v) // 4
    mid = v[k:len(v) - k]                                  # inter-quartile samples
    spread = (mid[-1] - mid[0]) / 2
    if spread > STABLE_CM:
        return None
    return {"height_cm": round(median(v), 1), "spread_cm": round(spread, 2), "samples": len(v)}


def bmi_info(height_cm: Optional[float], weight_kg: Optional[float], age=None) -> Dict:
    if not height_cm or not weight_kg:
        return {"bmi": None}
    bmi = round(weight_kg / (height_cm / 100) ** 2, 1)
    try:
        adult = age is None or float(age) >= 18
    except (TypeError, ValueError):
        adult = True
    if adult:
        cat = "Underweight" if bmi < 18.5 else "Healthy" if bmi < 25 else "Overweight" if bmi < 30 else "Obese"
        note = "WHO adult categories."
    else:
        cat = None
        note = "Under 18: compare with BMI-for-age charts (WHO / IAP), not adult categories."
    return {"bmi": bmi, "bmi_category": cat, "bmi_note": note}


# ------------------------------------------------------------------ no sheets: the body itself is the ruler

L_EYE, R_EYE = 2, 5
IPD_BY_AGE = [(4, 4.9), (6, 5.1), (8, 5.3), (10, 5.5), (12, 5.7), (14, 5.9), (16, 6.05)]    # eye spacing, cm (children)
IPD_ADULT = {"male": 6.4, "female": 6.1}
SHOULDER_BY_AGE = [(4, 24.0), (6, 26.0), (8, 28.0), (10, 30.0), (12, 32.0), (14, 34.5), (16, 36.5)]   # shoulder width, cm
SHOULDER_ADULT = {"male": 41.2, "female": 36.8}
BMI_BY_AGE = [(5, 15.3), (8, 15.7), (10, 16.5), (12, 17.7), (14, 19.3), (16, 20.5)]    # WHO BMI-for-age medians
BMI_ADULT = {"male": 23.0, "female": 22.0}
BODY_NEED = 40             # frames standing still before it measures by itself (~3-5 s)
BODY_MIN = 8               # frames needed before "capture" can give a number
BODY_UNCERTAINTY_CM = 8


def _sex(g) -> Optional[str]:
    g = str(g or "").strip().lower()
    return "female" if g in ("f", "female", "girl", "woman") else "male" if g in ("m", "male", "boy", "man") else None


def _by_age(table, adult: Dict[str, float], age, sex) -> float:
    """Average size for this age (children) or sex (adults); both sexes averaged when unknown."""
    grown = adult.get(sex) if sex else (adult["male"] + adult["female"]) / 2
    try:
        a = float(age)
    except (TypeError, ValueError):
        return grown
    if a >= 18:
        return grown
    pts = table + [(18, grown)]
    if a <= pts[0][0]:
        return pts[0][1]
    for (a0, v0), (a1, v1) in zip(pts, pts[1:]):
        if a0 <= a <= a1:
            return v0 + (v1 - v0) * (a - a0) / (a1 - a0)
    return grown


def typical_weight(height_cm: float, age=None, sex=None) -> float:
    """A typical (median-BMI) weight for this height and age - an estimate, not a weighing."""
    return round(_by_age(BMI_BY_AGE, BMI_ADULT, age, sex) * (height_cm / 100) ** 2, 1)


def body_estimate(lm, mask: Optional[np.ndarray], w: int, h: int, age=None, sex=None) -> Dict:
    """One frame, no sheets: height from the body's own proportions. {"height_cm", "by_eyes", "by_shoulders"} or {"problem"}."""
    if lm is None:
        return {"problem": "no_person"}
    vis = lambda *ids: all(lm[i][2] >= 0.5 for i in ids)
    if not vis(NOSE, L_EYE, R_EYE, L_SHOULDER, R_SHOULDER, L_HIP, R_HIP, L_ANKLE, R_ANKLE):
        return {"problem": "body_not_whole"}
    P = lambda i: (lm[i][0] * w, lm[i][1] * h)
    if vis(L_KNEE, R_KNEE):
        knees = [angle(P(L_HIP), P(L_KNEE), P(L_ANKLE)), angle(P(R_HIP), P(R_KNEE), P(R_ANKLE))]
        if min(knees) < 160:
            return {"problem": "body_not_straight"}
    sh_y = (P(L_SHOULDER)[1] + P(R_SHOULDER)[1]) / 2
    ny = P(NOSE)[1]
    top = head_top(mask, lm, w, h) if mask is not None else None
    top_y = top[1] if top else ny - 0.78 * (sh_y - ny)          # head top ~0.78 x nose-to-shoulders above the nose
    ext = body_extent(mask, lm, w, h) if mask is not None else None
    if ext:
        sole_y = ext["bottom"]
    else:
        sole_y = max([P(i)[1] for i in (L_HEEL, R_HEEL, L_FOOT, R_FOOT) if lm[i][2] >= 0.5] or [P(L_ANKLE)[1], P(R_ANKLE)[1]])
    if top_y <= 1 or sole_y >= h - 2:
        return {"problem": "body_not_whole"}
    px = sole_y - top_y
    ipd_px = math.dist(P(L_EYE), P(R_EYE))
    sh_px = math.dist(P(L_SHOULDER), P(R_SHOULDER))
    if ipd_px < 4 or sh_px < 12 or px < 0.25 * h:
        return {"problem": "body_too_far"}
    if sh_px < 0.13 * px:                                       # shoulders look narrow: turned side-on
        return {"problem": "body_face_camera"}
    by_eyes = px * _by_age(IPD_BY_AGE, IPD_ADULT, age, sex) / ipd_px
    by_shoulders = px * _by_age(SHOULDER_BY_AGE, SHOULDER_ADULT, age, sex) / sh_px
    est = (0.9 * by_eyes + 0.7 * by_shoulders) / 1.6            # the original estimator's weights
    if not 70 <= est <= 230:
        return {"problem": "body_unsure"}
    return {"height_cm": float(est), "by_eyes": float(by_eyes), "by_shoulders": float(by_shoulders)}


PROBLEM_TEXT = {
    "no_reference": "Can't see the FLOOR sheet - stand it on the floor against the wall next to your heels, fully in view",
    "no_top_reference": "Now tape the TOP sheet on the wall anywhere above your head (no measuring needed)",
    "reference_mismatch": "The two sheets don't match - print both at 100 % (actual size) and tape them flat",
    "no_person": "Step into the camera view",
    "not_whole_body": "Head and feet must both be visible - move the camera back or tilt it",
    "not_straight": "Stand tall with straight knees - heels, back and head against the wall",
    "marker_not_on_floor": "Put the FLOOR sheet on the floor against the wall, right next to your heels",
    "no_mask": "Body outline not available - update MediaPipe or use another browser/camera",
    "no_outline": "Can't see your outline clearly - stand against a plain wall, no bag or loose clothes",
    "body_not_whole": "Step back - your head and feet must both be in the picture",
    "body_not_straight": "Stand straight, feet together, arms down",
    "body_too_far": "Come a little closer to the camera",
    "body_face_camera": "Face the camera",
    "body_unsure": "Hold still - can't read your size yet",
}


# ------------------------------------------------------------------ the camera test

class HeightWeight(Exercise):
    key, name, icon, category = "height_weight", "Height & Weight (BMI)", "📏", "body composition"
    khelo_india = True
    age_groups = "5+"
    metric, unit, higher_is_better = "height", "cm", True
    duration = 180
    camera = "front"
    needs_frames = True               # the server also passes the camera picture (for the wall reference)
    setup = ["Print the two DeepFit sheets (FLOOR and TOP) at 100 % - or use two plain A4 sheets (long side up) on a darker wall",
             "FLOOR sheet: cut on the dashed line, stand it on the floor against the wall and tape it flat",
             "TOP sheet: tape it on the same wall anywhere above your head, a little to the side - no measuring needed",
             "Stand next to the floor sheet: shoes and cap off, heels, back and head on the wall, hair flat",
             "Camera 2-3 m away at chest height - both sheets, your head and your feet in view"]
    counting = ("Height = floor (the FLOOR sheet) to the top of your head, from your outline. The two sheets give the exact "
                "picture-to-wall mapping in cm even if the camera is tilted, and the head top's distance from the wall is "
                "corrected. It finishes when 25 frames agree within ±0.5 cm (accuracy ≈ ±1 cm). "
                "Weight is read from your scale (photo) or typed.")
    form_cues = ["Stand tall, chin level", "Stay still for 3 seconds", "Hair flat, no cap, no shoes"]
    blind_adaptation = ["A helper tapes the sheet and guides the athlete to the wall; spoken 'hold still' and the result"]
    deaf_adaptation = ["Big captions for each step; green flash when measured"]

    def __init__(self, **kw):
        super().__init__(**kw)
        self.samples: List[float] = []
        self.ref: Optional[Dict] = None               # {"kind", "floor", "top"} - what the camera found on the wall
        self.fit_rms: Optional[float] = None
        self.stable: Optional[Dict] = None
        self.weight_kg: Optional[float] = None
        self.weight_source: Optional[str] = None
        self.weight_detail: Optional[Dict] = None
        self.age = None
        self.problems: Dict[str, int] = {}
        self.camera: Optional[Dict] = None
        self.sex: Optional[str] = None
        self.body_samples: List[float] = []        # no sheets: estimates from the body's own proportions
        self.body_parts: List = []
        self.body: Optional[Dict] = None

    def configure(self, weight_kg=None, weight_source=None, weight_detail=None, age=None, sex=None, **_):
        try:
            if weight_kg is not None and 10 <= float(weight_kg) <= 250:
                self.weight_kg = round(float(weight_kg), 1)
                self.weight_source = weight_source if weight_source in ("scale_photo", "typed") else "typed"
        except (TypeError, ValueError):
            pass
        self.weight_detail = weight_detail if isinstance(weight_detail, dict) else None
        self.age = age
        self.sex = _sex(sex)

    def process(self, pose, t):
        if self.stable is None:
            self.feedback = self.feedback or "Stand against the wall next to the floor sheet"

    def feed_frame(self, bgr, landmarks, mask, t):
        """Called by the server with the camera picture, the landmarks (pose_backend) and the person mask."""
        if self.finished:
            return
        lm = [(p.x, p.y, getattr(p, "visibility", 1.0)) for p in landmarks.landmark] if landmarks is not None else None
        m = measure(bgr, lm, mask)
        if m.get("refs"):
            self.ref = m["refs"]
        if "problem" in m:
            if m["problem"] == "no_reference" and not self.samples:     # no sheets on the wall: estimate from the body
                self._body_frame(lm, mask, bgr.shape[1], bgr.shape[0])
                return
            self.problems[m["problem"]] = self.problems.get(m["problem"], 0) + 1
            self.feedback = PROBLEM_TEXT[m["problem"]]
            return
        self.samples.append(m["height_cm"])
        self.camera = m.get("camera")
        self.fit_rms = m.get("fit_rms_cm")
        st = stable_value(self.samples)
        if st:
            self.stable = st
            self.finished = True
            self.feedback = f"Measured: {st['height_cm']} cm"
            self.event("rep", f"{st['height_cm']} centimetres")
        else:
            self.feedback = f"Hold still… measuring ({min(len(self.samples), NEED_SAMPLES)}/{NEED_SAMPLES})"

    # ---- no sheets: "just stand"
    def _body_frame(self, lm, mask, w, h):
        e = body_estimate(lm, mask, w, h, self.age, self.sex)
        if "problem" in e:
            self.problems[e["problem"]] = self.problems.get(e["problem"], 0) + 1
            self.feedback = PROBLEM_TEXT[e["problem"]]
            return
        self.body_samples = (self.body_samples + [e["height_cm"]])[-120:]
        self.body_parts = (self.body_parts + [(e["by_eyes"], e["by_shoulders"])])[-120:]
        n = len(self.body_samples)
        if n >= BODY_NEED:
            self._finish_body("auto")
        else:
            self.feedback = f"Stand still… measuring ({n}/{BODY_NEED}) - or say 'capture'"

    def _body_reading(self) -> Optional[Dict]:
        if len(self.body_samples) < BODY_MIN:
            return None
        v = sorted(self.body_samples[-BODY_NEED:])
        k = len(v) // 4
        mid = v[k:len(v) - k] or v
        est = median(v)
        parts = self.body_parts[-BODY_NEED:]
        by_eyes, by_sh = median(p[0] for p in parts), median(p[1] for p in parts)
        spread = (mid[-1] - mid[0]) / 2
        # how well the two rulers agree and how steady the reading is (not an accuracy promise)
        agree = abs(by_eyes - by_sh) / est
        conf = int(max(20, min(90, round(92 - 250 * agree - 250 * spread / est))))
        return {"height_cm": round(est, 1), "spread_cm": round(spread, 1), "samples": len(v), "by_eyes_cm": round(by_eyes, 1),
                "by_shoulders_cm": round(by_sh, 1), "confidence": conf}

    def _finish_body(self, how: str):
        r = self._body_reading()
        if r is None:
            return
        self.body = {**r, "how": how}
        self.finished = True
        w = self.weight_kg or typical_weight(r["height_cm"], self.age, self.sex)
        self.feedback = f"Height ≈ {r['height_cm']:.0f} cm · weight ≈ {w:.0f} kg"
        self.event("rep", f"About {r['height_cm']:.0f} centimetres")

    def capture(self) -> Optional[str]:
        """'capture' (said aloud, or the S key): measure now with what the camera has seen. Returns a problem, or None."""
        if self.finished:
            return None
        if self.samples:                                   # sheets on the wall: take the median so far
            if len(self.samples) < 5:
                return "Hold still a moment longer - then say 'capture' again"
            v = sorted(self.samples[-NEED_SAMPLES * 2:])
            k = len(v) // 4
            mid = v[k:len(v) - k] or v
            self.stable = {"height_cm": round(median(v), 1), "spread_cm": round((mid[-1] - mid[0]) / 2, 2), "samples": len(v)}
            self.finished = True
            self.feedback = f"Measured: {self.stable['height_cm']} cm"
            self.event("rep", f"{self.stable['height_cm']} centimetres")
            return None
        if len(self.body_samples) >= BODY_MIN:
            self._finish_body("capture")
            return None
        return "Stand in full view (head to feet) and hold still, then say 'capture' again"

    def live(self) -> Dict:
        """What the screen shows while measuring: height, weight and how steady the reading is."""
        if self.stable or len(self.samples) >= 3:
            hv = self.stable["height_cm"] if self.stable else round(median(self.samples[-9:]), 1)
            return {"mode": "sheets", "height_cm": hv, "weight_kg": self.weight_kg, "weight_estimated": False,
                    "confidence": 99 if self.stable else min(95, 50 + 2 * len(self.samples)),
                    "samples": len(self.samples), "need": NEED_SAMPLES}
        r = self.body or self._body_reading()
        if r is None and self.body_samples:
            r = {"height_cm": round(median(self.body_samples), 1), "confidence": 20}
        if r is None:
            return {"mode": "body", "height_cm": None, "weight_kg": None, "confidence": 0, "samples": 0, "need": BODY_NEED}
        wv = self.weight_kg or typical_weight(r["height_cm"], self.age, self.sex)
        return {"mode": "body", "height_cm": r["height_cm"], "weight_kg": wv, "weight_estimated": not self.weight_kg,
                "confidence": r["confidence"], "samples": len(self.body_samples), "need": BODY_NEED}

    def value(self) -> float:
        if self.stable:
            return self.stable["height_cm"]
        if self.body:
            return self.body["height_cm"]
        return round(median(self.samples), 1) if len(self.samples) >= 5 else 0.0

    def stats(self):
        s = super().stats()
        ref = self.ref or {}
        s["height"] = {"samples": len(self.samples), "need": NEED_SAMPLES, "reference": ref.get("kind") if ref.get("floor") else None,
                       "floor": bool(ref.get("floor")), "top": bool(ref.get("top")),
                       "live_cm": round(median(self.samples[-9:]), 1) if self.samples else None}
        s["live"] = self.live()
        return s

    def result(self):
        if not self.stable and not self.body and not self.samples and len(self.body_samples) >= BODY_MIN:
            self._finish_body("time up")                  # time ran out: use what was seen
        if self.body and not self.stable:
            return self._body_result()
        r = super().result()
        h = self.value() or None
        r.update({"height_cm": h, "weight_kg": self.weight_kg, "weight_source": self.weight_source,
                  "weight_detail": self.weight_detail, **bmi_info(h, self.weight_kg, self.age),
                  "measurement": {"reference": (self.ref or {}).get("kind"),
                                  "reference_px": ((self.ref or {}).get("floor") or {}).get("size_px"),
                                  "sheets": [k for k in ("floor", "top") if (self.ref or {}).get(k)],
                                  "fit_rms_cm": round(self.fit_rms, 2) if self.fit_rms is not None else None,
                                  "samples": len(self.samples), "spread_cm": (self.stable or {}).get("spread_cm"),
                                  "stable": bool(self.stable), "problems": self.problems,
                                  "camera_distance_cm": round(self.camera["dist"]) if self.camera else None,
                                  "camera_height_cm": round(self.camera["y"]) if self.camera else None,
                                  "method": "floor + top reference sheets, head-top outline (MediaPipe), parallax-corrected"}})
        if not self.stable:
            r["incomplete"] = True
        return r


    def _body_result(self):
        r = super().result()
        b = self.body
        real = self.weight_kg is not None
        w = self.weight_kg if real else typical_weight(b["height_cm"], self.age, self.sex)
        r.update({"height_cm": b["height_cm"], "weight_kg": w, "weight_source": self.weight_source if real else "estimate",
                  "weight_detail": self.weight_detail,
                  **(bmi_info(b["height_cm"], w, self.age) if real else
                     {"bmi": None, "bmi_category": None,
                      "bmi_note": "Height and weight are estimates from your body. BMI needs your weight from a scale."}),
                  "estimate": True,
                  "measurement": {"reference": "body", "estimate": True, "uncertainty_cm": BODY_UNCERTAINTY_CM,
                                  "samples": b["samples"], "spread_cm": b["spread_cm"], "stable": True,
                                  "confidence": b["confidence"], "by_eyes_cm": b["by_eyes_cm"],
                                  "by_shoulders_cm": b["by_shoulders_cm"], "how": b["how"], "problems": self.problems,
                                  "method": "estimated from body proportions (eye spacing and shoulder width), no wall sheets; "
                                            "weight = typical for that height and age"}})
        r.pop("incomplete", None)
        return r


# ------------------------------------------------------------------ still photos (phone app)

def measure_photos(images: List[np.ndarray], backend=None) -> Dict:
    """Height from a few still photos (phone app): each photo measured, then combined."""
    from pose_backend import PoseBackend
    pb = backend or PoseBackend(segmentation=True, complexity=1, still_images=True)
    values, problems, ref_kind = [], {}, None
    try:
        for img in images[:8]:
            lms, mask = pb.process(img)
            lm = [(p.x, p.y, getattr(p, "visibility", 1.0)) for p in lms.landmark] if lms is not None else None
            m = measure(img, lm, mask)
            if (m.get("refs") or {}).get("floor"):
                ref_kind = m["refs"]["kind"]
            if "problem" in m:
                problems[m["problem"]] = problems.get(m["problem"], 0) + 1
            else:
                values.append(m["height_cm"])
    finally:
        if backend is None:
            pb.close()
    if not values:
        top = max(problems, key=problems.get) if problems else "no_person"
        return {"ok": False, "problem": top, "message": PROBLEM_TEXT[top], "reference": ref_kind}
    v = sorted(values)
    spread = (v[-1] - v[0]) / 2
    return {"ok": spread <= 1.0, "height_cm": round(median(v), 1), "spread_cm": round(spread, 2), "photos_used": len(v),
            "reference": ref_kind, "message": None if spread <= 1.0 else "Photos disagree - stand still and measure again"}


def marker_svg(role: str = "floor") -> str:
    """A printable code as SVG, sized in centimetres (print at 100 %). role: "floor" or "top"."""
    img = cv2.aruco.generateImageMarker(cv2.aruco.getPredefinedDictionary(MARKER_DICT), MARKER_IDS[role], 6)   # 6 x 6 cells
    cell = MARKER_CM / 6
    rects = "".join(f'<rect x="{c * cell:.4f}" y="{r * cell:.4f}" width="{cell + 0.002:.4f}" height="{cell + 0.002:.4f}"/>'
                    for r in range(6) for c in range(6) if img[r, c] < 128)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{MARKER_CM}cm" height="{MARKER_CM}cm" '
            f'viewBox="0 0 {MARKER_CM} {MARKER_CM}" shape-rendering="crispEdges">'
            f'<rect width="{MARKER_CM}" height="{MARKER_CM}" fill="#fff"/><g fill="#000">{rects}</g></svg>')


def register():
    import exercise_engine as EE
    EE.add_exercise(HeightWeight)


register()
