"""
DeepFit exercise engine.

Every camera test (sit-ups, push-ups, plank, flamingo balance, ...) is one class
with the same interface, so one Flask blueprint (exercise_blueprint.py) and one
page (templates/exercise.html) run all of them.

Input to each exercise: MediaPipe Pose landmarks (33 points, normalised x/y and a
visibility score) for one video frame, plus the time.

    ex = EXERCISES["pushups"]()          # new attempt
    ex.update(pose, t)                   # every frame
    ex.stats()                           # live numbers for the page
    ex.result()                          # final value for the database

Thresholds are deliberately simple and are listed at the top of each class so
they can be tuned after real testing.
"""

import math
import time
from collections import deque
from statistics import median
from typing import Dict, List, Optional

# MediaPipe Pose landmark indices
NOSE = 0
L_SHOULDER, R_SHOULDER = 11, 12
L_ELBOW, R_ELBOW = 13, 14
L_WRIST, R_WRIST = 15, 16
L_INDEX, R_INDEX = 19, 20
L_HIP, R_HIP = 23, 24
L_KNEE, R_KNEE = 25, 26
L_ANKLE, R_ANKLE = 27, 28
L_HEEL, R_HEEL = 29, 30
L_FOOT, R_FOOT = 31, 32

VIS = 0.5  # minimum landmark visibility
FOREARM_RATIO = 0.146      # forearm length / standing height (Drillis & Contini) - turns pixels into cm for curls
MAX_SWING_PCT = 15         # curls: body swing allowed, % of shoulder width
MAX_DRIFT_PCT = 25         # curls: elbow drifting up/forward allowed, % of upper-arm length


class Pose:
    """Landmarks in pixel coordinates (x right, y down) with visibility."""

    def __init__(self, landmarks, width: int, height: int):
        self.w, self.h = width, height
        self.pts = [(lm[0] * width, lm[1] * height, lm[2]) for lm in landmarks]

    @classmethod
    def from_mediapipe(cls, pose_landmarks, width, height):
        return cls([(l.x, l.y, getattr(l, "visibility", 1.0)) for l in pose_landmarks.landmark], width, height)

    def p(self, i):
        return self.pts[i][0], self.pts[i][1]

    def vis(self, *idx) -> bool:
        return all(self.pts[i][2] >= VIS for i in idx)

    def mid(self, a, b):
        return ((self.pts[a][0] + self.pts[b][0]) / 2, (self.pts[a][1] + self.pts[b][1]) / 2)

    def dist(self, a, b) -> float:
        (x1, y1), (x2, y2) = self.p(a), self.p(b)
        return math.hypot(x2 - x1, y2 - y1)

    def best_side(self, left: List[int], right: List[int]) -> Optional[List[int]]:
        """The body side the camera sees better (for side-on exercises)."""
        lv = sum(self.pts[i][2] for i in left)
        rv = sum(self.pts[i][2] for i in right)
        side = left if lv >= rv else right
        return side if self.vis(*side) else None


def angle(a, b, c) -> float:
    """Angle ABC in degrees (points as (x, y))."""
    v1 = (a[0] - b[0], a[1] - b[1])
    v2 = (c[0] - b[0], c[1] - b[1])
    n = math.hypot(*v1) * math.hypot(*v2)
    if n == 0:
        return 180.0
    cos = max(-1.0, min(1.0, (v1[0] * v2[0] + v1[1] * v2[1]) / n))
    return math.degrees(math.acos(cos))


def elevation(a, b) -> float:
    """Angle of the line a->b above the horizontal, 0..90 degrees."""
    dx, dy = b[0] - a[0], a[1] - b[1]
    return math.degrees(math.atan2(abs(dy), abs(dx) + 1e-6))


# ---------------------------------------------------------------- base class

class Exercise:
    key = "base"
    name = "Exercise"
    icon = "🏃"
    category = "general"
    khelo_india = False                    # part of the Khelo India school fitness battery
    age_groups = "9+"
    metric = "reps"                        # what result() reports
    unit = "reps"
    higher_is_better = True
    duration = 60                          # seconds; None = ends by itself
    camera = "side"                        # side | front | none
    setup: List[str] = []
    counting = ""
    form_cues: List[str] = []
    blind_adaptation: List[str] = []
    deaf_adaptation: List[str] = []

    def __init__(self, height_cm: float = 165.0):
        self.height_cm = height_cm or 165.0
        self.count = 0                     # valid reps
        self.invalid = 0                   # reps rejected for form
        self.faults: Dict[str, int] = {}
        self.feedback = "Get into position"
        self.events: deque = deque(maxlen=20)   # rep / fault events for audio & visual cues
        self.finished = False
        self.started_at: Optional[float] = None
        self.last_t = 0.0
        self.pose_seen = False
        self._event_id = 0
        # Audio mirror: 0..1 "how close is the body to the correct position" (None = not applicable)
        self.mirror_value: Optional[float] = None
        self.mirror_label = ""
        self._mirror_hist: deque = deque(maxlen=3)
        self.sm = Smoother()                 # median filter for every signal a threshold is applied to

    # --- helpers for subclasses
    def bones_ok(self, pose: "Pose", pairs, lo: float = 0.65, hi: float = 1.5) -> bool:
        """False when a body segment suddenly looks much longer or shorter than it has been - one landmark was
        put in the wrong place for a frame (bones can't stretch). Such frames are skipped, not counted."""
        if not hasattr(self, "_bones"):
            self._bones: Dict = {}
        lens = [(a, b, pose.dist(a, b)) for a, b in pairs if pose.vis(a, b)]   # only points the model is sure of
        bad = False
        for a, b, L in lens:
            d = self._bones.get((a, b))
            if d is not None and len(d) >= 8:
                m = median(d)
                if m > 0 and not (lo * m <= L <= hi * m):
                    bad = True
        if not bad:
            for a, b, L in lens:
                self._bones.setdefault((a, b), deque(maxlen=45)).append(L)
        return not bad

    def event(self, kind: str, text: str):
        self._event_id += 1
        self.events.append({"id": self._event_id, "kind": kind, "text": text})

    def fault(self, name: str, text: str):
        self.faults[name] = self.faults.get(name, 0) + 1
        self.feedback = text
        self.event("fault", text)

    def rep(self, text: Optional[str] = None):
        self.count += 1
        self.feedback = text or f"Rep {self.count}!"
        self.event("rep", str(self.count))

    # --- interface
    def update(self, pose: Optional[Pose], t: float):
        self.last_t = t
        if self.started_at is None:
            self.started_at = t
        if pose is None:
            self.feedback = "No person detected - step into the camera view"
            self.mirror_value = None
            return
        self.pose_seen = True
        self.process(pose, t)
        m = self.mirror(pose, t)
        if m is None:
            self.mirror_value = None
        else:
            self._mirror_hist.append(max(0.0, min(1.0, m)))
            self.mirror_value = round(sum(self._mirror_hist) / len(self._mirror_hist), 3)

    def mirror(self, pose: Pose, t: float) -> Optional[float]:
        """Audio-mirror signal for this exercise; subclasses override. None = no tone."""
        return None

    def process(self, pose: Pose, t: float):  # pragma: no cover - overridden
        raise NotImplementedError

    def value(self) -> float:
        return float(self.count)

    def stats(self) -> Dict:
        total = self.count + self.invalid
        form = round(100 * self.count / total) if total else (100 if self.count else 0)
        return {
            "value": round(self.value(), 1),
            "unit": self.unit,
            "reps": self.count,
            "invalid_reps": self.invalid,
            "form_percentage": form,
            "feedback": self.feedback,
            "events": list(self.events),
            "finished": self.finished,
            "mirror": self.mirror_value,
            "mirror_label": self.mirror_label,
        }

    def result(self) -> Dict:
        s = self.stats()
        return {
            "value": round(self.value(), 2),
            "unit": self.unit,
            "metric": self.metric,
            "higher_is_better": self.higher_is_better,
            "repetitions": self.count if self.metric == "reps" else None,
            "invalid_reps": self.invalid,
            "form_score": s["form_percentage"],
            "form_faults": dict(self.faults),
        }

    @classmethod
    def info(cls) -> Dict:
        return {
            "key": cls.key, "name": cls.name, "icon": cls.icon, "category": cls.category,
            "khelo_india": cls.khelo_india, "age_groups": cls.age_groups,
            "metric": cls.metric, "unit": cls.unit, "higher_is_better": cls.higher_is_better,
            "duration": cls.duration, "camera": cls.camera, "setup": cls.setup,
            "counting": cls.counting, "form_cues": cls.form_cues,
            "blind_adaptation": cls.blind_adaptation, "deaf_adaptation": cls.deaf_adaptation,
        }


