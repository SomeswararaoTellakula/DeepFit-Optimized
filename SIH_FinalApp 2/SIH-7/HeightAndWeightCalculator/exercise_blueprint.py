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

import math
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

import cv2
from flask import Blueprint, Response, abort, jsonify, redirect, render_template, request, session

import benchmarks
import exercise_engine as EE          # first: registers the Coachability + Growth tests
import passport
import pose_backend
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
PUSHUP_VARIANTS = ("pushups", "pushups_modified")
HOME_TESTS = ("height_weight", "situps", "vertical_jump", "dumbbell_curls")   # started from the home page buttons
# The four home-page tests keep their original DeepFit screens (in standard mode); the shared engine runs them.
# After Submit they go straight to the cumulative results. Blind / deaf modes use the accessible /ex/<key> page.
CLASSIC = {"height_weight": ("height.html", "/height"), "situps": ("index_situp.html", "/situp/"),
           "dumbbell_curls": ("index_dumbbell.html", "/dumbbell_ui"), "vertical_jump": ("index_verticaljump.html", "/vertical_jump_ui")}
RESULTS_URL = "/dashboard"
# After Submit each of the four goes to its own original result page
RESULT_PAGES = {"situps": "/displaysitup", "dumbbell_curls": "/displaydumbbell", "vertical_jump": "/displayVerticalJump",
                "height_weight": "/performance_dashboard"}

# Times are stored in UTC and SHOWN in India time (IST has no daylight saving, so a fixed +5:30 is exact).
IST = timezone(timedelta(hours=5, minutes=30), "IST")


