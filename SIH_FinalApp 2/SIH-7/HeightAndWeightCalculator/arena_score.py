"""
DeepFit Arena scoring - the server's own calculation from the raw game measurements.

The browser sends what it measured in every trial (reaction times, jump heights, which way
the player moved, the moves they did, pulse estimates). The server recomputes every score
from those raw values and ignores any scores the browser computed, so the profile that gets
signed is the server's.

Six talent traits, each 0-100 (STARTER scales - tune them with field data):
    reflex        reaction time to a raider appearing          (Raider Dodge)
    agility       dodge success + peak sideways speed           (Raider Dodge)
    power         best jump height                              (Log Jump)
    anticipation  reading the bowler before the ball is seen    (Read the Bowler)
    learning      how fast errors fall over 3 tries             (Copy the Combo)
    heart         heart-rate recovery after effort (camera PPG) (Pulse checks)

Two ways to play (scope):
    full   the whole body was in view: every level.
    upper  only from the waist up (sitting at a laptop, phone propped close): Shadow Boxing
           (raises the heart rate), Heart Scan, Read the Bowler (by leaning), Dance-off and the
           final scan. Reflexes, agility and power are then "not measured" - never zero - and the
           run goes on the upper-body leaderboard. A player who unlocks the bonus levels (Raider
           Dodge, Log Jump, Bull Run) becomes a full run.
The scope is decided here from what was measured, not taken from the browser.
"""

from statistics import median
from typing import Dict, List, Optional

from coachability import align, coachability_score, MOVES

TRAITS = ["reflex", "agility", "power", "anticipation", "learning", "heart"]
LABELS = {"reflex": "Reflexes", "agility": "Agility", "power": "Power", "anticipation": "Game reading",
          "learning": "Learning speed", "heart": "Heart recovery"}
LEVEL_WEIGHT = {"easy": 1.0, "medium": 2.0, "hard": 3.0}
MIN_PULSE_QUALITY = 0.25

# "Sports to try": weights over the traits (starter values from typical sport demands)
SPORTS = {
    "Kabaddi": {"agility": .30, "reflex": .20, "power": .20, "anticipation": .20, "heart": .10},
    "Cricket (batting)": {"anticipation": .40, "reflex": .30, "agility": .10, "learning": .20},
    "Sprinting": {"reflex": .30, "power": .45, "agility": .15, "heart": .10},
    "Football": {"agility": .25, "anticipation": .25, "heart": .25, "reflex": .15, "learning": .10},
    "Badminton": {"reflex": .30, "agility": .30, "anticipation": .30, "learning": .10},
    "Hockey": {"agility": .30, "anticipation": .25, "heart": .25, "reflex": .20},
    "Boxing": {"reflex": .35, "anticipation": .25, "agility": .20, "heart": .20},
    "Volleyball": {"power": .40, "anticipation": .30, "reflex": .20, "learning": .10},
    "Long-distance running": {"heart": .70, "learning": .10, "agility": .20},
    "Archery / shooting": {"learning": .50, "anticipation": .20, "heart": .30},
}


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def _num(v, lo: float, hi: float) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if lo <= f <= hi else None


def score_dodge(trials: List[Dict]):
    trials = [t for t in (trials or []) if isinstance(t, dict)][:30]
    if len(trials) < 3:
        return None, None, {}
    ok = [t for t in trials if t.get("ok")]
    # under 120 ms is faster than a human can react to something they saw - it was a guess
    rts = [r for r in (_num(t.get("rt"), 120, 2000) for t in ok) if r is not None]
    peaks = [p for p in (_num(t.get("peak_v"), 0, 15) for t in ok) if p is not None]
    success = len(ok) / len(trials)
    reflex = round(100 * _clamp01((900 - median(rts)) / 650), 1) if rts else None
    # peak sideways speed in shoulder widths a second, read only from new camera frames: a quick sidestep is about
    # 4-6, a very fast one 8+ (a repeated frame used to inflate it, so the old /4 scale gave nearly everyone full marks)
    agility = round(100 * (0.5 * success + 0.5 * _clamp01((median(peaks) if peaks else 0) / 8.0)), 1)
    return reflex, agility, {"trials": len(trials), "dodged": len(ok), "median_reaction_ms": round(median(rts)) if rts else None,
                             "median_peak_speed_sw_s": round(median(peaks), 2) if peaks else None}


def score_jump(trials: List[Dict]):
    trials = [t for t in (trials or []) if isinstance(t, dict)][:20]
    if not trials:
        return None, {}
    heights = [h for h in (_num(t.get("cm"), 0, 120) for t in trials if t.get("ok")) if h is not None]
    best = max(heights) if heights else 0.0
    return round(100 * _clamp01(best / 45.0), 1), {"jumps": len(trials), "cleared": len(heights), "best_cm": round(best, 1)}


