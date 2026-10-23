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

    # --- helpers for subclasses
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


class RepState:
    """Two-threshold rep counter with a little debouncing."""

    def __init__(self, frames: int = 2):
        self.stage = None
        self.prev = None
        self.frames = frames
        self._pending = None
        self._n = 0

    def see(self, stage: Optional[str]) -> Optional[str]:
        """Feed 'down'/'up'/None each frame; returns the new stage when it changes.
        self.prev tells which stage it came from (None at the very start)."""
        if stage is None or stage == self.stage:
            self._pending, self._n = None, 0
            return None
        if stage == self._pending:
            self._n += 1
        else:
            self._pending, self._n = stage, 1
        if self._n >= self.frames:
            self.prev = self.stage
            self.stage, self._pending, self._n = stage, None, 0
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
        self.rs = RepState()
        self.mirror_label = "Tone rises as you sit up; highest when you are up"

    def mirror(self, pose, t):
        side = pose.best_side([L_SHOULDER, L_HIP], [R_SHOULDER, R_HIP])
        return _ramp(elevation(pose.p(side[1]), pose.p(side[0])), 5, self.UP_ELEV) if side else None

    def process(self, pose, t):
        side = pose.best_side([L_SHOULDER, L_HIP, L_KNEE], [R_SHOULDER, R_HIP, R_KNEE])
        if not side:
            self.feedback = "Turn side-on so your shoulder, hip and knee are visible"
            return
        elev = elevation(pose.p(side[1]), pose.p(side[0]))
        st = self.rs.see("down" if elev < self.DOWN_ELEV else ("up" if elev > self.UP_ELEV else None))
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
        self.rs = RepState()
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
        elev = elevation(pose.p(side[1]), pose.p(side[0]))
        self.max_elev = max(getattr(self, "max_elev", 0), elev)
        st = self.rs.see("down" if elev < self.DOWN_ELEV else ("up" if elev > self.UP_ELEV else None))
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
    knee_variant = False
    setup = ["Hands under shoulders, body straight from head to heels", "Phone side-on at floor level, about 2 m away"]
    counting = "One rep = lower until the elbows bend to about 90°, then push up until the arms are straight. The body must stay straight."
    form_cues = ["Keep hips in line - no sagging or piking", "Chest goes down, not just the head", "Full lock-out at the top"]
    blind_adaptation = ["Spoken count; spoken 'keep your body straight' when hips sag",
                        "Optional tactile marker (folded towel) under the chest to feel the bottom position"]
    deaf_adaptation = ["Green flash per counted rep, red border when the body line breaks"]

    def __init__(self, **kw):
        super().__init__(**kw)
        self.rs = RepState()
        self.bad_line_in_rep = False
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
        sh, el, wr, hp, en = (pose.p(i) for i in side)
        elbow = angle(sh, el, wr)
        body = angle(sh, hp, en)
        if body < self.STRAIGHT:
            self.bad_line_in_rep = True
        st = self.rs.see("down" if elbow < self.DOWN else ("up" if elbow > self.UP else None))
        if st == "down":
            self.feedback = "Push up!"
        elif st == "up" and self.rs.prev != "down":
            self.bad_line_in_rep = False
            self.feedback = "Lower your chest"
        elif st == "up":
            if self.bad_line_in_rep:
                self.invalid += 1
                self.fault("body_line", "Not counted - keep your body straight")
            else:
                self.rep()
            self.bad_line_in_rep = False


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
        self.mirror_label = "Tone rises as your hips line up; steady high tone = perfect plank"

    def mirror(self, pose, t):
        side = pose.best_side([L_SHOULDER, L_HIP, L_ANKLE], [R_SHOULDER, R_HIP, R_ANKLE])
        return _ramp(angle(*(pose.p(i) for i in side)), 135, 174) if side else None

    def process(self, pose, t):
        dt = 0.0 if self._prev_t is None else min(0.5, t - self._prev_t)
        self._prev_t = t
        side = pose.best_side([L_SHOULDER, L_HIP, L_ANKLE], [R_SHOULDER, R_HIP, R_ANKLE])
        good = False
        if side:
            sh, hp, an = (pose.p(i) for i in side)
            good = angle(sh, hp, an) >= self.STRAIGHT and elevation(an, sh) <= self.MAX_TORSO_ELEV
        if good:
            self.broken_since = None
            if not self.holding:
                self.holding = True
                self.event("start", "Holding")
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
                self.finished = True
                self.feedback = f"Plank ended at {int(self.hold)} s"
                self.event("end", self.feedback)
        else:
            self.feedback = "Get into a straight plank to start the clock" if side else "Turn side-on - shoulder, hip and ankle visible"

    def value(self):
        return self.hold


