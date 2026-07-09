"""P1-12: ai_client hardening — key lookup without the cwd hazard, defensive
response handling, line-based fence stripping, dry-run parity, retries, exit
codes. NO test performs live network I/O: the opener is always injected, and
an autouse fixture blanks the API key so nothing can go live by accident.
"""
import base64
import io
import json
import os
import sys
import urllib.error

import pytest

import ai_client


@pytest.fixture(autouse=True)
def _no_live_network(monkeypatch, tmp_path):
    """No env key, no real home key file, notice flag reset - and any
    accidental use of the real urlopen would still need a key it can't find."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    # checkout-resident key files (tools/ and repo root, derived from __file__)
    # must be neutralized too - a real key in the checkout is legitimate
    monkeypatch.setattr(ai_client, "__file__", str(tmp_path / "home" / "tools" / "ai_client.py"))
    monkeypatch.setattr(ai_client, "_cwd_notice_shown", False)
    assert ai_client.available() is False


def _home(tmp_path):
    h = tmp_path / "home"
    h.mkdir(exist_ok=True)
    return h


# ---------- key lookup ----------
def test_cwd_key_file_ignored_with_notice(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".openrouter_key").write_text("planted-key")
    key, src = ai_client._load_key()
    assert key == ""                                  # never the planted one
    err = capsys.readouterr().err
    assert "ignoring ./.openrouter_key" in err
    # notice is once-per-process, not spammed
    ai_client._load_key()
    assert "ignoring" not in capsys.readouterr().err


def test_home_key_found_and_source_reported(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (_home(tmp_path) / ".openrouter_key").write_text("home-key\n")
    key, src = ai_client._load_key()
    assert key == "home-key"
    assert src.endswith(".openrouter_key")
    assert ai_client.available() is True              # lazy: sees it post-import


def test_env_var_beats_key_files_and_planted_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".openrouter_key").write_text("planted-key")
    (_home(tmp_path) / ".openrouter_key").write_text("home-key")
    monkeypatch.setenv("OPENROUTER_API_KEY", "env-key")
    key, src = ai_client._load_key()
    assert key == "env-key" and "environment" in src


# ---------- fake openers ----------
class _Resp:
    def __init__(self, body):
        self._body = body if isinstance(body, bytes) else json.dumps(body).encode()

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _ok_body(text="hello"):
    return {"choices": [{"message": {"content": text}}]}


# ---------- response shapes ----------
def test_200_error_body_raises_runtimeerror_naming_it(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    opener = lambda req, timeout=None: _Resp({"error": {"message": "insufficient credits"}})
    with pytest.raises(RuntimeError) as ei:
        ai_client.ask("hi", opener=opener)
    assert "insufficient credits" in str(ei.value)


def test_missing_content_raises_with_body_excerpt(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    opener = lambda req, timeout=None: _Resp({"choices": [{"message": {"content": None}}]})
    with pytest.raises(RuntimeError) as ei:
        ai_client.ask("hi", opener=opener)
    assert "response shape" in str(ei.value) and "choices" in str(ei.value)


def test_no_key_raises(monkeypatch):
    with pytest.raises(RuntimeError) as ei:
        ai_client.ask("hi", opener=lambda *a, **k: _Resp(_ok_body()))
    assert "OPENROUTER_API_KEY" in str(ei.value)


def test_success_returns_content(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    assert ai_client.ask("hi", opener=lambda req, timeout=None: _Resp(_ok_body("out"))) == "out"


# ---------- retries ----------
def test_retry_on_503_then_success(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    sleeps = []
    monkeypatch.setattr(ai_client.time, "sleep", lambda s: sleeps.append(s))
    calls = []

    def opener(req, timeout=None):
        calls.append(1)
        if len(calls) == 1:
            raise urllib.error.HTTPError("u", 503, "unavailable",
                                         {"Retry-After": "7"}, io.BytesIO(b"busy"))
        return _Resp(_ok_body("recovered"))

    assert ai_client.ask("hi", opener=opener) == "recovered"
    assert len(calls) == 2
    assert sleeps == [7.0]                            # honors Retry-After


def test_non_retryable_http_error_raises_immediately(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.setattr(ai_client.time, "sleep", lambda s: (_ for _ in ()).throw(AssertionError))
    calls = []

    def opener(req, timeout=None):
        calls.append(1)
        raise urllib.error.HTTPError("u", 401, "unauthorized", {}, io.BytesIO(b"bad key"))

    with pytest.raises(RuntimeError) as ei:
        ai_client.ask("hi", opener=opener)
    assert len(calls) == 1 and "401" in str(ei.value) and "bad key" in str(ei.value)


def test_persistent_503_raises_after_attempts(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.setattr(ai_client.time, "sleep", lambda s: None)
    calls = []

    def opener(req, timeout=None):
        calls.append(1)
        raise urllib.error.HTTPError("u", 503, "unavailable", {}, io.BytesIO(b""))

    with pytest.raises(RuntimeError):
        ai_client.ask("hi", opener=opener, attempts=3)
    assert len(calls) == 3


def test_urlerror_retried(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.setattr(ai_client.time, "sleep", lambda s: None)
    calls = []

    def opener(req, timeout=None):
        calls.append(1)
        if len(calls) < 2:
            raise urllib.error.URLError("network down")
        return _Resp(_ok_body("back"))

    assert ai_client.ask("hi", opener=opener) == "back"


# ---------- fence stripping ----------
@pytest.mark.parametrize("txt,expect", [
    ('{"a": 1}', {"a": 1}),                                        # plain
    ('```json\n{"a": 1}\n```', {"a": 1}),                          # lowercase tag
    ('```JSON\n{"a": 1}\n```', {"a": 1}),                          # uppercase tag
    ('```\n{"a": "has ``` inside"}\n```', {"a": "has ``` inside"}),  # embedded fence
    ('```json\n{"a": 1}', {"a": 1}),                               # unterminated
])
def test_ask_json_fence_cases(monkeypatch, txt, expect):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    opener = lambda req, timeout=None: _Resp(_ok_body(txt))
    assert ai_client.ask_json("hi", opener=opener) == expect


def test_strip_fences_pure():
    assert ai_client.strip_fences("```JSON\n{}\n```") == "{}"
    assert ai_client.strip_fences("no fences") == "no fences"


# ---------- payload / dry-run parity ----------
def test_redacted_payload_json_mode_carries_response_format_and_no_raw_base64(tmp_path):
    img = tmp_path / "page.png"
    img.write_bytes(b"\x89PNG not really a png but bytes")
    p = ai_client._redacted_payload("prompt", [str(img)], json_mode=True)
    assert p["response_format"] == {"type": "json_object"}          # dry-run parity
    blob = json.dumps(p)
    assert base64.b64encode(img.read_bytes()).decode() not in blob  # redacted
    assert "bytes base64" in blob


def test_build_payload_sends_data_collection_deny():
    p = ai_client.build_payload("x")
    assert p["provider"] == {"data_collection": "deny"}


def test_unsupported_image_type_raises_valueerror(tmp_path):
    bad = tmp_path / "art.tiff"
    bad.write_bytes(b"data")
    with pytest.raises(ValueError) as ei:
        ai_client.build_payload("x", [str(bad)])
    assert ".tiff" in str(ei.value)


# ---------- CLI ----------
def test_cli_failure_exits_1(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["ai_client.py", "a prompt"])
    with pytest.raises(SystemExit) as ei:
        ai_client.main()                                # no key -> ask raises
    assert ei.value.code == 1
    assert "AI call failed" in capsys.readouterr().err


def test_cli_unknown_flag_exits_2(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["ai_client.py", "--frobnicate", "x"])
    with pytest.raises(SystemExit) as ei:
        ai_client.main()
    assert ei.value.code == 2
    assert "usage" in capsys.readouterr().err


def test_cli_dry_run_unreadable_image_exits_1(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["ai_client.py", "--dry-run", "p",
                                      str(tmp_path / "missing.png")])
    with pytest.raises(SystemExit) as ei:
        ai_client.main()
    assert ei.value.code == 1
    assert "dry-run failed" in capsys.readouterr().err


def test_cli_check_reports_key_source(tmp_path, monkeypatch, capsys):
    (_home(tmp_path) / ".openrouter_key").write_text("home-key")
    monkeypatch.setattr(sys, "argv", ["ai_client.py", "--check"])
    ai_client.main()
    out = capsys.readouterr().out
    assert "API key set      : yes" in out
    assert "Key source" in out and ".openrouter_key" in out


# ---------- P3-5: NDA upload gate + sanitized error bodies ----------
def test_upload_allowed_defaults_true_and_honors_env(monkeypatch):
    monkeypatch.delenv(ai_client.UPLOAD_ENV, raising=False)
    assert ai_client.upload_allowed() is True
    for v in ("0", "no", "false", "OFF"):
        monkeypatch.setenv(ai_client.UPLOAD_ENV, v)
        assert ai_client.upload_allowed() is False
    monkeypatch.setenv(ai_client.UPLOAD_ENV, "1")
    assert ai_client.upload_allowed() is True


def test_ask_with_images_refused_when_upload_blocked(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.setenv(ai_client.UPLOAD_ENV, "0")
    img = tmp_path / "page.png"
    img.write_bytes(b"png bytes")
    called = []
    opener = lambda req, timeout=None: called.append(1) or _Resp(_ok_body())
    with pytest.raises(RuntimeError) as ei:
        ai_client.ask("hi", [str(img)], opener=opener)
    assert ai_client.UPLOAD_ENV in str(ei.value)
    assert called == []                                # nothing left the machine
    # a text-only call is NOT gated (no client imagery involved)
    assert ai_client.ask("hi", opener=lambda req, timeout=None: _Resp(_ok_body("t"))) == "t"


def test_http_error_message_is_one_capped_line_full_body_on_stderr(monkeypatch, capsys):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    big_body = ("<html>\n  <body>\n    upstream error   \n" + "x" * 300 + "\n</body></html>").encode()

    def opener(req, timeout=None):
        raise urllib.error.HTTPError("u", 401, "unauthorized", {}, io.BytesIO(big_body))

    with pytest.raises(RuntimeError) as ei:
        ai_client.ask("hi", opener=opener)
    msg = str(ei.value)
    assert "\n" not in msg and len(msg) <= len("OpenRouter HTTP 401: ") + 120
    assert "upstream error" in msg
    err = capsys.readouterr().err
    assert "OpenRouter HTTP 401 response body" in err and "x" * 300 in err