class Smoother:
    """Median of each signal over the last ~0.22 s (at least 3 frames). Pose models jitter and now and then
    put a landmark in the wrong place for a frame or two; a median removes that without lagging behind real
    movement. Every threshold below is applied to smoothed values."""

    def __init__(self, window: float = 0.22, min_n: int = 3):
        self.window, self.min_n = window, min_n
        self.buf: Dict[str, deque] = {}

    def __call__(self, key: str, v: Optional[float], t: float) -> Optional[float]:
        if v is None:
            return None
        d = self.buf.setdefault(key, deque(maxlen=64))
        d.append((t, v))
        while len(d) > self.min_n and t - d[0][0] > self.window:
            d.popleft()
        return median(x for _, x in d)

    def reset(self, *keys):
        for k in keys or list(self.buf):
            self.buf.pop(k, None)


class RepState:
    """Two-threshold rep counter with a little debouncing (frames in a row) and a minimum time between
    stage changes (a real movement can't flip down/up faster than min_gap)."""

    def __init__(self, frames: int = 2, min_gap: float = 0.0):
        self.stage = None
        self.prev = None
        self.frames = frames
        self.min_gap = min_gap
        self._pending = None
        self._n = 0
        self._t_change = -1e9

    def see(self, stage: Optional[str], t: Optional[float] = None) -> Optional[str]:
        """Feed 'down'/'up'/None each frame; returns the new stage when it changes.
        self.prev tells which stage it came from (None at the very start)."""
        if stage is None or stage == self.stage:
            self._pending, self._n = None, 0
            return None
        if stage == self._pending:
            self._n += 1
        else:
            self._pending, self._n = stage, 1
        if self._n >= self.frames and (t is None or self.stage is None or t - self._t_change >= self.min_gap):
            self.prev = self.stage
            self.stage, self._pending, self._n = stage, None, 0
            if t is not None:
                self._t_change = t
            return stage
        return None


# ---------------------------------------------------------------- exercises

class SitUps(Exercise):
    key, name, icon, category = "situps", "Sit-ups", "🏋️", "core"
    duration = 60
    DOWN_ELEV, UP_ELEV = 20, 55   # torso angle above the floor, degrees
    setup = ["Lie on your back, knees bent, feet flat", "Hands crossed on chest or behind head",
             "Place the phone side-on, about 2 m away, whole body visible"]
    counting = "One rep = from lying (torso under 20° from the floor) to sitting up (over 55°) and back down."
    form_cues = ["Keep feet on the floor", "Don't pull your neck", "Shoulders touch the floor each rep"]
    blind_adaptation = ["Spoken count after every rep", "Spoken time left at 30 s and 10 s",
                        "A helper may place the athlete on the mat, then steps out of view"]
    deaf_adaptation = ["Green flash on every counted rep", "Big on-screen countdown and captions"]

    def __init__(self, **kw):
        super().__init__(**kw)
        self.rs = RepState(min_gap=0.25)
        self.mirror_label = "Tone rises as you sit up; highest when you are up"

    def mirror(self, pose, t):
        side = pose.best_side([L_SHOULDER, L_HIP], [R_SHOULDER, R_HIP])
        return _ramp(elevation(pose.p(side[1]), pose.p(side[0])), 5, self.UP_ELEV) if side else None

    def process(self, pose, t):
        side = pose.best_side([L_SHOULDER, L_HIP, L_KNEE], [R_SHOULDER, R_HIP, R_KNEE])
        if not side:
            self.feedback = "Turn side-on so your shoulder, hip and knee are visible"
            return
        if not self.bones_ok(pose, [(side[0], side[1]), (side[1], side[2])]):
            return
        elev = self.sm("elev", elevation(pose.p(side[1]), pose.p(side[0])), t)
        st = self.rs.see("down" if elev < self.DOWN_ELEV else ("up" if elev > self.UP_ELEV else None), t)
        if st == "up":
            self.feedback = "Good - now lie back down"
        elif st == "down":
            if self.rs.prev == "up":
                self.rep()
            else:
                self.feedback = "Sit up!"


def _ramp(x, lo, hi):
    """0 at lo, 1 at hi (works for lo > hi too)."""
    if hi == lo:
        return 1.0
    return max(0.0, min(1.0, (x - lo) / (hi - lo)))


class PartialCurlUp(Exercise):
    key, name, icon, category = "partial_curlup", "Partial Curl-up", "🔄", "core"
    khelo_india, duration = True, 60
    DOWN_ELEV, UP_ELEV = 12, 25   # torso lift above the floor, degrees
    setup = ["Lie on your back, knees bent about 140°, feet flat", "Arms straight by your sides, palms down",
             "Phone side-on, about 2 m away, whole body visible"]
    counting = "One rep = lift shoulders until the torso is about 25° off the floor, then lower until the head is back down."
    form_cues = ["Slide hands forward along the floor", "Keep heels on the floor", "Slow, steady rhythm"]
    blind_adaptation = ["Spoken count and 'lower down' / 'curl up' cues", "Tactile strip on the mat marks how far the hands slide"]
    deaf_adaptation = ["Green flash per counted rep, red border when a rep is not counted", "Captions show 'curl up' / 'lower down'"]

    def __init__(self, **kw):
        super().__init__(**kw)
        self.rs = RepState(min_gap=0.2)
        self.mirror_label = "Tone rises as you curl up; highest at the right height (about 25°)"

    def mirror(self, pose, t):
        side = pose.best_side([L_SHOULDER, L_HIP], [R_SHOULDER, R_HIP])
        if not side:
            return None
        elev = elevation(pose.p(side[1]), pose.p(side[0]))
        return _ramp(elev, 3, self.UP_ELEV) if elev <= 45 else _ramp(elev, 70, 45)   # too high = falls again

    def process(self, pose, t):
        side = pose.best_side([L_SHOULDER, L_HIP, L_KNEE], [R_SHOULDER, R_HIP, R_KNEE])
        if not side:
            self.feedback = "Turn side-on so your shoulder, hip and knee are visible"
            return
        if not self.bones_ok(pose, [(side[0], side[1]), (side[1], side[2])]):
            return
        elev = self.sm("elev", elevation(pose.p(side[1]), pose.p(side[0])), t)
        self.max_elev = max(getattr(self, "max_elev", 0), elev)
        st = self.rs.see("down" if elev < self.DOWN_ELEV else ("up" if elev > self.UP_ELEV else None), t)
        if st == "up":
            self.feedback = "Lower back down"
        elif st == "down":
            if self.rs.prev == "up":
                if self.max_elev > 60:
                    self.invalid += 1
                    self.fault("full_situp", "Not counted - only curl up partway, not a full sit-up")
                else:
                    self.rep()
            else:
                self.feedback = "Curl up"
            self.max_elev = 0


