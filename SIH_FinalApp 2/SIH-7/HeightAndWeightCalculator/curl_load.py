"""
Weighted dumbbell curls: what the camera can and cannot tell about the weight.

Size alone does not tell the weight: an adjustable dumbbell is just as long at 2.5 kg as at 10 kg,
and a water bottle can stand in for a light one. And the body angles depend on how heavy the weight
is FOR THAT PERSON, not on its kilograms: a strong adult curls 10 kg with the same smooth, upright
form a child shows with 2 kg. So DeepFit:
  1. DETECTS the weight: the athlete shows the dumbbell to the camera and a vision model reads the
     number printed on it ("5 KG", "10 LB") - vision_reader.read_dumbbell. If no number is visible it
     estimates from the type and size and asks the athlete to confirm (or pick the weight),
  2. SAM 3.1 checks that a dumbbell really is in the hand during the set,
  3. the camera measures how that weight moved - per rep: how far the elbow bent (top angle),
     how fast the hand rose (m/s), how much the body swung and how far the elbow drifted forward,
     and how much the speed dropped from the first reps to the last (fatigue),
  4. the INTERNAL BENCHMARKS check the weight (weight_check): for that weight and the athlete's
     age group, the table gives the expected lifting speed. A dumbbell that moves far faster than
     anyone in the group could move that weight was lighter than detected; far slower = heavier.
From weight + reps + speed it estimates the one-rep max (1RM): the heaviest curl the athlete could do once.

Benchmarks per weight live in curl_load_benchmarks.csv (edit it in Excel). Each row gives, for an
age band / gender / population and a dumbbell weight: the target clean reps in 60 s, the expected
hand speed and elbow angle at that weight, and the form limits. ALL ARE STARTER VALUES, to be
replaced with values learned from real test data (export_curl_dataset.py writes that dataset).

References for the formulas (the constants for curls are starters):
  Brzycki 1993 / Epley 1985 - 1RM from weight and repetitions
  Gonzalez-Badillo & Sanchez-Medina 2010 - load-velocity relationship, velocity loss as fatigue
  Drillis & Contini 1966 - forearm length is about 0.146 x standing height
"""

import csv
import math
import os
from statistics import mean, median
from typing import Dict, List, Optional

import benchmarks

HERE = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(HERE, "curl_load_benchmarks.csv")

LOADS = [1, 2, 2.5, 3, 4, 5, 6, 7.5, 8, 10, 12.5, 15, 17.5, 20]   # common dumbbells, kg
FOREARM_RATIO = 0.146            # forearm length / standing height
V0, VMVT = 1.4, 0.35             # starter load-velocity line for hand speed in a curl (m/s at 0% and 100% 1RM)
MAX_SWING_PCT = 15               # body swing allowed, % of shoulder width
MAX_DRIFT_PCT = 25               # elbow drifting up/forward, % of upper-arm length
REF_1RM_ADULT_M = 10.0           # starter one-arm curl 1RM (kg) for a 19-30 year old man - deliberately low
AGE_1RM = {(5, 8): 0.3, (9, 12): 0.45, (13, 15): 0.7, (16, 18): 0.9, (19, 30): 1.0, (31, 45): 0.95, (46, 99): 0.8}
FEMALE_1RM = 0.6
POP_1RM = {"standard": 1.0, "blind": 0.85, "deaf": 1.0}


def ref_1rm(age_band, gender: str, population: str) -> float:
    f = AGE_1RM[age_band] * (FEMALE_1RM if gender == "F" else 1.0) * POP_1RM.get(population, 1.0)
    return round(REF_1RM_ADULT_M * f, 2)


def reps_at(load: float, one_rm: float) -> float:
    """Reps someone with this 1RM can do at this load (Brzycki, inverted). 0 = too heavy."""
    if load <= 0 or one_rm <= 0:
        return 0.0
    if load > one_rm:
        return 0.0
    return max(1.0, 37.0 - 36.0 * load / one_rm)


def expected_speed(load: float, one_rm: float) -> float:
    return round(max(VMVT, V0 - (V0 - VMVT) * min(1.0, load / one_rm)), 2)


def expected_top_angle(load: float, one_rm: float) -> float:
    """Elbow angle at the top of the curl. Heavier (for you) = the elbow bends less."""
    return round(35 + 15 * min(1.0, load / one_rm), 1)


