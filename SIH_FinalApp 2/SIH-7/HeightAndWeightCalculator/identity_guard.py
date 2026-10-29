"""
Identity guard for DeepFit.

Makes sure the person doing an exercise is the same person who registered.

How it works
------------
* Face detection:   OpenCV YuNet   (models/face/face_detection_yunet_2023mar.onnx, ~0.2 MB)
* Face recognition: OpenCV SFace   (models/face/face_recognition_sface_2021dec.onnx, ~37 MB)

Both run on the CPU through OpenCV's DNN module, take roughly 10-30 ms per
frame and need no TensorFlow / DeepFace, so they do not slow the laptop down.

The registration photo is turned into a 128-number "face fingerprint"
(embedding) once and cached. Every check compares the live face with that
fingerprint using cosine similarity. SFace's published threshold is 0.363;
we use 0.40 by default (slightly stricter). Override with the
DEEPFIT_FACE_THRESHOLD environment variable.

If the model files are missing the guard falls back to the old FaceVerifier
so the app still starts, and logs a clear warning.
"""

import base64
import hashlib
import logging
import os
import threading
import time
from typing import Dict, Optional, Tuple

import cv2
import numpy as np

logger = logging.getLogger("IdentityGuard")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_DIR = os.path.join(BASE_DIR, "models", "face")
DETECTOR_PATH = os.path.join(MODEL_DIR, "face_detection_yunet_2023mar.onnx")
RECOGNIZER_PATH = os.path.join(MODEL_DIR, "face_recognition_sface_2021dec.onnx")

MATCH_THRESHOLD = float(os.environ.get("DEEPFIT_FACE_THRESHOLD", "0.40"))
# How long a successful pre-exercise verification stays valid (seconds)
VERIFY_TTL_SECONDS = int(os.environ.get("DEEPFIT_VERIFY_TTL", "300"))
# Smallest face (in pixels) we accept in the registration photo
MIN_REGISTRATION_FACE = 60
# During an exercise: if no face is seen for this many seconds it counts as one
# strike (someone could hide their face to avoid the check). 0 disables.
FACE_HIDDEN_SECONDS = float(os.environ.get("DEEPFIT_FACE_HIDDEN_SECONDS", "15"))
# Large images are shrunk before detection; faces stay plenty big and it is much faster
MAX_DETECT_SIDE = 640
# During an exercise a "mismatch" only counts as a strike when the face is clear enough to judge
# (big enough, facing the camera, not tilted) AND the similarity is clearly low. A side-on or lying
# face (sit-ups, jumps) gives a low score even for the right person - that is "unclear", not a mismatch.
STRIKE_THRESHOLD = float(os.environ.get("DEEPFIT_FACE_STRIKE", "0.30"))
MIN_LIVE_FACE = int(os.environ.get("DEEPFIT_MIN_LIVE_FACE", "56"))


def face_quality(row) -> Tuple[bool, str]:
    """Is this YuNet face good enough to say 'this is NOT the athlete'?  row = x,y,w,h, r-eye, l-eye, nose, ..."""
    import math
    w, h = float(row[2]), float(row[3])
    if min(w, h) < MIN_LIVE_FACE:
        return False, "small"
    rx, ry, lx, ly, nx, ny = (float(v) for v in row[4:10])
    eye = math.hypot(lx - rx, ly - ry)
    if eye < 0.25 * w:
        return False, "side_on"                     # profile view: the eyes almost overlap
    roll = abs(math.degrees(math.atan2(ly - ry, lx - rx)))
    roll = min(roll, 180 - roll)
    if roll > 30:
        return False, "tilted"                      # lying down or head on one side
    # yaw: nose position between the eyes (0 = centred)
    ex, ey = (lx - rx) / eye, (ly - ry) / eye
    t = ((nx - (rx + lx) / 2) * ex + (ny - (ry + ly) / 2) * ey) / eye
    if abs(t) > 0.35:
        return False, "turned"
    if len(row) > 14 and float(row[14]) < 0.8:
        return False, "blurry"
    return True, "ok"


