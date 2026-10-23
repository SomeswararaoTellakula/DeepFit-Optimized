"""
DeepFit Arena - "the game IS the trial".

A full-body camera game that runs in any browser (body tracking runs on the player's own
device, MediaPipe Pose for the web). Hidden inside the game is a talent assessment:
reflexes, agility, power, game reading (anticipation), learning speed and heart-rate
recovery (pulse read from the face colour).

Meta models (server side, all optional - the game works without them):
    Muse Spark   game master: explains the profile in the player's language and designs the
                 next session around their weak spots (structured JSON)
    SAM 3.1      finds the whole person (head to feet) for an exact size calibration, and
                 the face for the pulse reading
    Muse Voice   voice commands in Indian languages ("start", "next", "repeat"...), so blind
    Transcribe   players and children who can't read can play
    Muse Image   the player's personal poster for the share card

Routes
    GET  /arena                     the game (?sim=1 = simulated player, for testing / demos without a camera)
    GET  /api/arena/status          which Meta models are reachable
    POST /api/arena/sam             {image, prompt: person|face} -> boxes
    POST /api/arena/voice?lang=te   WAV body -> {transcript, intent}
    POST /api/arena/score           {raw} -> profile (server's own calculation)
    POST /api/arena/coach           {raw, lang, name, age} -> story + next-session plan
    POST /api/arena/art             {raw, lang} -> poster image
    POST /api/arena/save            {raw, lang, coach} -> signed result + share link
    GET  /arena/r/<id>/<token>      shareable, verifiable result card
"""

import json
import os
import random
from datetime import datetime
from typing import Dict, Optional

from flask import Blueprint, abort, jsonify, render_template, request, session

import arena_score
import meta_models
import passport
from db_config import get_db
from error_logger import log_error, log_info

try:
    from bson import ObjectId
except Exception:  # pragma: no cover
    ObjectId = None

arena_bp = Blueprint("arena", __name__)

LANGS = {"en": "English", "hi": "Hindi", "te": "Telugu"}
MAX_JSON = 2 * 1024 * 1024
MAX_AUDIO = 4 * 1024 * 1024

DEFAULT_PLAN = {"raider_window_ms": 1500, "log_speed": 1.0, "bowler_hard_share": 0.35, "combo_length": 4}
PLAN_LIMITS = {"raider_window_ms": (900, 2200), "log_speed": (0.7, 1.6), "bowler_hard_share": (0.0, 0.8),
               "combo_length": (3, 6)}

INTENT_WORDS = {
    "yes": ["yes", "yeah", "bonus", "हाँ", "हां", "हा ", "जी", "అవును", "ఔను", "సరే"],
    "no": ["no thanks", "nahi", "नहीं", "వద్దు", "లేదు"],
    "start": ["start", "begin", "go", "play", "ready", "शुरू", "शुरु", "चलो", "स्टार्ट", "ప్రారంభ", "మొదలు", "స్టార్ట్", "రెడీ"],
    "next": ["next", "skip", "continue", "अगला", "आगे", "తర్వాత", "తరువాత", "ముందుకు", "నెక్స్ట్"],
    "repeat": ["repeat", "again", "say that", "फिर से", "दोबारा", "दुबारा", "మళ్ళీ", "మళ్లీ", "తిరిగి"],
    "results": ["result", "score", "how did i do", "नतीजा", "स्कोर", "परिणाम", "ఫలితం", "స్కోర్", "రిజల్ట్"],
    "help": ["help", "मदद", "सहायता", "సహాయం", "హెల్ప్"],
}


def _clamp_plan(p: Optional[Dict]) -> Dict:
    out = dict(DEFAULT_PLAN)
    for k, (lo, hi) in PLAN_LIMITS.items():
        try:
            v = float((p or {}).get(k, out[k]))
            out[k] = int(round(min(hi, max(lo, v)))) if k in ("raider_window_ms", "combo_length") else round(min(hi, max(lo, v)), 2)
        except (TypeError, ValueError):
            pass
    return out


