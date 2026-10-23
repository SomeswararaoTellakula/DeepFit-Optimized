"""
One blueprint for every test in exercise_engine.py.

Pages
    /tests                 all tests, progress, "next test", report
    /ex/<key>              the test page (same layout for every exercise)
API
    POST /ex/<key>/start   face-verified start (camera opens on the server)
    GET  /ex/<key>/video_feed
    GET  /ex/<key>/stats
    POST /ex/<key>/stop    finish + save + benchmark + next test
    POST /ex/<key>/manual  save a coach-timed result (50 m, 600 m)
    POST /ex/<key>/cleanup
    GET  /api/tests/progress

Works for normal accounts (session['user_id']) and for blind athletes registered
through the blind flow (session['blind_user_id']).
"""

import threading
import time
from datetime import datetime
from typing import Dict, Optional

import cv2
from flask import Blueprint, Response, abort, jsonify, render_template, request, session

import benchmarks
import exercise_engine as EE          # first: registers the Coachability + Growth tests
import passport
import potential
from db_config import get_db
from error_logger import log_error, log_info
from identity_guard import REQUIRE_FACE_CHECK, LiveIdentityMonitor, is_recently_verified
from perf import FrameThrottle, POSE_COMPLEXITY, encode_jpeg, mjpeg_chunk, open_camera, release_camera

try:
    from bson import ObjectId
except Exception:  # pragma: no cover
    ObjectId = None

exercise_bp = Blueprint("exercises", __name__)

MODES = ("standard", "blind", "deaf")
COUNTDOWN = 3.0
# Recommended order: Khelo India battery first, then the extra DeepFit tests
RECOMMENDED = ["height_weight", "growth_measures", "partial_curlup", "pushups", "pushups_modified", "sit_and_reach",
               "flamingo_balance", "plate_tapping", "coachability",
               "situps", "plank", "squats", "jumping_jacks", "vertical_jump", "broad_jump", "dumbbell_curls",
               "dash_50m", "run_600m"]
HEIGHT_WEIGHT_CARD = {
    "key": "height_weight", "name": "Height & Weight (BMI)", "icon": "📏", "category": "body composition",
    "khelo_india": True, "camera": "front", "url": "/height", "metric": "bmi", "unit": "",
    "setup": ["Stand 2-3 m from the camera, full body visible"],
}


# ------------------------------------------------------------------ who is testing

def current_athlete() -> Optional[Dict]:
    db = get_db()
    if session.get("user_id"):
        uid = str(session["user_id"])
        doc = None
        if db is not None and ObjectId is not None:
            try:
                doc = db.users.find_one({"_id": ObjectId(uid)})
            except Exception:
                doc = None
        doc = doc or {}
        return {"kind": "user", "id": uid, "ref": f"user:{uid}", "verify_key": uid,
                "name": doc.get("name", "Athlete"), "age": doc.get("age"), "gender": doc.get("gender"),
                "email": doc.get("email"), "photo": doc.get("photo"),
                "verify_url": "/api/verify_user_identity", "default_mode": "standard"}
    if session.get("blind_user_id"):
        bid = str(session["blind_user_id"])
        doc = None
        if db is not None and ObjectId is not None:
            try:
                doc = db.blind_registrations.find_one({"_id": ObjectId(bid)})
            except Exception:
                doc = None
        doc = doc or {}
        return {"kind": "blind", "id": bid, "ref": f"blind:{bid}", "verify_key": f"blind:{bid}",
                "name": doc.get("name", "Athlete"), "age": doc.get("age"), "gender": doc.get("gender"),
                "email": None, "photo": doc.get("photo"),
                "verify_url": "/api/verify_blind_identity", "default_mode": "blind"}
    return None


def _height_for(ath: Dict) -> float:
    """Height in cm used to turn pixels into cm (jumps, sit & reach)."""
    h = session.get("athlete_height_cm")
    if h:
        return float(h)
    db = get_db()
    if db is not None and ath.get("email"):
        for coll in ("Final_Estimated_Height_and_Weight", "Height and Weight"):
            try:
                d = db[coll].find_one({"user_email": ath["email"]}, sort=[("timestamp", -1)])
                v = d and (d.get("final_height_cm") or d.get("height_cm"))
                if v and 120 <= float(v) <= 220:
                    return float(v)
            except Exception:
                pass
    return 165.0