def decode_base64_image(data: str) -> Optional[np.ndarray]:
    """Turn a 'data:image/jpeg;base64,...' string (or raw base64) into a BGR image."""
    if not data:
        return None
    try:
        if "," in data:
            data = data.split(",", 1)[1]
        raw = base64.b64decode(data)
    except Exception:
        return None
    # Pillow applies the phone-camera EXIF rotation; fall back to plain OpenCV
    try:
        import io
        from PIL import Image, ImageOps
        pil = ImageOps.exif_transpose(Image.open(io.BytesIO(raw))).convert("RGB")
        return cv2.cvtColor(np.asarray(pil), cv2.COLOR_RGB2BGR)
    except Exception:
        pass
    try:
        return cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
    except Exception:
        return None


class IdentityGuard:
    """Thread-safe singleton wrapper around YuNet + SFace."""

    _instance = None
    _instance_lock = threading.Lock()

    @classmethod
    def get(cls) -> "IdentityGuard":
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def __init__(self):
        self._lock = threading.Lock()  # OpenCV DNN nets are not thread-safe
        self._ref_cache: Dict[str, np.ndarray] = {}
        self.detector = None
        self.recognizer = None
        self.backend = "none"
        self._legacy = None

        has_api = hasattr(cv2, "FaceDetectorYN") and hasattr(cv2, "FaceRecognizerSF")
        has_files = os.path.exists(DETECTOR_PATH) and os.path.exists(RECOGNIZER_PATH)
        if has_api and has_files:
            try:
                self.detector = cv2.FaceDetectorYN.create(DETECTOR_PATH, "", (320, 320), 0.8, 0.3, 5000)
                self.recognizer = cv2.FaceRecognizerSF.create(RECOGNIZER_PATH, "")
                self.backend = "sface"
                logger.info("IdentityGuard ready (YuNet + SFace, threshold=%.2f)", MATCH_THRESHOLD)
            except Exception as e:
                logger.error("Could not load face models: %s", e)

        if self.backend == "none":
            logger.warning(
                "IdentityGuard: face models not found in %s - run 'python download_face_models.py'. "
                "Falling back to the old (much weaker) FaceVerifier.", MODEL_DIR)
            try:
                from face_verifier import FaceVerifier
                self._legacy = FaceVerifier(threshold=0.70)
                self.backend = "legacy"
            except Exception as e:
                logger.error("Legacy FaceVerifier unavailable too: %s", e)

    # ------------------------------------------------------------------ helpers
    @property
    def available(self) -> bool:
        return self.backend in ("sface", "legacy")

    def _detect(self, img: np.ndarray) -> np.ndarray:
        """Return YuNet face rows (in original image coordinates), largest first."""
        h, w = img.shape[:2]
        scale = min(1.0, MAX_DETECT_SIDE / float(max(h, w)))
        small = cv2.resize(img, (int(w * scale), int(h * scale))) if scale < 1.0 else img
        sh, sw = small.shape[:2]
        self.detector.setInputSize((sw, sh))
        _, faces = self.detector.detect(small)
        if faces is None or len(faces) == 0:
            return np.zeros((0, 15), dtype=np.float32)
        faces = faces.copy()
        faces[:, :14] /= scale
        areas = faces[:, 2] * faces[:, 3]
        return faces[np.argsort(-areas)]

    def _embed(self, img: np.ndarray, face_row: np.ndarray) -> np.ndarray:
        aligned = self.recognizer.alignCrop(img, face_row)
        return self.recognizer.feature(aligned).copy()

    def _score(self, a: np.ndarray, b: np.ndarray) -> float:
        return float(self.recognizer.match(a, b, cv2.FaceRecognizerSF_FR_COSINE))

    # ------------------------------------------------------------- registration
    def check_registration_photo(self, photo_b64: str) -> Tuple[bool, str]:
        """Is this photo good enough to verify against later? (exactly one clear face)"""
        if self.backend != "sface":
            return True, "Face models not installed - photo not checked"
        img = decode_base64_image(photo_b64)
        if img is None:
            return False, "Could not read the photo. Please capture it again."
        with self._lock:
            faces = self._detect(img)
        if len(faces) == 0:
            return False, "No face found in the photo. Face the camera in good light and retake it."
        if len(faces) > 1:
            return False, "More than one face in the photo. Only you should be in the picture."
        if min(faces[0][2], faces[0][3]) < MIN_REGISTRATION_FACE:
            return False, "Your face is too small in the photo. Move closer to the camera and retake it."
        return True, "Photo OK"

    def reference_embedding(self, ref_key: str, photo_b64: str) -> Optional[np.ndarray]:
        """Embedding of the registration photo, computed once and cached."""
        digest = hashlib.sha1(photo_b64.encode("utf-8", "ignore")).hexdigest()[:16]
        key = f"{ref_key}:{digest}"
        if key in self._ref_cache:
            return self._ref_cache[key]
        img = decode_base64_image(photo_b64)
        if img is None:
            return None
        with self._lock:
            faces = self._detect(img)
            if len(faces) == 0:
                return None
            emb = self._embed(img, faces[0])
        if len(self._ref_cache) > 200:
            self._ref_cache.clear()
        self._ref_cache[key] = emb
        return emb

    # ---------------------------------------------------------------- matching
    def verify_frame(self, ref_key: str, photo_b64: str, frame: np.ndarray,
                     require_single_face: bool = True) -> Tuple[bool, float, Dict]:
        """
        Compare a live frame with the registered photo.

        Returns (is_match, score, info). info['reason'] is one of:
        match, mismatch, no_face, multiple_faces, no_reference_face, bad_frame, unavailable
        """
        info: Dict = {"method": self.backend, "threshold": MATCH_THRESHOLD, "face_detected": False}
        if frame is None or frame.size == 0:
            info["reason"] = "bad_frame"
            return False, 0.0, info

        if self.backend == "legacy":
            ok, conf, dbg = self._legacy.verify(photo_b64, frame)
            dbg = dict(dbg)
            dbg["reason"] = "match" if ok else ("mismatch" if dbg.get("face_detected") else "no_face")
            return bool(ok), float(conf), dbg
        if self.backend != "sface":
            info["reason"] = "unavailable"
            return False, 0.0, info

        ref = self.reference_embedding(ref_key, photo_b64)
        if ref is None:
            info["reason"] = "no_reference_face"
            return False, 0.0, info

        t0 = time.time()
        with self._lock:
            faces = self._detect(frame)
            info["faces"] = int(len(faces))
            if len(faces) == 0:
                info["reason"] = "no_face"
                return False, 0.0, info
            info["face_detected"] = True
            # Judge the LARGEST face = the person closest to the camera, i.e. the one
            # doing the exercise. The registered athlete standing in the background
            # while someone else exercises must NOT count as a match.
            best = self._score(ref, self._embed(frame, faces[0]))
            usable, why = face_quality(faces[0])
        info["similarity"] = round(best, 4)
        info["usable"], info["quality"] = usable, why
        info["ms"] = int((time.time() - t0) * 1000)

        if len(faces) > 1 and require_single_face:
            info["reason"] = "multiple_faces"
            return False, best, info
        is_match = best >= MATCH_THRESHOLD
        info["reason"] = "match" if is_match else "mismatch"
        return is_match, best, info

    def verify_base64(self, ref_key: str, photo_b64: str, frame_b64: str,
                      require_single_face: bool = True) -> Tuple[bool, float, Dict]:
        frame = decode_base64_image(frame_b64)
        if frame is None:
            return False, 0.0, {"reason": "bad_frame", "method": self.backend}
        return self.verify_frame(ref_key, photo_b64, frame, require_single_face)