class PushUps(Exercise):
    key, name, icon, category = "pushups", "Push-ups", "💪", "strength"
    khelo_india, duration = True, 60
    DOWN, UP, STRAIGHT = 95, 150, 150   # elbow angle down/up, body line angle
    DOWN_RATIO, UP_RATIO = 0.76, 0.93   # shoulder-to-hand distance vs the straight-arm top (0.71 = elbows at 90°)
    knee_variant = False
    setup = ["Hands under shoulders, body straight from head to heels", "Phone side-on at floor level, about 2 m away"]
    counting = "One rep = lower until the elbows bend to about 90°, then push up until the arms are straight. The body must stay straight."
    form_cues = ["Keep hips in line - no sagging or piking", "Chest goes down, not just the head", "Full lock-out at the top"]
    blind_adaptation = ["Spoken count; spoken 'keep your body straight' when hips sag",
                        "Optional tactile marker (folded towel) under the chest to feel the bottom position"]
    deaf_adaptation = ["Green flash per counted rep, red border when the body line breaks"]

    BAD_LINE_FRAMES, BAD_LINE_SHARE = 3, 0.2   # body line broken for >= 3 frames and >= 20 % of the rep = not counted

    def __init__(self, **kw):
        super().__init__(**kw)
        self.rs = RepState(frames=1, min_gap=0.25)   # one frame is enough: the median + bone check remove glitches
        self.bad_line_in_rep = False
        self._bad_n = self._rep_n = 0
        self.mirror_label = "Tone is highest and steady when your body is a straight line"

    def mirror(self, pose, t):
        end, end_r = (L_KNEE, R_KNEE) if self.knee_variant else (L_ANKLE, R_ANKLE)
        side = pose.best_side([L_SHOULDER, L_HIP, end], [R_SHOULDER, R_HIP, end_r])
        return _ramp(angle(*(pose.p(i) for i in side)), 135, 172) if side else None

    def process(self, pose, t):
        end = L_KNEE if self.knee_variant else L_ANKLE
        end_r = R_KNEE if self.knee_variant else R_ANKLE
        side = pose.best_side([L_SHOULDER, L_ELBOW, L_WRIST, L_HIP, end], [R_SHOULDER, R_ELBOW, R_WRIST, R_HIP, end_r])
        if not side:
            self.feedback = "Turn side-on - shoulder, elbow, wrist, hip and " + ("knee" if self.knee_variant else "ankle") + " must be visible"
            return
        if not self.bones_ok(pose, [(side[0], side[1]), (side[1], side[2]), (side[0], side[3]), (side[3], side[4])]):
            return
        sh, el, wr, hp, en = (pose.p(i) for i in side)
        k = "L" if side[0] == L_SHOULDER else "R"           # the two arms look different from the side: keep apart
        elbow = self.sm("elbow" + k, angle(sh, el, wr), t)
        body = self.sm("body" + k, angle(sh, hp, en), t)
        # depth that a camera a little off side-on can't fake: the shoulder-to-hand line is nearly vertical, so
        # turning the camera doesn't shorten it the way it opens up the elbow angle. The straight-arm reference is
        # the 90th percentile of the last few seconds (one bad frame can't set it).
        reach = self.sm("reach" + k, math.hypot(wr[0] - sh[0], wr[1] - sh[1]), t)
        hist = self.__dict__.setdefault("_reach_hist", {}).setdefault(k, deque(maxlen=120))
        hist.append(reach)
        srt = sorted(hist)
        top = srt[int(0.9 * (len(srt) - 1))]
        ratio = reach / top if (top > 0 and len(srt) >= 10) else 1.0
        # deep enough = the elbow bends AND the shoulders come down (a left/right mix-up of the arms can bend the
        # "elbow" for a frame but can't bring the shoulders down), or the shoulders come right down
        down = (elbow < self.DOWN and ratio < 0.85) or ratio < self.DOWN_RATIO
        up = elbow > self.UP and ratio > self.UP_RATIO
        if not up:                                 # body line is judged over this rep's frames only
            self._rep_n += 1
            if body < self.STRAIGHT:
                self._bad_n += 1
        self.bad_line_in_rep = self._bad_n >= max(self.BAD_LINE_FRAMES, self.BAD_LINE_SHARE * self._rep_n)
        st = self.rs.see("down" if down else ("up" if up else None), t)
        if st == "down":
            self.feedback = "Push up!"
        elif st == "up" and self.rs.prev != "down":
            self._bad_n = self._rep_n = 0
            self.feedback = "Lower your chest"
        elif st == "up":
            if self.bad_line_in_rep:
                self.invalid += 1
                self.fault("body_line", "Not counted - keep your body straight")
            else:
                self.rep()
            self._bad_n = self._rep_n = 0
        elif up and self.rs.stage == "up":
            self._bad_n = self._rep_n = 0          # resting at the top: the next rep starts fresh


class ModifiedPushUps(PushUps):
    key, name, icon = "pushups_modified", "Modified Push-ups (knees)", "🤸"
    knee_variant = True
    setup = ["Knees on the floor, hands under shoulders", "Straight line from head to knees",
             "Phone side-on at floor level, about 2 m away"]
    counting = "Same as push-ups, but the straight line is from shoulders to knees."


class Plank(Exercise):
    key, name, icon, category = "plank", "Plank Hold", "🧱", "core"
    metric, unit, duration = "hold_time", "s", 180
    STRAIGHT, MAX_TORSO_ELEV, GRACE = 155, 40, 2.0
    SETTLE = 0.6          # straight for this long before the clock starts (credited once it starts)
    MIN_HOLD = 3.0        # a break before this much hold = still getting into position, not the end
    setup = ["Forearms on the floor, elbows under shoulders", "Body straight from head to heels",
             "Phone side-on at floor level, about 2 m away"]
    counting = "Time starts when you are in a straight plank and stops when the body line breaks for more than 2 seconds (or at 3 minutes)."
    form_cues = ["Squeeze glutes", "Don't let hips sag or rise", "Breathe steadily"]
    blind_adaptation = ["Spoken time every 10 s", "Spoken warning 'hips' the moment the line breaks, before the 2-second grace ends"]
    deaf_adaptation = ["Large running clock; screen border turns red when the line breaks"]

    def __init__(self, **kw):
        super().__init__(**kw)
        self.hold = 0.0
        self.holding = False
        self.broken_since: Optional[float] = None
        self._prev_t: Optional[float] = None
        self._last_called = 0
        self._good_since: Optional[float] = None
        self.mirror_label = "Tone rises as your hips line up; steady high tone = perfect plank"

    def mirror(self, pose, t):
        side = pose.best_side([L_SHOULDER, L_HIP, L_ANKLE], [R_SHOULDER, R_HIP, R_ANKLE])
        return _ramp(angle(*(pose.p(i) for i in side)), 135, 174) if side else None

    def process(self, pose, t):
        dt = 0.0 if self._prev_t is None else min(0.5, t - self._prev_t)
        self._prev_t = t
        side = pose.best_side([L_SHOULDER, L_HIP, L_ANKLE], [R_SHOULDER, R_HIP, R_ANKLE])
        if not side:                       # can't see the body: the clock pauses, nothing is decided
            self.feedback = "Turn side-on - shoulder, hip and ankle visible"
            return
        if not self.bones_ok(pose, [(side[0], side[1]), (side[1], side[2])]):
            return
        sh, hp, an = (pose.p(i) for i in side)
        good = (self.sm("line", angle(sh, hp, an), t) >= self.STRAIGHT
                and self.sm("elev", elevation(an, sh), t) <= self.MAX_TORSO_ELEV)
        if good and not self.holding:
            if self._good_since is None:
                self._good_since = t
            if t - self._good_since < self.SETTLE:
                self.feedback = "Hold still in a straight plank…"
                return
            self.holding = True
            self.event("start", "Holding")
            dt = t - self._good_since           # the settling time counts once the plank is confirmed
        elif not good and not self.holding:
            self._good_since = None
        if good:
            self.broken_since = None
            self.hold += dt
            self.feedback = f"Hold it! {int(self.hold)} s"
            if int(self.hold) // 10 > self._last_called:
                self._last_called = int(self.hold) // 10
                self.event("tick", f"{self._last_called * 10} seconds")
        elif self.holding:
            if self.broken_since is None:
                self.broken_since = t
                self.fault("line_break", "Fix your hips - straight line!")
            elif t - self.broken_since > self.GRACE:
                if self.hold < self.MIN_HOLD:      # was only settling in: start again, don't end the test
                    self.holding, self.hold, self.broken_since, self._good_since = False, 0.0, None, None
                    self.feedback = "Get into a straight plank to start the clock"
                    return
                self.finished = True
                self.feedback = f"Plank ended at {int(self.hold)} s"
                self.event("end", self.feedback)
        else:
            self.feedback = "Get into a straight plank to start the clock"

    def value(self):
        return self.hold


