"""
Reading numbers off photos with a vision model (Muse Spark, or the Groq fallback - llm.py):

    read_scale(photo)     -> the weight shown on a bathroom scale's display
    read_dumbbell(photo)  -> the weight printed / moulded on a dumbbell (or an estimate from its look)

A camera cannot weigh anything, but it can READ: the number on the scale display or on the end of
a dumbbell is exact. When no number is visible, the dumbbell answer is only an estimate from its
type and size and is marked as such, so the athlete confirms it.
"""

import base64
import io
from typing import Dict, Optional

import llm

SCALE_SCHEMA = {
    "type": "object",
    "properties": {
        "is_scale_display": {"type": "boolean"},
        "reading": {"type": ["number", "null"], "description": "the number on the display exactly as shown"},
        "unit": {"type": "string", "enum": ["kg", "lb", "st", "unknown"]},
        "confidence": {"type": "number", "description": "0-1: how sure the digits were read correctly"},
        "notes": {"type": "string"},
    },
    "required": ["is_scale_display", "reading", "unit", "confidence"],
}

DUMBBELL_SCHEMA = {
    "type": "object",
    "properties": {
        "object": {"type": "string", "enum": ["dumbbell", "kettlebell", "weight plate", "water bottle", "other", "none"]},
        "marked_weight": {"type": ["number", "null"], "description": "weight printed/moulded on it, as written"},
        "marked_unit": {"type": "string", "enum": ["kg", "lb", "none"]},
        "label_text": {"type": "string", "description": "the text you read on it"},
        "estimated_kg": {"type": ["number", "null"], "description": "if no number is readable: best guess from type and size"},
        "dumbbell_type": {"type": "string", "enum": ["hex", "round", "vinyl/neoprene", "adjustable", "chrome", "bottle", "other"]},
        "count": {"type": "integer", "description": "how many dumbbells are visible"},
        "confidence": {"type": "number"},
    },
    "required": ["object", "marked_weight", "marked_unit", "label_text", "estimated_kg", "confidence"],
}

LB = 0.45359237


def to_data_url(data: bytes) -> str:
    """Any photo bytes -> upright JPEG data URL, max 1280 px (smaller requests, EXIF rotation applied)."""
    from PIL import Image, ImageOps
    img = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
    img.thumbnail((1280, 1280))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=88)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def decode_b64_image(s: str) -> Optional[bytes]:
    try:
        s = str(s or "")
        if s.startswith("data:"):
            s = s.split(",", 1)[1]
        raw = base64.b64decode(s, validate=False)
        return raw if 100 < len(raw) < 12 * 1024 * 1024 else None
    except Exception:
        return None


def read_scale(photo: bytes) -> Dict:
    if not llm.configured():
        return {"ok": False, "error": "No AI key on the server - type the weight instead."}
    try:
        url = to_data_url(photo)
    except Exception:
        return {"ok": False, "error": "That is not a photo we can read."}
    out = llm.vision_json(
        "This should be a photo of a bathroom / weighing scale display. Read the number shown on the display exactly "
        "(digits and decimal point). Say which unit it shows. If the digits are blurred, cut off or it is not a scale, "
        "set reading to null or is_scale_display to false. Do not guess digits you cannot see.",
        url, SCALE_SCHEMA, name="scale_reading")
    if out is None:
        return {"ok": False, "error": "The AI could not be reached - type the weight instead."}
    r = out.get("reading")
    if not out.get("is_scale_display") or not isinstance(r, (int, float)):
        return {"ok": False, "error": "Couldn't read the display - fill the frame with the numbers, avoid glare, try again.",
                "model": out.get("_model")}
    unit = out.get("unit")
    kg = r * LB if unit == "lb" else r * 6.35029318 if unit == "st" else r
    if not 10 <= kg <= 250:
        return {"ok": False, "error": f"Read {r} {unit}, which is not a body weight - try again.", "model": out.get("_model")}
    conf = float(out.get("confidence") or 0)
    return {"ok": True, "kg": round(kg, 1), "reading": r, "unit": unit, "confidence": round(conf, 2),
            "sure": conf >= 0.7, "model": out.get("_model")}


def read_dumbbell(photo: bytes) -> Dict:
    if not llm.configured():
        return {"ok": False, "error": "No AI key on the server - the weight can't be detected automatically."}
    try:
        url = to_data_url(photo)
    except Exception:
        return {"ok": False, "error": "That is not a photo we can read."}
    out = llm.vision_json(
        "Someone holds a dumbbell (or similar weight) up to the camera to show how heavy it is. Find the weight printed, "
        "engraved or moulded on it (often on the end cap or the side, e.g. '5 KG', '10LB', '2.5'). Read it exactly. "
        "If no number is readable, give your best estimate in kg from the type and size compared with the hand, and set "
        "marked_weight to null. If you see no weight at all, set object to 'none'.",
        url, DUMBBELL_SCHEMA, name="dumbbell")
    if out is None:
        return {"ok": False, "error": "The AI could not be reached - try again or pick the weight."}
    model = out.get("_model")
    if out.get("object") in ("none", "other", None):
        return {"ok": False, "error": "No dumbbell found - hold it close to the camera with the number facing it.", "model": model}
    marked, unit = out.get("marked_weight"), out.get("marked_unit")
    if isinstance(marked, (int, float)) and marked > 0:
        kg = marked * LB if unit == "lb" else marked
        if 0.25 <= kg <= 60:
            return {"ok": True, "kg": round(kg, 2), "source": "label", "sure": True, "label_text": out.get("label_text"),
                    "object": out.get("object"), "type": out.get("dumbbell_type"), "model": model,
                    "confidence": round(float(out.get("confidence") or 0), 2)}
    est = out.get("estimated_kg")
    if out.get("object") == "water bottle" and not isinstance(est, (int, float)):
        est = 1.0
    if isinstance(est, (int, float)) and 0.25 <= est <= 60:
        return {"ok": True, "kg": round(est * 2) / 2, "source": "estimate", "sure": False, "object": out.get("object"),
                "type": out.get("dumbbell_type"), "model": model, "confidence": round(float(out.get("confidence") or 0), 2),
                "note": "No number was readable - this is an estimate from its size. Show the end with the number to be exact."}
    return {"ok": False, "error": "Couldn't see a number on the dumbbell - turn the end with '5 KG' etc. towards the camera.",
            "model": model}
