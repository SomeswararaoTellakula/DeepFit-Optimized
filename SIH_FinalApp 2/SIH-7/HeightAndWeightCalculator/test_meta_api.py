"""
Quick check that the Meta Model API key works and that tool calling works.

    python test_meta_api.py
"""
import json
import os

import requests

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

key = os.environ.get("MODEL_API_KEY") or os.environ.get("META_API_KEY")
model = os.environ.get("META_MODEL", "muse-spark-1.3")
base = os.environ.get("META_API_BASE", "https://api.meta.ai/v1")
if not key:
    raise SystemExit("MODEL_API_KEY is not set in .env")

h = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}

print(f"1) Plain chat with {model} ...")
r = requests.post(f"{base}/chat/completions", headers=h, timeout=90, json={
    "model": model, "messages": [{"role": "user", "content": "Reply with one short sentence: what is a sit-up?"}]})
print("   HTTP", r.status_code)
if r.status_code != 200:
    raise SystemExit("   " + r.text[:500])
print("   ->", r.json()["choices"][0]["message"]["content"])

print("2) Tool calling ...")
tools = [{"type": "function", "function": {
    "name": "get_my_progress_summary", "description": "Get the athlete's progress.",
    "parameters": {"type": "object", "properties": {}, "required": []}}}]
msgs = [{"role": "user", "content": "How is my progress? Use the tool."}]
r = requests.post(f"{base}/chat/completions", headers=h, timeout=90,
                  json={"model": model, "messages": msgs, "tools": tools, "tool_choice": "auto"})
print("   HTTP", r.status_code)
msg = r.json()["choices"][0]["message"]
calls = msg.get("tool_calls") or []
print("   tool calls:", [c["function"]["name"] for c in calls])
if calls:
    msgs.append({"role": "assistant", "content": msg.get("content"), "tool_calls": calls})
    for c in calls:
        msgs.append({"role": "tool", "tool_call_id": c["id"],
                     "content": json.dumps({"situps": {"best": 24, "latest": 24, "first": 18}})})
    r = requests.post(f"{base}/chat/completions", headers=h, timeout=90,
                      json={"model": model, "messages": msgs, "tools": tools, "tool_choice": "auto"})
    print("   HTTP", r.status_code)
    print("   ->", (r.json()["choices"][0]["message"].get("content") or "")[:300])
print("Done - the AI Coach should work.")
