"""Realistic camera-facing landmark tracks for the Arena detectors (dodge, log jump, bowler lean, bull-run steps),
built with the same 3-D body, phone/laptop camera and MediaPipe-like errors as exbench.py. Each track carries the
truth, so the JavaScript detectors in static/arena/motion.js can be scored against it (arena_bench.mjs).

    python3 arena_tracks.py [trials]  ->  arena_tracks.json (next to this file, ~40 MB, not kept in git)
"""
import json, math, os, random, sys
import numpy as np
import exbench as X


def figure(B, lat=0.0, up=0.0, lean=0.0, knee=(0.0, 0.0), arms_guard=False):
    """Front view, person faces the camera (+x). lat = sideways shift of the whole body (cm, + = person's left),
    up = whole body raised (jump), lean = upper body tilted sideways (deg, + = to the person's left),
    knee = how high each knee is lifted (cm) when running on the spot."""
    P = X.front_figure(B)
    hip_c = (P["lhip"] + P["rhip"]) / 2
    if lean:
        a = math.radians(lean)
        for k in ("lsh", "rsh", "lel", "rel", "lwr", "rwr", "nose", "leye", "reye", "lear", "rear", "mouthl", "mouthr",
                  "lindex", "rindex", "lpinky", "rpinky", "lthumb", "rthumb"):
            v = P[k] - hip_c
            y, z = v[1], v[2]
            P[k] = hip_c + np.array([v[0], y * math.cos(a) - z * math.sin(a), z * math.cos(a) + y * math.sin(a)])
    for s, h in (("l", knee[0]), ("r", knee[1])):
        if h > 0:
            P[s + "kn"] = P[s + "kn"] + np.array([0.45 * h, h, 0])
            P[s + "an"] = P[s + "an"] + np.array([0.1 * h, 0.8 * h, 0])
            P[s + "heel"] = P[s + "heel"] + np.array([0.1 * h, 0.8 * h, 0])
            P[s + "foot"] = P[s + "foot"] + np.array([0.1 * h, 0.8 * h, 0])
    for k in P:
        P[k] = P[k] + np.array([0.0, up, lat])
    return P


def film_front(rnd, fn, T, B, noise=1.0):
    """Laptop (landscape) or phone (portrait) camera 2.5-4 m in front, a little above or below hip height."""
    seq, cam = X.film(rnd, fn, T, "front", (0, 0.55 * B.H, 0), (1.25 * B.H, "y"), noise=noise, yaw_max=12)
    return seq, cam


def smooth(x):
    return X.smooth(x)


def mirror_dir(cam, B):
    """+1 if moving to the person's own left (+z) increases the game's MIRRORED x, else -1."""
    p0 = cam.project(np.array([0.0, 0.55 * B.H, 0.0])); p1 = cam.project(np.array([0.0, 0.55 * B.H, 20.0]))
    return -1 if p1[0] > p0[0] else 1


def sc_dodge(rnd):
    """6 cues; after each the player reacts (200-700 ms) and steps sideways ~1.3-2.2 shoulder widths to the safe side."""
    B = X.Body(rnd)
    sw = B.sw
    cues, t = [], 2.5
    for _ in range(6):
        side = rnd.choice([-1, 1])          # +1 = player must move to their own left
        rt = rnd.uniform(0.2, 0.7)
        dist = rnd.uniform(1.3, 2.2) * sw
        dur = rnd.uniform(0.35, 0.7)        # time to cover the distance
        wrong = rnd.random() < 0.1          # starts the wrong way first
        cues.append({"t": t, "side": side, "rt": rt, "dist": dist, "dur": dur, "wrong": wrong})
        t += rt + dur + 1.2 + rnd.uniform(0.6, 1.5) + 0.9   # move back to the centre
    T = t + 1.0

    def lat_at(tt):
        for c in cues:
            t0 = c["t"] + c["rt"]
            back0 = t0 + c["dur"] + 0.9
            if c["t"] <= tt < back0 + 1.0:
                if tt < t0:
                    return 0.0
                x = 0.0
                if c["wrong"]:
                    if tt < t0 + 0.18:
                        return -c["side"] * 0.3 * sw * smooth((tt - t0) / 0.18)
                    t0 += 0.18
                if tt < t0 + c["dur"]:
                    return c["side"] * c["dist"] * smooth((tt - t0) / c["dur"]) - (c["side"] * 0.3 * sw * (1 - smooth((tt - t0) / c["dur"])) if c["wrong"] else 0)
                if tt < back0:
                    return c["side"] * c["dist"]
                return c["side"] * c["dist"] * (1 - smooth((tt - back0) / 1.0))
        return 0.3 * math.sin(tt * 1.3)

    seq, cam = film_front(rnd, lambda tt: figure(B, lat=lat_at(tt)), T, B)
    md = mirror_dir(cam, B)
    truth = []
    for c in cues:
        # truth: when the hips really crossed 0.25 shoulder widths to the safe side, and the peak sideways speed
        ts = np.arange(c["t"], c["t"] + c["rt"] + c["dur"] + 0.6, 0.001)
        xs = np.array([lat_at(x) for x in ts]) * c["side"]
        cross = next((ts[i] for i in range(len(ts)) if xs[i] > 0.25 * sw), None)
        v = np.diff(xs) / 0.001
        truth.append({"t": c["t"], "side": c["side"], "mdir": c["side"] * md, "onset": c["t"] + c["rt"], "cross": cross,
                      "peak_sw_s": float(np.max(v) / sw), "wrong": c["wrong"]})
    return seq, cam, {"cues": truth, "sw_cm": sw}


