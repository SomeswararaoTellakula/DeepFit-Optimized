"""
Meta Model API helpers used by DeepFit Arena (https://dev.meta.ai/docs).

    chat_json(...)       Muse Spark with a JSON schema  (POST /v1/chat/completions, response_format=json_schema)
    sam_boxes(...)       SAM 3.1 boxes for a text prompt (POST /v1/responses, model sam-3.1)
    transcribe(...)      Muse Voice Transcribe            (POST /v1/asr/transcribe, multipart, 16-bit mono WAV)
    generate_image(...)  Muse Image                       (POST /v1/images/generations)

Every helper returns None (and logs why) instead of raising, so the game keeps working
offline or without an API key - each caller has a non-AI fallback.

Settings (.env): MODEL_API_KEY (or META_API_KEY), META_API_BASE, META_MODEL.
"""

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

import requests

log = logging.getLogger("meta_models")

API_BASE = os.environ.get("META_API_BASE", "https://api.meta.ai/v1")
CHAT_MODEL = os.environ.get("META_MODEL", "muse-spark-1.3")
SAM_MODEL = os.environ.get("META_SAM_MODEL", "sam-3.1")
ASR_MODEL = os.environ.get("META_ASR_MODEL", "muse-voice-transcribe-1.0")
IMAGE_MODEL = os.environ.get("META_IMAGE_MODEL", "muse-image-1.0")

# the last error per helper, shown on the Arena "AI status" panel
last_error: Dict[str, Optional[str]] = {"chat": None, "sam": None, "asr": None, "image": None}


def api_key() -> Optional[str]:
    return os.environ.get("MODEL_API_KEY") or os.environ.get("META_API_KEY")


def available() -> bool:
    return bool(api_key())


def _headers(json_body: bool = True) -> Dict[str, str]:
    h = {"Authorization": f"Bearer {api_key()}"}
    if json_body:
        h["Content-Type"] = "application/json"
    return h


def _fail(kind: str, msg: str) -> None:
    last_error[kind] = msg[:300]
    log.warning("Meta %s call failed: %s", kind, msg[:300])


# ------------------------------------------------------------------ Muse Spark (structured JSON)

def chat_json(system: str, user: str, schema: Dict[str, Any], name: str = "result",
              timeout: float = 45.0) -> Optional[Dict[str, Any]]:
    """Ask Muse Spark for JSON that matches `schema`."""
    if not available():
        _fail("chat", "MODEL_API_KEY is not set")
        return None
    body = {
        "model": CHAT_MODEL,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "response_format": {"type": "json_schema", "json_schema": {"name": name, "schema": schema}},
    }
    try:
        r = requests.post(f"{API_BASE}/chat/completions", headers=_headers(), json=body, timeout=timeout)
        if r.status_code >= 400:
            _fail("chat", f"HTTP {r.status_code}: {r.text[:200]}")
            return None
        content = r.json()["choices"][0]["message"]["content"]
        if isinstance(content, list):          # some servers return content parts
            content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
        m = re.search(r"\{.*\}", content, re.S)  # tolerate text around the JSON
        out = json.loads(m.group(0) if m else content)
        last_error["chat"] = None
        return out if isinstance(out, dict) else None
    except Exception as e:  # network, JSON, unexpected shape
        _fail("chat", repr(e))
        return None


# ------------------------------------------------------------------ SAM 3.1 (boxes for a text prompt)

BOX_RE = re.compile(r"<\|box;([^|]*)\|>")


