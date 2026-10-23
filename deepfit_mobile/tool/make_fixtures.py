"""
Golden fixtures for the Dart engine (test/engine_parity_test.dart).

Synthetic body movements are run through the PYTHON engine of the website
(exercise_engine.py, coachability.py, growth.py) with the same clock offset the phone
uses (T0 = 1000 s) and the same rounding the phone applies before uploading. The Dart
test feeds the same tracks to lib/engine and must get the same counts, events and texts.

Run after changing a threshold on BOTH sides:
    python3 tool/make_fixtures.py        (from the deepfit_mobile folder)
"""
import json
import math
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.normpath(os.path.join(HERE, "..", "..", "SIH_FinalApp 2", "SIH-7", "HeightAndWeightCalculator"))
sys.path.insert(0, APP)
import exercise_engine as E      # noqa: E402
import coachability as C         # noqa: E402
import growth as G               # noqa: E402

OUT = os.path.join(HERE, "..", "test", "fixtures", "engine_cases.json")
T0 = 1000.0
FPS = 15
W, H = 640, 480


# ---------------------------------------------------------------- synthetic bodies (normalised x, y, visibility)
def blank():
    return [[0.5, 0.5, 1.0] for _ in range(33)]

def setpt(lm, i, x, y): lm[i] = [x, y, 1.0]

def both(lm, li, ri, x, y): setpt(lm, li, x, y); setpt(lm, ri, x, y)

def torso(theta_deg, knee=(0.62, 0.62)):
    lm = blank(); hip = (0.5, 0.75); r = 0.22
    th = math.radians(theta_deg)
    sh = (hip[0] - r * math.cos(th) * (W / W), hip[1] - r * math.sin(th) * (W / H))
    both(lm, E.L_SHOULDER, E.R_SHOULDER, *sh); both(lm, E.L_HIP, E.R_HIP, *hip)
    both(lm, E.L_KNEE, E.R_KNEE, *knee); both(lm, E.L_ANKLE, E.R_ANKLE, 0.72, 0.75)
    return lm

def cycle(fn, lo, hi, reps, steps=8, hold=3):
    seq = []
    for _ in range(reps):
        seq += [fn(lo)] * hold + [fn(lo + (hi - lo) * k / steps) for k in range(steps + 1)] + [fn(hi)] * hold
        seq += [fn(hi - (hi - lo) * k / steps) for k in range(steps + 1)]
    return seq + [fn(lo)] * hold

def push(elbow_deg, sag=0.0, knees=False):
    lm = blank(); sh = (0.35, 0.55); hip = (0.6, 0.58 + sag); an = (0.85, 0.61)
    both(lm, E.L_SHOULDER, E.R_SHOULDER, *sh); both(lm, E.L_HIP, E.R_HIP, *hip)
    both(lm, E.L_ANKLE, E.R_ANKLE, *an); both(lm, E.L_KNEE, E.R_KNEE, 0.72, 0.6 + sag / 2)
    # wrist below shoulder on floor, elbow positioned so angle(sh,el,wr)=elbow_deg
    L = 0.09; half = math.radians(elbow_deg) / 2
    wr = (sh[0], sh[1] + 2 * L * math.sin(half) * W / H)
    el = (sh[0] - L * math.cos(half), (sh[1] + wr[1]) / 2)
    both(lm, E.L_WRIST, E.R_WRIST, *wr); both(lm, E.L_ELBOW, E.R_ELBOW, *el)
    return lm

def squat(knee_deg):
    lm = blank(); an = (0.5, 0.9); kn = (0.56, 0.72); th = math.radians(180 - knee_deg)
    # thigh from knee back towards hip, rotated by knee angle
    v = (an[0] - kn[0], an[1] - kn[1]); n = math.hypot(*v); v = (v[0] / n, v[1] / n)
    c, s = math.cos(math.radians(knee_deg)), math.sin(math.radians(knee_deg))
    thigh = (v[0] * c + v[1] * s, -v[0] * s + v[1] * c)
    hip = (kn[0] + thigh[0] * 0.18, kn[1] + thigh[1] * 0.18)
    sh = (hip[0] + 0.03, hip[1] - 0.25)
    both(lm, E.L_ANKLE, E.R_ANKLE, *an); both(lm, E.L_KNEE, E.R_KNEE, *kn)
    both(lm, E.L_HIP, E.R_HIP, *hip); both(lm, E.L_SHOULDER, E.R_SHOULDER, *sh)
    return lm