def _body() -> Dict:
    raw = request.get_data(cache=False) or b""
    if len(raw) > MAX_JSON:
        abort(413)
    try:
        d = json.loads(raw.decode("utf-8")) if raw else {}
    except ValueError:
        d = {}
    return d if isinstance(d, dict) else {}


def _athlete() -> Optional[Dict]:
    uid = session.get("user_id")
    db = get_db()
    if not uid or db is None or ObjectId is None:
        return None
    try:
        doc = db.users.find_one({"_id": ObjectId(uid)})
    except Exception:
        doc = None
    if not doc:
        return None
    return {"id": str(doc["_id"]), "ref": f"user:{doc['_id']}", "name": doc.get("name"), "age": doc.get("age"),
            "gender": doc.get("gender"), "email": doc.get("email")}


def _last_plan(ath: Optional[Dict]) -> Dict:
    db = get_db()
    if ath and db is not None:
        try:
            docs = list(db.arena_sessions.find({"athlete_ref": ath["ref"]}))
            docs.sort(key=lambda d: str(d.get("created", "")), reverse=True)
            if docs and docs[0].get("next_plan"):
                return _clamp_plan(docs[0]["next_plan"])
        except Exception:
            pass
    return dict(DEFAULT_PLAN)


# ------------------------------------------------------------------ page

@arena_bp.route("/arena")
def arena_page():
    ath = _athlete()
    height = 165.0
    if ath:
        try:
            from exercise_blueprint import _height_for
            height = _height_for({"email": ath.get("email")})
        except Exception:
            pass
    cfg = {
        "sim": request.args.get("sim") == "1",
        "lang": request.args.get("lang") if request.args.get("lang") in LANGS else "en",
        "loggedIn": bool(ath), "name": (ath or {}).get("name") or "", "age": (ath or {}).get("age"),
        "gender": (ath or {}).get("gender"), "heightCm": height, "plan": _last_plan(ath),
        "metaAvailable": meta_models.available(), "aiAvailable": meta_models.ai_available(),
    }
    return render_template("arena.html", cfg=cfg, langs=LANGS)


@arena_bp.route("/api/arena/status")
def arena_status():
    import llm
    return jsonify({"meta_key": meta_models.available(), "ai": llm.status(), "last_errors": meta_models.last_error,
                    "models": {"chat": meta_models.CHAT_MODEL, "sam": meta_models.SAM_MODEL,
                               "asr": meta_models.ASR_MODEL, "image": meta_models.IMAGE_MODEL}})


# ------------------------------------------------------------------ SAM 3.1

@arena_bp.route("/api/arena/sam", methods=["POST"])
def arena_sam():
    d = _body()
    prompt = d.get("prompt")
    img = str(d.get("image") or "")
    if prompt not in ("person", "face") or not img.startswith("data:image/") or len(img) > 1_500_000:
        return jsonify({"ok": False, "error": "bad request"}), 400
    boxes = meta_models.sam_boxes(img, prompt)
    if boxes is None:
        return jsonify({"ok": False, "error": meta_models.last_error.get("sam") or "SAM unavailable"})
    return jsonify({"ok": True, "boxes": boxes[:3]})


# ------------------------------------------------------------------ voice commands

def _intent(text: str, lang: str) -> str:
    t = (text or "").lower()
    for intent, words in INTENT_WORDS.items():
        if any(w in t for w in words):
            return intent
    if t.strip() and meta_models.ai_available():
        out = meta_models.chat_json(
            "You map a short spoken command from a fitness game to one intent. The player may speak "
            "English, Hindi or Telugu (or mix them).",
            f"Spoken command: {text!r}",
            {"type": "object", "properties": {"intent": {"type": "string",
                                                         "enum": ["start", "next", "repeat", "results", "help", "yes", "no", "unknown"]}},
             "required": ["intent"], "additionalProperties": False}, name="intent", timeout=15)
        if out and out.get("intent") in ("start", "next", "repeat", "results", "help", "yes", "no"):
            return out["intent"]
    return "unknown"