def build_csv(path: str = CSV_PATH) -> None:
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["population", "gender", "age_min", "age_max", "load_kg", "target_clean_reps_60s", "expected_speed_m_s",
                    "expected_top_angle_deg", "max_swing_pct", "max_elbow_drift_pct", "ref_1rm_kg", "note"])
        for pop in benchmarks.POPULATIONS:
            for g in ("M", "F"):
                for band in benchmarks.AGE_BANDS:
                    cap = benchmarks.target_for("dumbbell_curls", (band[0] + band[1]) / 2, g, pop)
                    cap_total = float(cap["target"]) if cap else 10.0       # light weights: the 60 s rep target
                    r1 = ref_1rm(band, g, pop)
                    for load in LOADS:
                        per_arm = reps_at(load, r1)
                        target = round(min(cap_total, 2 * per_arm), 1) if per_arm else 0.0
                        w.writerow([pop, g, band[0], band[1], load, target, expected_speed(load, r1), expected_top_angle(load, r1),
                                    MAX_SWING_PCT, MAX_DRIFT_PCT, r1,
                                    "starter value - replace after field testing" if target else "heavier than the starter 1RM - try a lighter dumbbell"])


_cache = None


def _rows():
    global _cache
    if _cache is None:
        if not os.path.exists(CSV_PATH):
            build_csv()
        with open(CSV_PATH, newline="") as f:
            _cache = list(csv.DictReader(f))
    return _cache


def reload():
    global _cache
    _cache = None


def target_for(load: float, age, gender, population: str = "standard") -> Optional[Dict]:
    """The benchmark row for the nearest listed dumbbell weight."""
    pop = population if population in benchmarks.POPULATIONS else "standard"
    try:
        age = float(int(float(age)))
    except (TypeError, ValueError):
        age = 20.0
    g = benchmarks._norm_gender(gender)
    rows = [r for r in _rows() if r["population"] == pop and r["gender"] == g and float(r["age_min"]) <= age <= float(r["age_max"])]
    if not rows or load is None:
        return None
    return min(rows, key=lambda r: abs(float(r["load_kg"]) - load))


# ------------------------------------------------------------------ strength estimates

def one_rm_from_reps(load: float, reps: float) -> Optional[float]:
    if not load or load <= 0 or reps < 1:
        return None
    if reps <= 10:
        return round(load * 36.0 / (37.0 - reps), 1)         # Brzycki
    if reps <= 20:
        return round(load * (1 + reps / 30.0), 1)            # Epley
    return None                                              # too light to say anything about the maximum


def one_rm_from_speed(load: float, speed: Optional[float]) -> Optional[float]:
    if not load or load <= 0 or not speed:
        return None
    pct = (V0 - speed) / (V0 - VMVT)
    if pct < 0.3:                                            # far too light: speed tells us little
        return None
    return round(load / min(pct, 1.0), 1)


def intensity(load: float, speed: Optional[float]) -> Optional[str]:
    if not load or not speed:
        return None
    pct = (V0 - speed) / (V0 - VMVT)
    return "light" if pct < 0.5 else "moderate" if pct < 0.75 else "heavy"


