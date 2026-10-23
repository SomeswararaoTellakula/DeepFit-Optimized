"""
One client for every AI text, vision and speech call in DeepFit, with automatic fallback.

    1. Meta Model API - Muse Spark                         (.env MODEL_API_KEY)
    2. Groq - Meta's Muse Spark open weights, then Llama   (.env GROQ_API_KEY)
       3.3 70B for text, a vision model for photos and
       Whisper for speech
    3. Google Gemini (OpenAI-compatible endpoint), last     (.env GEMINI_API_KEY)
       resort for text, photos and speech. The interface
       shows it as "DeepFit AI" (the real model is in
       /api/arena/status and the logs).

If a provider answers 401 / 402 / 403 / 404 (wrong key, no billing or credits, no access to the
model, model retired) it is skipped for 15 minutes and the next one answers - so the AI Coach,
the Arena game master, voice commands and the photo readers keep working while the Meta
account has no credits yet.

Model lists can be changed without code (comma separated, tried in order):
    META_MODEL=muse-spark-1.3
    GROQ_CHAT_MODELS=meta-models/muse-spark-open,llama-3.3-70b-versatile
    GROQ_VISION_MODELS=meta-models/muse-spark-open,qwen/qwen3.8-27b
    GROQ_ASR_MODEL=whisper-large-v3-turbo
    GEMINI_MODELS=gemini-3.8-flash,gemini-2.5-flash
"""

import json
import logging
import os
import re
import time
from typing import Dict, List, Optional

import requests

log = logging.getLogger("llm")

META_BASE = os.environ.get("META_API_BASE", "https://api.meta.ai/v1")
GROQ_BASE = os.environ.get("GROQ_API_BASE", "https://api.groq.com/openai/v1")
GEMINI_BASE = os.environ.get("GEMINI_API_BASE", "https://generativelanguage.googleapis.com/v1beta/openai")
GEMINI_LABEL = "DeepFit AI"                 # what the interface shows when Gemini answered
SKIP_SECONDS = 900

LABELS = {
    "meta-models/muse-spark-open": "Muse Spark open weights (Groq)",
    "llama-3.3-70b-versatile": "Llama 3.3 70B (Groq)",
    "llama-3.1-8b-instant": "Llama 3.1 8B (Groq)",
    "qwen/qwen3.8-27b": "Qwen vision (Groq)",
}

_skip: Dict[str, float] = {}                 # "base|model" -> time until which it is skipped
last_used: Dict[str, Optional[str]] = {"chat": None, "vision": None, "asr": None}     # real model (diagnostics)
last_label: Dict[str, Optional[str]] = {"chat": None, "vision": None}                 # what the interface may show
last_errors: List[str] = []


class LLMError(Exception):
    pass


def _list(env: str, default: str) -> List[str]:
    return [m.strip() for m in os.environ.get(env, default).split(",") if m.strip()]


def meta_key() -> Optional[str]:
    return os.environ.get("MODEL_API_KEY") or os.environ.get("META_API_KEY")


def groq_key() -> Optional[str]:
    return os.environ.get("GROQ_API_KEY")


def gemini_key() -> Optional[str]:
    return os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")


def configured() -> bool:
    return bool(meta_key() or groq_key() or gemini_key())


def routes(kind: str = "chat") -> List[Dict]:
    """Providers/models to try, in order. kind: chat | vision."""
    out = []
    if meta_key():
        m = os.environ.get("META_MODEL", "muse-spark-1.3")
        out.append({"provider": "meta", "base": META_BASE, "key": meta_key(), "model": m, "label": "Muse Spark (Meta)",
                    "reasoning": os.environ.get("META_REASONING_EFFORT", "low") or None, "system_role": "developer"})
    if groq_key():
        models = (_list("GROQ_VISION_MODELS", "meta-models/muse-spark-open,qwen/qwen3.8-27b") if kind == "vision"
                  else _list("GROQ_CHAT_MODELS", "meta-models/muse-spark-open,llama-3.3-70b-versatile"))
        for m in models:
            out.append({"provider": "groq", "base": GROQ_BASE, "key": groq_key(), "model": m, "label": LABELS.get(m, m + " (Groq)"),
                        "reasoning": "low" if "muse-spark" in m else None, "system_role": "system"})
    if gemini_key():
        for m in _list("GEMINI_MODELS", "gemini-3.8-flash,gemini-2.5-flash"):
            out.append({"provider": "gemini", "base": GEMINI_BASE, "key": gemini_key(), "model": m, "label": GEMINI_LABEL,
                        "real": m + " (Gemini)", "reasoning": "low", "system_role": "system"})
    return out


