"""
Maturity estimate + Hidden Potential Index.

Maturity offset (years from peak height velocity, PHV) uses the Mirwald et al. (2002)
sex-specific equations:

  Boys:  -9.236 + 0.0002708*LL*SH - 0.001663*Age*LL + 0.007216*Age*SH + 0.02292*(W/H*100)
  Girls: -9.376 + 0.0001882*LL*SH + 0.0022*Age*LL + 0.005841*Age*SH - 0.002658*Age*W + 0.07693*(W/H*100)

  LL = leg length (cm) = height - sitting height, SH = sitting height (cm),
  W = weight (kg), H = height (cm), Age in years.

Limits (stated in the literature): developed on European-ancestry samples, best between
roughly ages 8 and 16-17, and the predictions are less spread out than reality - treat
the result as "about N years before/after the growth spurt", not an exact date.

Hidden Potential Index (0-100) =
    0.30 * maturity-adjusted fitness + 0.40 * coachability + 0.30 * growth headroom
Weights are starter values; tune them once real data exists.
"""

import os
from typing import Dict, List, Optional

import benchmarks

# Typical age at peak height velocity. Common reference values; Indian norms may differ -
# override with DEEPFIT_MEAN_APHV_M / DEEPFIT_MEAN_APHV_F.
MEAN_APHV = {"M": float(os.environ.get("DEEPFIT_MEAN_APHV_M", "13.8")),
             "F": float(os.environ.get("DEEPFIT_MEAN_APHV_F", "11.8"))}
W_FIT, W_COACH, W_HEAD = 0.30, 0.40, 0.30
NON_FITNESS = {"coachability", "growth_measures", "height_weight"}


def _sex(g) -> str:
    g = str(g or "").strip().upper()
    return "F" if g.startswith(("F", "W", "G")) else "M"


def maturity_offset(age: float, sex, height_cm: float, sitting_cm: float, weight_kg: float) -> Dict:
    s = _sex(sex)
    age = float(age)
    H, SH, W = float(height_cm), float(sitting_cm), float(weight_kg)
    LL = H - SH
    wh = W / H * 100
    if s == "M":
        off = -9.236 + 0.0002708 * LL * SH - 0.001663 * age * LL + 0.007216 * age * SH + 0.02292 * wh
    else:
        off = (-9.376 + 0.0001882 * LL * SH + 0.0022 * age * LL + 0.005841 * age * SH
               - 0.002658 * age * W + 0.07693 * wh)
    aphv = age - off
    delta = aphv - MEAN_APHV[s]                # + = later than average (late developer)
    status = "late" if delta >= 1.0 else ("early" if delta <= -1.0 else "on time")
    valid = 8 <= age <= 17.5
    return {
        "maturity_offset": round(off, 2),
        "predicted_aphv": round(aphv, 2),
        "mean_aphv": MEAN_APHV[s],
        "years_vs_average": round(delta, 2),
        "status": status,
        "sitting_height_cm": round(SH, 1), "leg_length_cm": round(LL, 1),
        "sitting_ratio": round(SH / H, 3),
        "valid_age": valid,
        "note": ("Estimate (Mirwald 2002 equation). Most reliable for ages 8-16; treat as ±1 year."
                 if valid else "Outside the 8-17 age range the equation is not reliable - shown for reference only."),
    }


def _ratio(ex: str, value: float, age, gender, population) -> Optional[float]:
    b = benchmarks.evaluate(ex, value, age, gender, population)
    if not b.get("available"):
        return None
    if b.get("percent_of_target") is not None:
        return b["percent_of_target"] / 100.0
    # diff-scored tests (sit and reach): 10 cm above target ~ 2x
    return max(0.0, 1 + (value - b["target"]) / 10.0)


def fitness_index(latest: Dict[str, Dict], age, gender, population="standard") -> Optional[float]:
    """0-100: average of min(result/target, 2) over completed fitness tests (50 = exactly on target)."""
    vals = []
    for ex, d in latest.items():
        if ex in NON_FITNESS or d.get("value") is None or d.get("incomplete"):
            continue
        r = _ratio(ex, float(d["value"]), age, gender, population)
        if r is not None:
            vals.append(min(r, 2.0) * 50)
    return round(sum(vals) / len(vals), 1) if vals else None


