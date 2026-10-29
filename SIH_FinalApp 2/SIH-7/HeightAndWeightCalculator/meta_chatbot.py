"""
DeepFit AI Coach - powered by Meta's Muse Spark through the Meta Model API, with automatic
fallback to Groq (Meta's Muse Spark open weights, then Llama 3.3 70B) - see llm.py.

* Chat Completions endpoint: https://api.meta.ai/v1/chat/completions (Groq: OpenAI-compatible)
* Function calling: the coach can read the logged-in athlete's own DeepFit data
  (profile, history, progress, benchmark comparison, exercise guides) using the
  tools in deepfit_tools.py - the same tools exposed over MCP by deepfit_mcp_server.py.
* Image understanding: photos / screenshots are sent as base64 data URLs.

Settings (.env):
    MODEL_API_KEY=...            Meta Model API key (META_API_KEY also accepted)
    GROQ_API_KEY=...             fallback provider (used when Meta has no credits / is unreachable)
    META_MODEL=muse-spark-1.3    model id
    META_REASONING_EFFORT=low    low | medium | high  (Muse Spark always reasons)
"""

import base64
import io
import json
import logging
import os
import time
from typing import Dict, List, Optional

import requests

from deepfit_tools import AthleteContext, openai_tool_specs, run_tool

logger = logging.getLogger("MetaChatbot")

API_BASE = os.environ.get("META_API_BASE", "https://api.meta.ai/v1")
DEFAULT_MODEL = os.environ.get("META_MODEL", "muse-spark-1.3")
REASONING_EFFORT = os.environ.get("META_REASONING_EFFORT", "low")
MAX_TOOL_ROUNDS = 5
MAX_HISTORY_TURNS = 12  # user turns kept in memory per athlete

SYSTEM_PROMPT = """You are DeepFit Coach, the AI assistant inside DeepFit - an AI sports talent
assessment platform used by schools, academies and athletes (including blind, deaf and other
para-athletes) in India.

What DeepFit measures with a single camera: 17 tests including the Khelo India battery (partial
curl-up, push-ups, sit and reach, flamingo balance, plate tapping, 50 m, 600 m, BMI), sit-ups, plank,
squats, jumping jacks, dumbbell curls, vertical and broad jump. It also has a Coachability Challenge
(how fast the athlete learns a new movement pattern), Growth Measures (sitting height -> how far from
the growth spurt), a Hidden Potential Index that combines them (finds late bloomers), and a Talent
Passport (signed, face-verified results with a QR code for scouts). Before every test the athlete's face is
matched with their registration photo, and it is re-checked during the test.

How to answer:
- When a question is about the athlete's own results, progress, profile or how they compare,
  CALL THE TOOLS to get real data first. Never invent numbers. If there is no data, say so and
  suggest which test to take.
- Be encouraging, specific and practical: concrete drills, sets/reps, technique cues.
- Keep answers short (under ~150 words) unless asked for detail. Use simple language; many users
  read on a phone or use a screen reader, so prefer short paragraphs and simple '-' bullet lists,
  no tables.
- You are not a doctor. For pain, injury, illness or medical questions, give general safety advice
  and recommend a qualified professional.
- Stay on fitness, sports, training, nutrition basics and how to use DeepFit."""


class MetaAPIError(Exception):
    pass