def to_ist(v) -> Optional[datetime]:
    """A stored time (datetime, '2026-10-27T15:27:41Z', ISO without zone, or '20261027_152741') in IST. Stored = UTC."""
    if v is None or v == "":
        return None
    try:
        if isinstance(v, datetime):
            d = v
        else:
            t = str(v).strip()
            if len(t) == 15 and t[8] == "_":
                d = datetime.strptime(t, "%Y%m%d_%H%M%S")
            else:
                d = datetime.fromisoformat(t.replace("Z", "+00:00").replace(" ", "T"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d.astimezone(IST)
    except (TypeError, ValueError):
        return None


@exercise_bp.app_template_filter("ist")
def _ist_filter(v, fmt="%d %b %Y, %I:%M %p IST"):
    d = to_ist(v)
    return d.strftime(fmt) if d else (v or "")


def ist_date(v) -> str:
    d = to_ist(v)
    return d.strftime("%Y-%m-%d") if d else str(v or "")[:10]


def test_url(key: str, mode: str = "standard") -> str:
    """Where a test is taken: the classic screen for the four home tests in standard mode, else the shared page."""
    if mode == "standard" and key in CLASSIC:
        return CLASSIC[key][1]
    return f"/ex/{key}?mode={mode}"


def test_keys(ath: Optional[Dict] = None, latest: Optional[Dict] = None) -> List[str]:
    """RECOMMENDED with one card per exercise: push-ups shows ONE variant - the one the athlete already did,
    else the Khelo India rule (girls: modified / knees, boys: full push-ups)."""
    latest = latest or {}
    done = [k for k in PUSHUP_VARIANTS if k in latest]
    if len(done) == 1:
        pick = done[0]
    else:
        g = str((ath or {}).get("gender") or "").strip().lower()
        pick = "pushups_modified" if g in ("f", "female", "girl", "woman") else "pushups"
    return [k for k in RECOMMENDED if k not in PUSHUP_VARIANTS or k == pick]


HEIGHT_WEIGHT_CARD = {
    "key": "height_weight", "name": "Height & Weight (BMI)", "icon": "📏", "category": "body composition",
    "khelo_india": True, "camera": "front", "url": "/ex/height_weight", "metric": "bmi", "unit": "",
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
                if v and 70 <= float(v) <= 230:          # children too (a 110 cm child is not 165 cm)
                    return float(v)
            except Exception:
                pass
    return 165.0


def _weight_for(ath: Dict) -> Optional[float]:
    """Body weight (kg) from the athlete's latest height & weight measurement, if there is one."""
    db = get_db()
    if db is None or not ath or not ath.get("email"):
        return None
    for coll in ("Final_Estimated_Height_and_Weight", "Height and Weight"):
        try:
            d = db[coll].find_one({"user_email": ath["email"]}, sort=[("timestamp", -1)])
            v = d and (d.get("final_weight_kg") or d.get("weight_kg"))
            if v and 15 <= float(v) <= 200:
                return float(v)
        except Exception:
            pass
    return None


def _check_dumbbell(ex, frame, pose_landmarks):
    """Background job: ask SAM 3.1 whether a dumbbell is really in the athlete's hand."""
    try:
        import base64
        import curl_load
        h, w = frame.shape[:2]
        lm = pose_landmarks.landmark
        wrists = [(lm[i].x * w, lm[i].y * h) for i in (EE.L_WRIST, EE.R_WRIST) if getattr(lm[i], "visibility", 1) >= 0.5]
        fore = [math.hypot((lm[a].x - lm[b].x) * w, (lm[a].y - lm[b].y) * h) for a, b in ((13, 15), (14, 16))]
        forearm = max(fore) if fore else 0.1 * h
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        url = "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode()
        cm_per_px = (EE.FOREARM_RATIO * ex.height_cm) / forearm if forearm else None
        ex.load_check = curl_load.dumbbell_check(url, w, h, wrists, forearm, cm_per_px)
    except Exception as e:
        ex.load_check = {"method": "sam-3.1", "seen": None, "reason": f"check failed: {e}"}


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
    # height & weight is also kept where the dashboard reads it (and the phone's tape entry goes there)
    db = get_db()
    if db is not None and ath.get("email"):
        def ts(d):
            return str(d.get("timestamp", "")).replace(" ", "T")[:19]
        for coll in ("Final_Estimated_Height_and_Weight", "Height and Weight"):
            try:
                d = db[coll].find_one({"user_email": ath["email"]}, sort=[("timestamp", -1)])
                if d and ("height_weight" not in latest or ts(d) > ts(latest["height_weight"])):
                    latest["height_weight"] = {"exercise_type": "height_weight",
                                               "value": d.get("final_height_cm") or d.get("height_cm"), "unit": "cm",
                                               "benchmark": {"rating": d.get("bmi_category")} if d.get("bmi_category") else None,
                                               "timestamp": ts(d)}
            except Exception:
                pass
    return latest


def _next_test(ath: Dict, mode: str, just_done: Optional[str] = None) -> Optional[Dict]:
    latest = _latest_by_exercise(ath)
    done = set(latest)
    if just_done:
        done.add(just_done)
    for k in test_keys(ath, latest):
        if k in done:
            continue
        cls = EE.EXERCISES[k]
        return {"key": k, "name": cls.name, "url": test_url(k, mode)}
    return None


def _save_result(manual_value: Optional[float] = None) -> Dict:
    ex, ath = ACTIVE.ex, ACTIVE.athlete
    if manual_value is not None:
        ex.manual_value = float(manual_value)
    res = ex.result()
    population = ACTIVE.mode if ACTIVE.mode in benchmarks.POPULATIONS else "standard"
    bench = load_benchmark(ex, res, ath, population) or benchmarks.evaluate(ex.key, res["value"], ath.get("age"), ath.get("gender"), population)
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
        **({"identity_scope": "time_entered"} if ex.camera == "none" else {}),   # stopwatch: the time was typed in
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
            if ex.key == "height_weight" and doc.get("height_cm") and not doc.get("incomplete") and doc.get("user_email"):
                db["Final_Estimated_Height_and_Weight"].insert_one(height_record(doc))   # dashboard + reports read this
            legacy = legacy_record(doc)
            if legacy:
                db[legacy[0]].insert_one(legacy[1])     # the cumulative dashboard and Best Results read these
        except Exception as e:
            log_error(f"Saving {ex.key} result failed: {e}")
    out = {k: v for k, v in doc.items() if k not in ("user_id", "date", "_id")}
    out["saved"] = saved
    if saved and "passport" in doc:
        out["passport_url"] = f"/passport/r/{doc['_id']}/{doc['passport']['token']}"
        out["passport"] = {"token": doc["passport"]["token"], "athlete_token": doc["athlete_token"]}
        out["result_id"] = str(doc["_id"])
        out["hand_check_prompt"] = hand_check_prompt(doc)
    out["next_test"] = _next_test(ath, ACTIVE.mode, just_done=ex.key)
    ACTIVE.result = out
    log_info(f"Test finished: {ex.key} = {res['value']} {res['unit']} ({bench.get('rating')}) mode={ACTIVE.mode}")
    return out


def legacy_record(doc: Dict):
    """Sit-ups, Vertical Jump and Dumbbell Curls now exist once (in this engine). The cumulative dashboard and
    Best Results / qualification still read the old pages' collections, so each real engine result is also
    written there in the old format. Returns (collection, record) or None."""
    key, email = doc.get("exercise_type"), doc.get("user_email")
    if key not in ("situps", "vertical_jump", "dumbbell_curls") or not email or doc.get("value") is None:
        return None
    now = datetime.utcnow()
    secs = int(doc.get("duration") or 0)
    base = {"user_email": email, "submission_time": now, "timer_time": f"{secs // 60}:{secs % 60:02d}",
            "exercise_result_id": str(doc.get("_id", "")), "source": "DeepFit test engine"}
    if key == "situps":
        return "situps", {**base, "reps_completed": int(doc["value"]), "form_quality": doc.get("form_score"), "created_at": now}
    if key == "vertical_jump":
        att = [float(a) for a in (doc.get("attempts") or [])]
        form = doc.get("jump_form") or []
        jumps = []
        for i, h in enumerate(att):
            f = form[i] if i < len(form) else {}
            jumps.append({"jump_number": i + 1, "height_cm": h, "body_angle": f.get("body_angle"),
                          "knee_angles": {"left": f.get("knee_left"), "right": f.get("knee_right")}})
        return "Vertical_Jump", {**base, "jumps": jumps, "max_height": float(doc["value"]), "total_jumps": len(att) or int(doc.get("repetitions") or 0),
                                 "average_height": round(sum(att) / len(att), 1) if att else float(doc["value"]), "jump_heights": att,
                                 "session_start": now.isoformat(timespec="seconds") + "Z"}
    arms = doc.get("arm_counts") or {}
    return "DumbBell", {**base, "total_reps": int(doc["value"]), "estimated_weight": doc.get("load_kg") or 0,
                        "left_reps": int(arms.get("left") or 0), "right_reps": int(arms.get("right") or 0), "session_duration": secs,
                        "timestamp": now.strftime("%Y%m%d_%H%M%S"), "exercise_type": "dumbbell_curls",
                        "analysis_date": now.isoformat(timespec="seconds") + "Z"}


def height_record(doc: Dict) -> Dict:
    """Same fields the old height page wrote, so the dashboard, reports and qualification keep working."""
    m = doc.get("measurement") or {}
    est = bool(doc.get("estimate") or m.get("estimate"))          # no wall sheets: estimated from the body
    ws = doc.get("weight_source")
    return {"user_email": doc.get("user_email"), "final_height_cm": doc.get("height_cm"),
            "final_weight_kg": doc.get("weight_kg"), "bmi": doc.get("bmi"), "bmi_category": doc.get("bmi_category"),
            "height_uncertainty": (f"±{m.get('uncertainty_cm') or 8} cm (estimate)" if est
                                   else f"±{max(0.5, m.get('spread_cm') or 0.5):.1f} cm"),
            "weight_uncertainty": ("typical weight for this height (estimate)" if ws == "estimate"
                                   else "as the scale" if ws == "scale_photo" else "typed"),
            "confidence_level": (f"estimate from body proportions, about ±{m.get('uncertainty_cm') or 8} cm" if est
                                 else "camera, about ±1 cm"), "total_instances": m.get("samples"),
            "method": f"camera + {m.get('reference') or 'reference'}; weight {doc.get('weight_source') or 'not given'}",
            "exercise_result_id": str(doc.get("_id", "")), "timestamp": datetime.utcnow()}


def load_benchmark(ex, res: Dict, ath: Dict, population: str) -> Optional[Dict]:
    """Weighted curls are compared with the target for the weight that was lifted (curl_load_benchmarks.csv).
    Height & weight has no 'score' - its benchmark is the BMI category (or BMI-for-age under 18)."""
    if ex.key == "height_weight":
        if not res.get("height_cm"):
            return {"available": False}
        return {"available": True, "unit": "cm",
                "rating": res.get("bmi_category") or ("Estimated" if res.get("estimate") else "Measured" if res.get("bmi") else "Height only"),
                "bmi": res.get("bmi"), "note": res.get("bmi_note") or "Add your weight to get the BMI."}
    if not isinstance(ex, EE.DumbbellCurls) or not res.get("load_kg"):
        return None
    import curl_load
    return curl_load.evaluate(res["load_analysis"], ath.get("age"), ath.get("gender"), population, ex.body_weight_kg)


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
    for k in test_keys(ath, latest):
        info = EE.EXERCISES[k].info()
        info["url"] = test_url(k, mode)
        info["available"] = True
        if k == "height_weight":
            info["metric"] = "bmi"
        info["on_home"] = k in HOME_TESTS
        last = latest.get(k)
        if last:
            info["last"] = {"value": last.get("value"), "unit": last.get("unit"),
                            "rating": (last.get("benchmark") or {}).get("rating"),
                            "when": ist_date(last.get("timestamp"))}
        cards.append(info)
    done = sum(1 for c in cards if c.get("last"))
    hp = None
    if ath:
        hp = potential.hidden_potential(latest, ath.get("age"), ath.get("gender"),
                                        mode if mode in benchmarks.POPULATIONS else "standard")
    return render_template("tests.html", athlete=ath, cards=cards, mode=mode, done=done, total=len(cards), home_tests=HOME_TESTS,
                           next_test=_next_test(ath, mode) if ath else None, hp=hp,
                           passport_url=f"/passport/a/{passport.athlete_token(ath['ref'])}" if ath else None)


@exercise_bp.route("/ex/<key>")
def exercise_page(key):
    cls = EE.EXERCISES.get(key)
    if cls is None:
        abort(404)
    ath = current_athlete()
    mode = _mode()
    if mode == "standard" and key in CLASSIC and request.args.get("page") != "shared":
        return redirect(CLASSIC[key][1])
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


def classic_page(key: str):
    """The original DeepFit screen for one of the four home tests, run by the shared engine (see static/js/classic_test.js)."""
    cls = EE.EXERCISES.get(key)
    if cls is None or key not in CLASSIC:
        abort(404)
    ath = current_athlete()
    if ath is None:
        return redirect(f"/login?next={CLASSIC[key][1]}")
    info = cls.info()
    ctx = {"key": key, "name": info["name"], "duration": cls.duration, "requireFace": bool(REQUIRE_FACE_CHECK),
           "verifyUrl": ath.get("verify_url", "/api/verify_user_identity"), "resultsUrl": RESULT_PAGES.get(key, RESULTS_URL)}
    return render_template(CLASSIC[key][0], user=ath, ex=info, classic=ctx)


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
        if key == "dumbbell_curls":
            try:
                load = float(data.get("load_kg") or 0)
            except (TypeError, ValueError):
                load = 0
            if load and not 0.5 <= load <= 60:
                return jsonify({"status": "error", "message": "Dumbbell weight must be between 0.5 and 60 kg."}), 400
            ACTIVE.ex.configure(load_kg=load or None, body_weight_kg=_weight_for(ath))
            det = data.get("load_detect") if isinstance(data.get("load_detect"), dict) else None
            try:
                same = det is not None and abs(float(det.get("kg")) - load) < 0.01
            except (TypeError, ValueError):
                same = False
            ACTIVE.ex.load_detect = ({k: det.get(k) for k in ("source", "kg", "label_text", "model", "sure", "object")}
                                     if same and load else {"source": "typed"} if load else None)
        if key == "height_weight":
            wd = data.get("weight_detail") if isinstance(data.get("weight_detail"), dict) else None
            ACTIVE.ex.configure(weight_kg=data.get("weight_kg"), weight_source=data.get("weight_source"),
                                weight_detail={k: wd.get(k) for k in ("reading", "unit", "model", "confidence")} if wd else None,
                                age=ath.get("age"), sex=ath.get("gender"))
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
            big = key in ("broad_jump", "height_weight")
            ACTIVE.camera = open_camera(1280 if big else 640, 720 if big else 480)
            if not ACTIVE.camera.isOpened():
                _release()
                return jsonify({"status": "error", "message": "Camera unavailable"})
            try:       # works with old (mp.solutions) and new (Tasks API) MediaPipe - see pose_backend.py
                ACTIVE.pose = pose_backend.PoseBackend(segmentation=getattr(cls, "needs_frames", False),
                                                       complexity=POSE_COMPLEXITY)
            except Exception as e:
                _release()
                log_error(f"Body tracking could not start: {e}")
                return jsonify({"status": "error", "message": "Body tracking could not start (the first run downloads a "
                                                              f"small model and needs internet): {e}"})
            ACTIVE.monitor.reset(ath["verify_key"], ath.get("photo"), side_view=(cls.camera == "side"))
        ACTIVE.recording = True
        ACTIVE.started = time.time()
    log_info(f"Test started: {key} mode={mode} athlete={ath['ref']}")
    return jsonify({"status": "success", "duration": cls.duration, "countdown": COUNTDOWN, "camera": cls.camera})


def _draw(frame, ex: EE.Exercise, pose_landmarks):
    pose_backend.draw(frame, pose_landmarks)
    refs = getattr(ex, "ref", None)
    if isinstance(refs, dict) and refs.get("kind"):          # height test: show the wall sheets that were found
        import numpy as np
        for role in ("floor", "top"):
            q = refs.get(role)
            if q and q.get("corners"):
                cv2.polylines(frame, [np.array(q["corners"], dtype=np.int32)], True, (60, 220, 60), 3)
                x, y = [int(v) for v in q["corners"][0]]
                cv2.putText(frame, role.upper(), (x, max(20, y - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (60, 220, 60), 2)
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
            res, mask = None, None
            if ACTIVE.pose is not None:
                res, mask = ACTIVE.pose.process(frame, now)
            if now - ACTIVE.started < COUNTDOWN:
                ex.feedback = f"Get ready… {int(COUNTDOWN - (now - ACTIVE.started)) + 1}"
            else:
                pose = EE.Pose.from_mediapipe(res, frame.shape[1], frame.shape[0]) if res is not None else None
                ex.update(pose, now)
                if getattr(ex, "needs_frames", False):       # height: measured on the picture itself
                    ex.feed_frame(frame, res, mask, now)
                if (isinstance(ex, EE.DumbbellCurls) and ex.load_kg and ex.load_check is None and pose is not None
                        and pose.vis(EE.L_WRIST, EE.R_WRIST, EE.L_ELBOW, EE.R_ELBOW)):
                    ex.load_check = {"method": "sam-3.1", "seen": None, "reason": "checking"}
                    threading.Thread(target=_check_dumbbell, args=(ex, frame.copy(), res), daemon=True).start()
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


@exercise_bp.route("/ex/<key>/capture", methods=["POST"])
def capture(key):
    """Height & Weight: 'capture' (said aloud, or the S key) - measure now with what the camera has seen so far."""
    ex = ACTIVE.ex
    if ACTIVE.key != key or ex is None or not hasattr(ex, "capture"):
        return jsonify({"ok": False, "message": "Start the measurement first"}), 400
    if not ACTIVE.recording:
        return jsonify({"ok": bool(ACTIVE.result), "result": ACTIVE.result})
    problem = ex.capture()
    if problem:
        return jsonify({"ok": False, "message": problem})
    return jsonify({"ok": True})          # the video stream sees 'finished' on its next frame and saves the result


@exercise_bp.route("/ex/<key>/abort", methods=["POST"])
def abort_test(key):
    """Reset: end the running test WITHOUT saving it (the stream sees the new token and stops)."""
    with ACTIVE.lock:
        if ACTIVE.key == key and ACTIVE.result is None:
            ACTIVE.token += 1
            _release()
            ACTIVE.clear()
    return ("", 204)


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


# ------------------------------------------------------------------ hand check (real-person accuracy)
# After a test, whoever watched can enter what they measured by hand. It is kept next to the result as a reference
# (the score and the passport do not change) and /validation compares the app with these hand values per test.
HAND_CHECK = {
    # key: (what to do, unit, tolerance that counts as "agrees")
    "situps": ("Count the sit-ups by hand while watching", "reps", 0),
    "partial_curlup": ("Count the curl-ups by hand while watching", "reps", 0),
    "pushups": ("Count the push-ups by hand while watching", "reps", 0),
    "pushups_modified": ("Count the push-ups by hand while watching", "reps", 0),
    "squats": ("Count the squats by hand while watching", "reps", 0),
    "jumping_jacks": ("Count the jumping jacks by hand while watching", "reps", 0),
    "dumbbell_curls": ("Count all curls (both arms) by hand while watching", "reps", 0),
    "flamingo_balance": ("Count the falls by hand while watching", "falls", 0),
    "plank": ("Time the plank with a stopwatch", "s", 1.0),
    "plate_tapping": ("Time the 25 cycles with a stopwatch", "s", 0.5),
    "run_600m": ("Time the run with a stopwatch (someone at the start and finish)", "s", 2.0),
    "vertical_jump": ("Measure the best jump with a tape (jump-and-reach marks on a wall)", "cm", 3.0),
    "broad_jump": ("Measure the best jump with a tape: start line to the back of the nearest heel", "cm", 3.0),
    "sit_and_reach": ("Read the ruler at the fingertips (cm past the toes, minus if short)", "cm", 2.0),
    "height_weight": ("Measure height against a wall with a tape", "cm", 1.0),
}


def hand_check_prompt(doc: Dict) -> Optional[Dict]:
    """What a person can measure by hand for this result (None = nothing to compare)."""
    k = doc.get("exercise_type")
    if k not in HAND_CHECK or doc.get("incomplete") or (k == "run_600m" and doc.get("timing") != "gps"):
        return None                       # coach-timed runs ARE the hand value
    label, unit, tol = HAND_CHECK[k]
    return {"label": label, "unit": unit, "tolerance": tol}


def _app_value(doc: Dict) -> Optional[float]:
    v = doc.get("height_cm") if doc.get("exercise_type") == "height_weight" else doc.get("value")
    return float(v) if isinstance(v, (int, float)) else None


def save_hand_check(doc: Dict, value, source: str) -> Dict:
    """Store the hand value on the result; returns the comparison for the screen."""
    pr = hand_check_prompt(doc)
    if pr is None:
        return {"ok": False, "error": "This result has nothing to check by hand."}
    try:
        v = float(value)
    except (TypeError, ValueError):
        return {"ok": False, "error": "Enter a number."}
    lo = -60 if doc.get("exercise_type") == "sit_and_reach" else 0
    if not (lo <= v <= 2000):
        return {"ok": False, "error": "That number is out of range."}
    app = _app_value(doc)
    hc = {"value": round(v, 2), "unit": pr["unit"], "source": source, "at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")}
    db = get_db()
    if db is not None:
        db.exercise_results.update_one({"_id": doc["_id"]}, {"$set": {"hand_check": hc}})
    diff = None if app is None else round(app - v, 2)
    agrees = diff is not None and abs(diff) <= pr["tolerance"] + 1e-9
    return {"ok": True, "app": app, "hand": round(v, 2), "unit": pr["unit"], "difference": diff, "agrees": agrees}


def validation_stats() -> Dict:
    """App vs hand values, per test, over every result someone checked by hand."""
    db = get_db()
    rows: Dict[str, List] = {}
    if db is not None:
        try:
            docs = list(db.exercise_results.find({}))
        except Exception:
            docs = []
        for d in docs:
            hc = d.get("hand_check")
            app = _app_value(d)
            pr = hand_check_prompt(d)
            if not hc or app is None or pr is None or not isinstance(hc.get("value"), (int, float)):
                continue
            rows.setdefault(d["exercise_type"], []).append((app, float(hc["value"]), pr))
    out = []
    for k, vals in sorted(rows.items()):
        diffs = [a - h for a, h, _ in vals]
        tol = vals[0][2]["tolerance"]
        out.append({"key": k, "name": getattr(EE.EXERCISES.get(k), "name", k), "unit": vals[0][2]["unit"], "n": len(vals),
                    "mean_abs": round(sum(abs(x) for x in diffs) / len(diffs), 2),
                    "bias": round(sum(diffs) / len(diffs), 2),
                    "agree_pct": round(100 * sum(1 for x in diffs if abs(x) <= tol + 1e-9) / len(diffs)),
                    "tolerance": tol, "worst": round(max(diffs, key=abs), 2)})
    return {"tests": out, "results_checked": sum(r["n"] for r in out)}


@exercise_bp.route("/api/hand_check", methods=["POST"])
def api_hand_check():
    """Website: the athlete (or the coach next to them) adds the hand-measured value to their own result."""
    data = request.get_json(silent=True) or {}
    doc, _ = _result_by_token(str(data.get("rid", "")), str(data.get("tok", "")))
    ath = current_athlete()
    if doc is None or ath is None or doc.get("athlete_ref") != ath["ref"]:
        return jsonify({"ok": False, "error": "Result not found."}), 404
    r = save_hand_check(doc, data.get("value"), "web")
    return jsonify(r), (200 if r["ok"] else 400)


@exercise_bp.route("/api/validation")
def api_validation():
    return jsonify(validation_stats())


@exercise_bp.route("/validation")
def validation_page():
    return render_template("validation.html", stats=validation_stats())


def _checked_at() -> str:
    """When the signature was re-checked (India time), shown to whoever scanned the QR."""
    return datetime.now(timezone.utc).astimezone(IST).strftime("%d %b %Y, %I:%M:%S %p IST")


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
        "load": doc.get("load_analysis") if doc.get("load_kg") else None, "load_check": doc.get("load_check") or {},
        "checked_at": _checked_at(), "card_id": tok,
        "figure": _skeleton_figure(replay, size.get("w") or 640, size.get("h") or 480),
    }


@exercise_bp.app_template_filter("who_ran")
def _who_ran(scope):
    """Passport line: what a timed result proves about who did it."""
    return passport.identity_scope_text(scope)


@exercise_bp.route("/passport/r/<rid>/<tok>")
def passport_result(rid, tok):
    v = _result_view(rid, tok)
    return render_template("passport.html", **{k: v[k] for k in (
        "p", "valid", "problems", "rating", "target", "share_url", "card_url", "athlete_url", "coach", "maturity",
        "checked_at", "load", "load_check")},
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
                                                "checked_at", "card_id", "figure", "share_url", "load", "load_check")},
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
                            "rating": (d.get("benchmark") or {}).get("rating"), "when": ist_date(d.get("timestamp")),
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


# ------------------------------------------------------------------ height marker + reading numbers off photos

@exercise_bp.route("/height/marker")
def height_marker():
    """The two printable DeepFit height sheets (FLOOR + TOP, 16 cm codes). Print at 100 % / 'actual size'."""
    import stature
    return render_template("height_marker.html", svg_floor=stature.marker_svg("floor"), svg_top=stature.marker_svg("top"),
                           size_cm=stature.MARKER_CM, gap_cm=stature.MARKER_GAP_CM)


def _photo_from_request() -> Optional[bytes]:
    import vision_reader
    if request.files.get("photo"):
        data = request.files["photo"].read()
        return data if 100 < len(data) < 12 * 1024 * 1024 else None
    return vision_reader.decode_b64_image((request.get_json(silent=True) or {}).get("photo"))


@exercise_bp.route("/api/vision/scale", methods=["POST"])
def vision_scale():
    """Photo of the bathroom-scale display -> the weight on it (read by the vision model)."""
    import vision_reader
    if current_athlete() is None:
        return jsonify({"ok": False, "error": "Please log in first."}), 401
    photo = _photo_from_request()
    if photo is None:
        return jsonify({"ok": False, "error": "No photo received."}), 400
    return jsonify(vision_reader.read_scale(photo))


@exercise_bp.route("/api/dumbbell/detect", methods=["POST"])
def dumbbell_detect():
    """Photo of the dumbbell -> its weight (number read off it, or an estimate the athlete confirms)."""
    import vision_reader
    if current_athlete() is None:
        return jsonify({"ok": False, "error": "Please log in first."}), 401
    photo = _photo_from_request()
    if photo is None:
        return jsonify({"ok": False, "error": "No photo received."}), 400
    return jsonify(vision_reader.read_dumbbell(photo))
