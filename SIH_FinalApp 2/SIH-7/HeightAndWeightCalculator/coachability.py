"""
Coachability Challenge - measures how fast an athlete LEARNS, not what they can do today.

1. A random movement pattern (5 moves) is generated - new for every attempt, so it
   can't be practised beforehand.
2. The athlete performs it 5 times. The camera recognises each move.
3. After every try the athlete gets ONE specific correction (the biggest mistake).
4. Errors per try are counted (wrong / missed / extra moves, late moves) and the
   score is how much the errors drop from try 1 to the last tries.

All moves are chosen because MediaPipe Pose can recognise them reliably from the
front: hands up, one hand up, hands on head, arms out, hands on hips, squat,
touch knees, step left, step right, jump.
"""

import math
import random
from collections import deque
from typing import Dict, List, Optional, Tuple

from exercise_engine import (Exercise, Pose, angle, NOSE, L_SHOULDER, R_SHOULDER, L_ELBOW, R_ELBOW, L_WRIST, R_WRIST,
                             L_HIP, R_HIP, L_KNEE, R_KNEE, L_ANKLE, R_ANKLE)

MOVES: Dict[str, str] = {
    "hands_up": "Both hands up",
    "left_hand_up": "Left hand up",
    "right_hand_up": "Right hand up",
    "hands_on_head": "Hands on head",
    "arms_out": "Arms out to the sides",
    "hands_on_hips": "Hands on hips",
    "squat": "Squat down",
    "touch_knees": "Touch your knees",
    "step_left": "Step to your left",
    "step_right": "Step to your right",
    "jump": "Jump",
}
UPPER = ["hands_up", "left_hand_up", "right_hand_up", "hands_on_head", "arms_out", "hands_on_hips"]
LOWER = ["squat", "touch_knees", "step_left", "step_right", "jump"]

TRIES = 5
PATTERN_LEN = 5
STABLE_FRAMES = 5          # a move must be held ~1/3 s (at 15 fps) to count
LATE_GAP = 2.5             # seconds between moves before a move counts as "late"
NEUTRAL_TO_START = 0.8     # seconds of standing neutral before each try
FINISH_NEUTRAL = 2.0       # standing neutral this long after moving ends the try early
REVIEW_TIME = 4.0          # seconds to read/hear the tip
PREVIEW_BASE, PREVIEW_PER_STEP = 1.5, 1.3   # time to read/hear the pattern before each try


def make_pattern(seed: Optional[int] = None, length: int = PATTERN_LEN) -> Tuple[str, List[str]]:
    """Random pattern with no move repeated back-to-back and at least two lower-body moves."""
    rnd = random.Random(seed)
    while True:
        seq: List[str] = []
        for _ in range(length):
            pool = [m for m in MOVES if not seq or m != seq[-1]]
            # step_left right after step_right (and v.v.) is just "go back"; avoid it
            if seq and seq[-1] in ("step_left", "step_right"):
                pool = [m for m in pool if m not in ("step_left", "step_right")]
            seq.append(rnd.choice(pool))
        if sum(m in LOWER for m in seq) >= 2 and sum(m in UPPER for m in seq) >= 2:
            code = "".join(rnd.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(5))
            return code, seq