def _strings(obj) -> List[str]:
    """All strings inside a JSON response (the SAM output text sits somewhere in `output`)."""
    out: List[str] = []
    if isinstance(obj, str):
        out.append(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            out.extend(_strings(v))
    elif isinstance(obj, list):
        for v in obj:
            out.extend(_strings(v))
    return out


def parse_boxes(text: str) -> List[Dict[str, float]]:
    """'<|box;x1=211;y1=228;x2=270;y2=254;w=320;h=334;c=0.91|>' -> [{x1, y1, x2, y2, w, h, c}] (source pixels)."""
    boxes = []
    for body in BOX_RE.findall(text or ""):
        fields = {}
        for part in body.split(";"):
            if "=" in part:
                k, v = part.split("=", 1)
                try:
                    fields[k.strip()] = float(v)
                except ValueError:
                    pass
        if all(k in fields for k in ("x1", "y1", "x2", "y2")):
            boxes.append(fields)
    return boxes


def sam_boxes(image_data_url: str, prompt: str, timeout: float = 40.0) -> Optional[List[Dict[str, float]]]:
    """Boxes (source pixels, best first) of every `prompt` match in the image, or None."""
    if not available():
        _fail("sam", "MODEL_API_KEY is not set")
        return None
    body = {
        "model": SAM_MODEL,
        "input": [{"type": "message", "role": "user", "content": [
            {"type": "input_text", "text": prompt},
            {"type": "input_image", "image_url": image_data_url},
        ]}],
        "metadata": {"include_confidence": "true"},
    }
    try:
        r = requests.post(f"{API_BASE}/responses", headers=_headers(), json=body, timeout=timeout)
        if r.status_code >= 400:
            _fail("sam", f"HTTP {r.status_code}: {r.text[:200]}")
            return None
        boxes: List[Dict[str, float]] = []
        for s in _strings(r.json()):
            boxes.extend(parse_boxes(s))
        boxes.sort(key=lambda b: (-(b.get("c", 0.5)), -((b["x2"] - b["x1"]) * (b["y2"] - b["y1"]))))
        last_error["sam"] = None
        return boxes
    except Exception as e:
        _fail("sam", repr(e))
        return None


# ------------------------------------------------------------------ Muse Voice Transcribe

LANG_NAMES = {"en": "English", "hi": "Hindi", "te": "Telugu", "ta": "Tamil", "kn": "Kannada", "mr": "Marathi", "bn": "Bengali"}


def transcribe(wav_bytes: bytes, langs: Optional[List[str]] = None, timeout: float = 30.0) -> Optional[str]:
    """Transcript of a short WAV clip (mono 16-bit PCM, 16 or 24 kHz), or None."""
    if not available():
        _fail("asr", "MODEL_API_KEY is not set")
        return None
    req: Dict[str, Any] = {"mode": "PUSH_TO_TALK", "model": ASR_MODEL, "audioEncoding": "WAV"}
    names = [LANG_NAMES[c] for c in (langs or []) if c in LANG_NAMES]
    if names:
        req["languageBias"] = names
    files = {
        "request": (None, json.dumps(req), "application/json"),
        "audio": ("voice.wav", wav_bytes, "audio/wav"),
    }
    try:
        r = requests.post(f"{API_BASE}/asr/transcribe", headers=_headers(json_body=False), files=files, timeout=timeout)
        if r.status_code >= 400:
            _fail("asr", f"HTTP {r.status_code}: {r.text[:200]}")
            return None
        text = (r.json() or {}).get("transcript")
        last_error["asr"] = None
        return text.strip() if isinstance(text, str) else None
    except Exception as e:
        _fail("asr", repr(e))
        return None


# ------------------------------------------------------------------ Muse Image

def generate_image(prompt: str, size: str = "1024x1024", timeout: float = 90.0) -> Optional[str]:
    """A data URL (webp) for the prompt, or None."""
    if not available():
        _fail("image", "MODEL_API_KEY is not set")
        return None
    body = {"model": IMAGE_MODEL, "prompt": prompt[:1500], "n": 1, "size": size,
            "response_format": "b64_json", "output_format": "webp", "reasoning_strength": "low"}
    try:
        r = requests.post(f"{API_BASE}/images/generations", headers=_headers(), json=body, timeout=timeout)
        if r.status_code >= 400:
            _fail("image", f"HTTP {r.status_code}: {r.text[:200]}")
            return None
        d = (r.json().get("data") or [{}])[0]
        last_error["image"] = None
        if d.get("b64_json"):
            return "data:image/webp;base64," + d["b64_json"]
        return d.get("url")
    except Exception as e:
        _fail("image", repr(e))
        return None