class Squats(Exercise):
    key, name, icon, category = "squats", "Squats", "🦵", "strength"
    DOWN, UP, MAX_LEAN = 100, 160, 60
    LEAN_FRAMES = 3       # chest too far forward for this many (smoothed) frames = rep not counted
    setup = ["Feet shoulder-width apart, arms forward", "Phone side-on about 2.5 m away, whole body visible"]
    counting = "One rep = bend until the knee angle is under 100° (thighs about parallel), then stand fully up."
    form_cues = ["Chest up", "Knees track over toes", "Heels stay down"]
    blind_adaptation = ["Spoken count; a chair behind the athlete can mark depth by touch (tap and rise)"]
    deaf_adaptation = ["Green flash per rep, red border when the chest drops too far forward"]

    def __init__(self, **kw):
        super().__init__(**kw)
        self.rs = RepState(min_gap=0.25)
        self.lean_bad = False
        self._lean_n = 0
        self.mirror_label = "Tone rises as you go down; highest at full depth"

    def mirror(self, pose, t):
        side = pose.best_side([L_HIP, L_KNEE, L_ANKLE], [R_HIP, R_KNEE, R_ANKLE])
        return _ramp(angle(*(pose.p(i) for i in side)), 170, self.DOWN) if side else None

    def process(self, pose, t):
        side = pose.best_side([L_SHOULDER, L_HIP, L_KNEE, L_ANKLE], [R_SHOULDER, R_HIP, R_KNEE, R_ANKLE])
        if not side:
            self.feedback = "Step back - hip, knee and ankle must be visible"
            return
        if not self.bones_ok(pose, [(side[1], side[2]), (side[2], side[3])]):
            return
        sh, hp, kn, an = (pose.p(i) for i in side)
        knee = self.sm("knee", angle(hp, kn, an), t)
        lean = self.sm("lean", 90 - elevation(hp, sh), t)
        if knee < 130 and lean > self.MAX_LEAN:
            self._lean_n += 1
            self.lean_bad = self._lean_n >= self.LEAN_FRAMES
        st = self.rs.see("down" if knee < self.DOWN else ("up" if knee > self.UP else None), t)
        if st == "down":
            self.feedback = "Drive up!"
        elif st == "up" and self.rs.prev != "down":
            self.lean_bad, self._lean_n = False, 0
            self.feedback = "Squat down"
        elif st == "up":
            if self.lean_bad:
                self.invalid += 1
                self.fault("lean", "Not counted - keep your chest up")
            else:
                self.rep()
            self.lean_bad, self._lean_n = False, 0


class JumpingJacks(Exercise):
    key, name, icon, category = "jumping_jacks", "Jumping Jacks", "⭐", "cardio"
    camera = "front"
    setup = ["Face the camera, about 2.5 m away, whole body visible", "Start with feet together, arms down"]
    counting = "One rep = jump to arms overhead (hands above the head) + feet wide, then back to arms down + feet together."
    form_cues = ["Hands go above the head", "Feet wider than shoulders", "Land softly"]
    blind_adaptation = ["Spoken count after every rep"]
    deaf_adaptation = ["Green flash per rep; big rep counter and captions"]

    def __init__(self, **kw):
        super().__init__(**kw)
        self.rs = RepState(frames=1, min_gap=0.15)
        # jacks are fast (at 10 fps the arms-overhead moment can be a single frame), so no median here; frames where
        # an arm or leg suddenly changes length are skipped instead, and the checks don't care which hand is which
        self.sm = Smoother(window=0.0, min_n=1)

    def process(self, pose, t):
        need = [L_SHOULDER, R_SHOULDER, L_WRIST, R_WRIST, L_ANKLE, R_ANKLE]
        if not pose.vis(*need):
            self.feedback = "Face the camera - hands and feet must be visible"
            return
        if not self.bones_ok(pose, [(L_SHOULDER, L_ELBOW), (L_ELBOW, L_WRIST), (R_SHOULDER, R_ELBOW), (R_ELBOW, R_WRIST),
                                    (L_HIP, L_ANKLE), (R_HIP, R_ANKLE)]):
            return
        shw = self.sm("shw", max(pose.dist(L_SHOULDER, R_SHOULDER), 1), t)
        feet = self.sm("feet", abs(pose.p(L_ANKLE)[0] - pose.p(R_ANKLE)[0]) / shw, t)
        sh_y = min(pose.p(L_SHOULDER)[1], pose.p(R_SHOULDER)[1])
        head_y = pose.p(NOSE)[1] if pose.vis(NOSE) else sh_y - 0.5 * shw
        hand = self.sm("hand", max(pose.p(L_WRIST)[1], pose.p(R_WRIST)[1]) - head_y, t) / shw   # lower hand vs head
        low = self.sm("low", min(pose.p(L_WRIST)[1], pose.p(R_WRIST)[1]) - sh_y, t) / shw
        if hand < 0 and feet > 1.3:
            st = self.rs.see("open", t)
        elif low > 0.3 and feet < 1.0:
            st = self.rs.see("closed", t)
        else:
            st = self.rs.see(None, t)
        if st == "closed" and getattr(self, "_was_open", False):
            self.rep()
            self._was_open = False
        elif st == "open":
            self._was_open = True
            self.feedback = "Back together"


