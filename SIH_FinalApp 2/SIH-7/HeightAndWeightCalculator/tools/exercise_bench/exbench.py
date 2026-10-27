"""Realistic stress test for every camera exercise in exercise_engine.py.

A 3-D stick person (body proportions from Drillis & Contini, +-4 % per person, height 125-190 cm) does each
exercise with human variation (speed, depth, pauses, bad reps, cheats). A pinhole phone camera (portrait or
landscape, 2-4 m, up to +-25 deg off the ideal angle, different heights) films it, and MediaPipe-like errors
are added: jitter that is correlated in time, low confidence on the hidden side, dropped frames, one-frame
glitches, left/right swaps, uneven frame rate. The engine never sees the truth; we compare its answer to it.

    python3 exbench.py [trials] [exercise ...]
"""
import math, random, sys, os, json, zlib
from statistics import mean
import numpy as np

sys.path.insert(0, os.environ.get("ENGINE_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")))
import exercise_engine as E

# ------------------------------------------------------------------ body
NAMES = {0: "nose", 2: "leye", 5: "reye", 7: "lear", 8: "rear", 9: "mouthl", 10: "mouthr",
         11: "lsh", 12: "rsh", 13: "lel", 14: "rel", 15: "lwr", 16: "rwr", 17: "lpinky", 18: "rpinky",
         19: "lindex", 20: "rindex", 21: "lthumb", 22: "rthumb", 23: "lhip", 24: "rhip", 25: "lkn", 26: "rkn",
         27: "lan", 28: "ran", 29: "lheel", 30: "rheel", 31: "lfoot", 32: "rfoot"}
EXTREMITY = {15, 16, 17, 18, 19, 20, 21, 22, 27, 28, 29, 30, 31, 32}
PARTNER = {a: b for a, b in [(2, 5), (7, 8), (9, 10), (11, 12), (13, 14), (15, 16), (17, 18), (19, 20), (21, 22),
                             (23, 24), (25, 26), (27, 28), (29, 30), (31, 32)]}
PARTNER.update({b: a for a, b in list(PARTNER.items())})


class Body:
    def __init__(self, rnd: random.Random, height=None):
        self.H = height or rnd.uniform(125, 190)
        j = lambda: rnd.uniform(0.96, 1.04)
        H = self.H
        self.upper, self.fore, self.hand = 0.186 * H * j(), 0.146 * H * j(), 0.10 * H * j()
        self.thigh, self.shank = 0.245 * H * j(), 0.246 * H * j()
        self.torso = 0.288 * H * j()             # hip joint -> shoulder joint
        self.neck = 0.105 * H * j()              # shoulder -> nose
        self.ank_h, self.foot = 0.039 * H, 0.15 * H * j()
        self.sw, self.hw = 0.22 * H * j(), 0.13 * H * j()     # shoulder / hip landmark spacing


def put(P, side_pts, z_half):
    """side_pts: {'sh': (x, y), ...} in the body's sagittal plane -> both sides in 3-D (x fwd, y up, z left)."""
    for k, (x, y) in side_pts.items():
        P["l" + k] = np.array([x, y, z_half.get(k, 0.0)])
        P["r" + k] = np.array([x, y, -z_half.get(k, 0.0)])


