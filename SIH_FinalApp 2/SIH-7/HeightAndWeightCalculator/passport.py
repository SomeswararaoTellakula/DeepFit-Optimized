"""
Talent Passport - tamper-evident, shareable results.

For every saved camera test DeepFit keeps:
  * a SKELETON-ONLY replay (33 body points per frame, ~10 fps - no image, no face)
  * an identity summary (face match before the test + live re-checks during it)
and signs result + identity + replay hash with HMAC-SHA256 using a server secret.

A scout scans the QR code -> the verify page recomputes the signature from the
database. If any number was edited, or the replay was swapped, it shows TAMPERED.

Secret: PASSPORT_SECRET in .env (falls back to SECRET_KEY). Use the SAME value on every server that shows
passports (the laptop and Render) - a result signed with one key shows NOT VALID on a server with another.
Results signed earlier with this server's SECRET_KEY (before PASSPORT_SECRET was set) still verify, and
PASSPORT_OLD_SECRETS (comma-separated) can list keys that were used before. Each passport stores a short
fingerprint of the key that signed it (not the key), so a key mismatch is reported as such.
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


DEV_SECRET = "deepfit-dev-passport-secret"       # public: used only when no secret is set (tests, first runs)


def _secret() -> bytes:
    s = os.environ.get("PASSPORT_SECRET") or os.environ.get("SECRET_KEY") or DEV_SECRET
    return s.encode("utf-8")


def _accepted_secrets() -> List[bytes]:
    """The signing key first, then keys this server used before. The public dev key only if nothing else is set."""
    keys = [os.environ.get("PASSPORT_SECRET"), os.environ.get("SECRET_KEY")]
    keys += [k.strip() for k in (os.environ.get("PASSPORT_OLD_SECRETS") or "").split(",")]
    out: List[bytes] = []
    for k in keys:
        if k and k.encode("utf-8") not in out:
            out.append(k.encode("utf-8"))
    return out or [DEV_SECRET.encode("utf-8")]


def key_id(secret: Optional[bytes] = None) -> str:
    """Short fingerprint of a signing key (safe to show: the key can't be worked out from it)."""
    return hashlib.sha256(b"deepfit-kid:" + (secret or _secret())).hexdigest()[:8]


def _canon(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def sign(payload: Dict, secret: Optional[bytes] = None) -> str:
    return hmac.new(secret or _secret(), _canon(payload), hashlib.sha256).hexdigest()


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
    if doc.get("timing"):                         # runs timed by the phone's GPS: method, verdict and the track are signed
        payload.update(timing=doc["timing"], run_verdict=doc.get("run_verdict"), track_hash=doc.get("track_hash"))
    if doc.get("identity_scope"):                 # what the result proves about who ran (signed, shown in plain words)
        payload["identity_scope"] = doc["identity_scope"]
    sig = sign(payload)
    return {"v": VERSION, "payload": payload, "sig": sig, "token": sig[:16], "kid": key_id(),
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
    for field in ("timing", "run_verdict", "track_hash", "identity_scope"):
        if (field in payload or doc.get(field) is not None) and payload.get(field) != doc.get(field):
            problems.append(f"'{field}' (how the run was timed or who was checked) was changed after signing.")
    if payload.get("replay_hash") != replay_hash(replay):
        problems.append("The movement replay does not match the signed result.")
    sig = pp.get("sig", "")
    if not any(hmac.compare_digest(sign(payload, k), sig) for k in _accepted_secrets()):
        here = key_id()
        if hmac.compare_digest(sign(payload, DEV_SECRET.encode("utf-8")), sig):
            problems.append("Signed with DeepFit's built-in test key (no PASSPORT_SECRET was set when it was saved), "
                            "so it can't prove it wasn't edited. Measure again after setting PASSPORT_SECRET.")
        elif pp.get("kid") and pp["kid"] != here:
            problems.append(f"Signed by a DeepFit server with a different key (key {pp['kid']}; this server's key is {here}). "
                            "Set the same PASSPORT_SECRET on the laptop and on Render, then restart both.")
        else:
            problems.append("Signature check failed - the passport data was edited, or it was signed with another "
                            f"server's PASSPORT_SECRET (this server's key is {here}).")
    return (not problems), problems


def identity_scope_text(scope) -> str:
    """Plain words for the passport: what this timed result proves about who did it."""
    s = str(scope or "")
    if s == "time_entered":
        return "Time entered by hand with the stopwatch - the phone did not watch the run."
    if s.startswith("start_mid") and s.endswith("_finish"):
        n = s[len("start_mid"):-len("_finish")]
        return f"Face matched at the start, at {n} random points during the run, and at the finish."
    if s == "start_finish":
        return "Face checked at the start and the finish only - not during the run (self-recorded)."
    return ""
