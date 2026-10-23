"""
Talent Passport - tamper-evident, shareable results.

For every saved camera test DeepFit keeps:
  * a SKELETON-ONLY replay (33 body points per frame, ~10 fps - no image, no face)
  * an identity summary (face match before the test + live re-checks during it)
and signs result + identity + replay hash with HMAC-SHA256 using a server secret.

A scout scans the QR code -> the verify page recomputes the signature from the
database. If any number was edited, or the replay was swapped, it shows TAMPERED.

Secret: PASSPORT_SECRET in .env (falls back to SECRET_KEY). Changing it invalidates
old passports, so set it once and keep it.
"""

import hashlib
import hmac
import json
import os
from typing import Dict, List, Optional, Tuple

VERSION = 1
REPLAY_FPS = 10
MAX_REPLAY_FRAMES = 3600            # 6 minutes at 10 fps

SIGNED_FIELDS = ["result_id", "athlete_ref", "athlete_display", "age", "gender", "exercise_type",
                 "exercise_name", "value", "unit", "timestamp", "mode", "coach_timed", "identity", "replay_hash"]


def _secret() -> bytes:
    s = os.environ.get("PASSPORT_SECRET") or os.environ.get("SECRET_KEY") or "deepfit-dev-passport-secret"
    return s.encode("utf-8")


def _canon(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def sign(payload: Dict) -> str:
    return hmac.new(_secret(), _canon(payload), hashlib.sha256).hexdigest()


def athlete_token(ref: str) -> str:
    """Unguessable, stable id for an athlete's public passport page."""
    return hmac.new(_secret(), b"athlete:" + ref.encode("utf-8"), hashlib.sha256).hexdigest()[:20]


def display_name(name: Optional[str]) -> str:
    """First name + last initial (privacy for minors)."""
    parts = (name or "Athlete").split()
    return parts[0] if len(parts) == 1 else f"{parts[0]} {parts[-1][0]}."


class ReplayRecorder:
    """Collects pose-only frames at ~10 fps during a test."""

    def __init__(self):
        self.frames: List[Dict] = []
        self._last = -1.0

    def add(self, t_rel: float, value: float, pose_landmarks) -> None:
        if pose_landmarks is None or len(self.frames) >= MAX_REPLAY_FRAMES:
            return
        if t_rel - self._last < 1.0 / REPLAY_FPS:
            return
        self._last = t_rel
        lm = [[round(p.x, 3), round(p.y, 3), round(getattr(p, "visibility", 1.0), 2)]
              for p in pose_landmarks.landmark]
        self.frames.append({"t": round(t_rel, 2), "v": round(float(value), 1), "lm": lm})

    def payload(self) -> Dict:
        return {"fps": REPLAY_FPS, "frames": self.frames}


def replay_hash(replay: Optional[Dict]) -> Optional[str]:
    if not replay or not replay.get("frames"):
        return None
    return hashlib.sha256(_canon({"fps": replay.get("fps"), "frames": replay["frames"]})).hexdigest()


def build(doc: Dict, replay: Optional[Dict], identity: Dict) -> Dict:
    """Return the 'passport' sub-document to store with a result (doc must already have _id)."""
    payload = {
        "result_id": str(doc["_id"]),
        "athlete_ref": doc["athlete_ref"],
        "athlete_display": display_name(doc.get("athlete_name")),
        "age": doc.get("athlete_age"),
        "gender": doc.get("athlete_gender"),
        "exercise_type": doc["exercise_type"],
        "exercise_name": doc.get("exercise_name"),
        "value": doc.get("value"),
        "unit": doc.get("unit"),
        "timestamp": doc.get("timestamp"),
        "mode": doc.get("mode"),
        "coach_timed": bool(doc.get("coach_timed")),
        "identity": identity,
        "replay_hash": replay_hash(replay),
    }
    if doc.get("load_kg") is not None:            # weighted tests: the declared dumbbell weight is signed too
        payload["load_kg"] = doc["load_kg"]
    sig = sign(payload)
    return {"v": VERSION, "payload": payload, "sig": sig, "token": sig[:16],
            "athlete_token": athlete_token(doc["athlete_ref"])}


def verify(doc: Dict, replay: Optional[Dict]) -> Tuple[bool, List[str]]:
    """Recompute everything from the stored result + replay. Returns (valid, problems)."""
    problems: List[str] = []
    pp = (doc or {}).get("passport")
    if not pp:
        return False, ["This result has no passport signature."]
    payload = dict(pp["payload"])
    # the stored result itself must still match what was signed
    for field, current in [("value", doc.get("value")), ("unit", doc.get("unit")),
                           ("exercise_type", doc.get("exercise_type")), ("timestamp", doc.get("timestamp")),
                           ("athlete_ref", doc.get("athlete_ref")), ("result_id", str(doc.get("_id")))]:
        if payload.get(field) != current:
            problems.append(f"'{field}' was changed after signing.")
    if "load_kg" in payload or doc.get("load_kg") is not None:
        if payload.get("load_kg") != doc.get("load_kg"):
            problems.append("'load_kg' (the dumbbell weight) was changed after signing.")
    if payload.get("replay_hash") != replay_hash(replay):
        problems.append("The movement replay does not match the signed result.")
    if not hmac.compare_digest(sign(payload), pp.get("sig", "")):
        problems.append("Signature check failed - the passport data was edited.")
    return (not problems), problems
