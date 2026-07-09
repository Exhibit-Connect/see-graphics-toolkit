#!/usr/bin/env python3
"""
Shared AI client for SEE tools — OpenRouter (company key).

Model + key are configuration, not hard-coded into the tools:
    OPENROUTER_API_KEY   your company key   (required for live calls)
    OPENROUTER_MODEL     default: anthropic/claude-opus-4.8

Standard library only (urllib) — no pip install needed. Multimodal:
pass image paths and they're sent inline (the model reads the images),
which is how intake.py shows the model the rendered placement pages.

Key lookup (in order): the env var, a .openrouter_key file next to this
script, at the repo root, or in your home directory. A .openrouter_key in
the CURRENT directory is deliberately IGNORED (with a notice) — a key file
planted inside an untrusted extracted job folder must not silently reroute
all AI traffic. Requests are sent with provider data_collection: deny.

CLI:
    python3 ai_client.py --check                 # show config + whether the key is set
    python3 ai_client.py --dry-run "prompt" [img...]   # print the exact request (no key needed)
    python3 ai_client.py "prompt" [img...]       # live call (needs the key)
Exit codes: 0 ok; 1 the call/dry-run failed; 2 usage error.
"""
import os, sys, json, base64, time, urllib.request, urllib.error

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL = os.environ.get("OPENROUTER_MODEL", "anthropic/claude-opus-4.8")
RETRY_CODES = {429, 500, 502, 503, 529}   # transient - worth another attempt
_MIME = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
         "webp": "image/webp", "gif": "image/gif"}
_cwd_notice_shown = False


def _load_key():
    """(key, source) — env var first, then key files: next to this script, the
    repo root, the home dir. The old FIRST entry — os.getcwd()/.openrouter_key —
    is gone: running intake inside an extracted client hand-off folder that
    happened to contain a planted .openrouter_key silently rerouted every AI
    call. A cwd key file now just earns a one-line stderr notice. Looked up
    lazily on every call (never frozen at import), so tests/env changes work."""
    global _cwd_notice_shown
    k = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if k:
        return k, "environment (OPENROUTER_API_KEY)"
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [os.path.join(here, ".openrouter_key"),
                  os.path.join(here, "..", ".openrouter_key"),
                  os.path.expanduser("~/.openrouter_key")]
    cwd_file = os.path.join(os.getcwd(), ".openrouter_key")
    if (os.path.exists(cwd_file) and not _cwd_notice_shown
            and os.path.abspath(cwd_file) not in {os.path.abspath(c) for c in candidates}):
        print("note: ignoring ./.openrouter_key in the current directory (a key file in a "
              "job folder must not reroute AI traffic) — use OPENROUTER_API_KEY, a key "
              "file in the toolkit, or ~/.openrouter_key", file=sys.stderr)
        _cwd_notice_shown = True
    for path in candidates:
        try:
            with open(path) as f:
                v = f.read().strip()
            if v:
                return v, path
        except OSError:
            pass
    return "", ""


# Deprecated alias: frozen at import for old callers reading ai_client.KEY.
# New code must call available()/ask(), which look the key up lazily.
KEY = _load_key()[0]


def available():
    return bool(_load_key()[0])


def _content(prompt, image_paths):
    content = [{"type": "text", "text": prompt}]
    for p in image_paths or []:
        ext = os.path.splitext(p)[1].lstrip(".").lower() or "png"
        mime = _MIME.get(ext)
        if not mime:
            raise ValueError(f"unsupported image type '.{ext}' for {p} — "
                             f"use one of: {', '.join(sorted(_MIME))}")
        b64 = base64.b64encode(open(p, "rb").read()).decode()
        content.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}})
    return content


def build_payload(prompt, image_paths=None, temperature=0, json_mode=False):
    payload = {"model": MODEL,
               "messages": [{"role": "user", "content": _content(prompt, image_paths)}],
               "temperature": temperature,
               # client artwork/hand-offs must not become training data
               "provider": {"data_collection": "deny"}}
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    return payload


def _extract_content(data):
    """The assistant text from a chat-completions body, or a RuntimeError that
    names what actually came back (OpenRouter returns 200 with an {'error':...}
    body for many failures; a bare KeyError helped nobody)."""
    if isinstance(data, dict) and data.get("error"):
        raise RuntimeError(f"OpenRouter returned an error: "
                           f"{json.dumps(data['error'])[:300]}")
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        content = None
    if not isinstance(content, str):
        raise RuntimeError("unexpected OpenRouter response shape (no message content): "
                           + json.dumps(data)[:300])
    return content