def jj(open_):
    lm = blank()
    setpt(lm, E.L_SHOULDER, 0.45, 0.35); setpt(lm, E.R_SHOULDER, 0.55, 0.35)
    if open_:
        setpt(lm, E.L_WRIST, 0.38, 0.2); setpt(lm, E.R_WRIST, 0.62, 0.2)
        setpt(lm, E.L_ANKLE, 0.38, 0.9); setpt(lm, E.R_ANKLE, 0.62, 0.9)
    else:
        setpt(lm, E.L_WRIST, 0.44, 0.6); setpt(lm, E.R_WRIST, 0.56, 0.6)
        setpt(lm, E.L_ANKLE, 0.48, 0.9); setpt(lm, E.R_ANKLE, 0.52, 0.9)
    return lm

def curl(a_l, a_r):
    lm = blank()
    for (s, e, w, sx, a) in [(E.L_SHOULDER, E.L_ELBOW, E.L_WRIST, 0.4, a_l), (E.R_SHOULDER, E.R_ELBOW, E.R_WRIST, 0.6, a_r)]:
        setpt(lm, s, sx, 0.3); setpt(lm, e, sx, 0.45)
        th = math.radians(a)
        setpt(lm, w, sx + 0.1 * math.sin(th) * H / W, 0.45 - 0.1 * math.cos(th))
    return lm

def stand(dx=0.0, dy=0.0, lift=0.0):
    lm = blank()
    setpt(lm, E.NOSE, 0.5 + dx, 0.15 + dy)
    for i, x in [(E.L_SHOULDER, 0.46), (E.R_SHOULDER, 0.54)]: setpt(lm, i, x + dx, 0.28 + dy)
    for i, x in [(E.L_HIP, 0.47), (E.R_HIP, 0.53)]: setpt(lm, i, x + dx, 0.55 + dy)
    setpt(lm, E.L_ANKLE, 0.47 + dx, 0.92 + dy - lift); setpt(lm, E.R_ANKLE, 0.53 + dx, 0.92 + dy)
    for i in (E.L_WRIST, E.R_WRIST): setpt(lm, i, 0.5 + dx, 0.6 + dy)
    return lm

def sit(reach_norm):
    lm = blank(); hp = (0.3, 0.75)
    both(lm, E.L_HIP, E.R_HIP, *hp); both(lm, E.L_KNEE, E.R_KNEE, 0.5, 0.75)
    both(lm, E.L_ANKLE, E.R_ANKLE, 0.7, 0.75); both(lm, E.L_FOOT, E.R_FOOT, 0.72, 0.73)
    both(lm, E.L_INDEX, E.R_INDEX, 0.72 + reach_norm, 0.7)
    return lm

def tap(side):
    lm = stand()
    x = {"left": 0.5 - 1.3 * 0.08, "right": 0.5 + 1.3 * 0.08, "mid": 0.5}[side]
    y = 0.28 + 0.9 * 0.08 * W / H
    setpt(lm, E.R_WRIST, x, y); setpt(lm, E.L_WRIST, 0.47, 0.6); setpt(lm, E.L_INDEX, 0.47, 0.6); setpt(lm, E.R_INDEX, x, y)
    return lm