REASON_MESSAGES = {
    "match": "Identity verified",
    "mismatch": "Face does not match the registered athlete",
    "no_face": "No face detected - look at the camera",
    "multiple_faces": "More than one person in view - only the athlete should be in frame",
    "no_reference_face": "No face found in your registration photo - please update your profile photo",
    "bad_frame": "Could not read the camera image",
    "unavailable": "Face verification is not available on the server",
}


def reason_message(info: Dict) -> str:
    return REASON_MESSAGES.get(info.get("reason", ""), "Identity check failed")


# --------------------------------------------------------------------------
# Server-side session gate: exercises can only start after a recent match
# --------------------------------------------------------------------------
def mark_verified(session, user_key: str, score: float) -> None:
    session["identity_verified"] = {"user": str(user_key), "at": time.time(), "score": round(float(score), 4)}


def clear_verified(session) -> None:
    session.pop("identity_verified", None)


def is_recently_verified(session, user_key: Optional[str]) -> bool:
    data = session.get("identity_verified")
    if not data or not user_key:
        return False
    return data.get("user") == str(user_key) and (time.time() - float(data.get("at", 0))) < VERIFY_TTL_SECONDS


REQUIRE_FACE_CHECK = os.environ.get("DEEPFIT_REQUIRE_FACE", "1") != "0"