def _rid(r: Dict) -> str:
    return r["base"] + "|" + r["model"]


def _skipped(r: Dict) -> bool:
    return _skip.get(_rid(r), 0) > time.time()


def _adapt(messages: List[Dict], r: Dict) -> List[Dict]:
    out = []
    for m in messages:
        m = dict(m)
        if m.get("role") in ("developer", "system"):
            m["role"] = r["system_role"]
        out.append(m)
    return out


def _note(err: str) -> None:
    last_errors.append(time.strftime("%H:%M:%S ") + err[:300])
    del last_errors[:-20]
    log.warning(err[:300])


def complete(messages: List[Dict], *, tools: Optional[List[Dict]] = None, schema: Optional[Dict] = None,
             schema_name: str = "result", json_mode: bool = False, vision: bool = False,
             timeout: float = 60.0) -> Dict:
    """Chat completion with fallback. Returns {"message": {...}, "label": "...", "provider": "..."}."""
    errors = []
    for r in routes("vision" if vision else "chat"):
        if _skipped(r):
            errors.append(f"{r['label']}: skipped after an earlier error")
            continue
        msgs = _adapt(messages, r)
        body: Dict = {"model": r["model"], "messages": msgs}
        if tools:
            body["tools"], body["tool_choice"] = tools, "auto"
        if schema is not None:
            if r["provider"] == "meta":
                body["response_format"] = {"type": "json_schema", "json_schema": {"name": schema_name, "schema": schema}}
            else:      # JSON object mode on Groq / Gemini; the schema goes into the instructions
                body["response_format"] = {"type": "json_object"}
                body["messages"] = [{"role": r["system_role"], "content": "Answer with one JSON object that matches this JSON schema: "
                                     + json.dumps(schema)}] + msgs
        elif json_mode:
            body["response_format"] = {"type": "json_object"}
        if r["reasoning"]:
            body["reasoning_effort"] = r["reasoning"]
        for attempt in range(2):
            try:
                resp = requests.post(f"{r['base']}/chat/completions", json=body, timeout=timeout,
                                     headers={"Authorization": f"Bearer {r['key']}", "Content-Type": "application/json"})
            except requests.RequestException as e:
                errors.append(f"{r['label']}: could not reach ({e.__class__.__name__})")
                break
            if resp.status_code == 200:
                try:
                    msg = resp.json()["choices"][0]["message"]
                except (ValueError, KeyError, IndexError):
                    errors.append(f"{r['label']}: unexpected answer")
                    break
                last_used["vision" if vision else "chat"] = r.get("real", r["label"])
                last_label["vision" if vision else "chat"] = r["label"]
                return {"message": msg, "label": r["label"], "provider": r["provider"]}
            text = resp.text[:300]
            if resp.status_code == 400 and "reasoning" in text.lower() and "reasoning_effort" in body:
                body.pop("reasoning_effort", None)          # this model takes no reasoning setting: retry once
                r["reasoning"] = None
                continue
            if resp.status_code in (401, 402, 403, 404):
                _skip[_rid(r)] = time.time() + SKIP_SECONDS
            elif resp.status_code == 429:
                _skip[_rid(r)] = time.time() + 20
            errors.append(f"{r.get('real', r['label'])}: HTTP {resp.status_code} {text}")
            break
    if not routes("vision" if vision else "chat"):
        errors.append("no AI key set (MODEL_API_KEY, GROQ_API_KEY or GEMINI_API_KEY in .env)")
    err = "; ".join(errors)
    _note(err)
    raise LLMError(err)


def parse_json(content) -> Optional[Dict]:
    if isinstance(content, list):                       # some servers return content parts
        content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
    content = content or ""
    m = re.search(r"\{.*\}", content, re.S)             # tolerate text around the JSON
    try:
        out = json.loads(m.group(0) if m else content)
    except (ValueError, AttributeError):
        return None
    return out if isinstance(out, dict) else None