def hidden_potential(latest: Dict[str, Dict], age, gender, population="standard") -> Dict:
    """Combine fitness (maturity-adjusted), coachability and growth headroom."""
    out: Dict = {"missing": []}
    try:
        age_f = float(age)
    except (TypeError, ValueError):
        age_f = None

    mat = (latest.get("growth_measures") or {}).get("maturity")
    out["maturity"] = mat
    if not mat:
        out["missing"].append("growth_measures")

    out["fitness_today"] = fitness_index(latest, age_f, gender, population) if age_f else None
    bio_age = None
    if mat and age_f is not None and mat.get("valid_age"):
        bio_age = max(5.0, age_f - mat["years_vs_average"])   # late developer -> younger biological age
    out["biological_age"] = round(bio_age, 1) if bio_age else None
    out["fitness_adjusted"] = fitness_index(latest, bio_age, gender, population) if bio_age else out["fitness_today"]
    if out["fitness_today"] is None:
        out["missing"].append("fitness_tests")

    coach = (latest.get("coachability") or {}).get("coachability")
    out["coachability"] = coach.get("score") if coach else None
    out["coachability_percentile"] = coach.get("percentile") if coach else None
    if coach is None:
        out["missing"].append("coachability")

    # Growth headroom: late developers still have their spurt ahead of them
    if mat and mat.get("valid_age"):
        out["headroom"] = round(max(0.0, min(100.0, 50 + 25 * mat["years_vs_average"])), 1)
    else:
        out["headroom"] = None

    parts = [(out["fitness_adjusted"], W_FIT), (out["coachability"], W_COACH), (out["headroom"], W_HEAD)]
    have = [(v, w) for v, w in parts if v is not None]
    if have:
        wsum = sum(w for _, w in have)
        out["index"] = round(sum(v * w for v, w in have) / wsum, 1)
    else:
        out["index"] = None
    out["complete"] = len(have) == 3
    out["late_bloomer"] = bool(
        mat and mat.get("valid_age") and mat["years_vs_average"] >= 1.0
        and (out["fitness_adjusted"] or 0) >= 50 and (out["coachability"] or 0) >= 60)
    out["summary"] = _summary(out)
    out["weights"] = {"fitness_adjusted": W_FIT, "coachability": W_COACH, "headroom": W_HEAD}
    return out


def _summary(o: Dict) -> str:
    if o["index"] is None:
        return "Take the fitness tests, the Growth Measures test and the Coachability Challenge to get your index."
    bits = []
    if o.get("late_bloomer"):
        bits.append("Late bloomer with high potential: behind peers in growth but keeping up and learning fast.")
    mat = o.get("maturity")
    if mat and mat.get("valid_age"):
        d = mat["years_vs_average"]
        if d >= 1:
            bits.append(f"Growth spurt is about {d:.1f} years later than average - more growth still to come.")
        elif d <= -1:
            bits.append(f"Matured about {-d:.1f} years earlier than average - today's results may flatter future potential.")
        else:
            bits.append("Maturing at a typical pace.")
    if o.get("coachability") is not None:
        c = o["coachability"]
        bits.append("Learns new movements very fast." if c >= 70 else
                    "Learns new movements at a normal pace." if c >= 40 else
                    "Learning speed was low in this session - retest when fresh.")
    if not o["complete"]:
        bits.append("Index is provisional until all three parts are done.")
    return " ".join(bits)


def rank_positions(entries: List[Dict], me: str) -> Dict:
    """entries: [{'ref', 'fitness', 'index'}]. Rank of `me` by today's fitness vs by potential."""
    def rank(key):
        vals = sorted([e for e in entries if e.get(key) is not None], key=lambda e: -e[key])
        for i, e in enumerate(vals, 1):
            if e["ref"] == me:
                return i, len(vals)
        return None, len(vals)
    r_fit, n_fit = rank("fitness")
    r_pot, n_pot = rank("index")
    return {"by_fitness": r_fit, "by_potential": r_pot, "group_size": max(n_fit, n_pot)}
