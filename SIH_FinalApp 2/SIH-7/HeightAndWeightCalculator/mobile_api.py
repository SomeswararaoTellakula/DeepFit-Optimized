"""
DeepFit mobile app API  -  /api/v1/...

The website keeps working exactly as before; this blueprint only ADDS JSON endpoints
for the Flutter app (folder deepfit_mobile/ next to this project).

How a phone result is trusted
-----------------------------
The phone runs the test on-device (works with no internet): camera, body tracking
(Google ML Kit, the same 33 body points as MediaPipe), rep counting with a Dart copy
of exercise_engine.py, voice, vibration, blind / deaf modes.

When the phone syncs it uploads
  * the skeleton track (33 points per frame, no images),
  * small face snapshots taken every few seconds during the test,
  * the score the phone computed.
The server then
  1. checks every face snapshot against the registration photo (same rules as the
     website: 3 mismatches in a row, or the face hidden too long, rejects the result),
  2. RE-RUNS the Python exercise engine on the skeleton track - the server's number is
     the one that is saved, so a modified app cannot inflate a score,
  3. saves the result, signs the Talent Passport and stores the skeleton replay.
Face snapshots are only used for the check and are not stored.

Endpoints
    GET  /api/v1/ping
    POST /api/v1/auth/login           {email, password}
    POST /api/v1/auth/register        {name, age, gender, place, phone, email, password, photo}
    GET  /api/v1/hub?mode=            tests, targets, last results, next test, Hidden Potential
    POST /api/v1/identity/verify      {frame, live}
    POST /api/v1/results              skeleton + snapshots (JSON, optionally gzip)
    POST /api/v1/height_weight        {height_cm, weight_kg, height_source, weight_source, measurement, weight_detail}
    POST /api/v1/height_weight/measure {photos: [jpeg base64, ...]}   height from photos (marker / A4 on the wall)
    POST /api/v1/vision/scale         {photo}   weight read off the scale display
    POST /api/v1/dumbbell/detect      {photo}   dumbbell weight read off the dumbbell
    GET  /api/v1/history?limit=
    GET  /api/v1/potential?mode=
    POST /api/v1/chat                 {message}
    POST /api/v1/chat/reset
"""

import functools
import json
import math
import os
import types
import zlib
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np
from flask import Blueprint, current_app, jsonify, request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

import benchmarks
import run_check
import exercise_blueprint as XB          # imports exercise_engine first (registers Coachability + Growth)
import exercise_engine as EE
import passport
import potential
from coachability import LOWER, MOVES, PATTERN_LEN, UPPER
from db_config import get_db
from error_logger import log_error, log_info
from identity_guard import FACE_HIDDEN_SECONDS, REQUIRE_FACE_CHECK, IdentityGuard, reason_message

try:
    import bcrypt
except Exception:  # pragma: no cover
    bcrypt = None
try:
    from bson import ObjectId
except Exception:  # pragma: no cover
    ObjectId = None

mobile_bp = Blueprint("mobile_api", __name__, url_prefix="/api/v1")

API_VERSION = 1
TOKEN_DAYS = 30
PRECHECK_MINUTES = 15
T0 = 1000.0                     # engine clock offset (the phone uses the same one)
MAX_BODY = 40 * 1024 * 1024     # bytes after decompression
MAX_FPS = 35
MAX_SNAPSHOTS = 400
SNAP_EVERY_MAX = 10.0           # at least one face snapshot per 10 s of camera test
MAX_STRIKES = 3
VALUE_TOLERANCE = 0.05          # phone vs server difference that still counts as "same"
HIDE_FROM_APP = {"user_id", "date", "_id"}


# ------------------------------------------------------------------ helpers

def _ok(**kw):
    return jsonify({"ok": True, **kw})


def _err(message: str, code: int = 400, **kw):
    return jsonify({"ok": False, "error": message, **kw}), code


class UploadTooLarge(Exception):
    pass


def json_errors(fn):
    """The website's global error handler returns an HTML page; the app needs JSON."""
    @functools.wraps(fn)
    def wrapper(*a, **kw):
        try:
            return fn(*a, **kw)
        except UploadTooLarge:
            return _err("Upload too large.", 413)
        except Exception as e:  # pragma: no cover - logged and reported
            log_error(f"mobile api {request.path} failed: {e}")
            return _err("Server error - please try again.", 500)
    return wrapper


def _signer(salt: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(current_app.secret_key, salt=salt)


def make_token(uid: str) -> str:
    return _signer("deepfit-mobile-v1").dumps({"uid": uid})


def _base_url() -> str:
    return XB.share_base()


def _num(v, lo, hi) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) and lo <= f <= hi else None