class DumbbellCurls(Exercise):
    key, name, icon, category = "dumbbell_curls", "Dumbbell Curls", "🏋️‍♂️", "strength"
    camera = "front"
    UP, DOWN = 55, 150
    setup = ["Stand facing the camera, a dumbbell (or water bottle) in each hand", "Elbows close to your sides, whole upper body visible"]
    counting = "Each arm counts separately: curl until the elbow angle is under 55°, lower until it is over 150°."
    form_cues = ["Keep elbows pinned", "No swinging", "Control the way down"]
    blind_adaptation = ["Spoken 'left' / 'right' counts", "Helper hands over the weights, then steps out of view"]
    deaf_adaptation = ["Green flash per rep; captions show which arm was counted"]

    EXTENDED = 140                     # elbow angle that counts as "arm hanging" when timing the lift

    def __init__(self, **kw):
        super().__init__(**kw)
        self.state = {"left": "down", "right": "down"}
        self.counts = {"left": 0, "right": 0}
        self._t_state = {"left": -1e9, "right": -1e9}
        # weight analysis (does not change counting, feedback or events - the phone app counts the same way)
        self.load_kg: Optional[float] = None
        self.body_weight_kg: Optional[float] = None
        self.load_check: Optional[Dict] = None          # filled by the server when SAM 3.1 looked for the dumbbell
        self.load_detect: Optional[Dict] = None         # how the weight was found: read off the dumbbell, estimated or typed
        self.reps_detail: List[Dict] = []
        self._forearm = {"left": deque(maxlen=90), "right": deque(maxlen=90)}
        self._upper = {"left": deque(maxlen=90), "right": deque(maxlen=90)}
        self._sw: deque = deque(maxlen=90)
        self._track: Dict[str, Optional[Dict]] = {"left": None, "right": None}
        self._rest: Dict[str, Optional[Dict]] = {"left": None, "right": None}   # body position with the arm hanging

    def configure(self, load_kg=None, body_weight_kg=None, **_):
        try:
            if load_kg is not None and 0 < float(load_kg) <= 60:
                self.load_kg = round(float(load_kg), 2)
        except (TypeError, ValueError):
            pass
        try:
            if body_weight_kg is not None and 15 <= float(body_weight_kg) <= 200:
                self.body_weight_kg = float(body_weight_kg)
        except (TypeError, ValueError):
            pass

    def process(self, pose, t):
        seen = False
        for arm, (s, e, w) in {"left": (L_SHOULDER, L_ELBOW, L_WRIST), "right": (R_SHOULDER, R_ELBOW, R_WRIST)}.items():
            if not pose.vis(s, e, w):
                continue
            seen = True
            raw = angle(pose.p(s), pose.p(e), pose.p(w))
            a = self.sm("a_" + arm, raw, t)                 # counting uses the smoothed angle...
            self._measure(arm, pose, (s, e, w), raw, t)     # ...the weight analysis keeps every raw detail
            if t - self._t_state[arm] < 0.2:           # a real curl can't flip faster than this
                continue
            if self.state[arm] == "down" and a < self.UP:
                self._t_state[arm] = t
                self.state[arm] = "up"
                self.counts[arm] += 1
                self.count += 1
                self.feedback = f"{arm.title()} {self.counts[arm]}"
                self.event("rep", f"{arm} {self.counts[arm]}")
                if self._track[arm] is not None:
                    self._track[arm]["counted"] = True
            elif self.state[arm] == "up" and a > self.DOWN:
                self.state[arm] = "down"
                self._t_state[arm] = t
                self._finish_rep(arm, t)
        if not seen:
            self.feedback = "Face the camera - shoulders, elbows and wrists visible"

    # ---- how the weight moved, per rep
    def _measure(self, arm, pose, ids, a, t):
        s, e, w = ids
        (sx, sy), (ex_, ey), (wx, wy) = pose.p(s), pose.p(e), pose.p(w)
        if a >= 150:
            self._forearm[arm].append(math.hypot(wx - ex_, wy - ey))
            self._upper[arm].append(math.hypot(ex_ - sx, ey - sy))
        sh = pose.mid(L_SHOULDER, R_SHOULDER) if pose.vis(L_SHOULDER, R_SHOULDER) else None
        if sh is not None and arm == "left":
            self._sw.append(pose.dist(L_SHOULDER, R_SHOULDER))
        tr = self._track[arm]
        if self.state[arm] == "down":
            # reference posture: the arm at its straightest (swing and elbow drift are measured from here)
            rest = self._rest[arm]
            if rest is None or a >= rest["a"] - 5:
                self._rest[arm] = {"a": max(a, rest["a"]) if rest else a, "sh": sh, "rel": ey - sy, "wy": wy}
        if self.state[arm] == "down" and a >= self.EXTENDED:
            # arm still hanging: the next rep's lift starts from here
            rest = self._rest[arm]
            self._track[arm] = {"t0": t, "wy0": wy, "rel0": rest["rel"], "sh0": rest["sh"], "min_a": a, "t_top": t,
                                "wy_top": wy, "min_rel": ey - sy, "swing": 0.0, "counted": False}
            if sh is not None and rest["sh"] is not None:
                self._track[arm]["swing"] = math.hypot(sh[0] - rest["sh"][0], sh[1] - rest["sh"][1])
            self._track[arm]["min_rel"] = min(rest["rel"], ey - sy)
            return
        if tr is None:
            return
        if a < tr["min_a"]:
            tr["min_a"], tr["t_top"] = a, t
        tr["wy_top"] = min(tr["wy_top"], wy)
        tr["min_rel"] = min(tr["min_rel"], ey - sy)
        if sh is not None and tr["sh0"] is not None:
            tr["swing"] = max(tr["swing"], math.hypot(sh[0] - tr["sh0"][0], sh[1] - tr["sh0"][1]))

    def _finish_rep(self, arm, t):
        tr, self._track[arm] = self._track[arm], None
        self._rest[arm] = None
        if not tr or not tr["counted"]:
            return
        fore = median(self._forearm[arm]) if self._forearm[arm] else None
        upper = median(self._upper[arm]) if self._upper[arm] else None
        sw = median(self._sw) if self._sw else None
        cm_per_px = (FOREARM_RATIO * self.height_cm) / fore if fore else None
        conc = max(tr["t_top"] - tr["t0"], 1 / 30)
        travel_cm = (tr["wy0"] - tr["wy_top"]) * cm_per_px if cm_per_px else None
        speed = round(travel_cm / 100 / conc, 2) if travel_cm and travel_cm > 0 else None
        swing = round(100 * tr["swing"] / sw, 1) if sw else None
        drift = round(100 * max(0.0, tr["rel0"] - tr["min_rel"]) / upper, 1) if upper else None
        clean = (swing is None or swing <= MAX_SWING_PCT) and (drift is None or drift <= MAX_DRIFT_PCT)
        if len(self.reps_detail) < 120:
            self.reps_detail.append({"arm": arm, "n": self.counts[arm], "t": round(tr["t0"] - (self.started_at or 0), 2),
                                     "top_angle": round(tr["min_a"], 1), "lift_s": round(conc, 2),
                                     "lower_s": round(max(t - tr["t_top"], 0), 2), "speed": speed,
                                     "swing_pct": swing, "drift_pct": drift, "clean": clean})

    def load_summary(self) -> Dict:
        import curl_load
        return curl_load.summarise(self.load_kg, self.reps_detail, self.counts)

    def stats(self):
        s = super().stats()
        s["left_reps"], s["right_reps"] = self.counts["left"], self.counts["right"]
        s["load"] = {"load_kg": self.load_kg, "clean_reps": sum(1 for r in self.reps_detail if r["clean"]),
                     "last": self.reps_detail[-1] if self.reps_detail else None}
        return s

    def result(self):
        r = super().result()
        r["load_kg"] = self.load_kg
        r["load_analysis"] = self.load_summary()
        r["reps_detail"] = self.reps_detail
        if self.load_check is not None:
            r["load_check"] = self.load_check
        if self.load_detect is not None:
            r["load_detect"] = self.load_detect
        return r


class _JumpBase(Exercise):
    """Shared calibration: stand still, measure body size in pixels to convert to cm."""
    camera = "side"
    duration = 90
    ATTEMPTS = 3

    G = 981.0                     # cm/s^2 - flight is ballistic, which lets us find the true top of the jump
    CALIB_N = 12

    def __init__(self, **kw):
        super().__init__(**kw)
        self.calib: deque = deque(maxlen=self.CALIB_N)
        self.base = None                  # dict with standing hip y, ankle x/y, cm_per_px
        self.airborne = False
        self.attempts: List[float] = []
        self.peak_rise = 0.0
        self.land_frames = 0
        self._up_n = 0
        self._flight: List = []           # (t, value) samples while in the air

    @staticmethod
    def _avg_visible(pose, a, b):
        pts = [pose.pts[i] for i in (a, b) if pose.pts[i][2] >= VIS]
        if not pts:
            return None
        return (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))

    def _standing(self, pose):
        """Side view: the far hip / ankle is often hidden behind the body - use whichever are visible."""
        # a hip or ankle put in the wrong place for a frame or two would look like a jump: the rigid parts (torso,
        # thigh, shin) can't change length, so such frames are skipped
        if not self.bones_ok(pose, [(L_SHOULDER, L_HIP), (R_SHOULDER, R_HIP), (L_HIP, L_KNEE), (R_HIP, R_KNEE),
                                    (L_KNEE, L_ANKLE), (R_KNEE, R_ANKLE)], lo=0.75, hi=1.33):
            return None
        head = next((pose.p(i) for i in (NOSE, 2, 5, 7, 8) if pose.pts[i][2] >= VIS), None)
        hip = self._avg_visible(pose, L_HIP, R_HIP)
        ank = self._avg_visible(pose, L_ANKLE, R_ANKLE)
        if head is None or hip is None or ank is None:
            return None
        lv, rv = pose.pts[L_ANKLE][2] >= VIS, pose.pts[R_ANKLE][2] >= VIS
        return {"hip_y": hip[1], "ank_x": ank[0], "ank_y": ank[1], "body_px": ank[1] - head[1],
                "l_ank_y": pose.p(L_ANKLE)[1] if lv else ank[1], "r_ank_y": pose.p(R_ANKLE)[1] if rv else ank[1],
                "both_feet": lv and rv}

    @staticmethod
    def _sd(vals):
        m = sum(vals) / len(vals)
        return math.sqrt(sum((v - m) * (v - m) for v in vals) / len(vals))

    def _calibrate(self, cur):
        self.calib.append(cur)
        if len(self.calib) < self.CALIB_N:
            self.feedback = "Stand still for calibration…"
            return False
        hips = [c["hip_y"] for c in self.calib]
        xs = [c["ank_x"] for c in self.calib]
        body = median(c["body_px"] for c in self.calib)
        # still = the hips and feet only jitter (camera noise), they don't drift or walk
        if self._sd(hips) > 0.015 * body or self._sd(xs) > 0.025 * body:
            self.feedback = "Stand still for calibration…"
            return False
        avg = {k: median(c[k] for c in self.calib) for k in cur if k != "both_feet"}
        # nose is ~0.92 of standing height; ankle ~0.04 above the floor
        avg["cm_per_px"] = (self.height_cm * 0.88) / max(avg["body_px"], 1)
        self.base = avg
        self.calib.clear()
        self.feedback = f"Ready - jump! (attempt {len(self.attempts) + 1} of {self.ATTEMPTS})"
        self.event("ready", self.feedback)
        return True

    def value(self):
        return max(self.attempts) if self.attempts else 0.0

    def _apex(self, samples) -> float:
        """Top of the flight from the hip samples: fit a ballistic curve (fixed gravity), so the peak is right
        even when no frame landed exactly on it (10-15 fps phones) and one bad frame can't inflate it."""
        vals = sorted(v for _, v in samples)
        # the second-highest frame (one jumpy frame can't make a jump) - unless the camera gave only a few frames
        robust = vals[-2] if len(vals) >= 4 else (vals[-1] if vals else 0.0)
        pts = [(t, v) for t, v in samples if v >= 0.5 * robust]
        # the curve fit is only for real flight: time spent above half the height must match free fall, and the fit
        # may only add what a gap between two frames can hide (a slow rise on the toes is not a flight)
        gap = max((b[0] - a[0] for a, b in zip(samples, samples[1:])), default=0.0)
        above = pts[-1][0] - pts[0][0] if pts else 0.0
        if not (robust > 0 and above <= 1.5 * 2 * math.sqrt(robust / self.G) + gap):
            pts = []
        max_gain = 0.5 * self.G * (gap / 2) * (gap / 2) + 2
        for _ in range(3):
            if len(pts) < 3:
                break
            t0 = pts[0][0]
            xs = [t - t0 for t, _ in pts]
            ys = [v + 0.5 * self.G * x * x for x, (_, v) in zip(xs, pts)]
            n = len(xs); mx, my = sum(xs) / n, sum(ys) / n
            sxx = sum((x - mx) * (x - mx) for x in xs)
            if sxx <= 1e-9:
                break
            b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
            a = my - b * mx
            res = [v - (a + b * x - 0.5 * self.G * x * x) for x, (_, v) in zip(xs, pts)]
            worst = max(range(n), key=lambda i: abs(res[i]))
            if abs(res[worst]) > 5 and n > 3:
                pts.pop(worst)
                continue
            top_t = b / self.G
            if min(xs) - 0.1 <= top_t <= max(xs) + 0.1:
                apex = a + b * b / (2 * self.G)
                if robust - 3 <= apex <= robust + max_gain:
                    return max(apex, robust)      # two frames already reached 'robust'; the fit finds the top between frames
            break
        return robust

    def stats(self):
        s = super().stats()
        s["attempts"] = [round(a, 1) for a in self.attempts]
        s["calibrated"] = self.base is not None
        return s