def sc_jump(rnd):
    """5 logs; the player jumps 0-60 cm (some just rise on their toes) when each arrives."""
    B = X.Body(rnd)
    g = 981.0
    ext = 0.05 * B.H
    logs, t = [], 3.0
    for _ in range(5):
        kind = rnd.random()
        h = 0.0 if kind < 0.1 else (rnd.uniform(4, 7) if kind < 0.2 else rnd.uniform(12, 55))   # nothing / toes / jump
        logs.append({"tArr": t, "h": h})
        t += 2.6 + rnd.uniform(0.5, 1.0)
    T = t

    def up_at(tt):
        for L in logs:
            h = L["h"]
            if h <= 0:
                continue
            if h < ext:                                   # rise on the toes and back down
                t0 = L["tArr"] - 0.3
                if t0 <= tt < t0 + 0.6:
                    return h * math.sin(math.pi * (tt - t0) / 0.6)
                continue
            flight = 2 * math.sqrt(2 * (h - ext) / g)
            t0 = L["tArr"] - flight / 2
            if t0 - 0.35 <= tt < t0:                      # dip, then push up onto the toes
                x = (tt - t0 + 0.35) / 0.35
                return -12 * math.sin(math.pi * min(1, x * 1.4)) + ext * max(0, (x - 0.7) / 0.3)
            if t0 <= tt < t0 + flight:
                x = (tt - t0) / flight
                return ext + (h - ext) * 4 * x * (1 - x)
            if t0 + flight <= tt < t0 + flight + 0.5:
                x = (tt - t0 - flight) / 0.5
                return ext * max(0, 1 - 3 * x) - 10 * math.sin(math.pi * x)
        return 0.2 * math.sin(tt * 2)

    seq, cam = film_front(rnd, lambda tt: figure(B, up=up_at(tt)), T, B)
    return seq, cam, {"logs": [{"tArr": L["tArr"], "h": L["h"]} for L in logs], "height_cm": B.H}


def sc_bowler(rnd):
    """8 balls; ~1.1-2.0 s after the delivery starts the player steps or leans to one side (or not at all)."""
    B = X.Body(rnd)
    balls, t = [], 2.5
    upper = rnd.random() < 0.3
    for _ in range(8):
        side = rnd.choice([-1, 1])
        none = rnd.random() < 0.1
        tm = t + rnd.uniform(1.3, 2.2)
        amt = rnd.uniform(0.7, 1.6) * B.sw
        balls.append({"t0": t, "tm": tm, "side": 0 if none else side, "amt": amt})
        t += 4.5 + rnd.uniform(0.5, 1.0)
    T = t

    def pose_at(tt):
        for b in balls:
            if b["side"] and b["tm"] <= tt < b["tm"] + 1.8:
                x = min(1, (tt - b["tm"]) / 0.4) if tt < b["tm"] + 1.2 else 1 - (tt - b["tm"] - 1.2) / 0.6
                if upper:                                   # upper-body game: lean, don't step
                    return figure(B, lean=b["side"] * 25 * x)
                return figure(B, lat=b["side"] * b["amt"] * x)
        return figure(B, lat=0.3 * math.sin(tt))

    seq, cam = film_front(rnd, pose_at, T, B)
    md = mirror_dir(cam, B)
    return seq, cam, {"balls": [{"t0": b["t0"], "side": b["side"], "mdir": b["side"] * md} for b in balls], "upper": upper}


def sc_escape(rnd):
    """Running on the spot for 10 s at 1.5-4 steps a second (knees up 10-35 cm)."""
    B = X.Body(rnd)
    rate = rnd.uniform(1.5, 4.0)
    lift = rnd.uniform(10, 35)
    T0, secs = 1.5, 10.0
    T = T0 + secs + 1.0
    n_true = 0
    steps = []
    t = T0
    while t < T0 + secs:
        steps.append(t)
        t += 1 / rate * rnd.uniform(0.9, 1.1)

    def kn_at(tt):
        if tt < T0 or tt > T0 + secs:
            return (0.0, 0.0)
        k = max(i for i, s in enumerate(steps) if s <= tt)
        ph = (tt - steps[k]) / ((steps[k + 1] if k + 1 < len(steps) else steps[k] + 1 / rate) - steps[k])
        h = lift * math.sin(math.pi * min(1, ph))
        return (h, 0.0) if k % 2 == 0 else (0.0, h)

    seq, cam = film_front(rnd, lambda tt: figure(B, knee=kn_at(tt), up=1.5 * math.sin(tt * rate * math.pi)), T, B)
    return seq, cam, {"t0": T0, "secs": secs, "steps": len(steps)}


SC = {"dodge": sc_dodge, "jump": sc_jump, "bowler": sc_bowler, "escape": sc_escape}

if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    out = {}
    for name, fn in SC.items():
        out[name] = []
        for k in range(n):
            rnd = random.Random(X.trial_seed("arena_" + name, k))
            seq, cam, truth = fn(rnd)
            out[name].append({"k": k, "vw": cam.W, "vh": cam.Hh, "truth": truth,
                              "frames": [[round(t * 1000, 1), None if lm is None else [[round(p[0], 4), round(p[1], 4), round(p[2], 3)] for p in lm]]
                                         for t, lm in seq]})
    json.dump(out, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "arena_tracks.json"), "w"))
    print({k: len(v) for k, v in out.items()})
