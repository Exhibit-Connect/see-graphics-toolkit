#!/usr/bin/env python3
"""
Shared AI client for SEE tools — OpenRouter (company key).

Model + key are configuration, not hard-coded into the tools:
    OPENROUTER_API_KEY   your company key   (required for live calls)
    OPENROUTER_MODEL     default: google/gemini-3.5-flash

Standard library only (urllib) — no pip install needed. Multimodal:
pass image paths and they're sent inline (Gemini Flash reads images),
which is how intake.py shows the model the rendered placement pages.

CLI:
    python3 ai_client.py --check                 # show config + whether the key is set
    python3 ai_client.py --dry-run "prompt" [img...]   # print the exact request (no key needed)
    python3 ai_client.py "prompt" [img...]       # live call (needs the key)
"""
import os, sys, json, base64, urllib.request, urllib.error

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL = os.environ.get("OPENROUTER_MODEL", "google/gemini-3.5-flash")


def _load_key():
    """Key from the env var first, then a local untracked file. The key is NEVER
    written into this script (it ships inside the kit) - keep it in .openrouter_key,
    which is gitignored and excluded from the kit zip."""
    k = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if k:
        return k
    here = os.path.dirname(os.path.abspath(__file__))
    for path in (os.path.join(os.getcwd(), ".openrouter_key"),
                 os.path.join(here, ".openrouter_key"),
                 os.path.join(here, "..", ".openrouter_key"),
                 os.path.expanduser("~/.openrouter_key")):
        try:
            with open(path) as f:
                v = f.read().strip()
            if v:
                return v
        except OSError:
            pass
    return ""


KEY = _load_key()


def available():
    return bool(KEY)


def _content(prompt, image_paths):
    content = [{"type": "text", "text": prompt}]
    for p in image_paths or []:
        ext = (os.path.splitext(p)[1].lstrip(".").lower() or "png").replace("jpg", "jpeg")
        b64 = base64.b64encode(open(p, "rb").read()).decode()
        content.append({"type": "image_url", "image_url": {"url": f"data:image/{ext};base64,{b64}"}})
    return content


def build_payload(prompt, image_paths=None, temperature=0, json_mode=False):
    payload = {"model": MODEL,
               "messages": [{"role": "user", "content": _content(prompt, image_paths)}],
               "temperature": temperature}
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    return payload


def ask(prompt, image_paths=None, temperature=0, json_mode=False, timeout=120):
    """Live call to OpenRouter. Raises if no key or on transport/HTTP error."""
    if not KEY:
        raise RuntimeError("OPENROUTER_API_KEY not set — export it to enable the AI step.")
    body = json.dumps(build_payload(prompt, image_paths, temperature, json_mode)).encode()
    req = urllib.request.Request(OPENROUTER_URL, data=body, headers={
        "Authorization": f"Bearer {KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://www.southeastexhibits.com",
        "X-Title": "SEE Graphics AI"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"OpenRouter HTTP {e.code}: {e.read().decode()[:300]}")
    return data["choices"][0]["message"]["content"]


def ask_json(prompt, image_paths=None, timeout=120):
    """ask() expecting a JSON object back; tolerant of ```json fences."""
    txt = ask(prompt, image_paths, temperature=0, json_mode=True, timeout=timeout)
    s = txt.strip()
    if s.startswith("```"):
        s = s.split("```", 2)[1].lstrip("json").strip() if "```" in s[3:] else s.strip("`")
    return json.loads(s)


def _redacted_payload(prompt, image_paths):
    p = build_payload(prompt, image_paths)
    for part in p["messages"][0]["content"]:
        if part.get("type") == "image_url":
            u = part["image_url"]["url"]
            part["image_url"]["url"] = u[:40] + f"...<{len(u)} bytes base64>"
    return p


def main():
    args = sys.argv[1:]
    if not args or args[0] == "--check":
        print(f"OpenRouter model : {MODEL}")
        print(f"API key set      : {'yes' if KEY else 'NO  (export OPENROUTER_API_KEY)'}")
        print(f"Endpoint         : {OPENROUTER_URL}")
        return
    if args[0] == "--dry-run":
        prompt = args[1] if len(args) > 1 else "(prompt)"
        print(json.dumps(_redacted_payload(prompt, args[2:]), indent=2))
        return
    try:
        print(ask(args[0], args[1:]))
    except Exception as e:
        print("AI call failed:", e)


if __name__ == "__main__":
    main()