class VerticalJump(_JumpBase):
    key, name, icon, category = "vertical_jump", "Vertical Jump", "⬆️", "power"
    metric, unit = "max_height", "cm"
    setup = ["Stand side-on to the camera, about 3 m away, whole body visible with space above the head",
             "Stand still until it says 'Ready', then jump straight up"]
    counting = "Jump height = how far the hips rise above their standing height, converted to cm using your height. Best of 3 jumps."
    form_cues = ["Swing the arms", "Land on the same spot", "Stand still between jumps"]
    blind_adaptation = ["Spoken 'ready - jump' after calibration", "Clap or beep marks the start of each attempt"]
    deaf_adaptation = ["Caption shows 'Ready - jump!' after calibration; green flash with the height after each jump"]

    def process(self, pose, t):
        cur = self._standing(pose)
        if cur is None:
            self.feedback = "Whole body must be visible (head to feet)"
            return
        if self.base is None:
            self._calibrate(cur)
            return
        rise = (self.base["hip_y"] - cur["hip_y"]) * self.base["cm_per_px"]
        if not self.airborne:
            self._up_n = self._up_n + 1 if rise > 6 else 0
            self._flight = (self._flight + [(t, rise)])[-2:]
            if self._up_n >= 2:                   # two frames in a row: a real take-off, not one bad frame
                self.airborne = True
                self.peak_rise = max(v for _, v in self._flight)
                self.feedback = "Up!"
        elif self.airborne:
            self._flight.append((t, rise))
            self.peak_rise = max(self.peak_rise, rise)
            if rise < 3:
                self.land_frames += 1
                if self.land_frames >= 3:
                    self.airborne, self.land_frames, self._up_n = False, 0, 0
                    self.peak_rise = self._apex(self._flight)
                    self._flight = []
                    if self.peak_rise < 8:        # a heel raise or a wobble, not a jump: ignore, stay ready
                        self.feedback = f"Ready - jump! (attempt {len(self.attempts) + 1} of {self.ATTEMPTS})"
                        return
                    self.attempts.append(self.peak_rise)
                    self.count = len(self.attempts)
                    self.feedback = f"Jump {len(self.attempts)}: {self.peak_rise:.0f} cm"
                    self.event("rep", f"{self.peak_rise:.0f} centimetres")
                    if len(self.attempts) >= self.ATTEMPTS:
                        self.finished = True
                    else:
                        self.base = None   # re-calibrate before next attempt
            else:
                self.land_frames = 0