def exercise_gate(session, db) -> Tuple[Optional[str], Optional[str], Optional[Dict], int]:
    """
    Call at the start of every exercise.

    Returns (user_id, registration_photo, error_json, http_code).
    error_json is None when the exercise may start.
    """
    user_id = session.get("user_id")
    if not REQUIRE_FACE_CHECK:
        photo = None
        if user_id and db is not None:
            try:
                from bson import ObjectId
                user = db.users.find_one({"_id": ObjectId(user_id)}, {"photo": 1})
                photo = user.get("photo") if user else None
            except Exception:
                pass
        return user_id, photo, None, 200

    if not user_id:
        return None, None, {"status": "error", "identity_required": True,
                            "message": "Please log in before starting an exercise."}, 401
    if db is None:
        return None, None, {"status": "error", "message": "Database unavailable"}, 500
    from bson import ObjectId
    user = db.users.find_one({"_id": ObjectId(user_id)}, {"photo": 1})
    photo = user.get("photo") if user else None
    if not photo:
        return None, None, {"status": "error", "identity_required": True,
                            "message": "No registration photo on your profile, so your identity cannot be checked."}, 403
    if not is_recently_verified(session, user_id):
        return None, None, {"status": "error", "identity_required": True,
                            "message": "Please verify your identity (face check) before starting."}, 403
    return user_id, photo, None, 200