def summarise(load: Optional[float], reps: List[Dict], counts: Dict[str, int]) -> Dict:
    """Everything the result and the benchmark need, from the per-rep measurements."""
    speeds = [r["speed"] for r in reps if r.get("speed")]
    clean = [r for r in reps if r.get("clean")]
    first = round(mean(speeds[:2]), 2) if len(speeds) >= 2 else (speeds[0] if speeds else None)
    last = round(mean(speeds[-2:]), 2) if len(speeds) >= 4 else None
    loss = round(100 * (first - last) / first) if first and last is not None and first > 0 else None
    arms = [c for c in counts.values() if c > 0]
    reps_per_arm = round(mean(arms)) if arms else 0
    clean_per_arm = {a: sum(1 for r in clean if r["arm"] == a) for a in counts}
    est_reps = one_rm_from_reps(load, max(clean_per_arm.values()) if clean_per_arm else 0) if load else None
    est_speed = one_rm_from_speed(load, first)
    if est_reps and loss is not None and loss < 20:
        est_reps_note = "the set did not slow down much, so this is a lower limit"
    else:
        est_reps_note = None
    # a set that slowed down a lot was close to failure, so the reps formula is reliable; otherwise trust the speed
    if est_reps and (loss is None or loss >= 20):
        est = est_reps
    else:
        est = est_speed or est_reps
    nxt = None
    if load and first:
        nxt = (min(LOADS, key=lambda x: abs(x - load * 1.25)) if intensity(load, first) == "light"
               else load if intensity(load, first) == "moderate" else max([x for x in LOADS if x < load] or [load]))
    return {
        "load_kg": load, "reps": len(reps), "clean_reps": len(clean), "reps_per_arm": reps_per_arm,
        "clean_per_arm": clean_per_arm,
        "first_speed_m_s": first, "last_speed_m_s": last, "velocity_loss_pct": loss,
        "mean_top_angle_deg": round(mean(r["top_angle"] for r in reps), 1) if reps else None,
        "mean_swing_pct": round(mean(r["swing_pct"] for r in reps if r.get("swing_pct") is not None), 1) if any(r.get("swing_pct") is not None for r in reps) else None,
        "mean_drift_pct": round(mean(r["drift_pct"] for r in reps if r.get("drift_pct") is not None), 1) if any(r.get("drift_pct") is not None for r in reps) else None,
        "intensity": intensity(load, first),
        "est_1rm_kg": est, "est_1rm_from_reps": est_reps, "est_1rm_from_speed": est_speed, "est_1rm_note": est_reps_note,
        "volume_kg": round((load or 0) * len(reps), 1),
        "next_load_kg": nxt,
    }


PLAUSIBLE_1RM = (0.35, 4.0)      # implied 1RM / the group's reference 1RM that still fits (starter values; the reference is deliberately low)
MAX_1RM_PER_BW = 0.6             # a one-arm curl 1RM above 60 % of body weight is beyond elite lifters


def weight_check(summary: Dict, ref_1rm_kg: float, body_weight_kg: Optional[float] = None) -> Dict:
    """Does the weight fit how it moved? The speed of the first reps says how heavy the dumbbell was
    FOR THIS ATHLETE (% of their 1RM). Weight / that % = the 1RM they would need. If that is far above
    what anyone in their age group (or anyone at their body weight) can lift, the dumbbell was lighter
    than detected; if far below, it was heavier (or the reps were slowed on purpose)."""
    load, v = summary.get("load_kg"), summary.get("first_speed_m_s")
    if not load:
        return {"status": "no_weight"}
    if v is None or summary.get("reps", 0) < 3:
        return {"status": "not_enough_reps", "text": "Do at least 3 reps so the weight can be checked."}
    exp_v = expected_speed(load, ref_1rm_kg)
    pct = min(max((V0 - v) / (V0 - VMVT), 0.05), 1.0)        # share of the athlete's 1RM, from the speed
    implied = load / pct
    ratio = implied / ref_1rm_kg
    like = max(0.5, round(ref_1rm_kg * pct * 2) / 2)           # weight a typical athlete of the group lifts this fast
    per_bw = implied / body_weight_kg if body_weight_kg else None
    out = {"expected_speed_m_s": exp_v, "measured_speed_m_s": v, "implied_1rm_kg": round(implied, 1),
           "ratio_to_group": round(ratio, 2), "moves_like_kg": like, "limits": list(PLAUSIBLE_1RM)}
    if ratio > PLAUSIBLE_1RM[1] or (per_bw is not None and per_bw > MAX_1RM_PER_BW):
        out.update(status="lighter", ok=False,
                   text=f"It moved like a lighter weight: at {load:g} kg we expect about {exp_v} m/s for your group, "
                        f"you lifted at {v} m/s (like ≈ {like:g} kg). Check the number on the dumbbell.")
    elif ratio < PLAUSIBLE_1RM[0]:
        out.update(status="heavier", ok=False,
                   text=f"It moved like a heavier weight: at {load:g} kg we expect about {exp_v} m/s for your group, "
                        f"you lifted at {v} m/s (like ≈ {like:g} kg). Check the dumbbell - or don't slow the lift on purpose.")
    else:
        out.update(status="consistent", ok=True,
                   text=f"The speed fits a {load:g} kg dumbbell: at {v} m/s it was about {round(100 * pct)}% of your max "
                        f"(a typical athlete in your group lifts it at ≈ {exp_v} m/s).")
    return out