def _retry_delay(e, attempt):
    """Seconds to wait before the next attempt, honoring Retry-After."""
    ra = None
    headers = getattr(e, "headers", None)
    if headers:
        ra = headers.get("Retry-After")
    try:
        return max(0.0, float(ra))
    except (TypeError, ValueError):
        return float(2 ** attempt)


def ask(prompt, image_paths=None, temperature=0, json_mode=False, timeout=120,
        opener=None, attempts=3):
    """Live call to OpenRouter. Raises RuntimeError if no key, on transport/HTTP
    errors (after up to `attempts` tries for transient 429/5xx/URLError/timeout),
    or when the 200 body carries an error / no content. `opener` is injectable
    for tests (defaults to urllib.request.urlopen) — the test suite never
    performs live network I/O."""
    key, _src = _load_key()
    if not key:
        raise RuntimeError("OPENROUTER_API_KEY not set — export it to enable the AI step.")
    opener = opener or urllib.request.urlopen
    body = json.dumps(build_payload(prompt, image_paths, temperature, json_mode)).encode()
    req = urllib.request.Request(OPENROUTER_URL, data=body, headers={
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://www.southeastexhibits.com",
        "X-Title": "SEE Graphics AI"})
    last_err = None
    for attempt in range(attempts):
        try:
            with opener(req, timeout=timeout) as r:
                data = json.loads(r.read().decode(errors="replace"))
            return _extract_content(data)
        except urllib.error.HTTPError as e:
            try:
                body_txt = e.read().decode(errors="replace")
            except Exception:
                body_txt = ""
            last_err = RuntimeError(f"OpenRouter HTTP {e.code}: {body_txt[:300]}")
            if e.code not in RETRY_CODES or attempt == attempts - 1:
                raise last_err
            time.sleep(_retry_delay(e, attempt))
        except (urllib.error.URLError, TimeoutError) as e:
            last_err = RuntimeError(f"OpenRouter unreachable: {e}")
            if attempt == attempts - 1:
                raise last_err
            time.sleep(float(2 ** attempt))
    raise last_err  # unreachable, kept for safety


def strip_fences(txt):
    """Remove a Markdown code fence AROUND a payload, line-based: drop the whole
    first fence line whatever its tag (```json, ```JSON, ...), strip only a
    trailing whole-line fence. A ``` embedded INSIDE the payload is untouched,
    and an unterminated fence still yields the body (the old split-based logic
    broke on all three). Pure."""
    s = txt.strip()
    if not s.startswith("```"):
        return s
    lines = s.splitlines()[1:]              # the entire ```<tag> line goes
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def ask_json(prompt, image_paths=None, timeout=120, opener=None):
    """ask() expecting a JSON object back; tolerant of ``` fences."""
    txt = ask(prompt, image_paths, temperature=0, json_mode=True, timeout=timeout,
              opener=opener)
    return json.loads(strip_fences(txt))


def _redacted_payload(prompt, image_paths, temperature=0, json_mode=False):
    """The EXACT request (incl. response_format when json_mode is set — the
    dry-run used to omit it, so the documented 'exact request' wasn't), with
    image bytes redacted to a length note."""
    p = build_payload(prompt, image_paths, temperature, json_mode)
    for part in p["messages"][0]["content"]:
        if part.get("type") == "image_url":
            u = part["image_url"]["url"]
            part["image_url"]["url"] = u[:40] + f"...<{len(u)} bytes base64>"
    return p


def main():
    args = sys.argv[1:]
    if not args or args[0] == "--check":
        key, src = _load_key()
        print(f"OpenRouter model : {MODEL}")
        print(f"API key set      : {'yes' if key else 'NO  (export OPENROUTER_API_KEY)'}")
        if key:
            print(f"Key source       : {src}")
        print(f"Endpoint         : {OPENROUTER_URL}")
        return
    if args[0] == "--dry-run":
        prompt = args[1] if len(args) > 1 else "(prompt)"
        try:
            # mirrors the CLI live call (json_mode=False); intake's dry-run
            # passes json_mode=True to mirror ITS live ask_json call
            print(json.dumps(_redacted_payload(prompt, args[2:]), indent=2))
        except (OSError, ValueError) as e:
            print(f"dry-run failed: {e}", file=sys.stderr)
            sys.exit(1)
        return
    if args[0].startswith("--"):
        print(f"unknown option {args[0]}\n"
              f"usage: ai_client.py [--check | --dry-run] \"prompt\" [image ...]",
              file=sys.stderr)
        sys.exit(2)
    try:
        print(ask(args[0], args[1:]))
    except Exception as e:
        print(f"AI call failed: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