class LiveIdentityMonitor:
    """
    Re-checks identity during an exercise without slowing the video stream.

    The stream calls submit(frame) every frame; at most one check runs at a time
    in a background thread, every `interval` seconds. After `max_strikes`
    consecutive mismatches `terminated` becomes True and the exercise must stop.
    """

    def __init__(self, interval: float = 2.0, max_strikes: int = 3):
        self.interval = interval
        self.max_strikes = max_strikes
        self.reset(None, None)

    def reset(self, ref_key: Optional[str], photo_b64: Optional[str], side_view: bool = False) -> None:
        self.ref_key = ref_key
        self.side_view = side_view   # side-on / lying tests: face is often in profile or hidden
        self.photo_b64 = photo_b64
        self.strikes = 0
        self.terminated = False
        self.checks = 0          # live re-checks run during the test (for the Talent Passport)
        self.passes = 0          # ... and how many matched
        self.best_score = 0.0
        self.last_status = "pending" if photo_b64 else "no_reference"
        self.last_score = 0.0
        self._last_run = 0.0
        self._busy = False
        self._last_face_seen = time.time()

    @property
    def enabled(self) -> bool:
        return bool(self.photo_b64) and IdentityGuard.get().available

    def submit(self, frame: np.ndarray) -> None:
        if not self.enabled or self.terminated or self._busy:
            return
        now = time.time()
        if now - self._last_run < self.interval:
            return
        self._last_run = now
        self._busy = True
        threading.Thread(target=self._run, args=(frame.copy(),), daemon=True).start()

    def _check(self, frame: np.ndarray):
        g = IdentityGuard.get()
        ok, score, info = g.verify_frame(self.ref_key, self.photo_b64, frame, require_single_face=False)
        if ok or not self.side_view:
            return ok, score, info
        # side-on tests: the athlete may be lying down (sit-ups) - look for an upright face in the turned image too
        for rot in (cv2.ROTATE_90_CLOCKWISE, cv2.ROTATE_90_COUNTERCLOCKWISE):
            ok2, s2, i2 = g.verify_frame(self.ref_key, self.photo_b64, cv2.rotate(frame, rot), require_single_face=False)
            if ok2 or (i2.get("usable") and not info.get("usable")):
                ok, score, info = ok2, s2, i2
            if ok:
                break
        return ok, score, info

    def _run(self, frame: np.ndarray) -> None:
        try:
            ok, score, info = self._check(frame)
            self.last_score = score
            reason = info.get("reason")
            if reason == "mismatch" and (not info.get("usable", True) or score >= STRIKE_THRESHOLD):
                # face too side-on / small / tilted to judge, or a borderline score: not proof of another person
                reason = "unclear_face"
            if reason in ("match", "mismatch"):         # only checks that could judge the face
                self.checks += 1
                self.best_score = max(self.best_score, float(score))
            if ok:
                self.passes += 1
            now = time.time()
            if ok:
                self.strikes = 0
                self.last_status = "verified"
                self._last_face_seen = now
            elif reason == "mismatch":
                self.strikes += 1
                self.last_status = "mismatch"
                self._last_face_seen = now
                logger.warning("Identity mismatch %d/%d (score %.3f)", self.strikes, self.max_strikes, score)
            elif reason == "unclear_face":
                self.last_status = "unclear_face"
            elif (reason == "no_face" and not self.side_view and FACE_HIDDEN_SECONDS > 0
                  and now - self._last_face_seen > FACE_HIDDEN_SECONDS):
                # A short head turn during a rep is fine; a face hidden for a long time is not
                self.strikes += 1
                self.last_status = "face_hidden"
                self._last_face_seen = now
                logger.warning("Face hidden for over %.0fs - strike %d/%d", FACE_HIDDEN_SECONDS, self.strikes, self.max_strikes)
            else:
                self.last_status = reason or "unknown"
            if self.strikes >= self.max_strikes:
                self.terminated = True
        except Exception as e:
            logger.error("Live identity check failed: %s", e)
        finally:
            self._busy = False

    def draw(self, frame: np.ndarray) -> None:
        """Small status badge in the corner of the video."""
        if not self.photo_b64:
            return
        colours = {"verified": (0, 200, 0), "mismatch": (0, 0, 255), "face_hidden": (0, 0, 255)}
        colour = colours.get(self.last_status, (0, 200, 255))
        label = {
            "verified": "ID verified",
            "mismatch": f"ID MISMATCH ({self.strikes}/{self.max_strikes})",
            "no_face": "Face not visible",
            "unclear_face": "ID: face side-on",
            "face_hidden": f"FACE HIDDEN ({self.strikes}/{self.max_strikes})",
            "pending": "Checking ID...",
        }.get(self.last_status, "Checking ID...")
        h, w = frame.shape[:2]
        cv2.rectangle(frame, (w - 250, 8), (w - 8, 40), (0, 0, 0), -1)
        cv2.putText(frame, label, (w - 242, 31), cv2.FONT_HERSHEY_SIMPLEX, 0.6, colour, 2)

    def status(self) -> Dict:
        return {
            "identity_status": self.last_status,
            "identity_strikes": self.strikes,
            "identity_error": self.terminated,
            "identity_checks": self.checks,
            "identity_passes": self.passes,
        }
