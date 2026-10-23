"""
DeepFit benchmarks: the target value for each test by age group, gender and
population (standard / blind / deaf).

The numbers live in exercise_benchmarks.csv so coaches can edit them in Excel.
They are STARTER values, set deliberately LOW until real test data is collected
(see build_starter_csv below). Replace them with Khelo India / SAI norms later.

    evaluate("pushups", 12, age=15, gender="M", population="standard")
    -> {"target": 4.5, "met": True, "rating": "Excellent", ...}
"""

import csv
import os
from typing import Dict, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(HERE, "exercise_benchmarks.csv")

AGE_BANDS = [(5, 8), (9, 12), (13, 15), (16, 18), (19, 30), (31, 45), (46, 99)]
POPULATIONS = ("standard", "blind", "deaf")

# exercise: (base target for a 16-18 / 19-30 male, unit, higher_is_better, scoring)
#   scoring "ratio": compare value/target; "diff": compare value-target (for values that can be negative)
STARTER = {
    "situps":           (10, "reps", True, "ratio"),
    "partial_curlup":   (10, "reps", True, "ratio"),
    "pushups":          (5, "reps", True, "ratio"),
    "pushups_modified": (5, "reps", True, "ratio"),
    "plank":            (20, "s", True, "ratio"),
    "squats":           (15, "reps", True, "ratio"),
    "jumping_jacks":    (20, "reps", True, "ratio"),
    "dumbbell_curls":   (10, "reps", True, "ratio"),
    "vertical_jump":    (15, "cm", True, "ratio"),
    "broad_jump":       (80, "cm", True, "ratio"),
    "sit_and_reach":    (-5, "cm", True, "diff"),
    "flamingo_balance": (10, "falls", False, "ratio"),
    "plate_tapping":    (30, "s", False, "ratio"),
    "dash_50m":         (12, "s", False, "ratio"),
    "run_600m":         (300, "s", False, "ratio"),
    "coachability":     (30, "pts", True, "ratio"),     # learning speed score 0-100
}
CATEGORY = {"coachability": "learning", "flamingo_balance": "balance", "plate_tapping": "coordination", "broad_jump": "power",
            "vertical_jump": "power", "dash_50m": "speed", "run_600m": "speed", "sit_and_reach": "flex"}
AGE_FACTOR = {(5, 8): 0.5, (9, 12): 0.75, (13, 15): 0.9, (16, 18): 1.0, (19, 30): 1.0, (31, 45): 0.85, (46, 99): 0.6}


def _population_factor(ex: str, pop: str) -> float:
    cat = CATEGORY.get(ex, "strength")
    if pop == "blind":
        return 0.7 if cat in ("balance", "power", "coordination", "speed") else 0.85
    if pop == "deaf":
        return 0.8 if cat == "balance" else 1.0
    return 1.0


def build_starter_csv(path: str = CSV_PATH) -> None:
    """(Re)generate the CSV with low starter targets for every exercise/age/gender/population."""
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["exercise", "population", "gender", "age_min", "age_max", "target", "unit",
                    "higher_is_better", "scoring", "note"])
        for ex, (base, unit, higher, scoring) in STARTER.items():
            for pop in POPULATIONS:
                for g in ("M", "F"):
                    for band in AGE_BANDS:
                        factor = AGE_FACTOR[band] * _population_factor(ex, pop)
                        if g == "F" and CATEGORY.get(ex) != "flex":
                            factor *= 0.85
                        if scoring == "diff":
                            target = base - (1 - factor) * 10          # e.g. -5 cm -> a bit lower
                        elif higher:
                            target = base * factor
                        else:
                            target = base / factor                     # more time / falls allowed
                        w.writerow([ex, pop, g, band[0], band[1], round(target, 1), unit,
                                    int(higher), scoring, "starter value - replace after field testing"])


_cache = None


def _rows():
    global _cache
    if _cache is None:
        if not os.path.exists(CSV_PATH):
            build_starter_csv()
        with open(CSV_PATH, newline="") as f:
            _cache = list(csv.DictReader(f))
    return _cache


def reload():
    global _cache
    _cache = None


def _norm_gender(g) -> str:
    g = str(g or "").strip().upper()
    return "F" if g.startswith("F") or g.startswith("W") else "M"


def target_for(exercise: str, age: Optional[float], gender, population: str = "standard") -> Optional[Dict]:
    pop = population if population in POPULATIONS else "standard"
    try:
        age = float(int(float(age)))      # completed years; bands are whole-year ranges (9-12, 13-15, ...)
    except (TypeError, ValueError):
        age = 20.0
    g = _norm_gender(gender)
    for r in _rows():
        if (r["exercise"] == exercise and r["population"] == pop and r["gender"] == g
                and float(r["age_min"]) <= age <= float(r["age_max"])):
            return r
    return None


def evaluate(exercise: str, value: float, age=None, gender=None, population: str = "standard") -> Dict:
    r = target_for(exercise, age, gender, population)
    if r is None:
        return {"available": False}
    target = float(r["target"])
    higher = r["higher_is_better"] in ("1", "True", "true")
    if r["scoring"] == "diff":
        delta = value - target
        rating = ("Needs work" if delta < -5 else "Fair" if delta < 0 else "Good" if delta < 10 else "Excellent")
        met = delta >= 0
        pct = None
    else:
        if value <= 0 and higher:
            ratio = 0.0
        elif not higher:
            if value > 0:
                ratio = target / value
            else:   # 0 falls is perfect; 0 seconds means the test wasn't completed
                ratio = 2.0 if r["unit"] == "falls" else 0.0
        else:
            ratio = value / target if target else 0.0
        met = ratio >= 1.0
        rating = ("Needs work" if ratio < 0.75 else "Fair" if ratio < 1.0 else "Good" if ratio < 1.5 else "Excellent")
        pct = round(100 * ratio)
    return {
        "available": True, "target": target, "unit": r["unit"], "higher_is_better": higher,
        "met": met, "rating": rating, "percent_of_target": pct,
        "population": r["population"], "gender": r["gender"], "age_band": f'{r["age_min"]}-{r["age_max"]}',
        "note": r.get("note", ""),
    }


if __name__ == "__main__":
    build_starter_csv()
    print("Wrote", CSV_PATH)