def _mode() -> str:
    m = (request.values.get("mode") or "").lower()
    if m in MODES:
        session["test_mode"] = m
    ath = current_athlete()
    return session.get("test_mode") or (ath or {}).get("default_mode", "standard")


# ------------------------------------------------------------------ one active test at a time

class ActiveTest:
    def __init__(self):
        self.lock = threading.RLock()
        self.token = 0          # bumps on every start, so an old video stream can't end a new test
        self.clear()

    def clear(self):
        self.key = None
        self.ex: Optional[EE.Exercise] = None
        self.camera = None
        self.pose = None
        self.recording = False
        self.started = None
        self.athlete = None
        self.mode = "standard"
        self.result = None
        self.monitor = LiveIdentityMonitor(interval=2.0, max_strikes=3)
        self.identity_stopped = False
        self.replay = passport.ReplayRecorder()      # skeleton-only replay for the Talent Passport
        self.precheck_score = None

    def elapsed(self) -> float:
        return 0.0 if self.started is None else max(0.0, time.time() - self.started - COUNTDOWN)

    def remaining(self) -> Optional[float]:
        d = self.ex.duration if self.ex else None
        return None if d is None else max(0.0, d - self.elapsed())


ACTIVE = ActiveTest()


def _close_pose():
    if ACTIVE.pose is not None:
        try:
            ACTIVE.pose.close()
        except Exception:
            pass
        ACTIVE.pose = None


def _release():
    ACTIVE.recording = False
    release_camera(ACTIVE.camera)
    ACTIVE.camera = None
    _close_pose()


# ------------------------------------------------------------------ results

def _results_for(ref: str):
    db = get_db()
    if db is None:
        return []
    try:
        return list(db.exercise_results.find({"athlete_ref": ref}))
    except Exception:
        return []


def _latest_by_exercise(ath: Dict) -> Dict[str, Dict]:
    latest: Dict[str, Dict] = {}
    for d in _results_for(ath["ref"]):
        k = d.get("exercise_type")
        if k and (k not in latest or str(d.get("timestamp", "")) > str(latest[k].get("timestamp", ""))):
            latest[k] = d
    # legacy height/weight page stores elsewhere
    db = get_db()
    if db is not None and ath.get("email"):
        for coll in ("Final_Estimated_Height_and_Weight", "Height and Weight"):
            try:
                d = db[coll].find_one({"user_email": ath["email"]}, sort=[("timestamp", -1)])
                if d:
                    latest["height_weight"] = {"exercise_type": "height_weight",
                                               "value": d.get("final_height_cm") or d.get("height_cm"), "unit": "cm",
                                               "timestamp": str(d.get("timestamp", ""))}
                    break
            except Exception:
                pass
    return latest


def _next_test(ath: Dict, mode: str, just_done: Optional[str] = None) -> Optional[Dict]:
    done = set(_latest_by_exercise(ath))
    if just_done:
        done.add(just_done)
    for k in RECOMMENDED:
        if k in done:
            continue
        if k == "height_weight":
            if ath["kind"] != "user":
                continue      # legacy height page needs a normal account
            return {"key": k, "name": HEIGHT_WEIGHT_CARD["name"], "url": "/height"}
        cls = EE.EXERCISES[k]
        return {"key": k, "name": cls.name, "url": f"/ex/{k}?mode={mode}"}
    return None