class MetaChatbot:
    """Drop-in replacement for the old GeminiChatbot (same public methods)."""

    def __init__(self, api_key: Optional[str] = None, model: str = DEFAULT_MODEL):
        import llm
        if not llm.configured():
            raise ValueError("No AI key set (MODEL_API_KEY or GROQ_API_KEY)")
        self.model = model
        self.history: List[Dict] = []
        self.last_label: Optional[str] = None

    # ------------------------------------------------------------ API call
    def _post(self, messages: List[Dict], use_tools: bool = True) -> Dict:
        """One completion: Meta Muse Spark first, then the Groq fallbacks (llm.py)."""
        import llm
        vision = any(isinstance(m.get("content"), list) and any(p.get("type") == "image_url" for p in m["content"])
                     for m in messages)
        try:
            res = llm.complete(messages, tools=openai_tool_specs() if use_tools else None, vision=vision, timeout=90)
        except llm.LLMError as e:
            raise MetaAPIError(str(e))
        self.last_label = res["label"]
        return {"choices": [{"message": res["message"]}]}

    # --------------------------------------------------------- main loop
    def _run(self, user_content, ctx: Optional[AthleteContext]) -> str:
        user_msg = {"role": "user", "content": user_content}
        turn: List[Dict] = [user_msg]
        use_tools = ctx is not None and ctx.known

        for _ in range(MAX_TOOL_ROUNDS + 1):
            messages = [{"role": "developer", "content": self._system(ctx)}] + self.history + turn
            data = self._post(messages, use_tools=use_tools)
            choice = (data.get("choices") or [{}])[0]
            msg = choice.get("message") or {}
            tool_calls = msg.get("tool_calls") or []

            if not tool_calls:
                answer = (msg.get("content") or "").strip() or "Sorry, I couldn't come up with an answer. Please rephrase."
                turn.append({"role": "assistant", "content": answer})
                self._remember(turn)
                return answer

            # The full assistant message (with tool_calls) must be replayed, then one tool message per call
            turn.append({"role": "assistant", "content": msg.get("content") or None, "tool_calls": tool_calls})
            for call in tool_calls:
                fn = call.get("function", {})
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                result = run_tool(fn.get("name", ""), args, ctx) if use_tools else {"error": "No athlete logged in"}
                logger.info("tool %s(%s) -> %s", fn.get("name"), args, str(result)[:200])
                turn.append({"role": "tool", "tool_call_id": call.get("id"),
                             "content": json.dumps(result, default=str)[:12000]})

        answer = "I looked up your data but couldn't finish the answer. Please ask again."
        turn.append({"role": "assistant", "content": answer})
        self._remember(turn)
        return answer

    def _system(self, ctx: Optional[AthleteContext]) -> str:
        if ctx is not None and ctx.known:
            who = f"\n\nThe logged-in athlete is {ctx._user.get('name', 'the athlete')}. Use the tools for their data."
        else:
            who = "\n\nNo athlete is logged in, so personal data tools are unavailable; answer generally."
        return SYSTEM_PROMPT + who + f"\nToday's date: {time.strftime('%Y-%m-%d')}."

    def _remember(self, turn: List[Dict]) -> None:
        # Images are not kept in history (large); keep a text placeholder instead
        first = dict(turn[0])
        if isinstance(first.get("content"), list):
            text = " ".join(p.get("text", "") for p in first["content"] if p.get("type") == "text")
            first["content"] = (text + " [image attached]").strip()
        self.history.extend([first] + turn[1:])
        # trim whole turns (never split an assistant tool_calls message from its tool results)
        starts = [i for i, m in enumerate(self.history) if m["role"] == "user"]
        if len(starts) > MAX_HISTORY_TURNS:
            self.history = self.history[starts[-MAX_HISTORY_TURNS]:]

    # ------------------------------------------------------- public API
    def send_message(self, message: str, ctx: Optional[AthleteContext] = None) -> str:
        try:
            return self._run(message, ctx)
        except MetaAPIError as e:
            logger.error("Meta API error: %s", e)
            return self._friendly_error(str(e))

    def send_message_with_image(self, message: str, image_data: bytes,
                                ctx: Optional[AthleteContext] = None) -> str:
        try:
            data_url = self._image_to_data_url(image_data)
        except Exception:
            return "I couldn't read that image. Please upload a JPG, PNG or WEBP photo."
        content = [
            {"type": "text", "text": message or "What do you see in this image? Give fitness/technique feedback if relevant."},
            {"type": "image_url", "image_url": {"url": data_url}},
        ]
        try:
            return self._run(content, ctx)
        except MetaAPIError as e:
            logger.error("Meta API image error: %s", e)
            return self._friendly_error(str(e))

    def analyze_file(self, message: str, file_path: str, ctx: Optional[AthleteContext] = None) -> str:
        with open(file_path, "rb") as f:
            data = f.read()
        if len(data) > 5 * 1024 * 1024:
            return "The file is too large. Please upload files smaller than 5 MB."
        if file_path.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")):
            return self.send_message_with_image(message, data, ctx)
        text = data.decode("utf-8", errors="ignore")
        if len(text) > 15000:
            text = text[:15000] + "\n\n[Content truncated...]"
        return self.send_message(f"{message}\n\nFile content:\n```\n{text}\n```", ctx)

    def reset_chat(self) -> bool:
        self.history = []
        return True

    # ------------------------------------------------------------ utils
    @staticmethod
    def _image_to_data_url(image_data: bytes) -> str:
        from PIL import Image, ImageOps
        img = ImageOps.exif_transpose(Image.open(io.BytesIO(image_data))).convert("RGB")
        img.thumbnail((1280, 1280))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()

    @staticmethod
    def _friendly_error(err: str) -> str:
        import llm
        e = err.lower()
        if "no ai key" in e:
            return ("The AI Coach has no API key yet. Put your Meta Model API key in the .env file as MODEL_API_KEY=... "
                    "(or in the host's environment settings) and restart.")
        if (llm.groq_key() or llm.gemini_key()) and ("groq" in e or "gemini" in e):
            return "The AI Coach is busy right now - all AI services are unavailable for a moment. Please try again in a minute."
        if "401" in e or "unauthorized" in e or "invalid api key" in e:
            return "The AI Coach isn't configured correctly (API key rejected). Please check MODEL_API_KEY."
        if "402" in e or "billing" in e:
            return ("The AI Coach is set up, but the Meta Model API account has no billing / credits for this key. "
                    "Check the credits and the key's project in the Meta developer console.")
        if "403" in e:
            return "The AI Coach doesn't have access to this model. Please check the Meta Model API account."
        if "404" in e:
            return ("The Meta Model API doesn't know this model name. Check META_MODEL in .env "
                    "(for example META_MODEL=muse-spark-1.3) and restart.")
        if "http 400" in e:
            return "The Meta Model API refused the request: " + err.split("HTTP 400", 1)[-1].strip()[:160]
        if "429" in e:
            return "The AI Coach is getting a lot of requests right now. Please try again in a few seconds."
        if "could not reach" in e:
            return "I can't reach the AI service right now. Please check the internet connection and try again."
        return "Sorry, something went wrong while answering. Please try again."
