import os, time, requests
from dotenv import load_dotenv
load_dotenv()
KEY = os.environ["GEMINI_API_KEY"]
BASE = "https://generativelanguage.googleapis.com/v1beta/openai"
H = {"Authorization": "Bearer " + KEY, "Content-Type": "application/json"}

r = requests.get(BASE + "/models", headers=H, timeout=30)
names = [m["id"].replace("models/", "") for m in r.json().get("data", [])]
print("Flash/lite models:", [n for n in names if "flash" in n or "lite" in n])

msgs = [{"role": "system", "content": 'Reply with JSON only: {"ok": true}'},
        {"role": "user", "content": "Health check."}]
tests = {
    "plain":        {},
    "effort_low":   {"reasoning_effort": "low"},
    "effort_none":  {"reasoning_effort": "none"},
    "json_mode":    {"response_format": {"type": "json_object"}},
    "app_settings": {"reasoning_effort": "low", "response_format": {"type": "json_object"},
                     "max_tokens": 8000, "temperature": 0},
}
model = os.environ.get("LLM_MODEL") or "gemini-3.8-flash"
print("Testing", model)
for name, extra in tests.items():
    t = time.time()
    try:
        r = requests.post(BASE + "/chat/completions", headers=H,
                          json={"model": model, "messages": msgs, **extra}, timeout=60)
        print(f"{name:13} {r.status_code} {time.time()-t:5.1f}s  {r.text[:110]!r}")
    except Exception as e:
        print(f"{name:13} ERROR {time.time()-t:5.1f}s  {e}")