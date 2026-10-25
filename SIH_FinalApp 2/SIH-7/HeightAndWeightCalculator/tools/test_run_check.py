"""Run:  python3 tools/test_run_check.py
GPS 600 m checks on simulated runs: honest runners/walkers pass, vehicles and fakes are flagged."""
import math, random, sys
import os; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import run_check as RC

LAT0, LON0 = 17.3850, 78.4867          # Hyderabad
M_LAT = 1 / 111_320
def m_lon(lat): return 1 / (111_320 * math.cos(math.radians(lat)))

def loop_xy(s, lap=200.0):              # a 200 m oval-ish loop: two 50 m straights + two semicircles
    s %= lap; r = 50 / math.pi
    if s < 50: return s, 0.0
    if s < 100: a = (s - 50) / r; return 50 + r * math.sin(a), r - r * math.cos(a)
    if s < 150: return 50 - (s - 100), 2 * r
    a = (s - 150) / r; return -r * math.sin(a), r + r * math.cos(a)

def make(speed_fn, total_s, cadence=None, gps_sigma=3.0, acc=5.0, hz=1.0, seed=1, mocked=False, teleports=0, extra_s=8, face_after=12, phone_err=0.0, activity=None, stop_at=None):
    """The athlete keeps going until the PHONE says 600 m (the phone runs the same distance code as the
    server), then stops; recording goes on for extra_s seconds (walking to the camera for the finish photo)."""
    rnd = random.Random(seed); pts, steps = [], []; s, t, dt = 0.0, 0.0, 0.05; next_fix, next_step = 0.0, 0.3
    ex = ey = 0.0; rho = 0.98 ** (1 / hz)        # phone GPS error drifts slowly (correlated), it doesn't jump every second
    finish = None; limit = (stop_at or total_s * 1.4)
    while t <= limit + extra_s and (finish is None or t <= finish + extra_s):
        moving = t <= limit and (finish is None)
        v = speed_fn(t) if moving else 0.0
        s += v * dt
        if t >= next_fix:
            x, y = loop_xy(s)
            ex = rho * ex + math.sqrt(1 - rho * rho) * rnd.gauss(0, gps_sigma); ey = rho * ey + math.sqrt(1 - rho * rho) * rnd.gauss(0, gps_sigma)
            x += ex + rnd.gauss(0, 0.3); y += ey + rnd.gauss(0, 0.3)
            pts.append({"t": round(t, 2), "lat": LAT0 + y * M_LAT, "lon": LON0 + x * m_lon(LAT0), "acc": acc, "mocked": mocked})
            next_fix += 1 / hz
            if finish is None and stop_at is None and len(pts) > 5:      # the phone's own check (same code as the server)
                tr = RC.distance_track(RC.clean_points(pts)[0])
                if tr and tr[-1][1] >= 600:
                    finish = t
        c = cadence(t) if cadence else 0
        if c and moving and t >= next_step:
            steps.append(round(t + rnd.gauss(0, 0.01), 3)); next_step = t + 1 / c * rnd.uniform(0.95, 1.05)
        t += dt
    for _ in range(teleports):
        i = rnd.randrange(5, len(pts) - 5); pts[i]["lat"] += 300 * M_LAT
    cross = RC.crossing_time(RC.distance_track(RC.clean_points(pts)[0]), 600) if not teleports else finish
    end = cross if cross is not None else (finish or limit)
    return {"points": pts, "steps": steps, "finish_face_t": None if face_after is None else end + face_after,
            "phone_time": (end or 0) + phone_err, "_true_m": None, **({"activity": activity} if activity else {})}

def run(name, r, expect, age=12, h=150):
    out = RC.check_run(r, 600, age=age, height_cm=h)
    got = "problem" if not out["ok"] else out["verdict"]
    status = "PASS" if got == expect else "FAIL"
    print(f"{status} {name:45s} -> {got:13s} time={out.get('value')} dist={out.get('distance_m')} steps={out.get('steps')}"
          + (f" | {out.get('problem')}" if not out['ok'] else "") + (f" | flags: {out['flags'][:3]}" if out.get('flags') else ""))
    return status == "PASS"

ok = True
# honest: 12-year-old runs 600 m in 150 s (4 m/s), cadence ~2.9 steps/s, slows a little at the end
ok &= run("honest runner, 12 y, 2:30", make(lambda t: 4.2 if t < 110 else 3.6, 150, cadence=lambda t: 2.9), "measured")
ok &= run("honest fast runner, 16 y, 1:45", make(lambda t: 5.7, 105.3, cadence=lambda t: 3.3), "measured", age=16, h=172)
ok &= run("honest walker, 1.4 m/s", make(lambda t: 1.4, 430, cadence=lambda t: 1.8), "measured")
ok &= run("honest runner, noisy GPS (8 m), 0.5 Hz", make(lambda t: 4.0, 150, cadence=lambda t: 2.9, gps_sigma=6, acc=12, hz=0.5, seed=4), "measured")
ok &= run("car, phone on the seat (10 m/s)", make(lambda t: 10.0, 60, cadence=None), "needs_recheck")
ok &= run("slow car / scooter (5 m/s), no steps", make(lambda t: 5.0, 120, cadence=None), "needs_recheck")
ok &= run("bike 6 m/s, phone in pocket (pedal bounce 1.2/s)", make(lambda t: 6.0, 100, cadence=lambda t: 1.2), "needs_recheck")
ok &= run("car, phone shaken 3x a second, 7 m/s", make(lambda t: 7.0, 86, cadence=lambda t: 3.0), "needs_recheck")
ok &= run("GPS teleports (spoofing)", make(lambda t: 4.0, 150, cadence=lambda t: 2.9, teleports=5), "needs_recheck")
ok &= run("mock location app", make(lambda t: 4.0, 150, cadence=lambda t: 2.9, mocked=True), "needs_recheck")
ok &= run("finish face photo 2 min later", make(lambda t: 4.0, 150, cadence=lambda t: 2.9, face_after=120), "needs_recheck")
ok &= run("no finish face photo", make(lambda t: 4.0, 150, cadence=lambda t: 2.9, face_after=None), "needs_recheck")
ok &= run("phone time edited (-20 s)", make(lambda t: 4.0, 150, cadence=lambda t: 2.9, phone_err=-20), "needs_recheck")
ok &= run("phone's own sensor: in_vehicle", make(lambda t: 4.0, 150, cadence=lambda t: 2.9, activity=[{"t": i, "type": "in_vehicle", "conf": 80} for i in range(20)]), "needs_recheck")
ok &= run("stopped at 450 m", make(lambda t: 4.0, 150, cadence=lambda t: 2.9, stop_at=112), "problem")
ok &= run("indoors: GPS accuracy 40 m", make(lambda t: 4.0, 150, cadence=lambda t: 2.9, acc=40), "problem")
# the honest limit: a slow vehicle with the phone shaken at a running rhythm and no activity data
out = RC.check_run(make(lambda t: 4.0, 150, cadence=lambda t: 2.9, seed=9), 600, age=12, height_cm=150)
print("KNOWN LIMIT  slow vehicle at running speed + phone shaken at a running rhythm ->", out["verdict"], "(only the phone's activity sensor or the face/pulse at the finish can catch this)")
print("\nALL RUN CHECK TESTS PASSED" if ok else "\nSOME RUN CHECK TESTS FAILED")
