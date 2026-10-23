"""
DeepFit tools - the athlete's own data, made available to an AI model.

The same tool set is used two ways:
  * by the in-app AI Coach chatbot (meta_chatbot.py) through function calling
  * by any MCP client (Claude Desktop, Cursor, ...) through deepfit_mcp_server.py

Every tool is READ-ONLY and is scoped to one athlete. In the web app the athlete
comes from the logged-in session, never from the model, so the chatbot can only
ever see the data of the person who is logged in.
"""

import os
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

try:
    from bson import ObjectId
except Exception:  # pragma: no cover
    ObjectId = None

try:
    import exercise_engine as _EE
    EXERCISES = tuple(dict.fromkeys(list(_EE.EXERCISES) + ["height_weight"]))
except Exception:  # pragma: no cover
    _EE = None
    EXERCISES = ("situps", "dumbbell_curls", "vertical_jump", "height_weight")

# ---------------------------------------------------------------- helpers

def _jsonable(value: Any) -> Any:
    """Make Mongo documents safe for JSON (ObjectId, datetime, bytes...)."""
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()
                if k not in ("password", "photo", "certificate", "profile_pic", "jumps", "calibration_data")}
    if isinstance(value, list):
        return [_jsonable(v) for v in value[:50]]
    if isinstance(value, datetime):
        return value.isoformat(timespec="minutes")
    if isinstance(value, (bytes, bytearray)):
        return None
    if ObjectId is not None and isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, float):
        return round(value, 2)
    return value


def _when(doc: Dict) -> str:
    for key in ("date", "timestamp", "analysis_date", "session_start", "created_at"):
        v = doc.get(key)
        if v:
            return v.isoformat() if isinstance(v, datetime) else str(v)
    return ""


class AthleteContext:
    """Who the tools are about, plus a database handle."""

    def __init__(self, db, user_id: Optional[str] = None, email: Optional[str] = None):
        self.db = db
        self.user_id = user_id
        self.email = email
        self._user = None
        if db is not None and (user_id or email):
            try:
                if user_id and ObjectId is not None:
                    self._user = db.users.find_one({"_id": ObjectId(user_id)})
                if self._user is None and email:
                    self._user = db.users.find_one({"email": email})
            except Exception:
                self._user = None
        if self._user:
            self.user_id = str(self._user.get("_id"))
            self.email = self._user.get("email", email)

    @property
    def known(self) -> bool:
        return self._user is not None

    def ids(self) -> List[Any]:
        """All the ways results reference this athlete (ObjectId, id string, email)."""
        out: List[Any] = []
        if self.user_id:
            out.append(self.user_id)
            if ObjectId is not None:
                try:
                    out.append(ObjectId(self.user_id))
                except Exception:
                    pass
        if self.email:
            out.append(self.email)
        return out


# ------------------------------------------------------------------ tools

def get_my_profile(ctx: AthleteContext) -> Dict:
    if not ctx.known:
        return {"error": "Athlete not found (not logged in, or unknown email)."}
    u = ctx._user
    return _jsonable({
        "name": u.get("name"),
        "age": u.get("age"),
        "gender": u.get("gender"),
        "place": u.get("place"),
        "member_since": u.get("created_at"),
        "has_registration_photo": bool(u.get("photo")),
    })