@arena_bp.route("/api/arena/voice", methods=["POST"])
def arena_voice():
    audio = request.get_data(cache=False) or b""
    if not audio or len(audio) > MAX_AUDIO or audio[:4] != b"RIFF":
        return jsonify({"ok": False, "error": "send a WAV clip"}), 400
    lang = request.args.get("lang") if request.args.get("lang") in LANGS else "en"
    text = meta_models.transcribe(audio, [lang, "en"])
    if text is None:
        return jsonify({"ok": False, "error": meta_models.last_error.get("asr") or "transcription unavailable"})
    return jsonify({"ok": True, "transcript": text, "intent": _intent(text, lang)})


# ------------------------------------------------------------------ scoring + Muse Spark game master

@arena_bp.route("/api/arena/score", methods=["POST"])
def arena_score_route():
    raw = _body().get("raw")
    return jsonify({"ok": True, "profile": arena_score.profile(raw), "points": arena_score.points(raw)})


COACH_SCHEMA = {
    "type": "object",
    "properties": {
        "story": {"type": "string", "description": "3-4 short encouraging sentences for the player"},
        "strengths": {"type": "array", "items": {"type": "string"}, "maxItems": 3},
        "focus": {"type": "string", "description": "one thing to work on, with a simple home drill"},
        "tip_for_parents": {"type": "string"},
        "next_session": {
            "type": "object",
            "properties": {
                "raider_window_ms": {"type": "integer", "description": "900-2200; lower = faster raiders"},
                "log_speed": {"type": "number", "description": "0.7-1.6; higher = faster logs"},
                "bowler_hard_share": {"type": "number", "description": "0-0.8; share of hardest bowler clips"},
                "combo_length": {"type": "integer", "description": "3-6 moves"},
                "reason": {"type": "string"},
            },
            "required": ["raider_window_ms", "log_speed", "bowler_hard_share", "combo_length", "reason"],
        },
    },
    "required": ["story", "strengths", "focus", "tip_for_parents", "next_session"],
}


