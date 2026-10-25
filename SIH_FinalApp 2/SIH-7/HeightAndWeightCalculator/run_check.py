"""
GPS-timed runs (600 m Run/Walk) measured by the phone the athlete carries - checked again on the server.

The phone sends the RAW track, not just a time:
  points: [{t, lat, lon, acc, spd?, mocked?}]   t = seconds since "Go"
  steps:  [t, t, ...]                             foot strikes from the phone's motion sensor
  activity (optional): [{t, type, conf}]         the phone's own activity guess (running / in_vehicle ...)
  finish_face_t: seconds since "Go" when the finish face photo was taken

The server recomputes the distance and the time itself and decides whether the run looks like a
person running. Every check either passes or raises a flag with a plain-words reason. Flags never
delete a result: the result is saved as "needs re-check" and the Talent Passport says so.

A phone cannot prove WHO carried it - that's what the face check at the start AND at the finish
(within 30 s of stopping) is for. Two people working together can still cheat; the re-test at the
real trial is the final check.
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple

EARTH_R = 6371008.8          # metres
MAX_ACCURACY_M = 25.0        # GPS fixes worse than this are dropped
MAX_POINT_SPEED = 12.0       # m/s between two fixes: faster = GPS jump (or a vehicle)
MAX_GAP_S = 10.0             # longest gap between fixes still trusted
FINISH_FACE_WITHIN_S = 30.0  # the finish face photo must be taken this soon after the finish
MIN_STEPS_PER_M = 0.45       # 600 m: at least ~270 steps (a 1.9 m adult sprinting stride ~2.2 m/step is the extreme)
MAX_STEPS_PER_M = 1.9        # 600 m: at most ~1140 steps (tiny walking steps)
# Fastest believable average speed (m/s) for a 600 m by age - above these the time would be close to
# national-record level for that age, so the run is flagged for a re-check (not rejected).
ELITE_AVG_SPEED = [(11, 5.2), (13, 5.8), (15, 6.4), (17, 6.9), (200, 7.6)]


def haversine(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * EARTH_R * math.asin(min(1.0, math.sqrt(h)))


def _num(v, lo=None, hi=None) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if math.isnan(x) or math.isinf(x) or (lo is not None and x < lo) or (hi is not None and x > hi):
        return None
    return x


def clean_points(points) -> Tuple[List[Dict], Dict]:
    """Valid, time-ordered fixes with good accuracy; counts what was dropped and why."""
    info = {"received": 0, "bad_accuracy": 0, "jumps": 0, "mocked": 0}
    pts = []
    for p in points if isinstance(points, list) else []:
        if not isinstance(p, dict):
            continue
        info["received"] += 1
        t, lat, lon = _num(p.get("t"), 0, 7200), _num(p.get("lat"), -90, 90), _num(p.get("lon"), -180, 180)
        acc = _num(p.get("acc"), 0, 10000)
        if t is None or lat is None or lon is None:
            continue
        if p.get("mocked"):
            info["mocked"] += 1
        if acc is None or acc > MAX_ACCURACY_M:
            info["bad_accuracy"] += 1
            continue
        pts.append({"t": t, "lat": lat, "lon": lon, "acc": acc})
    pts.sort(key=lambda p: p["t"])
    out: List[Dict] = []
    for p in pts:          # drop fixes that would mean an impossible jump from the last kept one
        if out:
            d, dt = haversine((out[-1]["lat"], out[-1]["lon"]), (p["lat"], p["lon"])), p["t"] - out[-1]["t"]
            if dt <= 0:
                continue
            if d / dt > MAX_POINT_SPEED and d > 2 * max(p["acc"], out[-1]["acc"]):
                info["jumps"] += 1
                continue
        out.append(p)
    return out, info


SMOOTH_S = 1.0               # positions are averaged over +-1 s of fixes before measuring distance


def smooth_xy(pts: List[Dict]) -> List[Tuple[float, float, float]]:
    """Positions in local metres, each averaged with the fixes within +-SMOOTH_S seconds (weighted by
    1/accuracy^2). GPS jitter otherwise adds up: a few metres of zig-zag per fix becomes tens of metres
    over a 600 m run. The phone app uses exactly the same steps, so both get the same distance."""
    if not pts:
        return []
    lat0, lon0 = pts[0]["lat"], pts[0]["lon"]
    kx = math.radians(1) * EARTH_R * math.cos(math.radians(lat0))
    ky = math.radians(1) * EARTH_R
    raw = [(p["t"], (p["lon"] - lon0) * kx, (p["lat"] - lat0) * ky, 1 / max(1.0, p["acc"]) ** 2) for p in pts]
    out, j0 = [], 0
    for t, _, _, _ in raw:
        while raw[j0][0] < t - SMOOTH_S:
            j0 += 1
        sw = sx = sy = 0.0
        j = j0
        while j < len(raw) and raw[j][0] <= t + SMOOTH_S:
            w = raw[j][3]
            sw += w; sx += w * raw[j][1]; sy += w * raw[j][2]
            j += 1
        out.append((t, sx / sw, sy / sw))
    return out


def distance_track(pts: List[Dict]) -> List[Tuple[float, float]]:
    """Cumulative distance (m) at each kept fix: [(t, metres)], from the smoothed positions. Moves of
    under 1.5 m (GPS drift while standing still) are not added until they add up."""
    xy = smooth_xy(pts)
    if not xy:
        return []
    out = [(xy[0][0], 0.0)]
    ax, ay, total = xy[0][1], xy[0][2], 0.0
    for t, x, y in xy[1:]:
        d = math.hypot(x - ax, y - ay)
        if d >= 1.5:
            total += d
            ax, ay = x, y
        out.append((t, total))
    return out


def crossing_time(track: List[Tuple[float, float]], target: float) -> Optional[float]:
    for (t0, d0), (t1, d1) in zip(track, track[1:]):
        if d0 < target <= d1:
            return t0 + (t1 - t0) * (target - d0) / (d1 - d0) if d1 > d0 else t1
    return None


def _elite_speed(age) -> float:
    a = _num(age, 3, 120) or 99
    return next(v for lim, v in ELITE_AVG_SPEED if a <= lim)


def check_run(run: Dict, target_m: float = 600.0, age=None, height_cm=None) -> Dict:
    """Recompute and check a GPS run. Returns {ok, value (s), distance_m, steps, verdict, checks, flags, problem}."""
    run = run if isinstance(run, dict) else {}
    pts, info = clean_points(run.get("points"))
    out: Dict = {"ok": False, "method": "gps+steps", "target_m": target_m, "points": info, "checks": [], "flags": []}

    def check(name: str, ok: bool, detail: str):
        out["checks"].append({"check": name, "ok": bool(ok), "detail": detail})
        if not ok:
            out["flags"].append(detail)

    if len(pts) < 10:
        out["problem"] = "Not enough GPS fixes - run outdoors with a clear view of the sky."
        return out
    track = distance_track(pts)
    t_cross = crossing_time(track, target_m)
    total = track[-1][1]
    out["distance_m"] = round(total, 1)
    if t_cross is None:
        out["problem"] = f"The phone measured only {total:.0f} m of the {target_m:.0f} m."
        return out
    t_go = 0.0
    secs = t_cross - t_go
    out.update(ok=True, value=round(secs, 2), distance_m=round(total, 1))
    run_pts = [p for p in pts if p["t"] <= t_cross + 1]

    # 1. GPS quality
    gaps = [b["t"] - a["t"] for a, b in zip(run_pts, run_pts[1:])]
    accs = sorted(p["acc"] for p in run_pts)
    med_acc = accs[len(accs) // 2]
    check("gps_quality", max(gaps or [0]) <= MAX_GAP_S and med_acc <= 15,
          f"GPS: median accuracy {med_acc:.0f} m, longest gap {max(gaps or [0]):.0f} s"
          + ("" if max(gaps or [0]) <= MAX_GAP_S and med_acc <= 15 else " - too weak to trust the distance"))
    check("no_gps_jumps", info["jumps"] <= 2, f"{info['jumps']} impossible GPS jumps removed"
          + ("" if info["jumps"] <= 2 else " - the location may have been faked"))
    check("not_mock_location", info["mocked"] == 0,
          "phone reports a real GPS location" if info["mocked"] == 0 else "phone reports a FAKE (mock) location app")

    # 2. speed believable for the age
    avg = target_m / secs if secs > 0 else 99
    elite = _elite_speed(age)
    check("speed_believable", avg <= elite,
          f"average {avg:.2f} m/s" + ("" if avg <= elite else f" - faster than near-record level for this age ({elite} m/s)"))
    fast5 = 0.0
    for i, (t0, d0) in enumerate(track):            # fastest 5 s stretch
        for t1, d1 in track[i + 1:]:
            if t1 - t0 >= 5:
                fast5 = max(fast5, (d1 - d0) / (t1 - t0))
                break
    out["fastest_5s_mps"] = round(fast5, 2)
    check("top_speed_human", fast5 <= 10.5, f"fastest 5 s: {fast5:.1f} m/s"
          + ("" if fast5 <= 10.5 else " - faster than any human runner (vehicle?)"))

    # 3. feet: steps from the motion sensor must match the distance and the speed
    steps = sorted(t for t in (_num(x, 0, 7200) for x in (run.get("steps") or [])) if t is not None and t <= t_cross)
    out["steps"] = len(steps)
    if not steps:
        check("steps_present", False, "no steps were recorded by the motion sensor")
    else:
        per_m = len(steps) / target_m
        h = _num(height_cm, 90, 230)
        lo, hi = MIN_STEPS_PER_M, MAX_STEPS_PER_M
        if h:      # a step can't be longer than ~1.4 x body height, or shorter than ~0.3 x
            lo, hi = max(lo, 1 / (1.4 * h / 100)), min(hi, 1 / (0.3 * h / 100))
        check("steps_match_distance", lo <= per_m <= hi,
              f"{len(steps)} steps for {target_m:.0f} m ({target_m / len(steps):.2f} m per step)"
              + ("" if lo <= per_m <= hi else " - does not fit running or walking (carried in a vehicle or shaken?)"))
        # moving windows with no steps = carried without running
        no_step_secs = 0.0
        for (t0, d0), (t1, d1) in zip(track, track[1:]):
            if t1 - t0 <= 0 or t1 > t_cross:
                continue
            v = (d1 - d0) / (t1 - t0)
            n = sum(1 for s in steps if t0 <= s < t1)
            if v > 2.0 and n == 0 and t1 - t0 >= 2:
                no_step_secs += t1 - t0
        check("no_moving_without_steps", no_step_secs <= 0.1 * secs,
              f"{no_step_secs:.0f} s moving fast with no steps" + ("" if no_step_secs <= 0.1 * secs else " - carried (vehicle/bike)?"))
        # step rhythm: running/walking cadence is 1.3-4.2 steps a second; a car or bike gives none or noise
        gaps_s = [b - a for a, b in zip(steps, steps[1:]) if 0 < b - a < 2]
        cad = (1 / (sum(gaps_s) / len(gaps_s))) if gaps_s else 0
        out["cadence_spm"] = round(cad * 60)
        check("human_cadence", 1.3 <= cad <= 4.2, f"step rhythm {cad * 60:.0f} steps a minute"
              + ("" if 1.3 <= cad <= 4.2 else " - not a running or walking rhythm"))
        # speed and rhythm must agree: step length = speed / cadence, per 20 s stretch
        bad = 0
        for t0 in range(0, int(secs) - 19, 10):
            seg = [x for x in track if t0 <= x[0] <= t0 + 20]
            if len(seg) < 2:
                continue
            v = (seg[-1][1] - seg[0][1]) / max(1e-6, seg[-1][0] - seg[0][0])
            n = sum(1 for s in steps if t0 <= s < t0 + 20)
            if v > 1.0 and n > 0 and (v * 20 / n) > 2.6:
                bad += 1
        check("stride_consistent", bad <= 1, "step length fits the speed all the way" if bad <= 1
              else f"{bad} stretches where each step would be over 2.6 m - faster than the feet")

    # 4. the phone's own activity guess (optional)
    acts = [a for a in (run.get("activity") or []) if isinstance(a, dict) and (_num(a.get("conf"), 0, 100) or 0) >= 60]
    if acts:
        veh = sum(1 for a in acts if str(a.get("type")) in ("in_vehicle", "on_bicycle", "automotive", "cycling"))
        check("phone_activity", veh <= 0.15 * len(acts),
              f"phone's own activity sensor: {veh} of {len(acts)} readings in a vehicle or on a bike")

    # 5. phone's time vs server's time
    phone = _num(run.get("phone_time"), 0, 7200)
    if phone is not None:
        check("phone_time_matches", abs(phone - secs) <= 3, f"phone said {phone:.1f} s, server computed {secs:.1f} s")

    # 6. finish face photo soon after the finish
    ff = _num(run.get("finish_face_t"), 0, 7200)
    check("finish_face_in_time", ff is not None and 0 <= ff - t_cross <= FINISH_FACE_WITHIN_S,
          "finish face photo " + ("missing" if ff is None else f"{ff - t_cross:.0f} s after the finish")
          + ("" if ff is not None and 0 <= ff - t_cross <= FINISH_FACE_WITHIN_S else f" - must be within {FINISH_FACE_WITHIN_S:.0f} s"))

    out["verdict"] = "measured" if not out["flags"] else "needs_recheck"
    return out