class Squats(Exercise):
    key, name, icon, category = "squats", "Squats", "🦵", "strength"
    DOWN, UP, MAX_LEAN = 100, 160, 55
    setup = ["Feet shoulder-width apart, arms forward", "Phone side-on about 2.5 m away, whole body visible"]
    counting = "One rep = bend until the knee angle is under 100° (thighs about parallel), then stand fully up."
    form_cues = ["Chest up", "Knees track over toes", "Heels stay down"]
    blind_adaptation = ["Spoken count; a chair behind the athlete can mark depth by touch (tap and rise)"]
    deaf_adaptation = ["Green flash per rep, red border when the chest drops too far forward"]

    def __init__(self, **kw):
        super().__init__(**kw)
        self.rs = RepState()
        self.lean_bad = False
        self.mirror_label = "Tone rises as you go down; highest at full depth"

    def mirror(self, pose, t):
        side = pose.best_side([L_HIP, L_KNEE, L_ANKLE], [R_HIP, R_KNEE, R_ANKLE])
        return _ramp(angle(*(pose.p(i) for i in side)), 170, self.DOWN) if side else None

    def process(self, pose, t):
        side = pose.best_side([L_SHOULDER, L_HIP, L_KNEE, L_ANKLE], [R_SHOULDER, R_HIP, R_KNEE, R_ANKLE])
        if not side:
            self.feedback = "Step back - hip, knee and ankle must be visible"
            return
        sh, hp, kn, an = (pose.p(i) for i in side)
        knee = angle(hp, kn, an)
        lean = 90 - elevation(hp, sh)
        if knee < 130 and lean > self.MAX_LEAN:
            self.lean_bad = True
        st = self.rs.see("down" if knee < self.DOWN else ("up" if knee > self.UP else None))
        if st == "down":
            self.feedback = "Drive up!"
        elif st == "up" and self.rs.prev != "down":
            self.lean_bad = False
            self.feedback = "Squat down"
        elif st == "up":
            if self.lean_bad:
                self.invalid += 1
                self.fault("lean", "Not counted - keep your chest up")
            else:
                self.rep()
            self.lean_bad = False