def json_answer(system: str, user, schema: Dict, name: str = "result", vision: bool = False, timeout: float = 45.0) -> Optional[Dict]:
    """Structured answer (dict) or None. user may be text or a list of content parts (text + image_url)."""
    try:
        res = complete([{"role": "system", "content": system}, {"role": "user", "content": user}],
                       schema=schema, schema_name=name, vision=vision, timeout=timeout)
    except LLMError:
        return None
    out = parse_json(res["message"].get("content"))
    if out is not None:
        out["_model"] = res["label"]
    return out


def vision_json(prompt: str, image_data_url: str, schema: Dict, name: str = "result", system: str = "") -> Optional[Dict]:
    content = [{"type": "text", "text": prompt}, {"type": "image_url", "image_url": {"url": image_data_url}}]
    return json_answer(system or "You read photos carefully and answer only with JSON.", content, schema, name, vision=True)


def groq_transcribe(wav_bytes: bytes, lang: Optional[str] = None, timeout: float = 30.0) -> Optional[str]:
    """Speech to text with Whisper on Groq (fallback when Meta's Muse Voice Transcribe is unavailable)."""
    if not groq_key():
        return None
    data = {"model": os.environ.get("GROQ_ASR_MODEL", "whisper-large-v3-turbo"), "response_format": "json"}
    if lang in ("en", "hi", "te", "ta", "kn", "mr", "bn"):
        data["language"] = lang
    try:
        r = requests.post(f"{GROQ_BASE}/audio/transcriptions", headers={"Authorization": f"Bearer {groq_key()}"},
                          data=data, files={"file": ("voice.wav", wav_bytes, "audio/wav")}, timeout=timeout)
    except requests.RequestException as e:
        _note(f"Whisper (Groq): could not reach ({e.__class__.__name__})")
        return None
    if r.status_code != 200:
        _note(f"Whisper (Groq): HTTP {r.status_code} {r.text[:200]}")
        return None
    text = (r.json() or {}).get("text")
    last_used["asr"] = "Whisper (Groq)"
    return text.strip() if isinstance(text, str) else None


def gemini_transcribe(wav_bytes: bytes, lang: Optional[str] = None, timeout: float = 30.0) -> Optional[str]:
    """Speech to text with Gemini (audio sent in a chat request) - the last fallback for voice commands."""
    import base64
    if not gemini_key():
        return None
    names = {"hi": "Hindi", "te": "Telugu", "en": "English"}
    prompt = ("Transcribe this short voice command exactly, in the language spoken"
              + (f" (probably {names[lang]})" if lang in names else "") + ". Reply with the words only.")
    for m in _list("GEMINI_MODELS", "gemini-3.8-flash,gemini-2.5-flash"):
        r = {"base": GEMINI_BASE, "model": m}
        if _skipped(r):
            continue
        body = {"model": m, "messages": [{"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "input_audio", "input_audio": {"data": base64.b64encode(wav_bytes).decode(), "format": "wav"}}]}]}
        try:
            resp = requests.post(f"{GEMINI_BASE}/chat/completions", json=body, timeout=timeout,
                                 headers={"Authorization": f"Bearer {gemini_key()}", "Content-Type": "application/json"})
        except requests.RequestException as e:
            _note(f"{m} (Gemini) speech: could not reach ({e.__class__.__name__})")
            return None
        if resp.status_code != 200:
            if resp.status_code in (401, 402, 403, 404):
                _skip[_rid(r)] = time.time() + SKIP_SECONDS
            _note(f"{m} (Gemini) speech: HTTP {resp.status_code} {resp.text[:200]}")
            continue
        try:
            text = resp.json()["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError):
            continue
        last_used["asr"] = m + " (Gemini)"
        return text.strip() if isinstance(text, str) else None
    return None


def status() -> Dict:
    return {"configured": configured(), "meta": bool(meta_key()), "groq": bool(groq_key()), "gemini": bool(gemini_key()),
            "chat_chain": list(dict.fromkeys(r["label"] for r in routes("chat"))),        # interface names
            "vision_chain": list(dict.fromkeys(r["label"] for r in routes("vision"))),
            "models": [r.get("real", r["label"]) for r in routes("chat")],              # real models (diagnostics)
            "skipped": [k.split("|")[1] for k, v in _skip.items() if v > time.time()],
            "last_used": last_used, "last_errors": last_errors[-5:]}