def _collect_history(ctx: AthleteContext, exercise: Optional[str], limit: int) -> List[Dict]:
    db = ctx.db
    rows: List[Dict] = []
    ids = ctx.ids()
    if db is None or not ids:
        return rows

    def want(name: str) -> bool:
        return exercise in (None, "", "all", name)

    # Standard results collection (all exercises write here)
    try:
        for d in db.exercise_results.find({"user_id": {"$in": ids}}):
            ex = d.get("exercise_type", "unknown")
            if want(ex):
                rows.append({
                    "exercise": ex,
                    "when": _when(d),
                    "repetitions": d.get("repetitions"),
                    "value": d.get("value"),
                    "unit": d.get("unit"),
                    "rating": (d.get("benchmark") or {}).get("rating"),
                    "target": (d.get("benchmark") or {}).get("target"),
                    "mode": d.get("mode"),
                    "duration_s": d.get("duration"),
                    "form_score": d.get("form_score"),
                    "notes": d.get("form_feedback"),
                })
    except Exception:
        pass

    # Detailed vertical jump sessions
    if want("vertical_jump") and ctx.email:
        try:
            for d in db["Vertical_Jump"].find({"user_email": ctx.email}):
                rows.append({
                    "exercise": "vertical_jump",
                    "when": _when(d),
                    "jumps": d.get("total_jumps"),
                    "max_height_cm": d.get("max_height"),
                    "average_height_cm": d.get("average_height"),
                })
        except Exception:
            pass

    # Height & weight estimates
    if want("height_weight") and ctx.email:
        for coll in ("Final_Estimated_Height_and_Weight", "Height and Weight"):
            try:
                for d in db[coll].find({"user_email": ctx.email}):
                    rows.append({
                        "exercise": "height_weight",
                        "when": _when(d),
                        "height_cm": d.get("final_height_cm") or d.get("height_cm"),
                        "weight_kg": d.get("final_weight_kg") or d.get("weight_kg"),
                    })
            except Exception:
                pass

    rows.sort(key=lambda r: r.get("when") or "", reverse=True)
    return [_jsonable({k: v for k, v in r.items() if v is not None}) for r in rows[:limit]]


def get_my_exercise_history(ctx: AthleteContext, exercise: str = "all", limit: int = 10) -> Dict:
    if not ctx.known:
        return {"error": "Athlete not found (not logged in, or unknown email)."}
    limit = max(1, min(int(limit or 10), 50))
    rows = _collect_history(ctx, exercise, limit)
    return {"exercise": exercise, "count": len(rows), "sessions": rows}


def get_my_progress_summary(ctx: AthleteContext) -> Dict:
    if not ctx.known:
        return {"error": "Athlete not found (not logged in, or unknown email)."}
    rows = _collect_history(ctx, None, 500)
    summary: Dict[str, Dict] = {}
    for r in rows:
        ex = r["exercise"]
        if "max_height_cm" in r:
            metric = "max_height_cm"
        elif ex == "height_weight":
            metric = "height_cm"
        elif r.get("unit") and r.get("value") is not None:
            metric = "value"
        else:
            metric = "repetitions"
        val = r.get(metric)
        label = r.get("unit") if metric == "value" else metric
        higher = True
        if _EE is not None and ex in _EE.EXERCISES:
            higher = _EE.EXERCISES[ex].higher_is_better
        s = summary.setdefault(f"{ex} ({label})", {"sessions": 0, "higher_is_better": higher})
        s["sessions"] += 1
        if isinstance(val, (int, float)):
            s["best"] = (max if higher else min)(s.get("best", val), val)
            s.setdefault("latest", val)           # rows are newest first
            s["first"] = val                       # ends up as the oldest
            s.setdefault("latest_date", r.get("when"))
    for s in summary.values():
        if "latest" in s and "first" in s and s["sessions"] > 1:
            s["change_since_first"] = round(s["latest"] - s["first"], 2)
    return {"athlete": ctx._user.get("name"), "by_exercise": summary,
            "note": "Rows newest first; 'change_since_first' compares latest vs oldest session."}