FALLBACK_TEXT = {
    "en": {
        "labels": {"reflex": "reflexes", "agility": "agility", "power": "power", "anticipation": "game reading",
                   "learning": "learning speed", "heart": "heart recovery"},
        "drills": {"reflex": "reaction drops: a friend drops a ball, you catch it before the second bounce",
                   "agility": "side-steps between two slippers 2 m apart, 3 x 20 seconds",
                   "power": "squat jumps, 3 x 8, landing softly",
                   "anticipation": "watch a bowler's or kicker's body and call the direction before the ball moves",
                   "learning": "copy a 5-step dance or drill from a video, then do it without looking",
                   "heart": "skipping or jogging 15 minutes, 4 days a week"},
        "story": "Great session! Your strongest areas today were {best}. Your profile suggests trying {sports}. Every session the game adapts to you.",
        "focus": "Work on {trait}: {drill}.", "no_focus": "Play again to complete your profile.",
        "none_best": "still being measured", "none_sports": "many sports",
        "parents": "Short, playful practice 3-4 times a week beats one long session. Let the child try the suggested sports at a local club.",
        "reason": "Adjusted to your results (offline coach).", "join": ", ",
    },
    "hi": {
        "labels": {"reflex": "प्रतिक्रिया की गति", "agility": "फुर्ती", "power": "ताकत", "anticipation": "खेल की समझ",
                   "learning": "सीखने की गति", "heart": "दिल की रिकवरी"},
        "drills": {"reflex": "रिएक्शन ड्रॉप: दोस्त गेंद गिराए, दूसरी उछाल से पहले पकड़ो",
                   "agility": "2 मीटर दूर रखी दो चप्पलों के बीच साइड-स्टेप, 20 सेकंड, 3 बार",
                   "power": "स्क्वाट जंप, 8 बार के 3 सेट, धीरे से उतरो",
                   "anticipation": "गेंदबाज़ या किक मारने वाले का शरीर देखो और गेंद चलने से पहले दिशा बोलो",
                   "learning": "वीडियो से 5 कदम का डांस या ड्रिल सीखो, फिर बिना देखे करो",
                   "heart": "हफ़्ते में 4 दिन, 15 मिनट रस्सी कूदना या जॉगिंग"},
        "story": "शानदार खेल! आज आपकी सबसे मज़बूत बातें रहीं: {best}। आप {sports} आज़मा सकते हैं। हर बार खेल आपके हिसाब से बदलता है।",
        "focus": "{trait} पर काम करो: {drill}।", "no_focus": "प्रोफ़ाइल पूरी करने के लिए फिर से खेलो।",
        "none_best": "अभी मापा जा रहा है", "none_sports": "कई खेल",
        "parents": "एक लंबे सत्र से बेहतर है हफ़्ते में 3-4 बार छोटा, मज़ेदार अभ्यास। बच्चे को सुझाए गए खेल पास के क्लब में आज़माने दें।",
        "reason": "आपके नतीजों के हिसाब से बदला गया (ऑफ़लाइन कोच)।", "join": ", ",
    },
    "te": {
        "labels": {"reflex": "ప్రతిస్పందన వేగం", "agility": "చురుకుదనం", "power": "శక్తి", "anticipation": "ఆట అవగాహన",
                   "learning": "నేర్చుకునే వేగం", "heart": "గుండె కోలుకునే శక్తి"},
        "drills": {"reflex": "రియాక్షన్ డ్రాప్: స్నేహితుడు బంతిని వదిలితే, రెండోసారి నేలను తాకేలోపు పట్టుకోండి",
                   "agility": "2 మీటర్ల దూరంలో ఉన్న రెండు చెప్పుల మధ్య పక్కకు అడుగులు, 20 సెకన్లు, 3 సార్లు",
                   "power": "స్క్వాట్ జంప్స్, 8 చొప్పున 3 సెట్లు, మెల్లగా దిగండి",
                   "anticipation": "బౌలర్ లేదా కిక్ చేసే వ్యక్తి శరీరాన్ని చూసి, బంతి కదలకముందే దిశను చెప్పండి",
                   "learning": "వీడియో నుండి 5 అడుగుల డాన్స్ లేదా డ్రిల్ నేర్చుకుని, చూడకుండా చేయండి",
                   "heart": "వారానికి 4 రోజులు, 15 నిమిషాలు స్కిప్పింగ్ లేదా జాగింగ్"},
        "story": "అద్భుతమైన ఆట! ఈరోజు మీ బలాలు: {best}. మీరు {sports} ప్రయత్నించవచ్చు. ప్రతిసారీ ఆట మీకు తగ్గట్టు మారుతుంది.",
        "focus": "{trait} మీద సాధన చేయండి: {drill}.", "no_focus": "ప్రొఫైల్ పూర్తి చేయడానికి మళ్లీ ఆడండి.",
        "none_best": "ఇంకా కొలుస్తున్నాం", "none_sports": "చాలా ఆటలు",
        "parents": "ఒక పెద్ద సెషన్ కంటే వారానికి 3-4 సార్లు చిన్న, సరదా సాధన మేలు. సూచించిన ఆటలను దగ్గరలోని క్లబ్‌లో ప్రయత్నించనివ్వండి.",
        "reason": "మీ ఫలితాల ప్రకారం మార్చాం (ఆఫ్‌లైన్ కోచ్).", "join": ", ",
    },
}