class BroadJump(_JumpBase):
    key, name, icon, category = "broad_jump", "Standing Broad Jump", "↔️", "power"
    metric, unit = "distance", "cm"
    setup = ["Camera side-on, 3-4 m away, the whole jump area visible (start line and about 2.5 m in front)",
             "Stand still at the start line until it says 'Ready', then jump forward with both feet"]
    counting = "Distance = how far the ankles travel from take-off to landing, converted to cm using your height. Best of 3 jumps."
    form_cues = ["Swing arms forward", "Take off and land with both feet", "Hold the landing, don't step back"]
    blind_adaptation = ["Tactile start line (tape) and a helper's voice from the landing area for direction",
                        "Spoken distance after each jump"]
    deaf_adaptation = ["Caption shows 'Ready - jump!'; distance shown in large text and captions"]

    BACK_TO_LINE_CM = 30          # later attempts start from the same line as the first

    def process(self, pose, t):
        cur = self._standing(pose)
        if cur is None:
            self.feedback = "Whole body must be visible (head to feet)"
            return
        if self.base is None:
            start = getattr(self, "_start", None)
            if start is not None and abs(cur["ank_x"] - start["ank_x"]) * start["cm_per_px"] > self.BACK_TO_LINE_CM:
                # standing still at the landing spot is not a new start - wait until they are back at the line
                self.calib.clear()
                self.feedback = "Walk back to the start line"
                return
            if self._calibrate(cur) and start is None:
                self._start = dict(self.base)
            return
        cpp = self.base["cm_per_px"]
        moved = abs(cur["ank_x"] - self.base["ank_x"]) * cpp
        # take-off = BOTH feet off the floor (walking only lifts one foot at a time); if the far foot is hidden,
        # the visible foot must lift and the hips must rise too
        lifted = min(self.base["l_ank_y"] - cur["l_ank_y"], self.base["r_ank_y"] - cur["r_ank_y"]) * cpp
        hip_up = (self.base["hip_y"] - cur["hip_y"]) * cpp
        off = lifted > 4 and (cur["both_feet"] or hip_up > 3)
        if getattr(self, "_landing", None) is not None:
            self._finish_landing(cur, t)
            return
        if not self.airborne:
            self._up_n = self._up_n + 1 if off else 0
            if self._up_n >= 2:
                self.airborne = True
                self._flight = []
                self.feedback = "Jump!"
        elif self.airborne:
            # landed = the feet have stopped (a camera that is a little tilted or not exactly side-on makes the
            # floor slope in the picture, so "back at the starting height" is not a reliable landing test)
            self._flight.append((t, cur["ank_x"], cur["ank_y"]))
            recent = [f for f in self._flight if t - f[0] <= 0.25][-6:]
            if moved > 20 and len(recent) >= 3:
                span = max(math.hypot(a[1] - b[1], a[2] - b[2]) for a in recent for b in recent) * cpp
                if span < 8:
                    self.airborne, self._up_n = False, 0
                    land_px = abs(median(f[1] for f in recent) - self.base["ank_x"])
                    self._flight = []
                    self._landing = {"px": land_px, "ank_x": median(f[1] for f in recent), "t": t, "calib": []}
                    self.feedback = "Hold the landing…"
            return

    def _finish_landing(self, cur, t):
        """Turn the landing into cm. If the athlete stands still at the landing spot, the body size there gives
        a second scale (a jump towards or away from the camera changes the size), and the two are averaged."""
        L, cpp0 = self._landing, self.base["cm_per_px"]
        near = abs(cur["ank_x"] - L["ank_x"]) * cpp0 < 15
        if near:
            L["calib"].append(cur["body_px"])
        done = (t - L["t"] >= 1.5 and len(L["calib"]) >= 6) or not near or t - L["t"] > 2.5
        if not done:
            return
        cpp = cpp0
        if len(L["calib"]) >= 6:
            tall = sorted(L["calib"])[len(L["calib"]) // 2:]          # standing up again, not the crouched landing
            body = median(tall)
            if abs(body - self.base["body_px"]) < 0.25 * self.base["body_px"]:
                cpp = (cpp0 + (self.height_cm * 0.88) / max(body, 1)) / 2
        moved = L["px"] * cpp
        self._landing = None
        self.attempts.append(moved)
        self.count = len(self.attempts)
        self.feedback = f"Jump {len(self.attempts)}: {moved:.0f} cm - walk back to the start line"
        self.event("rep", f"{moved:.0f} centimetres")
        if len(self.attempts) >= self.ATTEMPTS:
            self.finished = True
        else:
            self.base = None


class SitAndReach(Exercise):
    key, name, icon, category = "sit_and_reach", "Sit and Reach", "🙆", "flexibility"
    khelo_india = True
    metric, unit, duration, higher_is_better = "reach", "cm", 45, True
    STRAIGHT_LEG, HOLD = 150, 1.0
    setup = ["Sit on the floor, legs straight, feet against a box or wall, side-on to the camera",
             "Reach forward slowly with both hands together and hold the furthest point for 1 second"]
    counting = "Reach = how far the fingertips go past the toes (negative if they stop before the toes), measured while the knees stay straight. Best held reach counts."
    form_cues = ["Keep knees flat", "No bouncing", "Hands together, hold 1 second"]
    blind_adaptation = ["A ruler with raised markings along the floor; spoken best reach after each hold"]
    deaf_adaptation = ["Live reach shown in captions; green flash when a new best reach is held"]

    def __init__(self, **kw):
        super().__init__(**kw)
        self.best: Optional[float] = None
        self.window: deque = deque()
        self.leg_px: deque = deque(maxlen=30)
        self._last_reach = None
        self.mirror_label = "Low tone = bend in the knees; tone rises the further you reach"

    def mirror(self, pose, t):
        side = pose.best_side([L_HIP, L_KNEE, L_ANKLE], [R_HIP, R_KNEE, R_ANKLE])
        if not side:
            return None
        knee = angle(*(pose.p(i) for i in side))
        if knee < self.STRAIGHT_LEG or self._last_reach is None:
            return 0.3 * _ramp(knee, 110, self.STRAIGHT_LEG)
        return 0.35 + 0.65 * _ramp(self._last_reach, -15, 15)

    def process(self, pose, t):
        side = pose.best_side([L_HIP, L_KNEE, L_ANKLE, L_FOOT, L_INDEX], [R_HIP, R_KNEE, R_ANKLE, R_FOOT, R_INDEX])
        if not side:
            self.feedback = "Sit side-on - hip, knee, foot and hand must be visible"
            return
        hp, kn, an, ft, fi = (pose.p(i) for i in side)
        if self.sm("knee", angle(hp, kn, an), t) < self.STRAIGHT_LEG:
            self.feedback = "Keep your knees straight"
            self.window.clear()
            return
        self.leg_px.append(math.hypot(an[0] - hp[0], an[1] - hp[1]))
        leg = sorted(self.leg_px)[len(self.leg_px) // 2]
        cm_per_px = (0.47 * self.height_cm) / max(leg, 1)        # hip-to-ankle ≈ 47% of height
        direction = 1 if ft[0] > hp[0] else -1                   # which way the legs point
        reach = (fi[0] - ft[0]) * direction * cm_per_px
        self._last_reach = reach
        self.window.append((t, reach))
        while self.window and t - self.window[0][0] > self.HOLD:
            self.window.popleft()
        vals = [r for _, r in self.window]
        if self.window and t - self.window[0][0] >= self.HOLD * 0.9 and len(vals) >= 5 and self._still(self.window):
            held = median(vals)
            if self.best is None or held > self.best + 0.5:
                self.best = held
                self.event("rep", f"{held:.0f} centimetres")
            self.feedback = f"Held {held:+.0f} cm - best {self.best:+.0f} cm"
        else:
            self.feedback = f"Reach… {reach:+.0f} cm"

    @staticmethod
    def _still(window) -> bool:
        """Held = the reach isn't moving: the trend over the last second is under 4 cm/s and the points stay
        within a few cm of it (camera jitter on the fingertip is allowed, sliding forward or bouncing isn't)."""
        ts = [t for t, _ in window]; vs = [v for _, v in window]
        n = len(ts); mt, mv = sum(ts) / n, sum(vs) / n
        stt = sum((x - mt) * (x - mt) for x in ts)
        slope = sum((x - mt) * (y - mv) for x, y in zip(ts, vs)) / stt if stt > 1e-9 else 0.0
        res = sorted(abs(y - (mv + slope * (x - mt))) for x, y in zip(ts, vs))
        return abs(slope) < 4.0 and res[int(0.8 * (n - 1))] < 5.0

    def value(self):
        return self.best if self.best is not None else 0.0


class FlamingoBalance(Exercise):
    key, name, icon, category = "flamingo_balance", "Flamingo Balance", "🦩", "balance"
    khelo_india, age_groups = True, "5-8 (all ages useful)"
    metric, unit, duration, higher_is_better = "falls", "falls", 60, False
    LIFT, DOWN_TIME = 0.06, 0.3
    camera = "front"
    setup = ["Face the camera, about 2.5 m away, whole body visible", "Stand on one leg, hold the other foot behind you with the same-side hand",
             "The 60-second clock starts once you are balanced"]
    counting = "Count the number of times the lifted foot touches the floor (or you lose balance) in 60 seconds of balancing. Fewer is better."
    form_cues = ["Fix your eyes on one spot", "Tighten your core", "Re-take the position quickly after a fall"]
    blind_adaptation = ["Proposed: allowed one fingertip of light touch on a wall (record 'touch support' with the result)",
                        "Spoken count of falls and time left"]
    deaf_adaptation = ["Same rules; falls flash on screen", "Note: some deaf athletes have inner-ear balance differences - use the deaf benchmark"]

    def __init__(self, **kw):
        super().__init__(**kw)
        self.balance_time = 0.0
        self.balancing = False
        self.down_since: Optional[float] = None
        self._prev_t: Optional[float] = None
        self.falls = 0
        self._sway: deque = deque(maxlen=12)
        self.mirror_label = "Steady high tone = steady balance; the tone drops and wobbles as you sway"

    def mirror(self, pose, t):
        if not pose.vis(L_HIP, R_HIP, L_SHOULDER, R_SHOULDER):
            return None
        shw = max(pose.dist(L_SHOULDER, R_SHOULDER), 1)
        self._sway.append(pose.mid(L_HIP, R_HIP)[0] / shw)
        if len(self._sway) < 4:
            return 1.0
        mean = sum(self._sway) / len(self._sway)
        sd = (sum((v - mean) ** 2 for v in self._sway) / len(self._sway)) ** 0.5
        return _ramp(sd, 0.12, 0.02) if self.balancing else 0.2

    def process(self, pose, t):
        dt = 0.0 if self._prev_t is None else min(0.5, t - self._prev_t)
        self._prev_t = t
        if not pose.vis(L_ANKLE, R_ANKLE, NOSE):
            self.feedback = "Whole body must be visible"
            return
        body = max(pose.mid(L_ANKLE, R_ANKLE)[1] - pose.p(NOSE)[1], 1)
        lifted = self.sm("lift", abs(pose.p(L_ANKLE)[1] - pose.p(R_ANKLE)[1]) / body, t) > self.LIFT
        if lifted and not self.balancing:
            if getattr(self, "_up_since", None) is None:
                self._up_since = t
            if t - self._up_since < 0.5:              # a wobble while getting into position is not a start
                self.feedback = "Hold the position…"
                return
        elif not lifted and not self.balancing:
            self._up_since = None
        if lifted:
            self.down_since = None
            if not self.balancing:
                self.balancing = True
                if getattr(self, "_up_since", None) is not None:
                    dt = t - self._up_since              # the settling half-second counts once confirmed
                self._up_since = None
                self.event("start", "Balancing")
            self.balance_time += dt
            self.feedback = f"Balancing… {int(self.balance_time)} s · falls {self.falls}"
            if self.balance_time >= 60:
                self.finished = True
                self.feedback = f"Done - {self.falls} falls"
        elif self.balancing:
            if self.down_since is None:
                self.down_since = t
            elif t - self.down_since >= self.DOWN_TIME:
                self.balancing = False
                self.down_since = None
                self.falls += 1
                self.fault("fall", f"Fall {self.falls} - lift your foot again")
        else:
            self.feedback = "Lift one foot behind you to start the clock"

    def value(self):
        return float(self.falls)

    def stats(self):
        s = super().stats()
        s["balance_time"] = round(self.balance_time, 1)
        s["falls"] = self.falls
        return s


class PlateTapping(Exercise):
    key, name, icon, category = "plate_tapping", "Plate Tapping", "👋", "coordination"
    khelo_india, age_groups = True, "5-8 (all ages useful)"
    metric, unit, duration, higher_is_better = "time", "s", 60, False
    CYCLES = 25
    camera = "front"
    setup = ["Face the camera at a table or standing, about 1.5 m away, upper body visible",
             "Two targets appear on screen left and right of you - touch them alternately with your preferred hand",
             "Timer starts at the first touch and stops after 25 full cycles (50 touches)"]
    counting = "Time to complete 25 left-right cycles. Lower is better."
    form_cues = ["Move only the tapping hand", "Touch the centre of each target", "Stay relaxed and rhythmic"]
    blind_adaptation = ["Use two physical plates at arm's length; a short beep confirms each valid touch",
                        "Helper guides the hand to each plate once before the test"]
    deaf_adaptation = ["Target lights up when touched; cycle counter in large text"]

    def __init__(self, **kw):
        super().__init__(**kw)
        self.targets = None
        self.next_side = "left"
        self.touches = 0
        self.t_first: Optional[float] = None
        self.t_done: Optional[float] = None

    def process(self, pose, t):
        if not pose.vis(L_SHOULDER, R_SHOULDER):
            self.feedback = "Face the camera - shoulders visible"
            return
        shw = max(pose.dist(L_SHOULDER, R_SHOULDER), 1)
        c = pose.mid(L_SHOULDER, R_SHOULDER)
        if self.targets is None:
            y = c[1] + 0.9 * shw
            # Image left/right (the athlete sees a mirrored preview)
            self.targets = {"left": (c[0] - 1.3 * shw, y, 0.45 * shw), "right": (c[0] + 1.3 * shw, y, 0.45 * shw)}
        tx, ty, r = self.targets[self.next_side]
        if self._touched(pose, (tx, ty), r, shw):
            self.touches += 1
            if self.t_first is None:
                self.t_first = t
                self.event("start", "Go")
            self.event("tap", self.next_side)
            self.next_side = "right" if self.next_side == "left" else "left"
            self.count = self.touches // 2
            if self.count >= self.CYCLES:
                self.t_done = t
                self.finished = True
                self.feedback = f"Done in {self.value():.1f} s"
                return
        self.feedback = f"Cycles {self.count}/{self.CYCLES} - touch the {self.next_side.upper()} target"

    @staticmethod
    def _seg_dist(p, a, b) -> float:
        """Distance from point p to the segment a-b (where the hand passed between two frames)."""
        ax, ay = a; bx, by = b; px, py = p
        dx, dy = bx - ax, by - ay
        L = dx * dx + dy * dy
        u = 0.0 if L <= 1e-9 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L))
        return math.hypot(ax + u * dx - px, ay + u * dy - py)

    def _touched(self, pose, target, r, shw) -> bool:
        prev = getattr(self, "_prev_hand", {})
        now = {i: pose.p(i) for i in (L_WRIST, R_WRIST, L_INDEX, R_INDEX) if pose.vis(i)}
        self._prev_hand = now
        hit = False
        for wr, ix in ((L_WRIST, L_INDEX), (R_WRIST, R_INDEX)):
            d = {}
            for i in (wr, ix):
                if i not in now:
                    continue
                a = prev.get(i)
                if a is None or math.hypot(now[i][0] - a[0], now[i][1] - a[1]) > 3.0 * shw:
                    a = now[i]                       # first sight, or a jump no hand can make in one frame
                d[i] = self._seg_dist(target, a, now[i])
            # a touch: a hand point is on the target now (as before), or the hand passed over it between two frames
            # (fast tapping at 10-15 fps) - for a pass-over, wrist and fingertip must both have crossed it
            if any(math.hypot(now[i][0] - target[0], now[i][1] - target[1]) < r for i in d):
                hit = True
            elif len(d) == 2 and max(d.values()) < r:
                hit = True
        return hit

    def value(self):
        if self.t_first is None:
            return 0.0
        end = self.t_done if self.t_done is not None else self.last_t
        return end - self.t_first

    def result(self):
        r = super().result()
        if self.t_done is None:
            r["incomplete"] = True        # did not finish 25 cycles in the time limit
            r["value"] = float(self.duration)
        return r

    def stats(self):
        s = super().stats()
        s["cycles"], s["next_target"] = self.count, self.next_side
        s["targets"] = self.targets
        return s