def compare_with_benchmark(ctx: AthleteContext) -> Dict:
    """Compare against the closest-matching athlete in AthleteData.csv."""
    if not ctx.known:
        return {"error": "Athlete not found (not logged in, or unknown email)."}
    try:
        import pandas as pd
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "AthleteData.csv")
        data = pd.read_csv(path)
    except Exception as e:
        return {"error": f"Benchmark dataset unavailable: {e}"}

    u = ctx._user
    hist = _collect_history(ctx, "height_weight", 1)
    height = hist[0].get("height_cm") if hist else None
    weight = hist[0].get("weight_kg") if hist else None
    gender = str(u.get("gender", "")).strip().upper()[:1]
    try:
        age = float(u.get("age"))
    except Exception:
        age = None
    if age is None:
        return {"error": "Age missing from profile, cannot pick a benchmark."}

    def score(row):
        s = abs(row["Age"] - age)
        if height:
            s += abs(row["Height_cm"] - height)
        if weight:
            s += abs(row["Weight_kg"] - weight)
        if gender and row["Gender"] != gender:
            s += 100
        return s

    best = data.loc[data.apply(score, axis=1).idxmin()]
    progress = get_my_progress_summary(ctx)["by_exercise"]
    return _jsonable({
        "matched_on": {"age": age, "gender": gender or None, "height_cm": height, "weight_kg": weight},
        "benchmark_athlete": {
            "age": int(best["Age"]), "gender": best["Gender"],
            "situps_per_min": float(best["Situps_per_min"]),
            "vertical_jump_cm": float(best["Vertical_Jump_cm"]),
            "dumbbell_curls_per_min": float(best["Dumbbell_Curl_per_min"]),
        },
        "athlete_best": {k: v.get("best") for k, v in progress.items()},
        "caveat": f"Benchmark dataset has only {len(data)} reference athletes; treat as indicative.",
    })


GUIDES = {
    "situps": {
        "setup": "Lie on your back, knees bent ~90 degrees, feet flat, hands behind head or crossed on chest. Camera side-on, whole body visible.",
        "counting": "A rep counts when the hip angle goes from above 150 degrees (lying) to below 100 degrees (sitting up).",
        "form_cues": ["Don't pull on your neck", "Exhale on the way up", "Lower slowly, shoulders touch the floor"],
        "duration": "3-minute test.",
    },
    "dumbbell_curls": {
        "setup": "Stand facing the camera, both arms visible, elbows close to the body.",
        "counting": "A rep counts when the elbow angle goes below 55 degrees (top) and back above 150 degrees (bottom). Left and right are counted separately.",
        "form_cues": ["Keep elbows still", "No swinging the torso", "Control the lowering phase"],
    },
    "vertical_jump": {
        "setup": "Stand still, full body visible, 2-3 m from the camera, for calibration first.",
        "counting": "Jump height is measured from the rise of the hips/feet relative to the calibrated standing position.",
        "form_cues": ["Swing arms for momentum", "Land softly on both feet", "Wait for 'calibrated' before jumping"],
    },
    "height_weight": {
        "setup": "Stand 2-3 m from the camera, full body visible, arms down, form-fitting clothes, plain background.",
        "counting": "Hold still ~5 seconds; results auto-save once stable.",
        "form_cues": ["Feet fully visible", "Stand straight", "Only one person in view"],
    },
    "identity_check": {
        "setup": "Before every test the face on camera is matched with the registration photo; it is re-checked every 2 s during the test.",
        "tips": ["Good front lighting", "Look straight at the camera", "Only the athlete in view"],
    },
}


def get_exercise_guide(ctx: AthleteContext, exercise: str) -> Dict:
    key = (exercise or "").strip().lower().replace(" ", "_")
    aliases = {"situp": "situps", "sit_ups": "situps", "curls": "dumbbell_curls", "dumbbell": "dumbbell_curls",
               "jump": "vertical_jump", "height": "height_weight", "weight": "height_weight",
               "face": "identity_check", "verification": "identity_check"}
    key = aliases.get(key, key)
    if key not in GUIDES and _EE is not None and key in _EE.EXERCISES:
        i = _EE.EXERCISES[key].info()
        return {"exercise": key, "name": i["name"], "setup": i["setup"], "counting": i["counting"],
                "form_cues": i["form_cues"], "blind_adaptation": i["blind_adaptation"],
                "deaf_adaptation": i["deaf_adaptation"], "khelo_india": i["khelo_india"]}
    if key not in GUIDES:
        return {"error": f"Unknown exercise '{exercise}'", "available": list(GUIDES)}
    return {"exercise": key, **GUIDES[key]}