def body(move="neutral", dx=0.0):
    """Front-facing figure (camera not mirrored: athlete's LEFT side is image RIGHT)."""
    lm = [[0.5, 0.5, 1.0] for _ in range(33)]
    def s(i, x, y): lm[i] = [x + dx, y, 1.0]
    s(E.NOSE, 0.5, 0.18)
    s(E.L_SHOULDER, 0.56, 0.3); s(E.R_SHOULDER, 0.44, 0.3)
    s(E.L_HIP, 0.54, 0.55); s(E.R_HIP, 0.46, 0.55)
    s(E.L_KNEE, 0.545, 0.72); s(E.R_KNEE, 0.455, 0.72)
    s(E.L_ANKLE, 0.55, 0.9); s(E.R_ANKLE, 0.45, 0.9)
    lw, rw = (0.58, 0.58), (0.42, 0.58)            # arms down
    if move == "hands_up": lw, rw = (0.56, 0.02), (0.44, 0.02)
    if move == "left_hand_up": lw = (0.56, 0.02)
    if move == "right_hand_up": rw = (0.44, 0.02)
    if move == "hands_on_head": lw, rw = (0.53, 0.1), (0.47, 0.1)
    if move == "arms_out": lw, rw = (0.80, 0.31), (0.20, 0.31)
    if move == "hands_on_hips": lw, rw = (0.57, 0.53), (0.43, 0.53)
    if move in ("squat", "touch_knees"):
        for i, (x, y) in {E.L_HIP: (0.54, 0.68), E.R_HIP: (0.46, 0.68), E.L_KNEE: (0.60, 0.74), E.R_KNEE: (0.40, 0.74),
                          E.L_SHOULDER: (0.56, 0.45), E.R_SHOULDER: (0.44, 0.45), E.NOSE: (0.5, 0.33)}.items(): s(i, x, y)
        if move == "touch_knees": lw, rw = (0.60, 0.73), (0.40, 0.73)
        else: lw, rw = (0.58, 0.62), (0.42, 0.62)
    s(E.L_WRIST, *lw); s(E.R_WRIST, *rw)
    # elbows: straight arm = midway; bent (hips / head) = pushed outward
    lsx, lsy = lm[E.L_SHOULDER][0] - dx, lm[E.L_SHOULDER][1]; rsx, rsy = lm[E.R_SHOULDER][0] - dx, lm[E.R_SHOULDER][1]
    if move in ("hands_on_hips", "hands_on_head"):
        s(E.L_ELBOW, max(lsx, lw[0]) + 0.08, (lsy + lw[1]) / 2); s(E.R_ELBOW, min(rsx, rw[0]) - 0.08, (rsy + rw[1]) / 2)
    else:
        s(E.L_ELBOW, (lsx + lw[0]) / 2, (lsy + lw[1]) / 2); s(E.R_ELBOW, (rsx + rw[0]) / 2, (rsy + rw[1]) / 2)
    if move == "jump":
        for i in (E.NOSE, E.L_SHOULDER, E.R_SHOULDER, E.L_HIP, E.R_HIP, E.L_KNEE, E.R_KNEE, E.L_ANKLE, E.R_ANKLE, E.L_WRIST, E.R_WRIST):
            lm[i][1] -= 0.08
    return lm

def move_frames(m):
    if m == "step_left": return [body("neutral", dx=+0.14)] * 8 + [body("neutral", dx=0.07)] * 2   # athlete's left = image right
    if m == "step_right": return [body("neutral", dx=-0.14)] * 8 + [body("neutral", dx=-0.07)] * 2
    return [body(m)] * 8

def fig(eye_y, hip_y, floor=0.95):
    lm = [[0.5, 0.5, 1.0] for _ in range(33)]
    for i in (G.L_EYE, G.R_EYE): lm[i] = [0.5, eye_y, 1.0]
    for i in (E.L_HIP, E.R_HIP): lm[i] = [0.5, hip_y, 1.0]
    for i in (E.L_HEEL, E.R_HEEL, E.L_FOOT, E.R_FOOT): lm[i] = [0.55, floor, 1.0]
    for i in (E.L_ANKLE, E.R_ANKLE): lm[i] = [0.53, floor - 0.02, 1.0]
    return lm


# ---------------------------------------------------------------- cases
def rnd_lm(lm):
    return [[round(p[0], 4), round(p[1], 4), round(p[2], 3)] for p in lm]