def _save_result(manual_value: Optional[float] = None) -> Dict:
    ex, ath = ACTIVE.ex, ACTIVE.athlete
    if manual_value is not None:
        ex.manual_value = float(manual_value)
    res = ex.result()
    population = ACTIVE.mode if ACTIVE.mode in benchmarks.POPULATIONS else "standard"
    bench = benchmarks.evaluate(ex.key, res["value"], ath.get("age"), ath.get("gender"), population)
    doc = {
        "athlete_ref": ath["ref"],
        "athlete_name": ath.get("name"),
        "athlete_age": ath.get("age"),
        "athlete_gender": ath.get("gender"),
        "exercise_type": ex.key,
        "exercise_name": ex.name,
        **res,
        "duration": int(round(ACTIVE.elapsed())) if ex.camera != "none" else None,
        "mode": ACTIVE.mode,
        "benchmark": bench,
        "identity_checked": ACTIVE.monitor.enabled,
        "identity_strikes": ACTIVE.monitor.strikes,
        "stopped_for_identity": ACTIVE.identity_stopped,
        "coach_timed": ex.camera == "none",
        "timestamp": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "date": datetime.utcnow(),
    }
    if ath["kind"] == "user":
        doc["user_email"] = ath.get("email")
        if ObjectId is not None:
            try:
                doc["user_id"] = ObjectId(ath["id"])
            except Exception:
                doc["user_id"] = ath["id"]
    else:
        doc["blind_user_id"] = ath["id"]

    # ---- Talent Passport: sign result + identity evidence + skeleton replay
    replay = ACTIVE.replay.payload() if ex.camera != "none" else None
    identity = {
        "pre_check": "face matched registration photo" if ACTIVE.precheck_score is not None else "not required",
        "pre_check_score": ACTIVE.precheck_score,
        "live_checks": ACTIVE.monitor.checks, "live_passes": ACTIVE.monitor.passes,
        "mismatch_strikes": ACTIVE.monitor.strikes,
    }
    if ObjectId is not None:
        doc["_id"] = ObjectId()
        doc["passport"] = passport.build(doc, replay, identity)
        doc["athlete_token"] = doc["passport"]["athlete_token"]
    db = get_db()
    saved = False
    if db is not None and not ACTIVE.identity_stopped:
        try:
            db.exercise_results.insert_one(dict(doc))
            saved = True
            if replay and replay["frames"] and "_id" in doc:
                db.pose_replays.insert_one({"_id": doc["_id"], **replay})
        except Exception as e:
            log_error(f"Saving {ex.key} result failed: {e}")
    out = {k: v for k, v in doc.items() if k not in ("user_id", "date", "_id")}
    out["saved"] = saved
    if saved and "passport" in doc:
        out["passport_url"] = f"/passport/r/{doc['_id']}/{doc['passport']['token']}"
        out["passport"] = {"token": doc["passport"]["token"], "athlete_token": doc["athlete_token"]}
    out["next_test"] = _next_test(ath, ACTIVE.mode, just_done=ex.key)
    ACTIVE.result = out
    log_info(f"Test finished: {ex.key} = {res['value']} {res['unit']} ({bench.get('rating')}) mode={ACTIVE.mode}")
    return out


def _finish(token: Optional[int] = None):
    with ACTIVE.lock:
        if token is not None and token != ACTIVE.token:
            return None
        if ACTIVE.ex is None or ACTIVE.result is not None:
            return ACTIVE.result
        _release()
        return _save_result()


# ------------------------------------------------------------------ pages

@exercise_bp.route("/tests")
def tests_hub():
    ath = current_athlete()
    mode = _mode()
    cards = []
    latest = _latest_by_exercise(ath) if ath else {}
    for k in RECOMMENDED:
        if k == "height_weight":
            info = dict(HEIGHT_WEIGHT_CARD)
            info["available"] = bool(ath and ath["kind"] == "user")
        else:
            info = EE.EXERCISES[k].info()
            info["url"] = f"/ex/{k}?mode={mode}"
            info["available"] = True
        last = latest.get(k)
        if last:
            info["last"] = {"value": last.get("value"), "unit": last.get("unit"),
                            "rating": (last.get("benchmark") or {}).get("rating"),
                            "when": str(last.get("timestamp", ""))[:10]}
        cards.append(info)
    done = sum(1 for c in cards if c.get("last"))
    hp = None
    if ath:
        hp = potential.hidden_potential(latest, ath.get("age"), ath.get("gender"),
                                        mode if mode in benchmarks.POPULATIONS else "standard")
    return render_template("tests.html", athlete=ath, cards=cards, mode=mode, done=done, total=len(cards),
                           next_test=_next_test(ath, mode) if ath else None, hp=hp,
                           passport_url=f"/passport/a/{passport.athlete_token(ath['ref'])}" if ath else None)