def ik2(a, b, L1, L2, bend_dir):
    """2-segment chain from point a to point b (2-D); returns the middle joint, bent towards bend_dir side."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    d = np.linalg.norm(b - a)
    d = min(max(d, abs(L1 - L2) + 1e-6), L1 + L2 - 1e-6)
    u = (b - a) / max(np.linalg.norm(b - a), 1e-9)
    x = (L1 * L1 - L2 * L2 + d * d) / (2 * d)
    h = math.sqrt(max(L1 * L1 - x * x, 0.0))
    n = np.array([-u[1], u[0]])
    if np.dot(n, bend_dir) < 0:
        n = -n
    return a + u * x + n * h


def face_and_hands(P, B, fwd=np.array([1.0, 0, 0])):
    """Nose/eyes/ears near the head; pinky/index/thumb near the wrists, pointing along the forearm."""
    sh_mid = (P["lsh"] + P["rsh"]) / 2
    if "nose" not in P:
        P["nose"] = sh_mid + np.array([0.03 * B.H, B.neck, 0]) if fwd[0] else sh_mid + np.array([0, B.neck, 0])
    n = P["nose"]
    for k, dz in (("leye", 0.03), ("reye", -0.03), ("lear", 0.07), ("rear", -0.07), ("mouthl", 0.02), ("mouthr", -0.02)):
        P[k] = n + np.array([-0.02 * B.H if "ear" in k else 0, 0.01 * B.H if "eye" in k else (-0.02 * B.H if "mouth" in k else 0), dz * B.H])
    for s in "lr":
        w, e = P[s + "wr"], P[s + "el"]
        u = (w - e) / max(np.linalg.norm(w - e), 1e-9)
        P[s + "index"] = w + u * 0.45 * B.hand
        P[s + "pinky"] = w + u * 0.4 * B.hand + np.array([0, 0, 0.02 * B.H * (1 if s == "l" else -1)])
        P[s + "thumb"] = w + u * 0.25 * B.hand + np.array([0, 0, -0.02 * B.H * (1 if s == "l" else -1)])
    for s in "lr":
        a = P[s + "an"]
        if s + "heel" not in P:
            P[s + "heel"] = a + np.array([-0.04 * B.H, -0.02 * B.H, 0])
        if s + "foot" not in P:
            P[s + "foot"] = a + np.array([0.11 * B.H, -0.035 * B.H, 0])


# ------------------------------------------------------------------ camera + MediaPipe-like errors
class Camera:
    def __init__(self, rnd, view, target, extent, yaw_max=25, portrait=None):
        self.portrait = rnd.random() < 0.6 if portrait is None else portrait
        self.W, self.Hh = (480, 640) if self.portrait else (640, 480)
        vfov = math.radians(62 if self.portrait else 48)
        self.f = (self.Hh / 2) / math.tan(vfov / 2)
        fill = rnd.uniform(0.55, 0.85)                        # how much of the frame the body fills
        span_px = fill * (self.W if extent[1] == "x" else self.Hh)
        dist = self.f * extent[0] / span_px
        self.yaw = math.radians(rnd.uniform(-yaw_max, yaw_max))
        cam_h = rnd.uniform(-0.15, 0.25) * extent[0]          # camera a bit below / above the body centre
        base = {"side_l": np.array([0, 0, 1.0]), "side_r": np.array([0, 0, -1.0]), "front": np.array([1.0, 0, 0])}[view]
        c, s = math.cos(self.yaw), math.sin(self.yaw)
        d = np.array([base[0] * c + base[2] * s, 0, -base[0] * s + base[2] * c])
        self.pos = np.asarray(target, float) + d * dist + np.array([0, cam_h, 0])
        fwd = np.asarray(target, float) - self.pos
        fwd /= np.linalg.norm(fwd)
        right = np.cross(fwd, np.array([0, 1.0, 0])); right /= np.linalg.norm(right)
        up = np.cross(right, fwd)
        self.R = np.stack([right, up, fwd])
        self.roll = math.radians(rnd.uniform(-4, 4))
        self.view = view

    def project(self, X):
        p = self.R @ (np.asarray(X) - self.pos)
        x, y = self.f * p[0] / p[2], -self.f * p[1] / p[2]
        cr, sr = math.cos(self.roll), math.sin(self.roll)
        x, y = x * cr - y * sr, x * sr + y * cr
        return (x + self.W / 2) / self.W, (y + self.Hh / 2) / self.Hh, p[2]


class Noise:
    def __init__(self, rnd, level=1.0):
        self.rnd = rnd
        self.sigma = rnd.uniform(0.004, 0.011) * level      # of the body's size in the image
        self.rho = 0.55
        self.state = {}
        self.p_drop, self.p_burst = rnd.uniform(0.005, 0.03) * level, 0.004 * level
        self.p_glitch, self.p_swap = 0.004 * level, 0.002 * level
        self.burst = 0
        self.glitch = {}
        self.swap = 0
        self.vis_base = {}

    def apply(self, pts2d, depth, cam, body_px):
        """pts2d: {idx: (x, y)} normalised; returns MediaPipe-like list of 33 [x, y, vis] or None."""
        r = self.rnd
        if self.burst > 0:
            self.burst -= 1
            return None
        if r.random() < self.p_burst:
            self.burst = r.randint(3, 10)
            return None
        if r.random() < self.p_drop:
            return None
        out = []
        sx, sy = body_px / cam.W, body_px / cam.Hh
        zs = [depth[i] for i in range(33)]
        zmin, zmax = min(zs), max(zs)
        for i in range(33):
            x, y = pts2d[i]
            k = 1.6 if i in EXTREMITY else 1.0
            ex, ey = self.state.get(i, (0.0, 0.0))
            a = math.sqrt(1 - self.rho ** 2)
            ex = self.rho * ex + a * r.gauss(0, self.sigma * k * sx)
            ey = self.rho * ey + a * r.gauss(0, self.sigma * k * sy)
            self.state[i] = (ex, ey)
            x, y = x + ex, y + ey
            if i in self.glitch:
                gx, gy, n = self.glitch[i]
                x, y = x + gx, y + gy
                self.glitch[i] = (gx, gy, n - 1)
                if n <= 1:
                    del self.glitch[i]
            elif r.random() < self.p_glitch:
                self.glitch[i] = (r.uniform(-0.15, 0.15), r.uniform(-0.15, 0.15), r.randint(1, 2))
            # confidence: lower for the far side in side views, very low outside the frame
            if i not in self.vis_base:
                self.vis_base[i] = (r.uniform(0.85, 0.99), r.uniform(0.45, 1.0))   # (normal, hidden-side factor)
            v, hidden = self.vis_base[i]
            j = PARTNER.get(i)
            if cam.view != "front" and j is not None and depth[i] > depth[j] + 3.0:
                v *= hidden                                  # the far side of the body: lower, but steady, confidence
            if not (-0.02 <= x <= 1.02 and -0.02 <= y <= 1.02):
                v = min(v, r.uniform(0.05, 0.35))
            v = min(1.0, max(0.0, v + r.gauss(0, 0.04)))
            out.append([x, y, v])
        if self.swap > 0 or r.random() < self.p_swap:     # left/right confusion for a few frames
            self.swap = self.swap - 1 if self.swap > 0 else r.randint(1, 3)
            for a_, b_ in ((13, 14), (15, 16), (25, 26), (27, 28)):
                out[a_], out[b_] = out[b_], out[a_]
        return out


def film(rnd, frames_fn, T, view, target, extent, fps=None, noise=1.0, yaw_max=25, portrait=None):
    """Render poses at an uneven frame rate. frames_fn(t) -> dict of 3-D joints. Yields (t, landmarks, cam)."""
    cam = Camera(rnd, view, target, extent, yaw_max=yaw_max, portrait=portrait)
    nz = Noise(rnd, noise)
    fps = fps or rnd.choice([10, 12, 15, 20, 24, 30])
    t, out = 0.0, []
    body_px = None
    while t <= T:
        P = frames_fn(t)
        proj, depth = {}, {}
        for i, nm in NAMES.items():
            x, y, z = cam.project(P[nm])
            proj[i], depth[i] = (x, y), z
        for i in range(33):
            if i not in proj:
                proj[i], depth[i] = proj[0], depth[0]
        if body_px is None:
            ys = [proj[i][1] * cam.Hh for i in (0, 27, 28)]
            xs = [proj[i][0] * cam.W for i in (0, 27, 28, 11, 23)]
            body_px = max(max(ys) - min(ys), max(xs) - min(xs), 50)
        out.append((t, nz.apply(proj, depth, cam, body_px)))
        t += (1 / fps) * rnd.uniform(0.8, 1.25)
    return out, cam


def run_engine(ex, seq, cam):
    for t, lm in seq:
        ex.update(E.Pose(lm, cam.W, cam.Hh) if lm is not None else None, t)
        if ex.finished:
            break
    return ex


def smooth(x):            # 0..1 -> 0..1 ease in/out
    x = min(1.0, max(0.0, x))
    return x * x * (3 - 2 * x)


def schedule(rnd, reps, dur, rest, make_rep):
    """List of (t0, t1, params) for each rep."""
    out, t = [], rnd.uniform(1.0, 2.0)
    for k in range(len(reps)):
        d = rnd.uniform(*dur)
        out.append((t, t + d, reps[k]))
        t += d + rnd.uniform(*rest)
    return out, t + rnd.uniform(1.0, 2.0)


def value_at(t, sched, rest_val, f):
    for t0, t1, p in sched:
        if t0 <= t <= t1:
            return f(p, (t - t0) / (t1 - t0))
    return rest_val


def updown(lo, hi, x, hold=0.15):
    """lo -> hi -> lo over x in 0..1 with a short hold at hi."""
    a = (1 - hold) / 2
    if x < a:
        return lo + (hi - lo) * smooth(x / a)
    if x < a + hold:
        return hi
    return hi + (lo - hi) * smooth((x - a - hold) / a)


# ------------------------------------------------------------------ exercises
def lying_torso(B, theta, arms="chest"):
    """Sit-up / curl-up: lying on the back, side view. Hip at x=0, head towards +x, feet towards -x."""
    th = math.radians(theta)
    hip = np.array([0.0, 0.07 * B.H])
    sh = hip + B.torso * np.array([math.cos(th), math.sin(th)])
    nose = sh + B.neck * np.array([math.cos(th + math.radians(25)), math.sin(th + math.radians(25))]) * 0.9
    an = np.array([-0.45 * B.H, B.ank_h])
    kn = ik2(hip, an, B.thigh, B.shank, np.array([0, 1.0]))
    u = (hip - sh) / np.linalg.norm(hip - sh)
    nrm = np.array([-u[1], u[0]]) if u[0] < 0 else np.array([u[1], -u[0]])
    if arms == "chest":
        el = sh + u * 0.10 * B.H + np.array([0, 0.05 * B.H])
        wr = sh + u * 0.02 * B.H + np.array([0, 0.06 * B.H])
    else:                                     # arms straight along the floor / reaching to the knees
        el = sh + u * B.upper * 0.95 + np.array([0, 0.01 * B.H])
        wr = el + u * B.fore
    P = {}
    put(P, {"sh": sh, "el": el, "wr": wr, "hip": hip, "kn": kn, "an": an},
        {"sh": B.sw / 2, "el": B.sw / 2 + 0.02 * B.H, "wr": B.sw / 2 - 0.03 * B.H, "hip": B.hw / 2, "kn": B.hw / 2, "an": 0.06 * B.H})
    P["nose"] = np.array([nose[0], nose[1], 0.0])
    face_and_hands(P, B)
    return P


def plank_line(B, elbow_deg=None, forearm=False, sag_deg=0.0, knees=False):
    """Push-up / plank, side view. Toes (or knees) at x=0, head towards +x."""
    a, b = B.upper, B.fore
    if knees:
        base = np.array([0.0, 0.05 * B.H]); L = B.torso + 0.03 * B.H + B.thigh * 0.98
    else:
        base = np.array([0.0, 0.06 * B.H]); L = B.torso + B.thigh + B.shank * 0.98
    if forearm:
        el = None
        sh_y = 0.03 * B.H + a
        sh = np.array([math.sqrt(max(L * L - (sh_y - base[1]) ** 2, 1)), sh_y])
        elb = np.array([sh[0], 0.03 * B.H]); wr = elb + np.array([b, 0.0])
    else:
        d_top = math.sqrt(a * a + b * b - 2 * a * b * math.cos(math.radians(172)))
        wy = 0.03 * B.H
        wx = math.sqrt(max(L * L - (wy + d_top - base[1]) ** 2, 1))
        wr = np.array([wx, wy])
        d = math.sqrt(a * a + b * b - 2 * a * b * math.cos(math.radians(elbow_deg)))
        sh = ik2(base, wr, L, d, np.array([0, 1.0]))        # shoulder: L from the toes, d from the wrist
        elb = ik2(sh, wr, a, b, np.array([-1.0, 0.2]))       # elbows point back towards the feet
    # hip on the body line; sag pulls it down (angle at the hip = 180 - 2*sag roughly)
    hip_frac = (B.thigh + B.shank) / (L if not knees else L) if not knees else B.thigh * 0.98 / L
    hip = base + (sh - base) * hip_frac
    u = (sh - base) / np.linalg.norm(sh - base)
    nrm = np.array([-u[1], u[0]])
    hip = hip - nrm * math.tan(math.radians(sag_deg)) * min(np.linalg.norm(hip - base), np.linalg.norm(sh - hip))
    if knees:
        kn = base
        an = kn + B.shank * np.array([-math.cos(math.radians(35)), math.sin(math.radians(35))])
    else:
        kn = base + (hip - base) * (B.shank / (B.thigh + B.shank))
        an = base
    nose = sh + B.neck * 0.9 * np.array([math.cos(math.radians(-5)), math.sin(math.radians(-5))]) * np.array([1, 1])
    nose = nose + np.array([0, 0.03 * B.H])
    P = {}
    put(P, {"sh": sh, "el": elb, "wr": wr, "hip": hip, "kn": kn, "an": an},
        {"sh": B.sw / 2, "el": B.sw / 2 + 0.04 * B.H, "wr": B.sw / 2 + 0.01 * B.H, "hip": B.hw / 2, "kn": B.hw / 2, "an": 0.07 * B.H})
    P["nose"] = np.array([nose[0], nose[1], 0.0])
    if not knees:
        for s in "lr":
            P[s + "heel"] = P[s + "an"] + np.array([-0.03 * B.H, 0.02 * B.H, 0])
            P[s + "foot"] = P[s + "an"] + np.array([0.03 * B.H, -0.05 * B.H, 0])
    face_and_hands(P, B)
    return P


def standing(B, knee=178.0, lean=4.0, hip_lift=0.0, ank_x=0.0, ank_y=None, arms="side", arm_ang=0.0,
             stance=None, lift_foot=None):
    """Side-plane standing figure (x forward). knee = knee angle, lean = torso lean from vertical (deg)."""
    ay = B.ank_h if ank_y is None else ank_y
    an = np.array([ank_x, ay])
    kd = math.radians(180 - knee)
    if knee >= 179.5:
        hip = an + np.array([0, B.shank + B.thigh])
        kn = an + np.array([0, B.shank])
    else:
        # shank leans forward, thigh back so the hip stays over the mid-foot
        d = math.sqrt(B.thigh ** 2 + B.shank ** 2 - 2 * B.thigh * B.shank * math.cos(math.radians(knee)))
        hip = an + np.array([-0.15 * d * math.sin(kd), d])
        hip[0] = an[0] - 0.25 * (B.thigh + B.shank - d)
        hip = an + (hip - an) / np.linalg.norm(hip - an) * d
        kn = ik2(an, hip, B.shank, B.thigh, np.array([1.0, 0]))
    hip = hip + np.array([0, hip_lift])
    if hip_lift:
        kn = kn + np.array([0, hip_lift]); an = an + np.array([0, hip_lift])
    lr = math.radians(lean)
    sh = hip + B.torso * np.array([math.sin(lr), math.cos(lr)])
    nose = sh + np.array([0.03 * B.H + B.neck * math.sin(lr) * 0.5, B.neck * math.cos(lr * 0.7)])
    if arms == "forward":
        el = sh + np.array([B.upper, 0]); wr = el + np.array([B.fore, 0])
    elif arms == "swing":
        ang = math.radians(arm_ang)        # 0 = hanging, +ve = forward/up, -ve = back
        el = sh + B.upper * np.array([math.sin(ang), -math.cos(ang)])
        wr = el + B.fore * np.array([math.sin(ang), -math.cos(ang)])
    else:
        el = sh + np.array([0, -B.upper]); wr = el + np.array([0.02 * B.H, -B.fore])
    P = {}
    zh = {"sh": B.sw / 2, "el": B.sw / 2 + 0.02 * B.H, "wr": B.sw / 2 + 0.02 * B.H, "hip": B.hw / 2, "kn": B.hw / 2,
          "an": (stance if stance is not None else 0.06 * B.H) / 2}
    put(P, {"sh": sh, "el": el, "wr": wr, "hip": hip, "kn": kn, "an": an}, zh)
    P["nose"] = np.array([nose[0], nose[1], 0.0])
    if lift_foot:
        s, up = lift_foot
        P[s + "an"] = P[s + "an"] + np.array([-0.12 * B.H * min(1, up / (0.2 * B.H)), up, 0])
        P[s + "kn"] = P[s + "kn"] + np.array([0.05 * B.H * min(1, up / (0.2 * B.H)), up * 0.35, 0])
    face_and_hands(P, B)
    return P


def front_figure(B, arm_abd=10.0, feet=0.1, bounce=0.0, flex=(0.0, 0.0), sway=0.0, lift=None, hand=None):
    """Front-facing figure: z is the person's left. arm_abd = arm angle from the body (deg),
    feet = ankle spacing (fraction of H), flex = elbow flexion per arm (deg, forearm forward/up)."""
    H = B.H
    hip_y = B.thigh + B.shank + B.ank_h + bounce
    P = {}
    for s, sg in (("l", 1), ("r", -1)):
        hip = np.array([0.0, hip_y, sg * B.hw / 2 + sway])
        an = np.array([0.0, B.ank_h + bounce, sg * feet * H / 2 + sway * 0.2])
        kn = hip + (an - hip) * (B.thigh / (B.thigh + B.shank))
        sh = np.array([0.0, hip_y + B.torso, sg * B.sw / 2 + sway])
        a = math.radians(arm_abd)
        el = sh + B.upper * np.array([0.0, -math.cos(a), sg * math.sin(a)])
        fl = math.radians(flex[0] if s == "l" else flex[1])
        if arm_abd < 30 and fl > 0:            # curl: forearm rotates forward and up in front of the body
            el = sh + np.array([0.02 * H, -B.upper, sg * 0.01 * H])
            wr = el + B.fore * np.array([math.sin(fl), -math.cos(fl), 0])
        else:
            wr = el + B.fore * np.array([0.0, -math.cos(a), sg * math.sin(a)])
        P[s + "sh"], P[s + "el"], P[s + "wr"], P[s + "hip"], P[s + "kn"], P[s + "an"] = sh, el, wr, hip, kn, an
    P["nose"] = np.array([0.04 * H, hip_y + B.torso + B.neck, sway])
    if lift:
        s, up = lift
        P[s + "an"] = P[s + "an"] + np.array([-0.15 * H, up, 0])
        P[s + "kn"] = P[s + "kn"] + np.array([0.04 * H, up * 0.3, 0])
    if hand is not None:                        # plate tapping: right wrist at a 3-D point
        P["rwr"] = hand
        P["rel"] = (P["rsh"] + hand) / 2 + np.array([0.02 * H, -0.03 * H, 0])
    face_and_hands(P, B)
    for s in "lr":
        P[s + "heel"] = P[s + "an"] + np.array([-0.04 * H, -0.02 * H, 0])
        P[s + "foot"] = P[s + "an"] + np.array([0.1 * H, -0.035 * H, 0])
    return P


def view_side(rnd):
    return rnd.choice(["side_l", "side_r"])


# Each scenario returns (engine, seq, cam, truth, kind) where kind tells how to score.
def sc_situps(rnd, cheat=True):
    B = Body(rnd)
    n = rnd.randint(6, 14)
    reps = []
    for _ in range(n):
        r = rnd.random()
        if cheat and r < 0.15:
            reps.append(("half", rnd.uniform(25, 42), rnd.uniform(0, 8)))      # does not sit up -> no count
        else:
            reps.append(("ok", rnd.uniform(62, 85), rnd.uniform(0, 12)))
    sched, T = schedule(rnd, reps, (1.0, 2.4), (0.0, 0.8), None)
    fn = lambda t: lying_torso(B, value_at(t, sched, 3.0, lambda p, x: updown(p[2], p[1], x)))
    seq, cam = film(rnd, fn, T, view_side(rnd), (0.1 * B.H, 0.15 * B.H, 0), (1.0 * B.H, "x"))
    return E.SitUps(height_cm=B.H), seq, cam, sum(1 for r in reps if r[0] == "ok"), "count"


def sc_curlup(rnd):
    B = Body(rnd)
    n = rnd.randint(8, 16)
    reps = []
    for _ in range(n):
        r = rnd.random()
        if r < 0.1:
            reps.append(("full", rnd.uniform(68, 85)))         # full sit-up: not counted (fault)
        elif r < 0.2:
            reps.append(("tiny", rnd.uniform(5, 9)))           # barely lifts: not counted
        else:
            reps.append(("ok", rnd.uniform(30, 42)))
    sched, T = schedule(rnd, reps, (0.9, 2.0), (0.0, 0.6), None)
    fn = lambda t: lying_torso(B, value_at(t, sched, 2.0, lambda p, x: updown(2.0, p[1], x)), arms="floor")
    seq, cam = film(rnd, fn, T, view_side(rnd), (0.1 * B.H, 0.1 * B.H, 0), (1.0 * B.H, "x"))
    return E.PartialCurlUp(height_cm=B.H), seq, cam, sum(1 for r in reps if r[0] == "ok"), "count"


def sc_pushups(rnd, knees=False):
    B = Body(rnd)
    n = rnd.randint(6, 15)
    reps = []
    for _ in range(n):
        r = rnd.random()
        if r < 0.12:
            reps.append(("shallow", rnd.uniform(118, 138), rnd.uniform(0, 4)))   # not deep enough: no count
        elif r < 0.22:
            reps.append(("sag", rnd.uniform(60, 85), rnd.uniform(22, 30)))       # hips sag: invalid
        else:
            reps.append(("ok", rnd.uniform(60, 88), rnd.uniform(-3, 4)))
    top = rnd.uniform(162, 176)
    sched, T = schedule(rnd, reps, (1.0, 2.6), (0.0, 0.7), None)

    def fn(t):
        e = value_at(t, sched, top, lambda p, x: updown(top, p[1], x))
        sag = value_at(t, sched, 0.0, lambda p, x: p[2] * math.sin(math.pi * x) if p[0] == "sag" else p[2])
        return plank_line(B, elbow_deg=e, sag_deg=sag, knees=knees)
    seq, cam = film(rnd, fn, T, view_side(rnd), (0.45 * B.H, 0.2 * B.H, 0), (1.15 * B.H, "x"))
    ex = E.ModifiedPushUps(height_cm=B.H) if knees else E.PushUps(height_cm=B.H)
    return ex, seq, cam, sum(1 for r in reps if r[0] == "ok"), "count"


def sc_plank(rnd):
    B = Body(rnd)
    t_in = rnd.uniform(1.5, 3.0)                  # gets into position
    hold = rnd.uniform(15, 50)
    T = t_in + hold + 4.5

    def fn(t):
        if t < t_in:
            return plank_line(B, forearm=True, sag_deg=30 * (1 - t / t_in) + 10)
        if t < t_in + hold:
            return plank_line(B, forearm=True, sag_deg=2 * math.sin(t * 1.3) + rnd.uniform(-0.5, 0.5))
        return plank_line(B, forearm=True, sag_deg=min(30, 12 + 15 * (t - t_in - hold)))
    seq, cam = film(rnd, fn, T, view_side(rnd), (0.45 * B.H, 0.15 * B.H, 0), (1.15 * B.H, "x"))
    return E.Plank(height_cm=B.H), seq, cam, hold, "seconds"


def sc_squats(rnd):
    B = Body(rnd)
    n = rnd.randint(6, 14)
    reps = []
    for _ in range(n):
        r = rnd.random()
        if r < 0.12:
            reps.append(("shallow", rnd.uniform(118, 140), 15))
        elif r < 0.2:
            reps.append(("lean", rnd.uniform(65, 90), rnd.uniform(64, 75)))
        else:
            reps.append(("ok", rnd.uniform(65, 92), None))
    sched, T = schedule(rnd, reps, (1.2, 2.8), (0.0, 0.8), None)

    def fn(t):
        k = value_at(t, sched, 177.0, lambda p, x: updown(177, p[1], x, 0.1))
        lean_peak = value_at(t, sched, None, lambda p, x: p[2])
        depth = (177 - k) / 100
        lean = 6 + 45 * depth if lean_peak is None else 6 + (lean_peak - 6) * min(1, depth / max(0.01, (177 - 80) / 100))
        return standing(B, knee=k, lean=lean, arms="forward")
    seq, cam = film(rnd, fn, T, view_side(rnd), (0, 0.5 * B.H, 0), (1.05 * B.H, "y"))
    return E.Squats(height_cm=B.H), seq, cam, sum(1 for r in reps if r[0] == "ok"), "count"


def sc_jacks(rnd):
    B = Body(rnd)
    n = rnd.randint(10, 25)
    reps = []
    for _ in range(n):
        if rnd.random() < 0.1:
            reps.append(("half", rnd.uniform(70, 95), rnd.uniform(0.35, 0.5)))    # arms only to shoulders
        else:
            reps.append(("ok", rnd.uniform(150, 175), rnd.uniform(0.36, 0.6)))
    sched, T = schedule(rnd, reps, (0.55, 1.1), (0.0, 0.25), None)
    closed = rnd.uniform(0.06, 0.12)

    def fn(t):
        def f(p, x):
            k = updown(0, 1, x, 0.2)
            return (10 + (p[1] - 10) * k, closed + (p[2] - closed) * k, 0.03 * B.H * math.sin(math.pi * min(1, x * 2)))
        a, fe, b = value_at(t, sched, (10, closed, 0.0), f)
        return front_figure(B, arm_abd=a, feet=fe, bounce=b)
    seq, cam = film(rnd, fn, T, "front", (0, 0.6 * B.H, 0), (1.25 * B.H, "y"))
    return E.JumpingJacks(height_cm=B.H), seq, cam, sum(1 for r in reps if r[0] == "ok"), "count"


def sc_curls(rnd):
    B = Body(rnd)
    n = rnd.randint(6, 14)
    together = rnd.random() < 0.5
    reps = []
    for _ in range(n):
        r = rnd.random()
        bottom = rnd.uniform(0, 18)                 # flexion at the bottom: elbow 162-180
        if r < 0.12:
            reps.append(("partial", rnd.uniform(80, 100), bottom))   # stops half way: no count
        else:
            reps.append(("ok", rnd.uniform(130, 150), bottom))       # flexion -> elbow 30-50
    sched, T = schedule(rnd, reps, (1.2, 2.6), (0.0, 0.6), None)
    truth = sum(1 for r in reps if r[0] == "ok") * (2 if together else 1)

    def fn(t):
        idx = None
        for k, (t0, t1, p) in enumerate(sched):
            if t0 <= t <= t1:
                idx = k
                fl = updown(p[2], p[1], (t - t0) / (t1 - t0))
                break
        if idx is None:
            fl = 8.0
            return front_figure(B, flex=(fl, fl), sway=0)
        other = 8.0
        if together:
            return front_figure(B, flex=(fl, fl))
        return front_figure(B, flex=(fl, other) if idx % 2 == 0 else (other, fl))
    seq, cam = film(rnd, fn, T, "front", (0, 0.75 * B.H, 0), (0.7 * B.H, "y"), yaw_max=20)
    if not together:
        truth = sum(1 for r in reps if r[0] == "ok")
    return E.DumbbellCurls(height_cm=B.H), seq, cam, truth, "count"


def sc_vjump(rnd):
    B = Body(rnd)
    jumps = [rnd.uniform(20, 55) for _ in range(3)]
    g = 981.0
    ext = 0.05 * B.H                                  # hip rises this much at take-off (on the toes)
    segs, t = [], rnd.uniform(1.8, 3.0)
    for h in jumps:
        cm = rnd.uniform(10, 25)
        flight = 2 * math.sqrt(2 * max(h - ext, 2) / g)
        segs.append((t, cm, h, flight))
        t += 0.45 + 0.25 + flight + 0.9 + rnd.uniform(1.8, 3.2)
    T = t

    def fn(tt):
        sway = 0.3 * math.sin(tt * 2.1)
        for t0, cm, h, flight in segs:
            if t0 <= tt < t0 + 0.45:                       # counter-movement down
                d = cm * smooth((tt - t0) / 0.45)
                return standing(B, knee=178 - 2.2 * d, lean=6 + 0.8 * d, hip_lift=0, arms="swing", arm_ang=-40 * smooth((tt - t0) / 0.45))
            if t0 + 0.45 <= tt < t0 + 0.7:                 # drive up to take-off
                x = (tt - t0 - 0.45) / 0.25
                d = cm * (1 - smooth(x))
                return standing(B, knee=178 - 2.2 * d, lean=6, hip_lift=ext * smooth(x), arms="swing", arm_ang=-40 + 200 * x)
            if t0 + 0.7 <= tt < t0 + 0.7 + flight:         # flight
                x = (tt - t0 - 0.7) / flight
                up = ext + (h - ext) * 4 * x * (1 - x)
                return standing(B, knee=178, lean=3, hip_lift=up, arms="swing", arm_ang=160 - 60 * x)
            if t0 + 0.7 + flight <= tt < t0 + 0.7 + flight + 0.9:   # landing: absorb then stand
                x = (tt - t0 - 0.7 - flight) / 0.9
                d = 15 * math.sin(math.pi * min(1, x * 1.3))
                return standing(B, knee=178 - 2.2 * d, lean=6 + 0.6 * d, hip_lift=ext * max(0, 1 - x * 4), arms="swing", arm_ang=100 * (1 - x))
        return standing(B, knee=178, lean=4 + sway * 0.3, ank_x=sway * 0.2, arms="side")
    seq, cam = film(rnd, fn, T, view_side(rnd), (0, 0.6 * B.H, 0), (1.35 * B.H, "y"))
    return E.VerticalJump(height_cm=B.H), seq, cam, max(jumps), "cm"


def sc_broad(rnd):
    B = Body(rnd)
    dists = [rnd.uniform(90, 230) for _ in range(3)]
    segs, t = [], rnd.uniform(1.8, 3.0)
    for D in dists:
        flight = 0.35 + D / 900
        segs.append((t, D, flight))
        t += 0.4 + 0.25 + flight + 0.7 + rnd.uniform(1.2, 2.0) + 2.5 + rnd.uniform(1.8, 2.8)
    T = t

    def fn(tt):
        for t0, D, flight in segs:
            if t0 <= tt < t0 + 0.4:
                d = 18 * smooth((tt - t0) / 0.4)
                return standing(B, knee=178 - 2.4 * d, lean=10 + 1.5 * d, arms="swing", arm_ang=-50 * smooth((tt - t0) / 0.4))
            if t0 + 0.4 <= tt < t0 + 0.65:
                x = (tt - t0 - 0.4) / 0.25
                return standing(B, knee=178 - 40 * (1 - smooth(x)), lean=35, hip_lift=0.04 * B.H * smooth(x), arms="swing", arm_ang=-50 + 170 * x)
            if t0 + 0.65 <= tt < t0 + 0.65 + flight:
                x = (tt - t0 - 0.65) / flight
                up = 0.04 * B.H + 0.22 * D * 4 * x * (1 - x)
                return standing(B, knee=150, lean=30, ank_x=D * x, hip_lift=up, arms="swing", arm_ang=120)
            t1 = t0 + 0.65 + flight
            if t1 <= tt < t1 + 0.7:
                x = (tt - t1) / 0.7
                d = 25 * math.sin(math.pi * min(1, x * 1.2))
                return standing(B, knee=178 - 2.5 * d, lean=10 + d, ank_x=D, arms="swing", arm_ang=60 * (1 - x))
            hold = segs[segs.index((t0, D, flight))]
            t2 = t1 + 0.7
            if t2 <= tt < t2 + 1.6:
                return standing(B, ank_x=D, arms="side")
            if t2 + 1.6 <= tt < t2 + 1.6 + 2.5:             # walk back: one foot at a time
                x = (tt - t2 - 1.6) / 2.5
                step = 0.06 * B.H * max(0, math.sin(math.pi * x * 6))
                side = "l" if int(x * 6) % 2 == 0 else "r"
                return standing(B, ank_x=D * (1 - smooth(x)), arms="side", lift_foot=(side, step))
        return standing(B, knee=178, lean=4, arms="side")
    seq, cam = film(rnd, fn, T, view_side(rnd), (60, 0.5 * B.H, 0), (2.6 * B.H, "x"), yaw_max=15)
    return E.BroadJump(height_cm=B.H), seq, cam, max(dists), "cm"


def sc_reach(rnd):
    B = Body(rnd)
    reaches = [rnd.uniform(-15, 20) for _ in range(2)]
    segs, t = [], rnd.uniform(1.5, 2.5)
    for r in reaches:
        segs.append((t, r))
        t += 2.5 + rnd.uniform(1.5, 2.5) + 2.0 + rnd.uniform(0.5, 1.5)
    T = t
    best = max(reaches)

    def pose(reach):
        hip = np.array([0.0, 0.09 * B.H])
        kn = hip + np.array([B.thigh, -0.02 * B.H])
        an = kn + np.array([B.shank, -(0.09 * B.H - 0.02 * B.H - B.ank_h) * 0 - 0.03 * B.H])
        foot_tip = an + np.array([0.02 * B.H, 0.09 * B.H])
        tip_x = foot_tip[0] + reach
        lean = math.radians(20 + 45 * smooth((reach + 25) / 45))
        sh = hip + B.torso * np.array([math.sin(lean), math.cos(lean)])
        # arm from shoulder to the hand reaching forward
        hand_tip = np.array([tip_x, an[1] + 0.06 * B.H])
        wr = hand_tip - np.array([0.45 * B.hand, 0])
        el = ik2(sh, wr, B.upper, B.fore, np.array([0, 1.0]))
        P = {}
        put(P, {"sh": sh, "el": el, "wr": wr, "hip": hip, "kn": kn, "an": an},
            {"sh": B.sw / 2, "el": B.sw / 2, "wr": 0.03 * B.H, "hip": B.hw / 2, "kn": B.hw / 2, "an": 0.06 * B.H})
        P["nose"] = np.array([sh[0] + 0.05 * B.H, sh[1] + 0.07 * B.H, 0])
        for s in "lr":
            P[s + "foot"] = np.array([foot_tip[0], foot_tip[1], P[s + "an"][2]])
            P[s + "heel"] = P[s + "an"] + np.array([-0.04 * B.H, -0.02 * B.H, 0])
        face_and_hands(P, B)
        for s in "lr":
            P[s + "index"] = np.array([hand_tip[0], hand_tip[1], P[s + "wr"][2]])   # fingertip = what the test measures
        return P

    def fn(tt):
        for t0, r in segs:
            if t0 <= tt < t0 + 2.5:
                return pose(-25 + (r + 25) * smooth((tt - t0) / 2.5))
            if t0 + 2.5 <= tt < t0 + 2.5 + 2.0:
                return pose(r + 0.4 * math.sin(tt * 3))
            if t0 + 4.5 <= tt < t0 + 6.5:
                return pose(r + (-25 - r) * smooth((tt - t0 - 4.5) / 2.0))
        return pose(-25)
    seq, cam = film(rnd, fn, T, view_side(rnd), (0.45 * B.H, 0.2 * B.H, 0), (1.0 * B.H, "x"), yaw_max=20)
    return E.SitAndReach(height_cm=B.H), seq, cam, best, "cm"


def sc_flamingo(rnd):
    B = Body(rnd)
    falls = rnd.randint(0, 5)
    side = rnd.choice("lr")
    # balance segments that add up to > 60 s, separated by falls
    segs, t = [], rnd.uniform(1.5, 3.0)
    total = 0.0
    parts = []
    while len(parts) < falls:                      # falls at least 2 s of balance apart (else it is one long fall)
        x = rnd.uniform(5, 55)
        if all(abs(x - q) >= 2.0 for q in parts):
            parts.append(x)
    parts.sort()
    cuts = [0.0] + parts + [75.0]                 # keeps balancing until the app says 60 s are done
    for k in range(len(cuts) - 1):
        dur = cuts[k + 1] - cuts[k]
        segs.append((t, t + dur))
        t += dur + (rnd.uniform(0.6, 2.5) if k < len(cuts) - 2 else 0)
    T = t + 0.5

    def fn(tt):
        sw = 0.012 * B.H * math.sin(tt * 1.7) + 0.006 * B.H * math.sin(tt * 4.1)
        for a, b in segs:
            if a <= tt < b:
                up = 0.27 * B.H * min(1, (tt - a) / 0.4)
                return front_figure(B, lift=(side, up), sway=sw)
        return front_figure(B, sway=sw)
    seq, cam = film(rnd, fn, T, "front", (0, 0.55 * B.H, 0), (1.15 * B.H, "y"))
    return E.FlamingoBalance(height_cm=B.H), seq, cam, falls, "count"


def sc_tapping(rnd):
    B = Body(rnd)
    cycles = 25
    period = rnd.uniform(0.22, 0.4)                # per touch
    t_start = rnd.uniform(1.0, 2.0)
    T = t_start + period * 50 + 1.5
    holder = {}

    def fn(tt):
        P = front_figure(B)
        if "targets" not in holder:
            holder["P0"] = P
            return P
        tg = holder["targets"]
        if tt < t_start:
            hand = (P["rsh"] + P["lsh"]) / 2 + np.array([0.15 * B.H, -0.15 * B.H, 0])
        else:
            k = int((tt - t_start) / period)
            if k >= 50:
                hand = tg[k % 2]
            else:
                x = ((tt - t_start) / period) - k
                a, b = tg[(k + 1) % 2], tg[k % 2]       # from the previous target to the next
                hand = a + (b - a) * smooth(min(1, x / 0.7))
        return front_figure(B, hand=hand)
    # targets in 3-D: points in the hand's plane that project onto the engine's on-screen targets
    cam = Camera(rnd, "front", (0, 0.75 * B.H, 0), (0.75 * B.H, "y"), yaw_max=15)
    P0 = front_figure(B)
    W, Hh = cam.W, cam.Hh
    pl, pr = cam.project(P0["lsh"]), cam.project(P0["rsh"])
    shw = math.hypot((pl[0] - pr[0]) * W, (pl[1] - pr[1]) * Hh)
    cx, cy = (pl[0] + pr[0]) / 2 * W, (pl[1] + pr[1]) / 2 * Hh
    want = {"left": (cx - 1.3 * shw, cy + 0.9 * shw), "right": (cx + 1.3 * shw, cy + 0.9 * shw)}

    def unproject(px, py, x_plane):
        # ray from the camera through the pixel, meet the plane x = x_plane (in front of the body)
        xs, ys = px - W / 2, -(py - Hh / 2)
        cr, sr = math.cos(-cam.roll), math.sin(-cam.roll)
        xs, ys = xs * cr + ys * sr * -1 * -1, -xs * sr + ys * cr
        d_cam = np.array([xs / cam.f, ys / cam.f, 1.0])
        d = cam.R.T @ d_cam
        s = (x_plane - cam.pos[0]) / d[0]
        return cam.pos + s * d
    aim = rnd.uniform(0.0, 0.25)
    tg = []
    for nm in ("left", "right"):
        px, py = want[nm]
        px += rnd.uniform(-aim, aim) * 0.45 * shw; py += rnd.uniform(-aim, aim) * 0.45 * shw
        tg.append(unproject(px, py, 0.18 * B.H))
    holder["targets"] = tg
    fps = rnd.choice([12, 15, 20, 24, 30])
    nz = Noise(rnd)
    seq, t, body_px = [], 0.0, None
    first = True
    while t <= T:
        P = P0 if first else fn(t)
        first = False
        proj, depth = {}, {}
        for i, nm in NAMES.items():
            x, y, z = cam.project(P[nm]); proj[i], depth[i] = (x, y), z
        for i in range(33):
            if i not in proj:
                proj[i], depth[i] = proj[0], depth[0]
        if body_px is None:
            body_px = max(abs(proj[0][1] - proj[23][1]) * Hh * 1.6, 50)
        lm = nz.apply(proj, depth, cam, body_px)
        if len(seq) == 0 and lm is None:          # the engine places the targets on the first frame it sees
            lm = [[proj[i][0], proj[i][1], 0.95] for i in range(33)]
        seq.append((t, lm))
        t += (1 / fps) * rnd.uniform(0.8, 1.25)
    return E.PlateTapping(height_cm=B.H), seq, cam, period * 49, "seconds_from_first"


SCENARIOS = {
    "situps": sc_situps, "partial_curlup": sc_curlup, "pushups": sc_pushups,
    "pushups_modified": lambda r: sc_pushups(r, knees=True), "plank": sc_plank, "squats": sc_squats,
    "jumping_jacks": sc_jacks, "dumbbell_curls": sc_curls, "vertical_jump": sc_vjump, "broad_jump": sc_broad,
    "sit_and_reach": sc_reach, "flamingo_balance": sc_flamingo, "plate_tapping": sc_tapping,
}


def score(ex, truth, kind):
    v = ex.value()
    if kind == "count":
        return v, truth, abs(v - truth)
    if kind == "seconds":
        return v, truth, abs(v - truth)
    if kind == "cm":
        return v, truth, abs(v - truth)
    if kind == "seconds_from_first":
        return v, truth, abs(v - truth)


def trial_seed(name, k, seed0=1000):
    return seed0 + k * 7919 + zlib.crc32(name.encode()) % 1000


def bench(trials=30, names=None, seed0=1000, verbose=False):
    rows = {}
    for name in (names or SCENARIOS):
        errs, exact, within1, out = [], 0, 0, []
        for k in range(trials):
            rnd = random.Random(trial_seed(name, k, seed0))
            ex, seq, cam, truth, kind = SCENARIOS[name](rnd)
            run_engine(ex, seq, cam)
            v, tr, err = score(ex, truth, kind)
            errs.append(err)
            if kind == "count":
                exact += err == 0; within1 += err <= 1
            out.append({"k": k, "truth": round(tr, 1), "got": round(v, 1), "err": round(err, 1), "portrait": cam.portrait,
                        "yaw": round(math.degrees(cam.yaw)), "invalid": getattr(ex, "invalid", 0)})
        kind = SCENARIOS[name](random.Random(0))[4]
        errs_sorted = sorted(errs)
        p90 = errs_sorted[int(0.9 * (len(errs) - 1))]
        rows[name] = {"kind": kind, "trials": trials, "mean_err": round(mean(errs), 2), "p90_err": round(p90, 2),
                      "exact_pct": round(100 * exact / trials) if kind == "count" else None,
                      "within1_pct": round(100 * within1 / trials) if kind == "count" else None, "cases": out}
        r = rows[name]
        if kind == "count":
            print(f"{name:18s} exact {r['exact_pct']:3d}%  within±1 {r['within1_pct']:3d}%  mean err {r['mean_err']:.2f}  p90 {r['p90_err']:.0f}")
        else:
            unit = "s" if kind.startswith("seconds") else "cm"
            print(f"{name:18s} mean err {r['mean_err']:.2f} {unit}  p90 {r['p90_err']:.2f} {unit}")
        if verbose:
            for c in out:
                if c["err"] > (0 if kind == "count" else 3):
                    print("     ", c)
    return rows


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 30
    names = [a for a in sys.argv[1:] if not a.isdigit() and not a.startswith("-")] or None
    rows = bench(n, names, verbose="-v" in sys.argv)
    if "--json" in sys.argv:
        json.dump(rows, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "exbench_result.json"), "w"), indent=1)