def track(frames, fps=FPS):
    return [[round((i + 1) / fps, 4), None if f is None else rnd_lm(f)] for i, f in enumerate(frames)]


def noisy(frames, seed, sd=0.003, drop=0.03, hide=0.02):
    """Camera-like jitter, a few low-visibility points and a few frames with nobody detected."""
    r = random.Random(seed)
    out = []
    for f in frames:
        if f is None or r.random() < hide:
            out.append(None)
            continue
        g = []
        for x, y, v in f:
            vv = v if r.random() > drop else round(r.uniform(0.2, 0.6), 3)
            g.append([x + r.gauss(0, sd), y + r.gauss(0, sd), vv])
        out.append(g)
    return out


def make_ex(case):
    ex = E.EXERCISES[case["key"]](height_cm=case["height_cm"])
    if case.get("inputs"):
        ex.configure(**case["inputs"])
    if case.get("pattern"):
        ex.code, ex.pattern = case["code"], list(case["pattern"])
    return ex


def expect(case):
    ex = make_ex(case)
    per, fb, events = [], [], []
    last_fb, last_id = None, 0
    for i, (t, lm) in enumerate(case["frames"]):
        ex.update(E.Pose(lm, case["w"], case["h"]) if lm is not None else None, T0 + t)
        per.append([round(ex.value(), 4), ex.count, 1 if ex.finished else 0, ex.mirror_value])
        if ex.feedback != last_fb:
            fb.append([i, ex.feedback])
            last_fb = ex.feedback
        for ev in ex.events:
            if ev["id"] > last_id:
                events.append([i, ev["kind"], ev["text"]])
                last_id = ev["id"]
        if ex.finished:
            break
    r = ex.result()
    final = {k: r.get(k) for k in ("value", "unit", "repetitions", "invalid_reps", "form_score", "form_faults", "incomplete")}
    if "coachability" in r:
        c = r["coachability"]
        final["coachability"] = {k: c.get(k) for k in ("score", "percentile", "errors_per_try", "reduction_pct",
                                                       "slope", "note", "tips", "tries_completed")}
    if "maturity" in r:
        final["maturity"] = r["maturity"]
    return {"per_frame": per, "feedback": fb, "events": events, "final": final, "frames_used": len(per)}


cases = []


def add(name, key, frames, height_cm=165.0, w=W, h=H, inputs=None, pattern=None, code=None, fps=FPS):
    case = {"name": name, "key": key, "w": w, "h": h, "height_cm": height_cm, "inputs": inputs,
            "pattern": pattern, "code": code, "frames": track(frames, fps)}
    case["expect"] = expect(case)
    cases.append(case)


# ---- lying / side-view tests
add("situps_5", "situps", cycle(torso, 0, 75, 5))
add("situps_noisy", "situps", noisy(cycle(torso, 0, 75, 4), 1))
add("curlup_6", "partial_curlup", cycle(torso, 0, 32, 6))
add("curlup_fullsitups", "partial_curlup", cycle(torso, 0, 75, 2))
add("pushups_7", "pushups", cycle(lambda a: push(a), 170, 70, 7))
add("pushups_sag", "pushups", cycle(lambda a: push(a, sag=0.12), 170, 70, 3))
add("pushups_noisy", "pushups", noisy(cycle(lambda a: push(a), 170, 70, 5), 2, sd=0.004))
add("pushups_modified_4", "pushups_modified", cycle(lambda a: push(a), 170, 70, 4))
add("plank_10s", "plank", [push(170)] * (10 * FPS) + [push(170, sag=0.15)] * (3 * FPS))
add("plank_noisy", "plank", noisy([push(170)] * (8 * FPS) + [push(170, sag=0.06)] * FPS + [push(170)] * (4 * FPS)
                                  + [push(170, sag=0.15)] * (3 * FPS), 3))
add("squats_6", "squats", cycle(squat, 175, 80, 6))
add("squats_noisy", "squats", noisy(cycle(squat, 175, 80, 4), 4))