@exercise_bp.route("/ex/<key>")
def exercise_page(key):
    cls = EE.EXERCISES.get(key)
    if cls is None:
        abort(404)
    ath = current_athlete()
    mode = _mode()
    info = cls.info()
    target = None
    if ath:
        pop = mode if mode in benchmarks.POPULATIONS else "standard"
        t = benchmarks.target_for(key, ath.get("age"), ath.get("gender"), pop)
        if t:
            target = {"value": float(t["target"]), "unit": t["unit"],
                      "higher_is_better": t["higher_is_better"] in ("1", "True")}
    return render_template("exercise.html", ex=info, athlete=ath, mode=mode, target=target,
                           height_cm=_height_for(ath) if ath else 165,
                           verify_url=(ath or {}).get("verify_url", "/api/verify_user_identity"),
                           require_face=REQUIRE_FACE_CHECK)


# ------------------------------------------------------------------ API

def _gate(ath):
    if ath is None:
        return {"status": "error", "message": "Please log in (or register) before starting a test."}, 401
    if not REQUIRE_FACE_CHECK:
        return None
    if not ath.get("photo"):
        return {"status": "error", "identity_required": True,
                "message": "No registration photo on your profile, so your identity cannot be checked."}, 403
    if not is_recently_verified(session, ath["verify_key"]):
        return {"status": "error", "identity_required": True,
                "message": "Please verify your identity (face check) before starting."}, 403
    return None


@exercise_bp.route("/ex/<key>/start", methods=["POST"])
def start(key):
    cls = EE.EXERCISES.get(key)
    if cls is None:
        abort(404)
    ath = current_athlete()
    err = _gate(ath)
    if err:
        return jsonify(err[0]), err[1]
    data = request.get_json(silent=True) or {}
    mode = data.get("mode") if data.get("mode") in MODES else _mode()
    try:
        h = float(data.get("height_cm") or 0)
        if 100 <= h <= 230:
            session["athlete_height_cm"] = h
    except (TypeError, ValueError):
        pass

    with ACTIVE.lock:
        _release()
        ACTIVE.clear()
        ACTIVE.token += 1
        ACTIVE.key, ACTIVE.athlete, ACTIVE.mode = key, ath, mode
        ACTIVE.ex = cls(height_cm=_height_for(ath))
        if key == "growth_measures":
            def num(name, lo, hi):
                try:
                    v = float(data.get(name))
                    return v if lo <= v <= hi else None
                except (TypeError, ValueError):
                    return None
            h, w, c = num("height_cm", 100, 230), num("weight_kg", 15, 200), num("chair_cm", 25, 80)
            if not (h and w and c):
                return jsonify({"status": "error", "message": "Enter standing height (cm), weight (kg) and chair height (cm) first."}), 400
            ACTIVE.ex.configure(height_cm=h, weight_kg=w, chair_cm=c, age=ath.get("age"), sex=ath.get("gender"))
        vs = session.get("identity_verified") or {}
        ACTIVE.precheck_score = vs.get("score")
        if cls.camera != "none":
            ACTIVE.camera = open_camera(1280 if key == "broad_jump" else 640, 720 if key == "broad_jump" else 480)
            if not ACTIVE.camera.isOpened():
                _release()
                return jsonify({"status": "error", "message": "Camera unavailable"})
            import mediapipe as mp
            ACTIVE.pose = mp.solutions.pose.Pose(model_complexity=POSE_COMPLEXITY,
                                                 min_detection_confidence=0.5, min_tracking_confidence=0.5)
            ACTIVE.monitor.reset(ath["verify_key"], ath.get("photo"))
        ACTIVE.recording = True
        ACTIVE.started = time.time()
    log_info(f"Test started: {key} mode={mode} athlete={ath['ref']}")
    return jsonify({"status": "success", "duration": cls.duration, "countdown": COUNTDOWN, "camera": cls.camera})