def _body() -> Dict:
    raw = request.get_data(cache=False) or b""
    if len(raw) > MAX_BODY:
        raise UploadTooLarge()
    if request.headers.get("Content-Encoding", "").lower() == "gzip":
        unz = zlib.decompressobj(16 + zlib.MAX_WBITS)      # bounded: a "zip bomb" can't fill memory
        try:
            raw = unz.decompress(raw, MAX_BODY + 1)
        except zlib.error:
            raw = b""
        if len(raw) > MAX_BODY:
            raise UploadTooLarge()
    try:
        data = json.loads(raw.decode("utf-8")) if raw else {}
    except ValueError:
        data = {}
    return data if isinstance(data, dict) else {}


def _athlete_from_doc(doc: Dict) -> Dict:
    uid = str(doc["_id"])
    return {"kind": "user", "id": uid, "ref": f"user:{uid}", "verify_key": uid,
            "name": doc.get("name", "Athlete"), "age": doc.get("age"), "gender": doc.get("gender"),
            "email": doc.get("email"), "photo": doc.get("photo"), "place": doc.get("place"),
            "default_mode": "standard"}


def _public(ath: Dict) -> Dict:
    return {"id": ath["id"], "name": ath.get("name"), "age": ath.get("age"), "gender": ath.get("gender"),
            "place": ath.get("place"), "email": ath.get("email"), "has_photo": bool(ath.get("photo")),
            "passport_url": f"{_base_url()}/passport/a/{passport.athlete_token(ath['ref'])}"}


def current_athlete() -> Optional[Dict]:
    h = request.headers.get("Authorization", "")
    if not h.startswith("Bearer "):
        return None
    try:
        data = _signer("deepfit-mobile-v1").loads(h[7:].strip(), max_age=TOKEN_DAYS * 86400)
    except (BadSignature, SignatureExpired):
        return None
    db = get_db()
    if db is None or ObjectId is None:
        return None
    try:
        doc = db.users.find_one({"_id": ObjectId(str(data.get("uid")))})
    except Exception:
        doc = None
    return _athlete_from_doc(doc) if doc else None


def login_required(fn):
    @functools.wraps(fn)
    def wrapper(*a, **kw):
        ath = current_athlete()
        if ath is None:
            return _err("Please log in again.", 401, auth=True)
        return fn(ath, *a, **kw)
    return wrapper


def _height_for(ath: Dict) -> float:
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


def _population(mode: str) -> str:
    return mode if mode in benchmarks.POPULATIONS else "standard"


def _targets(key: str, ath: Dict) -> Dict:
    out = {}
    for pop in benchmarks.POPULATIONS:
        r = benchmarks.target_for(key, ath.get("age"), ath.get("gender"), pop)
        if r:
            out[pop] = {"target": float(r["target"]), "unit": r["unit"],
                        "higher_is_better": r["higher_is_better"] in ("1", "True", "true"),
                        "scoring": r["scoring"], "age_band": f'{r["age_min"]}-{r["age_max"]}'}
    return out


def _next_key(latest: Dict) -> Optional[str]:
    for k in XB.RECOMMENDED:
        if k not in latest:
            return k
    return None


# ------------------------------------------------------------------ basics + accounts

@mobile_bp.route("/ping")
def ping():
    guard = IdentityGuard.get()
    return _ok(server="DeepFit", api=API_VERSION, require_face=REQUIRE_FACE_CHECK,
               face_engine=bool(guard.available), time=datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"))


@mobile_bp.route("/auth/login", methods=["POST"])
@json_errors
def login():
    data = _body()
    email = str(data.get("email") or "").strip().lower()
    password = str(data.get("password") or "")
    if not email or not password:
        return _err("Email and password are required.")
    db = get_db()
    if db is None:
        return _err("Database unavailable.", 503)
    user = db.users.find_one({"email": email})
    stored = (user or {}).get("password")
    if isinstance(stored, str):
        stored = stored.encode("utf-8")
    if not user or not stored or bcrypt is None or not bcrypt.checkpw(password.encode("utf-8"), stored):
        return _err("Invalid email or password.", 401)
    ath = _athlete_from_doc(user)
    log_info(f"Mobile login: {email}")
    return _ok(token=make_token(ath["id"]), athlete=_public(ath))


@mobile_bp.route("/auth/register", methods=["POST"])
@json_errors
def register():
    """Same rules as the website's /signup (exactly one clear face in the photo)."""
    d = _body()
    name = str(d.get("name") or "").strip()
    gender = str(d.get("gender") or "").strip()
    place = str(d.get("place") or "").strip()
    phone = str(d.get("phone") or "").strip()
    email = str(d.get("email") or "").strip().lower()
    password = str(d.get("password") or "")
    photo = str(d.get("photo") or "")
    age = _num(d.get("age"), 5, 99)
    if not all([name, gender, place, phone, email, password, photo]) or age is None:
        return _err("All fields including the photo are required (age 5-99).")
    if "@" not in email or "." not in email:
        return _err("Invalid email format.")
    if not phone.isdigit() or len(phone) < 10:
        return _err("Invalid phone number.")
    if len(password) < 6:
        return _err("Password must be at least 6 characters long.")
    if not photo.startswith("data:image"):
        photo = "data:image/jpeg;base64," + photo
    ok, msg = IdentityGuard.get().check_registration_photo(photo)
    if not ok:
        return _err(msg)
    db = get_db()
    if db is None:
        return _err("Database unavailable.", 503)
    if db.users.find_one({"email": email}):
        return _err("Email already registered.")
    if bcrypt is None:
        return _err("Server is missing bcrypt.", 500)
    doc = {"name": name, "age": int(age), "gender": gender, "place": place, "phone": phone, "email": email,
           "password": bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()),
           "photo": photo, "created_at": datetime.utcnow(), "registered_from": "mobile"}
    doc["_id"] = db.users.insert_one(doc).inserted_id
    ath = _athlete_from_doc(doc)
    log_info(f"Mobile registration: {email}")
    return _ok(token=make_token(ath["id"]), athlete=_public(ath))