def _fallback_coach(prof: Dict, plan: Dict, lang: str = "en") -> Dict:
    """Rule-based coach used when Muse Spark is not reachable (no key, no internet, billing)."""
    L = FALLBACK_TEXT.get(lang, FALLBACK_TEXT["en"])
    t = prof["traits"]
    have = {k: v for k, v in t.items() if v is not None}
    best = sorted(have, key=lambda k: -have[k])[:2]
    weak = min(have, key=lambda k: have[k]) if have else None
    nxt = dict(plan)
    if t.get("reflex") is not None:
        nxt["raider_window_ms"] = int(plan["raider_window_ms"] - 150 if t["reflex"] >= 60 else plan["raider_window_ms"] + 100)
    if t.get("anticipation") is not None:
        nxt["bowler_hard_share"] = plan["bowler_hard_share"] + (0.15 if t["anticipation"] >= 60 else -0.1)
    if t.get("learning") is not None:
        nxt["combo_length"] = plan["combo_length"] + (1 if t["learning"] >= 70 else 0)
    sports = L["join"].join(s["sport"] for s in prof["sports"][:2]) or L["none_sports"]
    return {
        "story": L["story"].format(best=L["join"].join(L["labels"][b] for b in best) or L["none_best"], sports=sports),
        "strengths": [arena_score.LABELS[b] for b in best],
        "focus": L["focus"].format(trait=L["labels"][weak], drill=L["drills"][weak]) if weak else L["no_focus"],
        "tip_for_parents": L["parents"],
        "next_session": {**_clamp_plan(nxt), "reason": L["reason"]},
        "source": "fallback",
    }


@arena_bp.route("/api/arena/coach", methods=["POST"])
def arena_coach():
    d = _body()
    prof = arena_score.profile(d.get("raw"))
    plan = _clamp_plan(d.get("plan_used"))
    lang = d.get("lang") if d.get("lang") in LANGS else "en"
    name = str(d.get("name") or "").strip()[:40]
    age = d.get("age")
    system = (
        "You are the game master and coach of DeepFit Arena, a camera fitness game that secretly measures sports talent "
        "for children and adults in India. Write warmly and simply for the player (and their parents), never shame, no "
        "medical claims, no promises of selection. Scores are 0-100 starter scales; pulse values are camera estimates. "
        f"Write every text field in {LANGS[lang]} (simple, spoken style)."
        " Design the next session so it is slightly harder where the player is strong and gives more practice where they are weak."
        " If profile.scope is 'upper', the player played from the waist up: traits that are null were NOT measured - never call"
        " them weak; invite the player to step back next time to unlock the full-body levels.")
    user = json.dumps({"player": {"name": name or None, "age": age}, "profile": prof, "plan_used": plan}, ensure_ascii=False)
    out = meta_models.chat_json(system, user, COACH_SCHEMA, name="arena_coach")
    if not out or not isinstance(out.get("next_session"), dict):
        res = _fallback_coach(prof, plan, lang)
    else:
        ns = out["next_session"]
        out["next_session"] = {**_clamp_plan(ns), "reason": str(ns.get("reason", ""))[:300]}
        import llm
        out["source"], out["model"] = "muse-spark", llm.last_label.get("chat")
        res = out
    return jsonify({"ok": True, "coach": res, "profile": prof, "points": arena_score.points(d.get("raw"))})


@arena_bp.route("/api/arena/art", methods=["POST"])
def arena_art():
    d = _body()
    prof = arena_score.profile(d.get("raw"))
    sport = (prof["sports"][0]["sport"] if prof["sports"] else "athletics").split(" (")[0]
    trait = (prof.get("top_trait") or "energy").lower()
    prompt = (f"Bold, joyful sports poster illustration of an anonymous young Indian athlete playing {sport}, "
              f"seen as a dynamic silhouette with motion trails that express {trait}, warm sunrise colours of rural India, "
              "village ground in the background, flat vector style, no text, no letters, no logos, no recognisable real person")
    img = meta_models.generate_image(prompt, size="1024x1024")
    if not img:
        return jsonify({"ok": False, "error": meta_models.last_error.get("image") or "image unavailable"})
    return jsonify({"ok": True, "image": img, "sport": sport})


# ------------------------------------------------------------------ save + share

def _payload(doc: Dict) -> Dict:
    p = doc["profile"]
    return {"id": str(doc["_id"]), "athlete_ref": doc.get("athlete_ref"), "display": doc.get("display"),
            "created": doc["created"], "traits": p["traits"], "overall": p["overall"],
            "sports": [s["sport"] for s in p["sports"]], "raw_hash": doc["raw_hash"],
            "points": (doc.get("points") or {}).get("total"), **({"scope": doc["scope"]} if doc.get("scope") else {})}