def score_bowler(trials: List[Dict]):
    answered = [t for t in (trials or []) if isinstance(t, dict) and t.get("answer") in ("L", "R")
                and t.get("target") in ("L", "R") and t.get("level") in LEVEL_WEIGHT][:30]
    if len(answered) < 4:
        return None, {"answered": len(answered)}
    w = sum(LEVEL_WEIGHT[t["level"]] for t in answered)
    hit = sum(LEVEL_WEIGHT[t["level"]] for t in answered if t["answer"] == t["target"])
    wacc = hit / w
    by_level = {}
    for lv in LEVEL_WEIGHT:
        ts = [t for t in answered if t["level"] == lv]
        if ts:
            by_level[lv] = f"{sum(t['answer'] == t['target'] for t in ts)}/{len(ts)}"
    return round(100 * _clamp01((wacc - 0.5) / 0.5), 1), {"answered": len(answered), "weighted_accuracy": round(wacc, 3),
                                                         "by_level": by_level}


def score_combo(combo: Dict):
    pattern = [m for m in (combo or {}).get("pattern", []) if m in MOVES][:8]
    tries = [t for t in (combo or {}).get("tries", []) if isinstance(t, dict)][:6]
    if len(pattern) < 3 or not tries:
        return None, {}
    errors = []
    for t in tries:
        done = [m for m in t.get("done", []) if m in MOVES][:20]
        errors.append(float(align(pattern, done)[0]))
    sc = coachability_score(errors, len(pattern))
    return sc["score"], {"pattern": pattern, "errors_per_try": errors, "reduction_pct": sc.get("reduction_pct"),
                         "note": sc.get("note")}


def score_pulse(pulses: List[Dict]):
    ps = [p for p in (pulses or []) if isinstance(p, dict)][:4]
    vals = []
    for p in ps:
        bpm = _num(p.get("bpm"), 40, 210)
        q = _num(p.get("quality"), 0, 1) or 0.0
        vals.append({"bpm": round(bpm) if bpm else None, "quality": round(q, 2), "ok": bool(bpm) and q >= MIN_PULSE_QUALITY})
    detail = {"checks": vals}
    if len(vals) >= 2 and vals[0]["ok"] and vals[-1]["ok"]:
        drop = vals[0]["bpm"] - vals[-1]["bpm"]
        detail["recovery_bpm"] = drop
        return round(100 * _clamp01(drop / 25.0), 1), detail
    return None, detail


# ------------------------------------------------------------------ game points (the fun part)
# Points are a pure function of the raw measurements, so the server can recompute them and the
# leaderboard can't be faked by editing the browser's score. Combo streaks follow the trial order.

RANKS = [(0.75, "Legend", "👑"), (0.55, "Pro", "🔥"), (0.35, "Rising Star", "⭐"), (0.0, "Rookie", "🌱")]
BOWLER_MULT = {"easy": 1.0, "medium": 1.5, "hard": 2.0}


def _mult(streak: int) -> float:
    return min(1.0 + 0.5 * streak, 2.5)


def _stars(ratio: Optional[float], hi: float = 0.9, mid: float = 0.6) -> int:
    if ratio is None:
        return 0
    return 3 if ratio >= hi else 2 if ratio >= mid else 1


FULL_BODY_LEVELS = ("dodge", "jump", "escape")


def scope(raw: Dict) -> str:
    """'full' when any whole-body level was played, else 'upper'."""
    raw = raw if isinstance(raw, dict) else {}
    return "full" if any(raw.get(k) for k in FULL_BODY_LEVELS) else "upper"