# ------------------------------------------------------------------ hub

@mobile_bp.route("/hub")
@json_errors
@login_required
def hub(ath):
    mode = request.args.get("mode") if request.args.get("mode") in XB.MODES else "standard"
    latest = XB._latest_by_exercise(ath)
    tests = []
    for k in XB.RECOMMENDED:
        if k == "height_weight":
            info = dict(XB.HEIGHT_WEIGHT_CARD)
            info.update({"camera": "none", "duration": None, "metric": "height", "unit": "cm",
                         "higher_is_better": True, "kind": "height_weight",
                         "setup": ["Height: tape the DeepFit marker (or an A4 sheet) on the wall, stand next to it, "
                                   "and let the camera measure you - or type a tape measurement",
                                   "Weight: photograph your scale's display - or type it",
                                   "Height is used to convert jumps and reach to cm"]})
            info.pop("url", None)
        else:
            info = EE.EXERCISES[k].info()
            info["kind"] = "stopwatch" if info["camera"] == "none" else "camera"
        info["targets"] = _targets(k, ath)
        last = latest.get(k)
        if last:
            info["last"] = {"value": last.get("value"), "unit": last.get("unit"),
                            "rating": (last.get("benchmark") or {}).get("rating"),
                            "when": str(last.get("timestamp", ""))[:10]}
        tests.append(info)
    hp = potential.hidden_potential(latest, ath.get("age"), ath.get("gender"), _population(mode))
    nk = _next_key(latest)
    return _ok(athlete=_public(ath), tests=tests, done=sum(1 for t in tests if t.get("last")), total=len(tests),
               next_test=nk, hidden_potential=hp, height_cm=_height_for(ath), require_face=REQUIRE_FACE_CHECK,
               face_hidden_seconds=FACE_HIDDEN_SECONDS, engine_t0=T0)


# ------------------------------------------------------------------ identity

def _verify(ath: Dict, frame_b64: str, single: bool) -> Tuple[bool, float, Dict]:
    guard = IdentityGuard.get()
    if not frame_b64:
        return False, 0.0, {"reason": "bad_frame"}
    if not frame_b64.startswith("data:image"):
        frame_b64 = "data:image/jpeg;base64," + frame_b64
    return guard.verify_base64(ath["verify_key"], ath["photo"], frame_b64, require_single_face=single)


@mobile_bp.route("/identity/verify", methods=["POST"])
@json_errors
@login_required
def identity_verify(ath):
    """Pre-test check (single face, returns a short-lived precheck token) or a live re-check."""
    data = _body()
    if not ath.get("photo"):
        return _err("No registration photo on your profile, so your identity cannot be checked.", 403)
    live = bool(data.get("live"))
    ok, score, info = _verify(ath, str(data.get("frame") or ""), single=not live)
    out = {"is_match": bool(ok), "score": round(float(score), 4), "reason": info.get("reason"),
           "message": reason_message(info)}
    if ok and not live:
        out["precheck_token"] = _signer("deepfit-precheck").dumps({"uid": ath["id"], "score": out["score"]})
    return _ok(**out)


def _precheck_score(token: Optional[str], ath: Dict) -> Optional[float]:
    if not token:
        return None
    try:
        d = _signer("deepfit-precheck").loads(token, max_age=PRECHECK_MINUTES * 60)
    except (BadSignature, SignatureExpired):
        return None
    return float(d.get("score")) if d.get("uid") == ath["id"] else None