def _draw(frame, ex: EE.Exercise, pose_landmarks):
    if pose_landmarks is not None:
        import mediapipe as mp
        mp.solutions.drawing_utils.draw_landmarks(
            frame, pose_landmarks, mp.solutions.pose.POSE_CONNECTIONS,
            mp.solutions.drawing_utils.DrawingSpec(color=(66, 200, 245), thickness=2, circle_radius=2),
            mp.solutions.drawing_utils.DrawingSpec(color=(255, 255, 255), thickness=2))
    if isinstance(ex, EE.PlateTapping) and ex.targets:
        for side, (x, y, r) in ex.targets.items():
            colour = (0, 220, 0) if side == ex.next_side else (120, 120, 120)
            cv2.circle(frame, (int(x), int(y)), int(r), colour, 3)
    h, w = frame.shape[:2]
    cv2.rectangle(frame, (0, h - 36), (w, h), (0, 0, 0), -1)
    cv2.putText(frame, ex.feedback[:70], (10, h - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1)


def _frames():
    token = ACTIVE.token
    throttle = FrameThrottle(24 if ACTIVE.key in ("vertical_jump", "broad_jump", "plate_tapping", "jumping_jacks") else 15)
    try:
        while ACTIVE.recording and ACTIVE.camera is not None and token == ACTIVE.token:
            ok, frame = ACTIVE.camera.read()
            if not ok:
                time.sleep(0.05)
                continue
            ex = ACTIVE.ex
            ACTIVE.monitor.submit(frame)
            if ACTIVE.monitor.terminated:
                ACTIVE.identity_stopped = True
                ex.feedback = "Stopped - a different person was detected"
                break

            now = time.time()
            res = None
            if ACTIVE.pose is not None:
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                res = ACTIVE.pose.process(rgb).pose_landmarks
            if now - ACTIVE.started < COUNTDOWN:
                ex.feedback = f"Get ready… {int(COUNTDOWN - (now - ACTIVE.started)) + 1}"
            else:
                pose = EE.Pose.from_mediapipe(res, frame.shape[1], frame.shape[0]) if res is not None else None
                ex.update(pose, now)
                ACTIVE.replay.add(now - ACTIVE.started - COUNTDOWN, ex.value(), res)
            _draw(frame, ex, res)
            ACTIVE.monitor.draw(frame)
            yield mjpeg_chunk(encode_jpeg(frame))

            rem = ACTIVE.remaining()
            if ex.finished or (rem is not None and rem <= 0):
                break
            throttle.wait()
    finally:
        # stream over: test finished, time up, identity failure, or the tab was closed
        try:
            _finish(token)
        except Exception as e:
            log_error(f"Finishing test failed: {e}")


@exercise_bp.route("/ex/<key>/video_feed")
def video_feed(key):
    if ACTIVE.key != key or not ACTIVE.recording:
        return Response(status=204)
    return Response(_frames(), mimetype="multipart/x-mixed-replace; boundary=frame")


@exercise_bp.route("/ex/<key>/stats")
def stats(key):
    if ACTIVE.key != key or ACTIVE.ex is None:
        return jsonify({"active": False})
    s = ACTIVE.ex.stats()
    started = ACTIVE.started or time.time()
    s.update({
        "active": ACTIVE.recording,
        "countdown": max(0, round(COUNTDOWN - (time.time() - started), 1)) if ACTIVE.recording else 0,
        "elapsed": round(ACTIVE.elapsed(), 1),
        "remaining": None if ACTIVE.remaining() is None else round(ACTIVE.remaining(), 1),
        "duration": ACTIVE.ex.duration,
        **ACTIVE.monitor.status(),
        "identity_error": ACTIVE.identity_stopped or ACTIVE.monitor.terminated,
        "result": ACTIVE.result,
    })
    return jsonify(s)


@exercise_bp.route("/ex/<key>/stop", methods=["POST"])
def stop(key):
    if ACTIVE.key != key or ACTIVE.ex is None:
        return jsonify({"status": "error", "message": "No active test"})
    if ACTIVE.ex.camera == "none" and ACTIVE.result is None:
        ACTIVE.recording = False      # coach-timed: nothing to save until a time is entered
        return jsonify({"status": "success", "result": None})
    result = _finish()
    return jsonify({"status": "success", "result": result})


@exercise_bp.route("/ex/<key>/manual", methods=["POST"])
def manual(key):
    """Coach-timed tests: the page's stopwatch posts the time here."""
    if ACTIVE.key != key or ACTIVE.ex is None or ACTIVE.ex.camera != "none":
        return jsonify({"status": "error", "message": "Start the test first"}), 400
    try:
        value = float((request.get_json(silent=True) or {}).get("value"))
        if not 1 <= value <= 3600:
            raise ValueError
    except (TypeError, ValueError):
        return jsonify({"status": "error", "message": "Enter a time between 1 and 3600 seconds"}), 400
    with ACTIVE.lock:
        if ACTIVE.result is None:
            ACTIVE.recording = False
            _save_result(manual_value=value)
    return jsonify({"status": "success", "result": ACTIVE.result})


@exercise_bp.route("/ex/<key>/cleanup", methods=["POST"])
def cleanup(key):
    if ACTIVE.key == key and ACTIVE.recording and ACTIVE.ex is not None and ACTIVE.ex.camera != "none":
        _finish()
    return ("", 204)


@exercise_bp.route("/api/tests/catalog")
def catalog():
    return jsonify(EE.catalog())


@exercise_bp.route("/api/tests/progress")
def progress():
    ath = current_athlete()
    if not ath:
        return jsonify({"error": "not logged in"}), 401
    latest = _latest_by_exercise(ath)
    out = {}
    for k, d in latest.items():
        out[k] = {"value": d.get("value"), "unit": d.get("unit"), "timestamp": str(d.get("timestamp", "")),
                  "rating": (d.get("benchmark") or {}).get("rating")}
    return jsonify({"athlete": ath["name"], "results": out, "next_test": _next_test(ath, _mode())})


# ------------------------------------------------------------------ Hidden Potential report

def _athlete_hp(ref: str, email: Optional[str], age, gender, population="standard") -> Dict:
    fake = {"ref": ref, "email": email}
    latest = _latest_by_exercise(fake)
    return potential.hidden_potential(latest, age, gender, population)


@exercise_bp.route("/potential")
def potential_report():
    ath = current_athlete()
    if not ath:
        return render_template("potential.html", athlete=None, hp=None, rank=None, mode=_mode())
    mode = _mode()
    pop = mode if mode in benchmarks.POPULATIONS else "standard"
    latest = _latest_by_exercise(ath)
    hp = potential.hidden_potential(latest, ath.get("age"), ath.get("gender"), pop)

    # Rank among athletes from the same place (or everyone, if no place is stored)
    entries, group = [], "all athletes on this DeepFit server"
    db = get_db()
    if db is not None and ath["kind"] == "user":
        me = db.users.find_one({"_id": ObjectId(ath["id"])}) if ObjectId is not None else None
        place = (me or {}).get("place")
        query = {"place": place} if place else {}
        group = f"athletes from {place}" if place else group
        for u in db.users.find(query):
            uref = f"user:{u['_id']}"
            o = _athlete_hp(uref, u.get("email"), u.get("age"), u.get("gender"), pop)
            if o["fitness_today"] is not None or o["index"] is not None:
                entries.append({"ref": uref, "fitness": o["fitness_today"], "index": o["index"]})
    rank = potential.rank_positions(entries, ath["ref"]) if entries else None
    if rank:
        rank["group"] = group
    return render_template("potential.html", athlete=ath, hp=hp, rank=rank, mode=mode,
                           passport_url=f"/passport/a/{passport.athlete_token(ath['ref'])}")


# ------------------------------------------------------------------ links that work on other devices

def _lan_ip() -> Optional[str]:
    """This computer's Wi-Fi / LAN address (no packet is sent)."""
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return None if ip.startswith("127.") else ip
    except OSError:
        return None


def share_base() -> str:
    """Base URL for QR codes and shared links. 'localhost' only works on this computer, so it is
    replaced by the LAN address; set PUBLIC_BASE_URL in .env once the server has a real domain."""
    import os
    base = os.environ.get("PUBLIC_BASE_URL")
    if base:
        return base.rstrip("/")
    host = request.host
    name, _, port = host.partition(":")
    if name in ("localhost", "127.0.0.1", "0.0.0.0"):
        ip = _lan_ip()
        if ip:
            host = f"{ip}:{port}" if port else ip
    return f"{request.scheme}://{host}"


# ------------------------------------------------------------------ Talent Passport (public, unguessable links)

def _result_by_token(rid: str, tok: str):
    db = get_db()
    if db is None or ObjectId is None:
        return None, None
    try:
        doc = db.exercise_results.find_one({"_id": ObjectId(rid)})
    except Exception:
        return None, None
    if not doc or not doc.get("passport") or doc["passport"].get("token") != tok:
        return None, None
    replay = db.pose_replays.find_one({"_id": doc["_id"]})
    if replay:
        replay = {"fps": replay.get("fps"), "frames": replay.get("frames", [])}
    return doc, replay


def _checked_at() -> str:
    """When the signature was re-checked (server's local time), shown to whoever scanned the QR."""
    now = datetime.now().astimezone()
    return now.strftime("%d %b %Y, %H:%M:%S ") + (now.tzname() or "")


def _qr_svg_inline(url: str) -> Optional[str]:
    """QR code as inline SVG made on the server (works offline and prints sharply). Needs segno."""
    try:
        import segno
    except ImportError:
        return None
    return segno.make_qr(url, error="m").svg_inline(scale=5, border=2, dark="#000", light="#fff")


SKELETON = [(11, 12), (11, 13), (13, 15), (12, 14), (14, 16), (11, 23), (12, 24), (23, 24), (23, 25), (25, 27),
            (24, 26), (26, 28), (27, 29), (29, 31), (27, 31), (28, 30), (30, 32), (28, 32)]


def _skeleton_figure(replay: Optional[Dict], frame_w: float = 640, frame_h: float = 480) -> Optional[Dict]:
    """One still of the skeleton replay (the moment the best value was reached), as SVG lines."""
    frames = (replay or {}).get("frames") or []
    if not frames:
        return None
    best = max(f.get("v", 0) for f in frames)
    f = next((f for f in frames if f.get("v", 0) == best), frames[len(frames) // 2])
    pts = [(p[0] * frame_w, p[1] * frame_h, p[2]) for p in f["lm"]]
    seen = [(x, y) for x, y, v in pts[11:] if v >= 0.4] + ([(pts[0][0], pts[0][1])] if pts[0][2] >= 0.4 else [])
    if len(seen) < 4:
        return None
    xs, ys = [x for x, _ in seen], [y for _, y in seen]
    pad = 0.12 * max(max(xs) - min(xs), max(ys) - min(ys), 1)
    box = (min(xs) - pad, min(ys) - pad, max(xs) - min(xs) + 2 * pad, max(ys) - min(ys) + 2 * pad)
    lines = [(pts[a][0], pts[a][1], pts[b][0], pts[b][1]) for a, b in SKELETON if pts[a][2] >= 0.4 and pts[b][2] >= 0.4]
    head = None
    if pts[0][2] >= 0.4:
        r = max(8.0, 0.35 * ((pts[11][0] - pts[12][0]) ** 2 + (pts[11][1] - pts[12][1]) ** 2) ** 0.5)
        head = (pts[0][0], pts[0][1], r)
    return {"viewbox": "%.1f %.1f %.1f %.1f" % box, "lines": lines, "head": head,
            "stroke": max(2.0, box[3] / 80), "t": f.get("t"), "v": f.get("v")}


def _result_view(rid: str, tok: str):
    doc, replay = _result_by_token(rid, tok)
    if doc is None:
        abort(404)
    valid, problems = passport.verify(doc, replay)
    size = doc.get("frame_size") or {}
    return {
        "doc": doc, "replay": replay, "p": doc["passport"]["payload"], "valid": valid, "problems": problems,
        "rating": (doc.get("benchmark") or {}).get("rating"),
        "target": (doc.get("benchmark") or {}).get("target"),
        "bench": doc.get("benchmark") or {},
        "share_url": share_base() + f"/passport/r/{rid}/{tok}",
        "card_url": f"/passport/r/{rid}/{tok}/card",
        "athlete_url": f"/passport/a/{doc['passport']['athlete_token']}",
        "coach": doc.get("coachability"), "maturity": doc.get("maturity"),
        "checked_at": _checked_at(), "card_id": tok,
        "figure": _skeleton_figure(replay, size.get("w") or 640, size.get("h") or 480),
    }


@exercise_bp.route("/passport/r/<rid>/<tok>")
def passport_result(rid, tok):
    v = _result_view(rid, tok)
    return render_template("passport.html", **{k: v[k] for k in (
        "p", "valid", "problems", "rating", "target", "share_url", "card_url", "athlete_url", "coach", "maturity",
        "checked_at")},
        scanned=request.args.get("scan") == "1",
        has_replay=bool(v["replay"] and v["replay"].get("frames")),
        replay_url=f"/api/passport/replay/{rid}/{tok}")


@exercise_bp.route("/passport/r/<rid>/<tok>/card")
def passport_result_card(rid, tok):
    """Printable verified result card (Print -> Save as PDF), with a QR code back to the live record."""
    v = _result_view(rid, tok)
    qr_target = v["share_url"] + "?scan=1"
    return render_template("passport_card.html", kind="result", qr_target=qr_target, qr_svg=_qr_svg_inline(qr_target),
                           **{k: v[k] for k in ("p", "valid", "problems", "rating", "bench", "coach", "maturity",
                                                "checked_at", "card_id", "figure", "share_url")},
                           back_url=f"/passport/r/{rid}/{tok}")


@exercise_bp.route("/api/passport/replay/<rid>/<tok>")
def passport_replay(rid, tok):
    doc, replay = _result_by_token(rid, tok)
    if doc is None or not replay:
        abort(404)
    return jsonify(replay)


def _athlete_view(atok: str) -> Dict:
    db = get_db()
    docs = []
    if db is not None:
        try:
            docs = list(db.exercise_results.find({"athlete_token": atok}))
        except Exception:
            docs = []
    out = {"name": "Athlete", "age": None, "gender": None, "rows": [], "hp": None, "checked_at": _checked_at(),
           "share_url": share_base() + f"/passport/a/{atok}", "card_url": f"/passport/a/{atok}/card"}
    if not docs:
        return out
    docs.sort(key=lambda d: str(d.get("timestamp", "")), reverse=True)
    latest: Dict[str, Dict] = {}
    for d in docs:
        if d.get("exercise_type") in latest:
            continue
        latest[d["exercise_type"]] = d
        ok, _ = passport.verify(d, None if d.get("coach_timed") else _result_by_token(str(d["_id"]), d["passport"]["token"])[1])
        out["rows"].append({"name": d.get("exercise_name"), "value": d.get("value"), "unit": d.get("unit"),
                            "rating": (d.get("benchmark") or {}).get("rating"), "when": str(d.get("timestamp", ""))[:10],
                            "valid": ok, "url": f"/passport/r/{d['_id']}/{d['passport']['token']}",
                            "coach_timed": d.get("coach_timed")})
    first = docs[0]
    out.update(name=passport.display_name(first.get("athlete_name")), age=first.get("athlete_age"),
               gender=first.get("athlete_gender"),
               hp=potential.hidden_potential(latest, first.get("athlete_age"), first.get("athlete_gender")))
    return out


@exercise_bp.route("/passport/a/<atok>")
def passport_athlete(atok):
    v = _athlete_view(atok)
    return render_template("passport_athlete.html", scanned=request.args.get("scan") == "1",
                           all_valid=bool(v["rows"]) and all(r["valid"] for r in v["rows"]), **v)


@exercise_bp.route("/passport/a/<atok>/card")
def passport_athlete_card(atok):
    v = _athlete_view(atok)
    if not v["rows"]:
        abort(404)
    qr_target = v["share_url"] + "?scan=1"
    return render_template("passport_card.html", kind="athlete", qr_target=qr_target, qr_svg=_qr_svg_inline(qr_target),
                           valid=all(r["valid"] for r in v["rows"]), card_id=atok,
                           back_url=f"/passport/a/{atok}", **v)


@exercise_bp.route("/qr.svg")
def qr_svg():
    """QR code as SVG, made on the server (works offline). Needs `pip install segno`."""
    data = (request.args.get("data") or "")[:500]
    if not data.startswith(("http://", "https://")):
        abort(400)
    try:
        import io
        import segno
    except ImportError:
        abort(404)
    buf = io.BytesIO()
    # make_qr = always a normal QR code (phones can't read "Micro QR")
    segno.make_qr(data, error="m").save(buf, kind="svg", scale=6, border=2)
    return Response(buf.getvalue(), mimetype="image/svg+xml")