@arena_bp.route("/api/arena/save", methods=["POST"])
def arena_save():
    import hashlib
    d = _body()
    raw = d.get("raw") if isinstance(d.get("raw"), dict) else {}
    prof = arena_score.profile(raw)
    if prof["overall"] is None:
        return jsonify({"ok": False, "error": "Play at least one level first."}), 400
    ath = _athlete()
    guest = str(d.get("name") or "").strip()[:40]
    coach = d.get("coach") if isinstance(d.get("coach"), dict) else {}
    db = get_db()
    if db is None or ObjectId is None:
        return jsonify({"ok": False, "error": "Database unavailable"}), 503
    doc = {
        "_id": ObjectId(), "created": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "athlete_ref": ath["ref"] if ath else None,
        "display": passport.display_name(ath["name"] if ath else guest) if (ath or guest) else "Guest player",
        "age": (ath or {}).get("age") or d.get("age"), "lang": d.get("lang") if d.get("lang") in LANGS else "en",
        "mode": d.get("mode") if d.get("mode") in ("standard", "blind", "deaf") else "standard",
        "camera": "simulated" if d.get("simulated") else "camera",
        "scope": arena_score.scope(raw),
        "raw": raw, "raw_hash": hashlib.sha256(json.dumps(raw, sort_keys=True, default=str).encode()).hexdigest(),
        "profile": prof,
        "points": arena_score.points(raw), "points_total": arena_score.points(raw)["total"],
        "coach": {k: coach.get(k) for k in ("story", "strengths", "focus", "tip_for_parents", "source", "model") if k in coach},
        "next_plan": _clamp_plan((coach.get("next_session") if coach else None) or d.get("plan_used")),
    }
    sig = passport.sign(_payload(doc))
    doc["sig"], doc["token"] = sig, sig[:16]
    try:
        db.arena_sessions.insert_one(dict(doc))
    except Exception as e:
        log_error(f"arena save failed: {e}")
        return jsonify({"ok": False, "error": "Could not save"}), 500
    log_info(f"Arena session saved: overall {prof['overall']} ({doc['display']}, {doc['camera']})")
    from exercise_blueprint import share_base
    path = f"/arena/r/{doc['_id']}/{doc['token']}"
    return jsonify({"ok": True, "url": path, "share_url": share_base() + path, "profile": prof, "points": doc["points"], "display": doc["display"],
                    "board": _board_position(doc)})


# ------------------------------------------------------------------ leaderboard

def _scope_of(r: Dict) -> str:
    return r.get("scope") or "full"          # games saved before upper-body mode were all full-body


def _board_rows(include_sim: bool = False, limit: int = 300, scope: str = "full"):
    """Leaderboard rows for one scope: full-body and upper-body runs are ranked separately."""
    db = get_db()
    if db is None:
        return []
    proj = {"display": 1, "points_total": 1, "points": 1, "created": 1, "camera": 1, "raw.quick": 1, "profile.overall": 1,
            "athlete_ref": 1, "mode": 1, "scope": 1}
    try:
        cur = db.arena_sessions.find({} if include_sim else {"camera": "camera"}, proj)
        if hasattr(cur, "limit"):        # a real MongoDB cursor (simple test stand-ins return lists)
            cur = cur.sort("points_total", -1).limit(limit)
        rows = [r for r in cur if include_sim or r.get("camera") == "camera"]
    except Exception as e:
        log_error(f"leaderboard failed: {e}")
        return []
    rows = [r for r in rows if _scope_of(r) == scope]
    rows.sort(key=lambda r: -(r.get("points_total") or 0))
    return rows


def _entry(r: Dict) -> Dict:
    pts = r.get("points") or {}
    return {"name": r.get("display") or "Player", "points": r.get("points_total") or 0, "rank": pts.get("rank"),
            "rank_icon": pts.get("rank_icon"), "stars": pts.get("stars"), "overall": (r.get("profile") or {}).get("overall"),
            "when": str(r.get("created") or "")[:10], "simulated": r.get("camera") == "simulated",
            "length": "quick" if (r.get("raw") or {}).get("quick", True) else "full", "mode": r.get("mode"),
            "scope": _scope_of(r)}