def get_my_hidden_potential(ctx: AthleteContext) -> Dict:
    """Hidden Potential Index: maturity-adjusted fitness + coachability + growth headroom."""
    if not ctx.known:
        return {"error": "Athlete not found (not logged in, or unknown email)."}
    try:
        import potential
    except Exception as e:  # pragma: no cover
        return {"error": f"potential module unavailable: {e}"}
    latest: Dict[str, Dict] = {}
    try:
        for d in ctx.db.exercise_results.find({"user_id": {"$in": ctx.ids()}}):
            k = d.get("exercise_type")
            if k and (k not in latest or str(d.get("timestamp", "")) > str(latest[k].get("timestamp", ""))):
                latest[k] = d
    except Exception:
        pass
    hp = potential.hidden_potential(latest, ctx._user.get("age"), ctx._user.get("gender"))
    return _jsonable({k: hp.get(k) for k in ("index", "complete", "late_bloomer", "summary", "fitness_today",
                                             "fitness_adjusted", "biological_age", "coachability",
                                             "coachability_percentile", "headroom", "maturity", "missing", "weights")})


# ------------------------------------------------------------- registry

TOOLS: Dict[str, Dict[str, Any]] = {
    "get_my_profile": {
        "fn": get_my_profile,
        "description": "Get the logged-in athlete's profile: name, age, gender, place, member since.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    "get_my_exercise_history": {
        "fn": get_my_exercise_history,
        "description": "List the athlete's recent DeepFit sessions (newest first) with reps, jump heights, height/weight and dates.",
        "parameters": {
            "type": "object",
            "properties": {
                "exercise": {"type": "string", "enum": ["all", *EXERCISES],
                             "description": "Which test to list, or 'all'."},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50,
                          "description": "Max sessions to return (default 10)."},
            },
            "required": [],
        },
    },
    "get_my_progress_summary": {
        "fn": get_my_progress_summary,
        "description": "Per-test summary of the athlete's progress: number of sessions, best, latest and change since the first session.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    "compare_with_benchmark": {
        "fn": compare_with_benchmark,
        "description": "Compare the athlete with the closest reference athlete (by age, gender, height, weight) in DeepFit's benchmark dataset.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    "get_my_hidden_potential": {
        "fn": get_my_hidden_potential,
        "description": ("The athlete's Hidden Potential Index (0-100): fitness adjusted for physical maturity "
                        "(growth-spurt timing from the Growth Measures test), coachability (learning speed from the "
                        "Coachability Challenge) and growth headroom; also whether they are a 'late bloomer'."),
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    "get_exercise_guide": {
        "fn": get_exercise_guide,
        "description": "How a DeepFit test works: camera setup, how reps/heights are counted, and form cues. Also explains the face identity check.",
        "parameters": {
            "type": "object",
            "properties": {"exercise": {"type": "string",
                                        "enum": [*EXERCISES, "identity_check"]}},
            "required": ["exercise"],
        },
    },
}


def openai_tool_specs() -> List[Dict]:
    """Tool list in Chat Completions format (Meta Model API is compatible)."""
    return [{"type": "function",
             "function": {"name": name, "description": t["description"], "parameters": t["parameters"]}}
            for name, t in TOOLS.items()]


def run_tool(name: str, args: Dict, ctx: AthleteContext) -> Dict:
    tool = TOOLS.get(name)
    if tool is None:
        return {"error": f"Unknown tool {name}"}
    allowed = set(tool["parameters"].get("properties", {}))
    clean = {k: v for k, v in (args or {}).items() if k in allowed}
    try:
        return tool["fn"](ctx, **clean)
    except Exception as e:
        return {"error": f"{name} failed: {e}"}