def evaluate(summary: Dict, age=None, gender=None, population: str = "standard", body_weight_kg: Optional[float] = None) -> Dict:
    """Benchmark for THIS weight: clean reps against the target for the nearest listed dumbbell."""
    load = summary.get("load_kg")
    r = target_for(load, age, gender, population)
    if r is None:
        return {"available": False}
    target = float(r["target_clean_reps_60s"])
    clean = summary.get("clean_reps", 0)
    out = {
        "available": True, "unit": "reps", "higher_is_better": True, "counted": "clean reps",
        "population": r["population"], "gender": r["gender"], "age_band": f'{r["age_min"]}-{r["age_max"]}',
        "load_kg": load, "benchmark_load_kg": float(r["load_kg"]), "ref_1rm_kg": float(r["ref_1rm_kg"]),
        "expected_speed_m_s": float(r["expected_speed_m_s"]), "expected_top_angle_deg": float(r["expected_top_angle_deg"]),
        "max_swing_pct": float(r["max_swing_pct"]), "max_elbow_drift_pct": float(r["max_elbow_drift_pct"]),
        "note": r.get("note", ""),
    }
    if target <= 0:
        # heavier than the starter maximum for this group: any clean rep beats the reference
        out.update({"target": 1.0, "met": clean >= 1, "percent_of_target": None,
                    "rating": "Excellent" if clean >= 1 else "Needs work",
                    "note": ("Lifted more than the starter maximum for this age group." if clean >= 1
                             else "Heavier than the starter maximum for this age group - try a lighter dumbbell.")})
    else:
        ratio = clean / target
        out.update({"target": target, "met": ratio >= 1.0, "percent_of_target": round(100 * ratio),
                    "rating": "Needs work" if ratio < 0.75 else "Fair" if ratio < 1.0 else "Good" if ratio < 1.5 else "Excellent"})
    out["weight_check"] = weight_check(summary, float(r["ref_1rm_kg"]), body_weight_kg)
    est = summary.get("est_1rm_kg")
    if est:
        out["strength_vs_ref_pct"] = round(100 * est / float(r["ref_1rm_kg"]))
        if body_weight_kg:
            out["est_1rm_per_kg_bodyweight"] = round(est / body_weight_kg, 3)
    return out


# ------------------------------------------------------------------ is a dumbbell really in the hand? (SAM 3.1)

def dumbbell_check(image_data_url: str, img_w: int, img_h: int, wrists: List[tuple], forearm_px: float,
                   cm_per_px: Optional[float] = None) -> Dict:
    """Ask SAM 3.1 for 'dumbbell' boxes and check one is held (box centre within ~1 forearm of a wrist).
    wrists are pixel positions in the same image. Never raises."""
    import meta_models
    if not meta_models.available():
        return {"method": "none", "seen": None, "reason": "Meta API key not set - weight not checked"}
    boxes = meta_models.sam_boxes(image_data_url, "dumbbell")
    if boxes is None:
        return {"method": "sam-3.1", "seen": None, "reason": meta_models.last_error.get("sam") or "SAM unavailable"}
    held = []
    for b in boxes[:6]:
        sx = img_w / b["w"] if b.get("w") else 1.0          # SAM reports pixels of the image it was given
        sy = img_h / b["h"] if b.get("h") else 1.0
        cx, cy = (b["x1"] + b["x2"]) / 2 * sx, (b["y1"] + b["y2"]) / 2 * sy
        if any(math.hypot(cx - wx, cy - wy) <= 1.2 * forearm_px for wx, wy in wrists):
            held.append({"length_cm": round(max(b["x2"] - b["x1"], b["y2"] - b["y1"]) * max(sx, sy) * cm_per_px, 1) if cm_per_px else None,
                         "confidence": b.get("c")})
    return {"method": "sam-3.1", "seen": bool(held), "held": len(held), "boxes": len(boxes),
            "length_cm": held[0]["length_cm"] if held else None}


if __name__ == "__main__":
    build_csv()
    print("Wrote", CSV_PATH)