def _board_position(doc: Dict) -> Dict:
    rows = _board_rows(include_sim=doc.get("camera") == "simulated", scope=_scope_of(doc))
    today = str(doc.get("created", ""))[:10]
    day = [r for r in rows if str(r.get("created", ""))[:10] == today]
    pos = lambda rs: next((i + 1 for i, r in enumerate(rs) if str(r.get("_id")) == str(doc["_id"])), None)
    return {"today": pos(day), "today_players": len(day), "all_time": pos(rows), "players": len(rows), "scope": _scope_of(doc)}


@arena_bp.route("/api/arena/leaderboard")
def arena_leaderboard():
    """Top players today and of all time (simulated games only when the page itself is in simulation mode)."""
    sc = "upper" if request.args.get("scope") == "upper" else "full"
    rows = _board_rows(include_sim=request.args.get("sim") == "1", scope=sc)
    today = datetime.utcnow().strftime("%Y-%m-%d")
    return jsonify({"ok": True, "scope": sc, "today": [_entry(r) for r in rows if str(r.get("created", ""))[:10] == today][:10],
                    "all_time": [_entry(r) for r in rows][:10]})


@arena_bp.route("/arena/r/<rid>/<tok>")
def arena_result(rid, tok):
    import hmac
    db = get_db()
    if db is None or ObjectId is None:
        abort(404)
    try:
        doc = db.arena_sessions.find_one({"_id": ObjectId(rid)})
    except Exception:
        doc = None
    if not doc or doc.get("token") != tok:
        abort(404)
    import hashlib
    problems = []
    if hashlib.sha256(json.dumps(doc.get("raw") or {}, sort_keys=True, default=str).encode()).hexdigest() != doc.get("raw_hash"):
        problems.append("The raw game measurements were changed after saving.")
    if arena_score.profile(doc.get("raw"))["traits"] != doc["profile"]["traits"]:
        problems.append("The scores no longer match the measurements.")
    if doc.get("points") is not None and arena_score.points(doc.get("raw"))["total"] != doc["points"].get("total"):
        problems.append("The game points no longer match the measurements.")
    if not hmac.compare_digest(passport.sign(_payload(doc)), doc.get("sig", "")):
        problems.append("Signature check failed - the result was edited.")
    from exercise_blueprint import _checked_at, _qr_svg_inline, share_base
    share_url = share_base() + f"/arena/r/{rid}/{tok}"
    return render_template("arena_result.html", doc=doc, prof=doc["profile"], valid=not problems, problems=problems,
                           scanned=request.args.get("scan") == "1", checked_at=_checked_at(), share_url=share_url,
                           qr_svg=_qr_svg_inline(share_url + "?scan=1"), radar=_radar(doc["profile"]["traits"]),
                           labels=arena_score.LABELS, langs=LANGS)


def _radar(traits: Dict) -> Dict:
    """Points for the six-trait radar chart (drawn on the server, so it also prints)."""
    import math
    keys, cx, cy, r = arena_score.TRAITS, 160, 150, 105

    def pt(i, rad):
        a = -math.pi / 2 + i * 2 * math.pi / len(keys)
        return round(cx + math.cos(a) * rad, 1), round(cy + math.sin(a) * rad, 1)

    rings = [" ".join("%s,%s" % pt(i, r * f) for i in range(len(keys))) for f in (0.25, 0.5, 0.75, 1)]
    spokes = [pt(i, r) for i in range(len(keys))]
    labels = [(arena_score.LABELS[k], *pt(i, r + 28)) for i, k in enumerate(keys)]
    shape = " ".join("%s,%s" % pt(i, r * (traits.get(k) or 0) / 100) for i, k in enumerate(keys))
    return {"rings": rings, "spokes": spokes, "labels": labels, "shape": shape, "cx": cx, "cy": cy}