def classify(pose: Pose, base: Dict) -> str:
    """Which move is the body doing right now? 'neutral', a MOVES key, or 'unknown'."""
    need = [NOSE, L_SHOULDER, R_SHOULDER, L_HIP, R_HIP, L_WRIST, R_WRIST]
    if not pose.vis(*need):
        return "unknown"
    sh = pose.mid(L_SHOULDER, R_SHOULDER)
    hp = pose.mid(L_HIP, R_HIP)
    torso = max(math.hypot(hp[0] - sh[0], hp[1] - sh[1]), 1.0)
    nose = pose.p(NOSE)
    lw, rw = pose.p(L_WRIST), pose.p(R_WRIST)
    legs = pose.vis(L_KNEE, R_KNEE, L_ANKLE, R_ANKLE)

    def near(a, b, k):
        return math.hypot(a[0] - b[0], a[1] - b[1]) < k * torso

    # whole-body moves first
    if legs and base:
        lift = min(base["l_ank_y"] - pose.p(L_ANKLE)[1], base["r_ank_y"] - pose.p(R_ANKLE)[1])
        if lift > 0.12 * torso:
            return "jump"
        # sideways shift measured along the athlete's own left direction (R_HIP -> L_HIP)
        lx, ly = pose.p(L_HIP)
        rx, ry = pose.p(R_HIP)
        d = (lx - rx, ly - ry)
        n = math.hypot(*d) or 1.0
        shift = ((hp[0] - base["hip_x"]) * d[0] + (hp[1] - base["hip_y"]) * d[1]) / n
        if shift > 0.45 * torso:
            return "step_left"
        if shift < -0.45 * torso:
            return "step_right"
        if near(lw, pose.p(L_KNEE), 0.4) and near(rw, pose.p(R_KNEE), 0.4):
            return "touch_knees"
        knee = (angle(pose.p(L_HIP), pose.p(L_KNEE), pose.p(L_ANKLE)) +
                angle(pose.p(R_HIP), pose.p(R_KNEE), pose.p(R_ANKLE))) / 2
        if knee < 125:
            return "squat"

    up_l = lw[1] < nose[1] - 0.45 * torso
    up_r = rw[1] < nose[1] - 0.45 * torso
    if up_l and up_r:
        return "hands_up"
    head = (nose[0], nose[1] - 0.35 * torso)
    if near(lw, head, 0.5) and near(rw, head, 0.5):
        return "hands_on_head"
    low_l = lw[1] > sh[1] + 0.2 * torso
    low_r = rw[1] > sh[1] + 0.2 * torso
    if up_l and low_r:
        return "left_hand_up"
    if up_r and low_l:
        return "right_hand_up"
    lsh, rsh = pose.p(L_SHOULDER), pose.p(R_SHOULDER)
    if (abs(lw[1] - lsh[1]) < 0.3 * torso and abs(rw[1] - rsh[1]) < 0.3 * torso
            and abs(lw[0] - lsh[0]) > 0.7 * torso and abs(rw[0] - rsh[0]) > 0.7 * torso):
        return "arms_out"
    # arms hanging also puts the wrists next to the hips - hands-on-hips needs BENT elbows
    if pose.vis(L_ELBOW, R_ELBOW):
        bend_l = angle(lsh, pose.p(L_ELBOW), lw)
        bend_r = angle(rsh, pose.p(R_ELBOW), rw)
    else:
        bend_l = bend_r = 180.0
    if near(lw, pose.p(L_HIP), 0.4) and near(rw, pose.p(R_HIP), 0.4) and bend_l < 130 and bend_r < 130:
        return "hands_on_hips"
    if low_l and low_r and bend_l > 140 and bend_r > 140:
        return "neutral"
    return "unknown"