# ---- front-view tests
seq = []
for _ in range(8):
    seq += [jj(False)] * 4 + [jj(True)] * 4
add("jumping_jacks_8", "jumping_jacks", seq + [jj(False)] * 4)
add("jumping_jacks_noisy", "jumping_jacks", noisy(seq, 5))
seq = []
for _ in range(5):
    seq += [curl(170, 170)] * 3 + [curl(40, 170)] * 3 + [curl(170, 40)] * 3
add("dumbbell_curls_5_5", "dumbbell_curls", seq)

cpp = 170 * 0.88 / (0.77 * H)
rise = 40 / cpp / H
seq = [stand()] * 20
for _ in range(3):
    seq += [stand(dy=-rise * s) for s in (0.3, 0.7, 1.0, 0.8, 0.4, 0)] + [stand()] * 20
add("vertical_jump_3x40", "vertical_jump", seq, height_cm=170)
d = 180 / cpp / W
seq = [stand()] * 20
for _ in range(3):
    seq += [stand(dx=d * s, dy=-0.04 * math.sin(math.pi * s)) for s in (0.1, 0.3, 0.5, 0.7, 0.9, 1.0)]
    seq += [stand(dx=d)] * 6 + [stand()] * 20
add("broad_jump_3x180", "broad_jump", seq, height_cm=170)
seq = ([stand()] * 10 + [stand(lift=0.1)] * (20 * FPS) + [stand()] * 8 + [stand(lift=0.1)] * (20 * FPS)
       + [stand()] * 8 + [stand(lift=0.1)] * (21 * FPS))
add("flamingo_2_falls", "flamingo_balance", seq)
add("sit_and_reach", "sit_and_reach", [sit(-0.1)] * 10 + [sit(-0.1 + 0.15 * k / 10) for k in range(11)] + [sit(0.05)] * 25)
add("sit_and_reach_bent", "sit_and_reach", [sit(0.02)] * 30)
seq = [tap("mid")] * 5
for _ in range(25):
    seq += [tap("left"), tap("mid"), tap("right"), tap("mid")]
add("plate_tapping_25", "plate_tapping", seq)
add("nobody", "situps", [None] * 8)

# ---- portrait phone frame (480 x 640) to make sure width/height are used the same way
add("pushups_portrait", "pushups", cycle(lambda a: push(a), 170, 70, 3), w=480, h=640)

# ---- Growth Measures
stand_px = 0.8 * H
cppg = 0.936 * 160 / stand_px
eye_sit = 0.95 - (84 + 45 - (1 - 0.936) * 160) / cppg / H
gin = {"height_cm": 160, "weight_kg": 45, "chair_cm": 45, "age": 13, "sex": "M"}
add("growth_84cm", "growth_measures", [fig(0.15, 0.5)] * 30 + [fig(0.2, 0.6)] * 10 + [fig(eye_sit, 0.66)] * 30,
    height_cm=160, inputs=gin)
add("growth_wrong_chair", "growth_measures", [fig(0.15, 0.5)] * 30 + [fig(0.2, 0.6)] * 10 + [fig(eye_sit, 0.66)] * 30,
    height_cm=160, inputs=dict(gin, chair_cm=20))
add("growth_girl", "growth_measures", [fig(0.15, 0.5)] * 30 + [fig(0.2, 0.6)] * 10 + [fig(eye_sit, 0.66)] * 30,
    height_cm=160, inputs=dict(gin, sex="Female", age=12))


# ---- Coachability: frames generated against the live Python engine, then frozen
def coach_track(pattern, code, attempts, noise_seed=None):
    ex = C.CoachabilityChallenge()
    ex.code, ex.pattern = code, list(pattern)
    fed = []

    def feed(f):
        fed.append(f)
        ex.update(E.Pose(f, W, H), T0 + round(len(fed) / FPS, 4))

    for att in attempts:
        guard = 0
        while ex.phase != "perform" and not ex.finished and guard < 600:
            feed(body())
            guard += 1
        for m in att:
            for f in move_frames(m) + [body()] * 3:
                feed(f)
        guard = 0
        while ex.phase == "perform" and guard < 600:
            feed(body())
            guard += 1
    return noisy(fed, noise_seed, sd=0.002, drop=0.0, hide=0.0) if noise_seed else fed