def points(raw: Dict) -> Dict:
    """Game points, stars per level (0-3) and the player's rank."""
    raw = raw if isinstance(raw, dict) else {}
    lv: Dict[str, Dict] = {}

    bx = raw.get("boxing") if isinstance(raw.get("boxing"), dict) else None
    if bx:
        secs = _num(bx.get("secs"), 1, 120) or 20
        hits = _num(bx.get("hits"), 0, 1000) or 0
        lv["boxing"] = {"points": round(50 * min(hits, 3 * secs)), "max": round(150 * secs),
                        "stars": 3 if hits / secs >= 2 else 2 if hits / secs >= 1.2 else 1}

    d = [t for t in (raw.get("dodge") or []) if isinstance(t, dict)][:30]
    if d:
        pts = streak = 0
        for t in d:
            if t.get("ok"):
                rt = _num(t.get("rt"), 120, 2000)
                pts += (100 + (max(0.0, (900 - rt) / 5) if rt else 0)) * _mult(streak)
                streak += 1
            else:
                streak = 0
        lv["dodge"] = {"points": round(pts), "max": round(_max_streak_sum(len(d), 256)), "stars": _stars(sum(1 for t in d if t.get("ok")) / len(d))}

    j = [t for t in (raw.get("jump") or []) if isinstance(t, dict)][:20]
    if j:
        pts = 0
        for t in j:
            if t.get("ok"):
                cm = _num(t.get("cm"), 0, 120) or 0
                tm = _num(t.get("timing"), -2000, 2000)
                pts += 100 + 3 * min(cm, 60) + (50 if tm is not None and abs(tm) <= 100 else 20 if tm is not None and abs(tm) <= 200 else 0)
        lv["jump"] = {"points": round(pts), "max": 330 * len(j), "stars": _stars(sum(1 for t in j if t.get("ok")) / len(j))}

    e = raw.get("escape") if isinstance(raw.get("escape"), dict) else None
    if e:
        secs = _num(e.get("secs"), 1, 120) or 10
        steps = _num(e.get("steps"), 0, 1000) or 0
        lv["escape"] = {"points": round(5 * min(steps, 4 * secs)), "max": round(20 * secs),
                        "stars": 3 if steps / secs >= 3.5 else 2 if steps / secs >= 2.5 else 1}

    ps = [p for p in (raw.get("pulse") or []) if isinstance(p, dict)][:4]
    if ps:
        ok = [bool(_num(p.get("bpm"), 40, 210)) and (_num(p.get("quality"), 0, 1) or 0) >= MIN_PULSE_QUALITY for p in ps]
        lv["pulse"] = {"points": sum(150 if o else 50 for o in ok), "max": 150 * len(ps), "stars": _stars(sum(ok) / len(ok), 0.99, 0.5)}

    b = [t for t in (raw.get("bowler") or []) if isinstance(t, dict) and t.get("level") in BOWLER_MULT][:30]
    if b:
        pts = best = streak = 0
        for i, t in enumerate(b):
            best += 150 * BOWLER_MULT[t["level"]] * _mult(i)
            if t.get("answer") in ("L", "R") and t.get("answer") == t.get("target"):
                pts += 150 * BOWLER_MULT[t["level"]] * _mult(streak)
                streak += 1
            else:
                streak = 0
        w = sum(LEVEL_WEIGHT[t["level"]] for t in b)
        hit = sum(LEVEL_WEIGHT[t["level"]] for t in b if t.get("answer") == t.get("target"))
        lv["bowler"] = {"points": round(pts), "max": round(best), "stars": _stars(hit / w, 0.8, 0.6)}

    c = raw.get("combo") if isinstance(raw.get("combo"), dict) else None
    pattern = [m for m in (c or {}).get("pattern", []) if m in MOVES][:8]
    tries = [t for t in (c or {}).get("tries", []) if isinstance(t, dict)][:6]
    if pattern and tries:
        pts, last_err = 0, None
        for t in tries:
            done = [m for m in t.get("done", []) if m in MOVES][:20]
            err = int(align(pattern, done)[0])
            pts += 50 * max(0, len(pattern) - err) + (300 if err == 0 else 0)
            last_err = err
        lv["combo"] = {"points": pts, "max": len(tries) * (50 * len(pattern) + 300),
                       "stars": 3 if last_err == 0 else 2 if last_err <= 1 else 1}

    total = sum(v["points"] for v in lv.values())
    best_total = sum(v["max"] for v in lv.values()) or 1
    ratio = total / best_total
    rank = next((name, icon) for th, name, icon in RANKS if ratio >= th)
    return {"total": total, "max": best_total, "percent": round(100 * ratio), "levels": lv,
            "stars": sum(v["stars"] for v in lv.values()), "max_stars": 3 * len(lv), "rank": rank[0], "rank_icon": rank[1],
            "scope": scope(raw)}


def _max_streak_sum(n: int, per: float) -> float:
    return sum(per * _mult(i) for i in range(n))


def profile(raw: Dict) -> Dict:
    raw = raw if isinstance(raw, dict) else {}
    reflex, agility, d_dodge = score_dodge(raw.get("dodge"))
    power, d_jump = score_jump(raw.get("jump"))
    anticipation, d_bowl = score_bowler(raw.get("bowler"))
    learning, d_combo = score_combo(raw.get("combo"))
    heart, d_pulse = score_pulse(raw.get("pulse"))
    traits = {"reflex": reflex, "agility": agility, "power": power, "anticipation": anticipation,
              "learning": learning, "heart": heart}
    have = [v for v in traits.values() if v is not None]
    overall = round(sum(have) / len(have), 1) if have else None
    sports = []
    for name, wts in SPORTS.items():
        used = {k: w for k, w in wts.items() if traits.get(k) is not None}
        if sum(used.values()) < 0.6:          # not enough of this sport's traits were measured
            continue
        match = sum(traits[k] * w for k, w in used.items()) / sum(used.values())
        sports.append({"sport": name, "match": round(match), "based_on": [LABELS[k] for k in used]})
    sports.sort(key=lambda s: -s["match"])
    best = max(((k, v) for k, v in traits.items() if v is not None), key=lambda kv: kv[1], default=(None, None))
    sc = scope(raw)
    not_measured = [k for k, v in traits.items() if v is None]
    return {
        "traits": traits, "labels": LABELS, "overall": overall, "sports": sports[:3],
        "scope": sc, "measured": [k for k, v in traits.items() if v is not None], "not_measured": not_measured,
        "scope_note": ("Measured: upper body. Reflexes, agility and power need the whole body in view - "
                       "they were not measured (not zero)." if sc == "upper" else "Measured: full body."),
        "top_trait": LABELS.get(best[0]) if best[0] else None,
        "details": {"dodge": d_dodge, "jump": d_jump, "bowler": d_bowl, "combo": d_combo, "pulse": d_pulse,
                    "calibration": (raw.get("calib") or {}).get("method")},
        "starter_note": "Starter scales - to be tuned with field data. Pulse values are camera estimates.",
    }