class JumpingJacks(Exercise):
    key, name, icon, category = "jumping_jacks", "Jumping Jacks", "⭐", "cardio"
    camera = "front"
    setup = ["Face the camera, about 2.5 m away, whole body visible", "Start with feet together, arms down"]
    counting = "One rep = jump to arms overhead + feet wide, then back to arms down + feet together."
    form_cues = ["Hands go above the head", "Feet wider than shoulders", "Land softly"]
    blind_adaptation = ["Spoken count after every rep"]
    deaf_adaptation = ["Green flash per rep; big rep counter and captions"]

    def __init__(self, **kw):
        super().__init__(**kw)
        self.rs = RepState()

    def process(self, pose, t):
        need = [L_SHOULDER, R_SHOULDER, L_WRIST, R_WRIST, L_ANKLE, R_ANKLE]
        if not pose.vis(*need):
            self.feedback = "Face the camera - hands and feet must be visible"
            return
        shw = max(pose.dist(L_SHOULDER, R_SHOULDER), 1)
        feet = abs(pose.p(L_ANKLE)[0] - pose.p(R_ANKLE)[0])
        sh_y = min(pose.p(L_SHOULDER)[1], pose.p(R_SHOULDER)[1])
        hands_up = pose.p(L_WRIST)[1] < sh_y and pose.p(R_WRIST)[1] < sh_y
        hands_down = pose.p(L_WRIST)[1] > sh_y + 0.3 * shw and pose.p(R_WRIST)[1] > sh_y + 0.3 * shw
        if hands_up and feet > 1.3 * shw:
            st = self.rs.see("open")
        elif hands_down and feet < 1.0 * shw:
            st = self.rs.see("closed")
        else:
            st = self.rs.see(None)
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
            a = angle(pose.p(s), pose.p(e), pose.p(w))
            self._measure(arm, pose, (s, e, w), a, t)
            if self.state[arm] == "down" and a < self.UP:
                self.state[arm] = "up"
                self.counts[arm] += 1
                self.count += 1
                self.feedback = f"{arm.title()} {self.counts[arm]}"
                self.event("rep", f"{arm} {self.counts[arm]}")
                if self._track[arm] is not None:
                    self._track[arm]["counted"] = True
            elif self.state[arm] == "up" and a > self.DOWN:
                self.state[arm] = "down"
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

    def __init__(self, **kw):
        super().__init__(**kw)
        self.calib: deque = deque(maxlen=20)
        self.base = None                  # dict with standing hip y, ankle x/y, cm_per_px
        self.airborne = False
        self.attempts: List[float] = []
        self.peak_rise = 0.0
        self.land_frames = 0

    def _standing(self, pose):
        need = [NOSE, L_HIP, R_HIP, L_ANKLE, R_ANKLE]
        if not pose.vis(*need):
            return None
        hip = pose.mid(L_HIP, R_HIP)
        ank = pose.mid(L_ANKLE, R_ANKLE)
        nose = pose.p(NOSE)
        return {"hip_y": hip[1], "ank_x": ank[0], "ank_y": ank[1], "body_px": ank[1] - nose[1],
                "l_ank_y": pose.p(L_ANKLE)[1], "r_ank_y": pose.p(R_ANKLE)[1]}

    def _calibrate(self, cur):
        self.calib.append(cur)
        if len(self.calib) < 12:
            self.feedback = "Stand still for calibration…"
            return False
        hips = [c["hip_y"] for c in self.calib]
        xs = [c["ank_x"] for c in self.calib]
        if max(hips) - min(hips) > 0.02 * cur["body_px"] or max(xs) - min(xs) > 0.03 * cur["body_px"]:
            self.feedback = "Stand still for calibration…"
            return False
        n = len(self.calib)
        avg = {k: sum(c[k] for c in self.calib) / n for k in cur}
        # nose is ~0.92 of standing height; ankle ~0.04 above the floor
        avg["cm_per_px"] = (self.height_cm * 0.88) / max(avg["body_px"], 1)
        self.base = avg
        self.calib.clear()
        self.feedback = f"Ready - jump! (attempt {len(self.attempts) + 1} of {self.ATTEMPTS})"
        self.event("ready", self.feedback)
        return True

    def value(self):
        return max(self.attempts) if self.attempts else 0.0

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
        if not self.airborne and rise > 6:
            self.airborne = True
            self.peak_rise = rise
            self.feedback = "Up!"
        elif self.airborne:
            self.peak_rise = max(self.peak_rise, rise)
            if rise < 3:
                self.land_frames += 1
                if self.land_frames >= 3:
                    self.airborne, self.land_frames = False, 0
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

    def process(self, pose, t):
        cur = self._standing(pose)
        if cur is None:
            self.feedback = "Whole body must be visible (head to feet)"
            return
        if self.base is None:
            self._calibrate(cur)
            return
        cpp = self.base["cm_per_px"]
        moved = abs(cur["ank_x"] - self.base["ank_x"]) * cpp
        # take-off = BOTH feet off the floor (walking only lifts one foot at a time)
        lifted = min(self.base["l_ank_y"] - cur["l_ank_y"], self.base["r_ank_y"] - cur["r_ank_y"]) * cpp
        if not self.airborne and lifted > 4:
            self.airborne = True
            self.feedback = "Jump!"
        elif self.airborne:
            on_floor = abs(cur["ank_y"] - self.base["ank_y"]) * cpp < 4
            if on_floor and moved > 20:
                self.land_frames += 1
                if self.land_frames >= 4:
                    self.airborne, self.land_frames = False, 0
                    self.attempts.append(moved)
                    self.count = len(self.attempts)
                    self.feedback = f"Jump {len(self.attempts)}: {moved:.0f} cm - walk back to the start line"
                    self.event("rep", f"{moved:.0f} centimetres")
                    if len(self.attempts) >= self.ATTEMPTS:
                        self.finished = True
                    else:
                        self.base = None
            else:
                self.land_frames = 0


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
        if angle(hp, kn, an) < self.STRAIGHT_LEG:
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
        if self.window and t - self.window[0][0] >= self.HOLD * 0.9 and max(vals) - min(vals) < 3:
            held = sum(vals) / len(vals)
            if self.best is None or held > self.best + 0.5:
                self.best = held
                self.event("rep", f"{held:.0f} centimetres")
            self.feedback = f"Held {held:+.0f} cm - best {self.best:+.0f} cm"
        else:
            self.feedback = f"Reach… {reach:+.0f} cm"

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
        lifted = abs(pose.p(L_ANKLE)[1] - pose.p(R_ANKLE)[1]) / body > self.LIFT
        if lifted:
            self.down_since = None
            if not self.balancing:
                self.balancing = True
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
        hands = [pose.p(i) for i in (L_WRIST, R_WRIST, L_INDEX, R_INDEX) if pose.vis(i)]
        tx, ty, r = self.targets[self.next_side]
        if any(math.hypot(hx - tx, hy - ty) < r for hx, hy in hands):
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