def align(target: List[str], done: List[str]):
    """Edit-distance alignment. Returns (distance, ops) with ops like ('ok'|'sub'|'miss'|'extra', ti, di)."""
    n, m = len(target), len(done)
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        dp[i][0] = i
    for j in range(m + 1):
        dp[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            cost = 0 if target[i - 1] == done[j - 1] else 1
            dp[i][j] = min(dp[i - 1][j] + 1, dp[i][j - 1] + 1, dp[i - 1][j - 1] + cost)
    ops = []
    i, j = n, m
    while i > 0 or j > 0:
        if i > 0 and j > 0 and dp[i][j] == dp[i - 1][j - 1] + (0 if target[i - 1] == done[j - 1] else 1):
            ops.append(("ok" if target[i - 1] == done[j - 1] else "sub", i - 1, j - 1))
            i, j = i - 1, j - 1
        elif i > 0 and dp[i][j] == dp[i - 1][j] + 1:
            ops.append(("miss", i - 1, None))
            i -= 1
        else:
            ops.append(("extra", None, j - 1))
            j -= 1
    return dp[n][m], list(reversed(ops))


def score_try(target: List[str], done: List[Tuple[str, float]], t_start: float) -> Dict:
    moves = [m for m, _ in done]
    times = [t for _, t in done]
    dist, ops = align(target, moves)
    late = []
    prev_t = t_start
    for op, ti, di in ops:
        if op in ("ok", "sub") and di is not None:
            if times[di] - prev_t > LATE_GAP and op == "ok":
                late.append(ti)
            prev_t = times[di]
    errors = dist + 0.5 * len(late)
    # pick the single most useful correction
    tip, step = None, None
    for op, ti, di in ops:
        if op == "miss":
            tip, step = f"You missed step {ti + 1}: {MOVES[target[ti]].lower()}. It comes after " \
                        f"{('the start' if ti == 0 else MOVES[target[ti - 1]].lower())}.", ti
            break
        if op == "sub":
            tip, step = f"Step {ti + 1} is {MOVES[target[ti]].lower()} - you did {MOVES[moves[di]].lower()}.", ti
            break
    if tip is None:
        for op, ti, di in ops:
            if op == "extra":
                tip = f"Extra move: {MOVES[moves[di]].lower()}. Go straight to the next step."
                break
    if tip is None and late:
        i = late[0]
        tip, step = (f"Step {i + 1} ({MOVES[target[i]].lower()}) was late - start it as soon as "
                     f"the step before ends."), i
    if tip is None:
        tip = "Perfect! Keep the same order and go a little faster."
    return {"errors": round(errors, 1), "edit_distance": dist, "late_steps": [i + 1 for i in late],
            "done": moves, "tip": tip, "tip_step": step,
            "ops": [{"op": o, "step": (ti + 1 if ti is not None else None),
                     "move": (moves[di] if di is not None else None)} for o, ti, di in ops]}


def coachability_score(errors: List[float], n: int) -> Dict:
    """0-100. Mostly how much errors fall (learning), partly final accuracy."""
    if not errors:
        return {"score": 0.0, "reduction_pct": 0, "note": "no tries"}
    first = errors[0]
    final = sum(errors[-2:]) / len(errors[-2:])
    accuracy = max(0.0, min(1.0, 1 - final / max(n, 1)))
    if first <= 0.5:
        # already perfect on the first try: learning can't be measured, rate on accuracy (ceiling)
        return {"score": round(75 + 15 * accuracy, 1), "reduction_pct": 0,
                "note": "Perfect from the first try - give a longer pattern to measure learning."}
    reduction = max(0.0, min(1.0, (first - final) / first))
    # least-squares slope of errors per try (negative = improving)
    xs = list(range(len(errors)))
    mx, my = sum(xs) / len(xs), sum(errors) / len(errors)
    sxx = sum((x - mx) ** 2 for x in xs) or 1
    slope = sum((x - mx) * (e - my) for x, e in zip(xs, errors)) / sxx
    return {"score": round(100 * (0.65 * reduction + 0.35 * accuracy), 1),
            "reduction_pct": round(100 * reduction), "slope": round(slope, 2)}


def starter_percentile(score: float, age=None) -> int:
    """Percentile against a STARTER norm (mean 45, sd 20) until real data exists."""
    z = (score - 45.0) / 20.0
    return int(round(100 * 0.5 * (1 + math.erf(z / math.sqrt(2)))))


class CoachabilityChallenge(Exercise):
    key, name, icon, category = "coachability", "Coachability Challenge", "🧠", "learning"
    metric, unit, higher_is_better = "coachability", "pts", True
    duration = 300            # hard cap; normally ends after 5 tries
    camera = "front"
    age_groups = "8+"
    setup = ["Face the camera, about 2.5-3 m away, whole body visible, space to step left and right",
             "Stand still with arms down until it says 'ready'",
             "A new 5-move pattern appears - do it in order. You get 5 tries and one tip after each try"]
    counting = ("Each try is compared with the pattern: a wrong, missed or extra move is 1 error, a late move "
                "is half an error. Your score is how much your errors drop from try 1 to the last tries "
                "(learning speed), plus how accurate you are at the end.")
    form_cues = ["Hold each move for a moment so the camera sees it", "Return arms down between tries",
                 "Listen to (or read) the tip - it's about your biggest mistake"]
    blind_adaptation = ["Every move of the pattern is spoken before each try, with its step number",
                        "A tone confirms each move the camera recognises; the tip is spoken",
                        "Steps are relative to the athlete's own body (your left), so no visual reference is needed"]
    deaf_adaptation = ["Pattern shown as numbered cards; the current step lights up",
                       "Tip shown in large captions; green / red flash for right / wrong moves"]

    def __init__(self, seed: Optional[int] = None, **kw):
        super().__init__(**kw)
        self.code, self.pattern = make_pattern(seed)
        self.phase = "ready"            # ready -> preview -> perform -> review -> ready ... -> done
        self.tries: List[Dict] = []
        self.done: List[Tuple[str, float]] = []
        self.base: Optional[Dict] = None
        self.neutral_since: Optional[float] = None
        self.try_start = 0.0
        self.review_until = 0.0
        self.cur_move = "unknown"
        self._cand, self._cand_n = None, 0
        self._last_added = None
        self._calib: deque = deque(maxlen=15)
        self.feedback = "Stand still, arms down, facing the camera"
        self.mirror_label = ""

    # --- helpers
    def _stable_move(self, mv: str) -> Optional[str]:
        if mv == self._cand:
            self._cand_n += 1
        else:
            self._cand, self._cand_n = mv, 1
        return mv if self._cand_n >= STABLE_FRAMES else None

    def _update_base(self, pose: Pose):
        if not pose.vis(L_HIP, R_HIP, L_ANKLE, R_ANKLE):
            return
        hp = pose.mid(L_HIP, R_HIP)
        self._calib.append({"hip_x": hp[0], "hip_y": hp[1],
                            "l_ank_y": pose.p(L_ANKLE)[1], "r_ank_y": pose.p(R_ANKLE)[1]})
        n = len(self._calib)
        self.base = {k: sum(c[k] for c in self._calib) / n for k in self._calib[0]}

    def _start_try(self, t):
        # Preview first: the pattern is shown and spoken; timing starts only at "Go"
        self.phase = "preview"
        self.preview_until = t + PREVIEW_BASE + PREVIEW_PER_STEP * len(self.pattern)
        n = len(self.tries) + 1
        self.feedback = f"Try {n} of {TRIES}: learn the pattern…"
        steps = ". ".join(f"{i + 1}, {MOVES[m]}" for i, m in enumerate(self.pattern))
        self.event("try", f"Try {n}. {steps}.")

    def _go(self, t):
        self.phase = "perform"
        self.done = []
        self.try_start = t
        self._last_added = None
        self.neutral_since = None
        self.feedback = f"Try {len(self.tries) + 1} of {TRIES}: go!"
        self.event("go", "Go!")

    def _end_try(self, t):
        res = score_try(self.pattern, self.done, self.try_start)
        res["try"] = len(self.tries) + 1
        res["seconds"] = round(t - self.try_start, 1)
        self.tries.append(res)
        self.count = len(self.tries)
        self.feedback = f"Try {res['try']}: {res['errors']:g} errors. Tip: {res['tip']}"
        self.event("tip", f"{res['errors']:g} errors. {res['tip']}")
        if len(self.tries) >= TRIES:
            self.phase = "done"
            self.finished = True
            sc = coachability_score([x["errors"] for x in self.tries], len(self.pattern))
            self.feedback = f"Finished! Coachability {sc['score']:.0f}/100"
            self.event("end", self.feedback)
        else:
            self.phase = "review"
            self.review_until = t + REVIEW_TIME
            self.neutral_since = None

    # --- main loop
    def process(self, pose, t):
        mv = classify(pose, self.base or {})
        stable = self._stable_move(mv)
        if stable:
            self.cur_move = stable

        if self.phase == "preview":
            if t >= self.preview_until:
                self._go(t)
            return

        if self.phase in ("ready", "review"):
            if self.phase == "review" and t < self.review_until:
                return
            if stable == "neutral":
                self._update_base(pose)
                self.neutral_since = self.neutral_since or t
                left = NEUTRAL_TO_START - (t - self.neutral_since)
                self.feedback = "Ready…" if left > 0 else "Go!"
                if left <= 0 and self.base:
                    self._start_try(t)
            elif stable:
                self.neutral_since = None
                self.feedback = "Stand still with your arms down to start the next try"
            return

        if self.phase == "perform":
            if stable and stable not in ("neutral", "unknown") and stable != self._last_added:
                self.done.append((stable, t))
                self._last_added = stable
                k = len(self.done)
                ok = k <= len(self.pattern) and self.pattern[k - 1] == stable
                self.event("move", f"{'✓' if ok else '✗'} {MOVES[stable]}")
                self.feedback = f"{MOVES[stable]} ({k}/{len(self.pattern)})"
            if stable == "neutral":
                self._last_added = None          # allow the same move again after returning to neutral
                self.neutral_since = self.neutral_since or t
            elif stable:
                self.neutral_since = None
            timeout = len(self.pattern) * 3.0 + 4.0
            finished_moves = len(self.done) >= len(self.pattern) and stable == "neutral"
            gave_up = self.done and self.neutral_since and t - self.neutral_since > FINISH_NEUTRAL
            if finished_moves or gave_up or t - self.try_start > timeout:
                self._end_try(t)

    # --- results
    def value(self):
        return coachability_score([x["errors"] for x in self.tries], len(self.pattern))["score"]

    def stats(self):
        s = super().stats()
        sc = coachability_score([x["errors"] for x in self.tries], len(self.pattern))
        s.update({
            "pattern": [{"key": m, "label": MOVES[m]} for m in self.pattern],
            "pattern_code": self.code,
            "phase": self.phase,
            "tries": [{"try": x["try"], "errors": x["errors"], "tip": x["tip"]} for x in self.tries],
            "current_try": min(len(self.tries) + (1 if self.phase == "perform" else 0), TRIES),
            "done_moves": [MOVES[m] for m, _ in self.done] if self.phase == "perform" else [],
            "current_move": MOVES.get(self.cur_move, self.cur_move),
            "score": sc["score"],
            "percentile": starter_percentile(sc["score"]),
        })
        return s

    def result(self):
        r = super().result()
        errs = [x["errors"] for x in self.tries]
        sc = coachability_score(errs, len(self.pattern))
        r.update({
            "repetitions": None,
            "form_score": None,
            "coachability": {
                "score": sc["score"], "percentile": starter_percentile(sc["score"]),
                "percentile_note": "starter norm (mean 45, sd 20) - replace with real data",
                "errors_per_try": errs, "reduction_pct": sc.get("reduction_pct"), "slope": sc.get("slope"),
                "note": sc.get("note"), "pattern": self.pattern, "pattern_code": self.code,
                "tips": [x["tip"] for x in self.tries], "tries_completed": len(self.tries),
            },
        })
        if len(self.tries) < TRIES:
            r["incomplete"] = True
        return r