pat, code = ["step_left", "left_hand_up", "squat", "jump", "hands_up"], "PCF54"
wrong = "arms_out"
add("coach_learner", "coachability",
    coach_track(pat, code, [pat[:2] + [wrong] + pat[3:4], pat[:3] + pat[4:], pat[:4] + [wrong], pat, pat]),
    pattern=pat, code=code)
pat2, code2 = ["hands_on_head", "touch_knees", "right_hand_up", "step_right", "hands_on_hips"], "Q7RT2"
add("coach_perfect", "coachability", coach_track(pat2, code2, [pat2] * 5), pattern=pat2, code=code2)
add("coach_nonlearner", "coachability", coach_track(pat2, code2, [pat2[:3]] * 5), pattern=pat2, code=code2)
add("coach_noisy", "coachability",
    coach_track(pat, code, [pat[:3], pat[:4], pat, pat, pat], noise_seed=9), pattern=pat, code=code)

# ---- pure functions used by the app (alignment, scoring, maturity, benchmarks)
import potential as POT   # noqa: E402
import benchmarks as B    # noqa: E402

funcs = {
    "align": [[list("abcd"), list("acbd"), C.align(list("abcd"), list("acbd"))[0]],
              [list("abcde"), list("ae"), C.align(list("abcde"), list("ae"))[0]],
              [list("ab"), list("xaby"), C.align(list("ab"), list("xaby"))[0]]],
    "coach_score": [[e, C.coachability_score(e, 5)] for e in
                    ([3, 2, 1, 0, 0], [3, 3, 3, 3, 3], [0, 0, 0, 0, 0], [2.5, 2, 1.5, 1, 0.5], [4, 4.5, 3, 3.5, 2], [1])],
    "percentile": [[s, C.starter_percentile(s)] for s in (0, 14, 30, 44.9, 45, 45.1, 60, 75, 90, 100)],
    "maturity": [[a, s, h, sh, w, POT.maturity_offset(a, s, h, sh, w)] for a, s, h, sh, w in
                 ((13.5, "M", 160, 84, 45), (12.5, "Female", 150, 79, 40), (16.5, "M", 172, 90, 60), (7.5, "F", 125, 68, 24))],
    "evaluate": [],
}
for ex_key, value in (("pushups", 4), ("pushups", 0), ("sit_and_reach", -8), ("sit_and_reach", 6), ("flamingo_balance", 0),
                      ("flamingo_balance", 7), ("plate_tapping", 25.5), ("coachability", 64), ("run_600m", 280)):
    for age, g, pop in ((14, "M", "standard"), (11, "Female", "blind"), (25, "F", "deaf")):
        row = B.target_for(ex_key, age, g, pop)
        tgt = {"target": float(row["target"]), "unit": row["unit"], "higher_is_better": row["higher_is_better"] in ("1", "True"),
               "scoring": row["scoring"], "age_band": f'{row["age_min"]}-{row["age_max"]}'}
        funcs["evaluate"].append([ex_key, value, tgt, B.evaluate(ex_key, value, age, g, pop)])

os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w") as f:
    json.dump({"t0": T0, "cases": cases, "functions": funcs}, f, separators=(",", ":"))
print(f"{len(cases)} cases, {sum(len(c['frames']) for c in cases)} frames -> {OUT} ({os.path.getsize(OUT) / 1e6:.1f} MB)")
for c in cases:
    fin = c["expect"]["final"]
    extra = fin.get("coachability", {}).get("errors_per_try") or (fin.get("maturity") or {}).get("status") or ""
    print(f"  {c['name']:22s} value={fin['value']:<7} reps={fin['repetitions']} invalid={fin['invalid_reps']} {extra}")