class _Stopwatch(Exercise):
    """Coach-timed tests (no pose tracking): the page shows a stopwatch."""
    camera = "none"
    metric, unit, higher_is_better = "time", "s", False
    duration = None

    def __init__(self, **kw):
        super().__init__(**kw)
        self.manual_value: Optional[float] = None

    def process(self, pose, t):
        self.feedback = "Use the stopwatch: Start on 'Go', Stop at the finish line"

    def value(self):
        return self.manual_value or 0.0


class Dash50m(_Stopwatch):
    key, name, icon, category = "dash_50m", "50 m Dash", "🏃", "speed"
    khelo_india = True
    setup = ["Mark 50 m on a flat track", "Coach presses Start on 'Go' and Stop when the chest crosses the line"]
    counting = "Time in seconds (coach-timed). Lower is better."
    form_cues = ["Start from a standing start", "Run through the finish line"]
    blind_adaptation = ["Run with a guide runner on a tether (as in para-athletics) or along a guide rope", "Audio 'Go' signal"]
    deaf_adaptation = ["Visual start: flag drop or start light instead of a whistle"]


class Run600m(_Stopwatch):
    key, name, icon, category = "run_600m", "600 m Run/Walk", "🏟️", "endurance"
    khelo_india = True
    setup = ["Use a measured track (e.g. 1.5 laps of 400 m)", "Walking is allowed; coach times the whole distance"]
    counting = "Time in seconds (coach-timed). Lower is better."
    form_cues = ["Pace yourself evenly", "Walk if you need to - keep moving"]
    blind_adaptation = ["Guide runner with tether; lap count announced by the guide"]
    deaf_adaptation = ["Visual start; lap count shown on a board"]


ORDER = [SitUps, PartialCurlUp, PushUps, ModifiedPushUps, Plank, Squats, JumpingJacks, DumbbellCurls,
         VerticalJump, BroadJump, SitAndReach, FlamingoBalance, PlateTapping, Dash50m, Run600m]
EXERCISES: Dict[str, type] = {cls.key: cls for cls in ORDER}


def catalog() -> List[Dict]:
    return [cls.info() for cls in ORDER]


# ---------------------------------------------------------------- extra tests in their own modules
def _register_extras():
    """Coachability Challenge and Growth Measures live in their own files (they import this one)."""
    import importlib
    for mod, name in (("stature", "HeightWeight"), ("growth", "GrowthMeasures"), ("coachability", "CoachabilityChallenge")):
        try:
            cls = getattr(importlib.import_module(mod), name)
        except Exception:        # that module is being imported right now (it imports this one) - it registers itself
            continue
        add_exercise(cls)


def add_exercise(cls):
    if cls.key not in EXERCISES:
        ORDER.append(cls)
        EXERCISES[cls.key] = cls


_register_extras()
