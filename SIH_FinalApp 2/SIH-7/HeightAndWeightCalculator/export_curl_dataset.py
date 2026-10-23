"""
Export the weighted-curl dataset (one row per rep) for tuning the starter benchmarks.

    python export_curl_dataset.py                  -> curl_reps.csv + curl_sessions.csv

Every weighted dumbbell-curl test stores, per rep: arm, elbow angle at the top, lift and lowering
time, hand speed, body swing and elbow drift, and whether the rep was clean - plus the dumbbell
weight, the athlete's age group and gender. Collected over many athletes this is the data to replace
the starter values in curl_load_benchmarks.csv (e.g. the speed at each weight for each age group, and
each athlete's own load-velocity line when they test with two different weights).

Athletes appear only as a pseudonymous token - no names, e-mails or photos are exported.
"""

import csv
import hashlib
import sys

from db_config import get_db

REP_COLS = ["athlete", "age", "gender", "mode", "timestamp", "source", "load_kg", "weight_seen", "arm", "rep", "t_s",
            "top_angle_deg", "lift_s", "lower_s", "speed_m_s", "swing_pct", "drift_pct", "clean"]
SESSION_COLS = ["athlete", "age", "gender", "mode", "timestamp", "source", "load_kg", "weight_seen", "reps", "clean_reps",
                "first_speed_m_s", "last_speed_m_s", "velocity_loss_pct", "mean_top_angle_deg", "mean_swing_pct",
                "mean_drift_pct", "est_1rm_kg", "intensity", "benchmark_target", "rating"]


def _pseudo(ref) -> str:
    return hashlib.sha256(("deepfit-curl-" + str(ref)).encode()).hexdigest()[:12]


def export(reps_path="curl_reps.csv", sessions_path="curl_sessions.csv") -> int:
    db = get_db()
    if db is None:
        print("Database unavailable")
        return 0
    docs = [d for d in db.exercise_results.find({"exercise_type": "dumbbell_curls"}) if d.get("load_kg")]
    with open(reps_path, "w", newline="") as fr, open(sessions_path, "w", newline="") as fs:
        wr, ws = csv.writer(fr), csv.writer(fs)
        wr.writerow(REP_COLS)
        ws.writerow(SESSION_COLS)
        for d in docs:
            base = [_pseudo(d.get("athlete_ref")), d.get("athlete_age"), d.get("athlete_gender"), d.get("mode"),
                    d.get("timestamp"), d.get("source", "web"), d.get("load_kg"), (d.get("load_check") or {}).get("seen")]
            for r in d.get("reps_detail") or []:
                wr.writerow(base + [r.get("arm"), r.get("n"), r.get("t"), r.get("top_angle"), r.get("lift_s"), r.get("lower_s"),
                                    r.get("speed"), r.get("swing_pct"), r.get("drift_pct"), int(bool(r.get("clean")))])
            a, b = d.get("load_analysis") or {}, d.get("benchmark") or {}
            ws.writerow(base + [a.get("reps"), a.get("clean_reps"), a.get("first_speed_m_s"), a.get("last_speed_m_s"),
                                a.get("velocity_loss_pct"), a.get("mean_top_angle_deg"), a.get("mean_swing_pct"),
                                a.get("mean_drift_pct"), a.get("est_1rm_kg"), a.get("intensity"), b.get("target"), b.get("rating")])
    print(f"Exported {len(docs)} weighted curl tests -> {reps_path}, {sessions_path}")
    return len(docs)


if __name__ == "__main__":
    export(*sys.argv[1:3])
