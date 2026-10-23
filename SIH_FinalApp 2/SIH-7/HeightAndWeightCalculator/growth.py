"""
Growth Measures test: sitting height and leg length from the camera, then the
maturity estimate (potential.maturity_offset).

Why this works with one camera: the camera stays still, so pixels mean the same
distance in both positions.
  1. STAND straight, side-on, on a marked spot: standing eye height in pixels.
     Eye height is ~93.6% of standing height, so cm-per-pixel = 0.936 * height / pixels.
  2. SIT on a chair placed on the same spot (feet still on the floor).
     Seated eye height (cm) = pixels * cm-per-pixel.
     Sitting height = seated eye height - chair height + (head above the eyes, ~6.4% of height).

The athlete (or teacher) types in standing height and weight measured with a tape and
scale - the camera only adds the sitting part, which schools rarely measure.
"""

from collections import deque
from typing import Dict, Optional

from exercise_engine import Exercise, Pose, L_HIP, R_HIP, L_HEEL, R_HEEL, L_FOOT, R_FOOT, L_ANKLE, R_ANKLE
import potential

L_EYE, R_EYE = 2, 5
EYE_RATIO = 0.936          # eye height / standing height (adult anthropometry; ~same in teens)
HOLD = 1.5                 # seconds to hold each position still


class GrowthMeasures(Exercise):
    key, name, icon, category = "growth_measures", "Growth Measures (sitting height)", "📐", "growth"
    metric, unit, higher_is_better = "maturity_offset", "yrs", True
    duration = 120
    camera = "side"
    age_groups = "8-17"
    setup = ["Enter your standing height and weight (measured with a tape and a scale) and the chair height",
             "Camera side-on, 2.5-3 m away, does not move during the test; whole body visible",
             "Stand straight on a marked spot until it says 'now sit', then sit on a chair placed on the SAME spot, back straight, feet flat"]
    counting = ("Measures sitting height and leg length, then estimates how many years you are from your "
                "growth spurt (Mirwald equation). Late developers get extra credit in the Hidden Potential Index.")
    form_cues = ["Stand tall, look straight ahead", "Sit tall, chin level", "Keep the camera and chair still"]
    blind_adaptation = ["A helper marks the spot and places the chair; the app says when to stand and when to sit",
                        "Spoken result at the end"]
    deaf_adaptation = ["Large 'STAND' / 'SIT' captions with a progress bar for each hold"]

    def __init__(self, **kw):
        super().__init__(**kw)
        self.inputs: Dict = {"height_cm": self.height_cm, "weight_kg": None, "chair_cm": 45.0, "age": None, "sex": "M"}
        self.phase = "stand"
        self.buf: deque = deque()
        self.stand_px = None
        self.floor_y = None
        self.cm_per_px = None
        self.measure: Optional[Dict] = None
        self.feedback = "Stand straight, side-on, on the marked spot"

    def configure(self, **inputs):
        self.inputs.update({k: v for k, v in inputs.items() if v is not None})

    def _eye_floor(self, pose: Pose):
        eyes = [pose.p(i)[1] for i in (L_EYE, R_EYE) if pose.vis(i)]
        feet = [pose.p(i)[1] for i in (L_HEEL, R_HEEL, L_FOOT, R_FOOT, L_ANKLE, R_ANKLE) if pose.vis(i)]
        if not eyes or not feet:
            return None
        return min(eyes), max(feet)

    def _stable(self, t, val) -> Optional[float]:
        self.buf.append((t, val))
        while self.buf and t - self.buf[0][0] > HOLD:
            self.buf.popleft()
        vals = [v for _, v in self.buf]
        if t - self.buf[0][0] >= HOLD * 0.9 and max(vals) - min(vals) < 0.02 * max(abs(sum(vals) / len(vals)), 1):
            return sum(vals) / len(vals)
        return None

    def process(self, pose, t):
        if self.phase == "done":
            return
        ef = self._eye_floor(pose)
        if ef is None:
            self.feedback = "Eyes and feet must be visible - step back or move the camera"
            self.buf.clear()
            return
        eye_y, floor_y = ef
        if self.phase == "stand":
            v = self._stable(t, floor_y - eye_y)
            self.feedback = "Stand still… measuring standing height"
            if v:
                H = float(self.inputs["height_cm"])
                self.stand_px, self.floor_y = v, floor_y
                self.stand_hip_y = pose.mid(L_HIP, R_HIP)[1] if pose.vis(L_HIP, R_HIP) else None
                self.cm_per_px = EYE_RATIO * H / v
                self.phase, self.buf = "sit", deque()
                self.feedback = "Now sit on the chair on the same spot, back straight"
                self.event("step", "Now sit on the chair, on the same spot. Back straight, look ahead.")
            return
        if self.phase == "sit":
            hip_y = pose.mid(L_HIP, R_HIP)[1] if pose.vis(L_HIP, R_HIP) else None
            seated = hip_y is not None and self.stand_hip_y is not None and hip_y - self.stand_hip_y > 0.12 * self.stand_px
            if not seated:
                self.buf.clear()
                self.feedback = "Sit down on the chair (same spot)"
                return
            v = self._stable(t, self.floor_y - eye_y)
            self.feedback = "Sit tall and still… measuring sitting height"
            if v:
                self._compute(v)

    def _compute(self, seated_px):
        H = float(self.inputs["height_cm"])
        seated_eye_cm = seated_px * self.cm_per_px
        SH = seated_eye_cm - float(self.inputs["chair_cm"]) + (1 - EYE_RATIO) * H
        ratio = SH / H
        if not 0.44 <= ratio <= 0.60:
            # outside human range: camera moved, wrong chair height, or slouching
            self.phase, self.buf = "stand", deque()
            self.fault("implausible", f"Sitting height came out {ratio:.0%} of height - check the chair height "
                                      "and that the camera did not move. Stand up to start again.")
            return
        m = {"height_cm": round(H, 1), "sitting_height_cm": round(SH, 1)}
        w, age = self.inputs.get("weight_kg"), self.inputs.get("age")
        if w and age:
            m.update(potential.maturity_offset(float(age) + 0.5, self.inputs.get("sex"), H, SH, float(w)))
        self.measure = m
        self.phase = "done"
        self.finished = True
        off = m.get("maturity_offset")
        self.feedback = (f"Sitting height {SH:.0f} cm. " +
                         (f"About {abs(off):.1f} years {'before' if off < 0 else 'after'} the growth spurt ({m['status']} developer)."
                          if off is not None else "Enter weight and age to get the maturity estimate."))
        self.event("end", self.feedback)

    def value(self):
        return (self.measure or {}).get("maturity_offset") or 0.0

    def stats(self):
        s = super().stats()
        s.update({"phase": self.phase, "measure": self.measure})
        return s

    def result(self):
        r = super().result()
        r.update({"repetitions": None, "form_score": None, "maturity": self.measure,
                  "inputs": {k: self.inputs.get(k) for k in ("height_cm", "weight_kg", "chair_cm")}})
        if not self.measure:
            r["incomplete"] = True
        return r