def check_snapshots(ath: Dict, snaps: List[Dict], precheck: Optional[float], test_seconds: float,
                    camera_test: bool) -> Dict:
    """Replays the website's live identity rules over the phone's face snapshots."""
    out = {"ok": True, "checks": 0, "passes": 0, "strikes": 0, "pre_check": "not required",
           "pre_check_score": None, "message": ""}
    if not REQUIRE_FACE_CHECK:
        return out
    if not ath.get("photo"):
        return {**out, "ok": False, "message": "No registration photo on your profile, so your identity cannot be checked."}
    if not IdentityGuard.get().available:
        return {**out, "ok": False, "message": "Face check is not available on the server right now."}
    snaps = sorted([s for s in snaps if isinstance(s, dict) and s.get("jpg")],
                   key=lambda s: float(s.get("t") or 0))[:MAX_SNAPSHOTS]
    need = 1 + int(test_seconds // SNAP_EVERY_MAX) if camera_test else 1
    if len(snaps) < min(need, 3) or (camera_test and len(snaps) < need // 2):
        return {**out, "ok": False, "message": "Not enough face snapshots were taken during the test - please retake it."}
    strikes = checks = passes = 0
    best = 0.0
    first_decisive = None            # (is_match, score) of the first snapshot that showed a face
    last_face_t = float(snaps[0].get("t") or 0)
    for s in snaps:
        t = float(s.get("t") or 0)
        ok, score, info = _verify(ath, str(s["jpg"]), single=False)
        reason = info.get("reason")
        if reason in ("match", "mismatch"):
            checks += 1
            best = max(best, float(score))
            if first_decisive is None:
                first_decisive = (bool(ok), float(score))
        if ok:
            passes += 1
            strikes = 0
            last_face_t = t
        elif reason == "mismatch":
            strikes += 1
            last_face_t = t
        elif reason in ("no_face", "multiple_faces") and FACE_HIDDEN_SECONDS > 0 and t - last_face_t > FACE_HIDDEN_SECONDS:
            strikes += 1
            last_face_t = t
        if strikes >= MAX_STRIKES:
            return {**out, "ok": False, "checks": checks, "passes": passes, "strikes": strikes,
                    "message": "A different person (or no face) was detected during the test - result not saved."}
    if precheck is not None:
        pre, pre_score = "face matched registration photo", precheck
    elif first_decisive and first_decisive[0]:
        pre, pre_score = "face matched registration photo (checked at sync)", round(first_decisive[1], 4)
    else:
        return {**out, "ok": False, "checks": checks, "passes": passes, "strikes": strikes,
                "message": "The face at the start of the test did not match the registered athlete - result not saved."}
    return {**out, "checks": checks, "passes": passes, "strikes": strikes, "pre_check": pre,
            "pre_check_score": pre_score, "best_score": round(best, 4)}


# ------------------------------------------------------------------ results

class _LM:
    __slots__ = ("x", "y", "visibility")

    def __init__(self, x, y, v):
        self.x, self.y, self.visibility = x, y, v


def parse_frames(frames, duration: Optional[float]) -> Tuple[Optional[List], Optional[str]]:
    """[[t, [[x, y, vis] * 33] | null], ...]  ->  [(t, [(x, y, v)] | None)]"""
    if not isinstance(frames, list):
        return None, "frames missing"
    out, prev = [], -1.0
    limit = (duration if duration is not None else 3600) + 1.0
    for f in frames:
        if not isinstance(f, (list, tuple)) or len(f) != 2:
            return None, "bad frame"
        t = _num(f[0], 0, limit)
        if t is None or t <= prev:
            return None, "bad frame times"
        prev = t
        lm = f[1]
        if lm is not None:
            if not isinstance(lm, list) or len(lm) != 33:
                return None, "bad landmarks"
            pts = []
            for p in lm:
                if not isinstance(p, (list, tuple)) or len(p) != 3:
                    return None, "bad landmark"
                x, y, v = _num(p[0], -5, 5), _num(p[1], -5, 5), _num(p[2], -0.01, 1.01)
                if x is None or y is None or v is None:
                    return None, "bad landmark value"
                pts.append((x, y, v))
            lm = pts
        out.append((t, lm))
    if out and len(out) > MAX_FPS * (out[-1][0] + 1) + 30:
        return None, "too many frames"
    return out, None


def _valid_pattern(pattern) -> bool:
    if not isinstance(pattern, list) or len(pattern) != PATTERN_LEN or any(m not in MOVES for m in pattern):
        return False
    if any(a == b for a, b in zip(pattern, pattern[1:])):
        return False
    return sum(m in LOWER for m in pattern) >= 2 and sum(m in UPPER for m in pattern) >= 2


def rerun(key: str, frames: List, width: int, height: int, height_cm: float, ath: Dict,
          inputs: Optional[Dict] = None, pattern=None, code=None, manual_value=None, load_kg=None):
    """Feed the phone's skeleton track through the Python engine. Returns (exercise, replay, last_t)."""
    cls = EE.EXERCISES[key]
    ex = cls(height_cm=height_cm)
    if key == "dumbbell_curls":
        ex.configure(load_kg=load_kg, body_weight_kg=XB._weight_for(ath))
    if key == "growth_measures":
        ex.configure(height_cm=inputs["height_cm"], weight_kg=inputs["weight_kg"], chair_cm=inputs["chair_cm"],
                     age=ath.get("age"), sex=ath.get("gender"))
    if key == "coachability":
        ex.code, ex.pattern = str(code or "PHONE")[:8], list(pattern)
    replay = passport.ReplayRecorder()
    last_t = 0.0
    for t, lm in frames:
        if cls.duration is not None and t > cls.duration + 0.25:
            break
        pose = EE.Pose(lm, width, height) if lm is not None else None
        ex.update(pose, T0 + t)
        last_t = t
        if lm is not None:
            replay.add(t, ex.value(), types.SimpleNamespace(landmark=[_LM(*p) for p in lm]))
        if ex.finished:
            break
    if cls.camera == "none":
        ex.manual_value = manual_value
    return ex, replay, last_t


def _phone_dumbbell_check(ex, snaps: List, frames: List, width: int, height: int) -> Dict:
    """SAM 3.1 on one of the phone's camera snapshots: is a dumbbell really in the hand?"""
    import base64
    import curl_load
    try:
        snaps = sorted([s for s in snaps if isinstance(s, dict) and s.get("jpg") and (_num(s.get("t"), 0, 3600) is not None)],
                       key=lambda s: float(s["t"]))
        for snap in snaps[:3]:
            t = float(snap["t"])
            lm = min(((ft, f) for ft, f in frames if f is not None), key=lambda x: abs(x[0] - t), default=(None, None))[1]
            if lm is None:
                continue
            url = str(snap["jpg"])
            url = url if url.startswith("data:image") else "data:image/jpeg;base64," + url
            img = cv2.imdecode(np.frombuffer(base64.b64decode(url.split(",", 1)[1]), np.uint8), cv2.IMREAD_COLOR)
            if img is None:
                continue
            h, w = img.shape[:2]
            wrists = [(lm[i][0] * w, lm[i][1] * h) for i in (15, 16) if lm[i][2] >= 0.5]
            fore = max(math.hypot((lm[a][0] - lm[b][0]) * w, (lm[a][1] - lm[b][1]) * h) for a, b in ((13, 15), (14, 16)))
            if not wrists or fore <= 0:
                continue
            out = curl_load.dumbbell_check(url, w, h, wrists, fore, (EE.FOREARM_RATIO * ex.height_cm) / fore)
            out["snapshot_t"] = round(t, 1)
            return out
        return {"method": "none", "seen": None, "reason": "no usable camera snapshot"}
    except Exception as e:
        return {"method": "sam-3.1", "seen": None, "reason": f"check failed: {e}"}


@mobile_bp.route("/results", methods=["POST"])
@json_errors
@login_required
def upload_result(ath):
    d = _body()
    key = str(d.get("exercise") or "")
    cls = EE.EXERCISES.get(key)
    if cls is None:
        return _err("Unknown test.")
    client_id = str(d.get("client_id") or "")[:64]
    db = get_db()
    if db is None:
        return _err("Database unavailable.", 503)
    if client_id:                      # the phone retried after a lost connection: answer with the saved result
        prev = db.exercise_results.find_one({"athlete_ref": ath["ref"], "client_id": client_id})
        if prev:
            return _ok(status="saved", duplicate=True, result=_out(prev, ath))
    mode = d.get("mode") if d.get("mode") in XB.MODES else "standard"
    camera_test = cls.camera != "none"

    frames, width, height, manual, rc = [], 0, 0, None, None
    if camera_test:
        frames, problem = parse_frames(d.get("frames"), cls.duration)
        if problem:
            return _err(f"Upload rejected: {problem}.")
        size = d.get("frame_size") or {}
        width, height = int(_num(size.get("w"), 64, 4096) or 0), int(_num(size.get("h"), 64, 4096) or 0)
        if not width or not height:
            return _err("Upload rejected: frame size missing.")
    elif key == "run_600m" and isinstance(d.get("gps_run"), dict):
        # timed by the phone's GPS + step counter: the server recomputes the time from the raw track
        rc = run_check.check_run(d["gps_run"], 600.0, age=ath.get("age"),
                                 height_cm=_num(d.get("height_cm"), 100, 230) or _height_for(ath))
        if not rc.get("ok"):
            return _err(rc.get("problem") or "The run could not be measured.")
        manual = rc["value"]
    else:
        manual = _num(d.get("manual_value"), 1, 3600)
        if manual is None:
            return _err("Enter a time between 1 and 3600 seconds.")

    inputs = None
    if key == "growth_measures":
        inp = d.get("inputs") or {}
        inputs = {"height_cm": _num(inp.get("height_cm"), 100, 230), "weight_kg": _num(inp.get("weight_kg"), 15, 200),
                  "chair_cm": _num(inp.get("chair_cm"), 25, 80)}
        if not all(inputs.values()):
            return _err("Enter standing height (cm), weight (kg) and chair height (cm) first.")
    pattern = d.get("pattern")
    if key == "coachability" and not _valid_pattern(pattern):
        return _err("Upload rejected: invalid Coachability pattern.")
    h_cm = _num(d.get("height_cm"), 100, 230) or _height_for(ath)

    test_seconds = frames[-1][0] if frames else 0.0
    ident = check_snapshots(ath, d.get("snapshots") or [], _precheck_score(d.get("precheck_token"), ath),
                            test_seconds, camera_test)
    if not ident["ok"]:
        log_info(f"Mobile result rejected ({key}, {ath['ref']}): {ident['message']}")
        return _ok(status="rejected", message=ident["message"], identity=ident)

    load_kg = _num(d.get("load_kg"), 0.5, 60) if key == "dumbbell_curls" else None
    ex, replay, last_t = rerun(key, frames, width, height, h_cm, ath, inputs, pattern, d.get("pattern_code"), manual, load_kg)
    if load_kg:
        ex.load_check = _phone_dumbbell_check(ex, d.get("snapshots") or [], frames, width, height)
        det = d.get("load_detect") if isinstance(d.get("load_detect"), dict) else {}
        ex.load_detect = ({k: det.get(k) for k in ("source", "kg", "label_text", "model", "sure", "object")}
                          if _num(det.get("kg"), 0.25, 60) == load_kg else {"source": "typed"})
    res = ex.result()
    if rc is not None:
        _finish_face(ath, rc, d.get("snapshots") or [])
    client_value = _num((d.get("client_result") or {}).get("value"), -1e6, 1e6)
    same = client_value is None or abs(client_value - float(res["value"])) <= max(VALUE_TOLERANCE, 0.01 * abs(res["value"]))
    bench = (XB.load_benchmark(ex, res, ath, _population(mode))
             or benchmarks.evaluate(key, res["value"], ath.get("age"), ath.get("gender"), _population(mode)))
    now = datetime.utcnow()
    doc = {
        "athlete_ref": ath["ref"], "athlete_name": ath.get("name"), "athlete_age": ath.get("age"),
        "athlete_gender": ath.get("gender"), "exercise_type": key, "exercise_name": ex.name, **res,
        "duration": int(round(last_t)) if camera_test else None, "mode": mode, "benchmark": bench,
        "identity_checked": REQUIRE_FACE_CHECK, "identity_strikes": ident["strikes"], "stopped_for_identity": False,
        "coach_timed": not camera_test and rc is None,
        **({"timing": "gps", "run_verdict": rc["verdict"], "run_check": {k: v for k, v in rc.items() if k != "points"},
            "track_hash": _track_hash(d["gps_run"])} if rc is not None else {}),
        "timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "date": now,
        "user_email": ath.get("email"), "source": "mobile", "client_id": client_id or None,
        "device": {k: str(v)[:60] for k, v in (d.get("device") or {}).items()} if isinstance(d.get("device"), dict) else None,
        "captured_at": str(d.get("captured_at") or "")[:32] or None,
        "frame_size": {"w": width, "h": height} if camera_test else None,   # to draw the skeleton with the right shape
        "server_check": {"recomputed": camera_test, "client_value": client_value, "server_value": res["value"],
                         "same_as_phone": bool(same), "frames": len(frames),
                         "fps": round(len(frames) / last_t, 1) if last_t > 0 else None},
    }
    if ObjectId is not None:
        try:
            doc["user_id"] = ObjectId(ath["id"])
        except Exception:
            doc["user_id"] = ath["id"]
    replay_payload = replay.payload() if camera_test else None
    identity = {"pre_check": ident["pre_check"], "pre_check_score": ident["pre_check_score"],
                "live_checks": ident["checks"], "live_passes": ident["passes"], "mismatch_strikes": ident["strikes"],
                "captured_on": "DeepFit phone app" + (" - score recomputed by the server from the skeleton" if camera_test else "")}
    if ObjectId is not None:
        doc["_id"] = ObjectId()
        doc["passport"] = passport.build(doc, replay_payload, identity)
        doc["athlete_token"] = doc["passport"]["athlete_token"]
    db.exercise_results.insert_one(dict(doc))
    legacy = XB.legacy_record(doc)
    if legacy:
        db[legacy[0]].insert_one(legacy[1])          # cumulative dashboard + Best Results read these
    if rc is not None and "_id" in doc:          # the raw GPS track, kept so the result can be re-checked later
        g = d["gps_run"]
        db.run_tracks.insert_one({"_id": doc["_id"], "points": (g.get("points") or [])[:7200],
                                  "steps": (g.get("steps") or [])[:20000], "activity": (g.get("activity") or [])[:2000],
                                  "track_hash": doc["track_hash"]})
    if replay_payload and replay_payload["frames"] and "_id" in doc:
        db.pose_replays.insert_one({"_id": doc["_id"], **replay_payload})
    log_info(f"Mobile result saved: {key} = {res['value']} {res['unit']} (phone said {client_value}) mode={mode}")
    return _ok(status="saved", result=_out(doc, ath), same_as_phone=bool(same))


def _track_hash(g: Dict) -> str:
    import hashlib
    return hashlib.sha256(json.dumps({"points": g.get("points"), "steps": g.get("steps")}, sort_keys=True,
                                     separators=(",", ":"), default=str).encode()).hexdigest()


def _finish_face(ath: Dict, rc: Dict, snaps: List) -> None:
    """GPS runs: the face photo taken at the finish must be the same athlete (a phone can be carried by
    anyone - this ties the finish to the registered face)."""
    if not REQUIRE_FACE_CHECK:
        return
    fin = [s for s in snaps if isinstance(s, dict) and s.get("jpg") and (_num(s.get("t"), 0, 7200) or 0) >= rc.get("value", 0)]
    if not fin:
        rc["checks"].append({"check": "finish_face_match", "ok": False, "detail": "no face photo at the finish"})
        rc["flags"].append("no face photo at the finish"); rc["verdict"] = "needs_recheck"
        return
    ok, score, info = _verify(ath, str(fin[0]["jpg"]), single=False)
    detail = "the face at the finish matched the athlete" if ok else "the face at the finish did NOT match the athlete"
    rc["checks"].append({"check": "finish_face_match", "ok": bool(ok), "detail": detail})
    if not ok:
        rc["flags"].append(detail); rc["verdict"] = "needs_recheck"


def _out(doc: Dict, ath: Dict) -> Dict:
    out = {k: v for k, v in doc.items() if k not in HIDE_FROM_APP and k != "passport"}
    if doc.get("passport") and doc.get("_id") is not None:
        out["passport_url"] = f"{_base_url()}/passport/r/{doc['_id']}/{doc['passport']['token']}"
        out["athlete_passport_url"] = f"{_base_url()}/passport/a/{doc['passport']['athlete_token']}"
    latest = XB._latest_by_exercise(ath)
    out["next_test"] = _next_key(latest)
    return json.loads(json.dumps(out, default=str))


@mobile_bp.route("/height_weight", methods=["POST"])
@json_errors
@login_required
def height_weight(ath):
    import stature
    d = _body()
    h, w = _num(d.get("height_cm"), 100, 230), _num(d.get("weight_kg"), 15, 200)
    if h is None or w is None:
        return _err("Enter height 100-230 cm and weight 15-200 kg.")
    db = get_db()
    if db is None:
        return _err("Database unavailable.", 503)
    client_id = str(d.get("client_id") or "")[:64]
    if client_id and db["Height and Weight"].find_one({"user_email": ath.get("email"), "client_id": client_id}):
        return _ok(status="saved", duplicate=True)
    hs = d.get("height_source") if d.get("height_source") in ("camera", "tape") else "tape"
    ws = d.get("weight_source") if d.get("weight_source") in ("scale_photo", "typed") else "typed"
    m = d.get("measurement") if isinstance(d.get("measurement"), dict) else {}
    info = stature.bmi_info(round(h, 1), round(w, 1), ath.get("age"))
    now = datetime.utcnow()
    db["Height and Weight"].insert_one({"user_email": ath.get("email"), "height_cm": round(h, 1), "weight_kg": round(w, 1),
                                        "bmi": info["bmi"], "bmi_category": info.get("bmi_category"), "timestamp": now,
                                        "source": "mobile_camera" if hs == "camera" else "mobile_manual",
                                        "measured_by": ("camera + " + str(m.get("reference") or "reference")) if hs == "camera" else "tape",
                                        "weight_source": ws, "client_id": client_id or None})
    if hs == "camera":        # same record the website's camera test writes (dashboard reads it first)
        db["Final_Estimated_Height_and_Weight"].insert_one({
            "user_email": ath.get("email"), "final_height_cm": round(h, 1), "final_weight_kg": round(w, 1),
            "bmi": info["bmi"], "bmi_category": info.get("bmi_category"),
            "height_uncertainty": f"±{max(0.5, _num(m.get('spread_cm'), 0, 10) or 0.5):.1f} cm",
            "weight_uncertainty": "as the scale" if ws == "scale_photo" else "typed", "confidence_level": "99%",
            "total_instances": int(_num(m.get("photos_used"), 0, 50) or 0), "method": f"phone camera + {m.get('reference') or 'reference'}",
            "timestamp": now})
    return _ok(status="saved", bmi=info["bmi"], bmi_category=info.get("bmi_category"), bmi_note=info.get("bmi_note"),
               height_cm=round(h, 1), weight_kg=round(w, 1), next_test=_next_key(XB._latest_by_exercise(ath)))


@mobile_bp.route("/height_weight/measure", methods=["POST"])
@json_errors
@login_required
def height_measure(ath):
    """Height from 3-6 still photos taken by the phone: the athlete next to the marker / A4 sheet on the wall."""
    import stature
    import vision_reader
    photos = (_body().get("photos") or [])[:6]
    imgs = []
    for p in photos:
        raw = vision_reader.decode_b64_image(p)
        img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR) if raw else None
        if img is not None:
            imgs.append(img)
    if not imgs:
        return _err("No photos received.")
    try:
        out = stature.measure_photos(imgs)
    except Exception as e:
        log_error(f"height measure failed: {e}")
        return _err("Body tracking could not start on the server (the first run downloads a small model).", 503)
    if not out.get("ok"):
        return _err(out.get("message") or "Could not measure - try again.", 422, **{k: v for k, v in out.items() if k != "ok"})
    return _ok(**out)


@mobile_bp.route("/vision/scale", methods=["POST"])
@json_errors
@login_required
def vision_scale(ath):
    import vision_reader
    raw = vision_reader.decode_b64_image(_body().get("photo"))
    if raw is None:
        return _err("No photo received.")
    return jsonify(vision_reader.read_scale(raw))


@mobile_bp.route("/dumbbell/detect", methods=["POST"])
@json_errors
@login_required
def dumbbell_detect(ath):
    import vision_reader
    raw = vision_reader.decode_b64_image(_body().get("photo"))
    if raw is None:
        return _err("No photo received.")
    return jsonify(vision_reader.read_dumbbell(raw))


@mobile_bp.route("/history")
@json_errors
@login_required
def history(ath):
    limit = int(_num(request.args.get("limit"), 1, 200) or 30)
    db = get_db()
    rows = []
    if db is not None:
        docs = list(db.exercise_results.find({"athlete_ref": ath["ref"]}))
        docs.sort(key=lambda x: str(x.get("timestamp", "")), reverse=True)
        for x in docs[:limit]:
            r = {"exercise": x.get("exercise_type"), "name": x.get("exercise_name"), "value": x.get("value"),
                 "unit": x.get("unit"), "rating": (x.get("benchmark") or {}).get("rating"),
                 "when": str(x.get("timestamp", "")), "mode": x.get("mode"), "source": x.get("source", "website")}
            if x.get("passport") and x.get("_id") is not None:
                r["passport_url"] = f"{_base_url()}/passport/r/{x['_id']}/{x['passport']['token']}"
            rows.append(r)
    return _ok(results=rows)


@mobile_bp.route("/potential")
@json_errors
@login_required
def potential_report(ath):
    mode = request.args.get("mode") if request.args.get("mode") in XB.MODES else "standard"
    pop = _population(mode)
    hp = potential.hidden_potential(XB._latest_by_exercise(ath), ath.get("age"), ath.get("gender"), pop)
    entries, group = [], "all athletes on this DeepFit server"
    db = get_db()
    if db is not None:
        place = ath.get("place")
        group = f"athletes from {place}" if place else group
        for u in db.users.find({"place": place} if place else {}):
            uref = f"user:{u['_id']}"
            o = XB._athlete_hp(uref, u.get("email"), u.get("age"), u.get("gender"), pop)
            if o["fitness_today"] is not None or o["index"] is not None:
                entries.append({"ref": uref, "fitness": o["fitness_today"], "index": o["index"]})
    rank = potential.rank_positions(entries, ath["ref"]) if entries else None
    if rank:
        rank["group"] = group
    return _ok(hidden_potential=json.loads(json.dumps(hp, default=str)), rank=rank,
               passport_url=f"{_base_url()}/passport/a/{passport.athlete_token(ath['ref'])}")


# ------------------------------------------------------------------ AI coach

@mobile_bp.route("/chat", methods=["POST"])
@json_errors
@login_required
def chat(ath):
    import chatbot_routes as CR
    from deepfit_tools import AthleteContext
    msg = str(_body().get("message") or "").strip()[:4000]
    if not msg:
        return _err("Message is required.")
    try:
        bot = CR.get_chatbot("u:" + ath["id"])
    except RuntimeError as e:
        return _err(str(e), 503)
    if bot.__class__.__name__ == "MetaChatbot":
        text = bot.send_message(msg, ctx=AthleteContext(get_db(), user_id=ath["id"]))
    else:
        text = bot.send_message(msg)
    return _ok(response=text, provider=CR.provider_name())


@mobile_bp.route("/chat/reset", methods=["POST"])
@json_errors
@login_required
def chat_reset(ath):
    import chatbot_routes as CR
    CR.chatbot_instances.pop("u:" + ath["id"], None)
    return _ok()
