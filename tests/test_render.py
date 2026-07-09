"""Tests for the shared HTML->PDF helper in tools/render.py.

It shells out to headless Chrome; the P0-16 hardening made the run-and-verify
logic injectable (`runner=`), so the success/failure paths are covered here
with fake processes — no Chrome is ever launched:
- file:// URLs are absolute and percent-encoded ('#' in a client filename used
  to make Chrome print its ERROR PAGE, which then shipped as the report),
- success requires exit 0 + a real file (or a size-stable file from a
  never-exiting Chrome) AND structural completeness (PDF %%EOF / PNG IEND),
- a PDF that is Chrome's own error page is rejected (tests/data/
  chrome_error_page.pdf is a copy of the corrupted docs/ PDF this repo shipped),
- missing Chrome still returns False gracefully so callers fall back.
"""
import os
import sys

import pytest

import render

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

PDF_OK = b"%PDF-1.4\n" + b"0" * 2000 + b"\n%%EOF\n"
PDF_TRUNCATED = b"%PDF-1.4\n" + b"0" * 2000          # no %%EOF
PNG_OK = b"\x89PNG\r\n\x1a\n" + b"0" * 2000 + b"\x00\x00\x00\x00IEND\xaeB\x60\x82"


class FakeProc:
    """A stand-in Chrome process: poll() reports `rc` (None = never exits)."""
    def __init__(self, rc, stderr=b"fake chrome stderr"):
        self._rc = rc
        self._stderr = stderr
        self.returncode = None

    def poll(self):
        self.returncode = self._rc
        return self._rc

    def terminate(self):
        pass

    def kill(self):
        pass

    def communicate(self, timeout=None):
        return None, None                       # stderr is a temp FILE, not a pipe


def make_runner(payload, rc=0, captured=None, stderr_payload=b"fake chrome stderr"):
    """Fake subprocess.Popen: writes `payload` (or nothing when None) to the
    --print-to-pdf/--screenshot target, returns a FakeProc exiting with rc.

    P0-16: _run_chrome must hand the runner a real writable FILE for stderr —
    never subprocess.PIPE (a pipe was drained only after the poll loop, so
    Chrome blocked once it wrote past the ~64KB buffer). The fake asserts
    that and writes `stderr_payload` there, like Chrome would."""
    def runner(args, stdout=None, stderr=None):
        if captured is not None:
            captured["args"] = list(args)
        assert hasattr(stderr, "write") and hasattr(stderr, "fileno"), \
            "stderr must be a real (temp) file, not subprocess.PIPE"
        stderr.write(stderr_payload)
        stderr.flush()
        out = next(a.split("=", 1)[1] for a in args
                   if a.startswith(("--print-to-pdf=", "--screenshot=")))
        if payload is not None:
            with open(out, "wb") as f:
                f.write(payload)
        return FakeProc(rc)
    return runner


def _html(tmp_path, name="x.html"):
    p = tmp_path / name
    p.write_text("<p>hi</p>")
    return str(p)


def test_html_to_pdf_is_callable():
    assert callable(render.html_to_pdf)


def test_missing_chrome_returns_false(monkeypatch, tmp_path):
    # resolve to a path that doesn't exist -> graceful False, no exception
    monkeypatch.setenv("SEE_CHROME", str(tmp_path / "no_such_chrome"))
    html = tmp_path / "x.html"
    html.write_text("<p>hi</p>")
    assert render.html_to_pdf(str(html), str(tmp_path / "x.pdf")) is False


def test_proofer_render_pdf_is_the_shared_helper():
    # make_proof.py and the proofer CLI call proofer.render_pdf — keep it wired
    import proofer
    assert proofer.render_pdf is render.html_to_pdf


def test_svg_px_size_prefers_width_height_attrs():
    svg = '<svg width="1290" height="555" viewBox="0 0 1290 555">'
    assert render.svg_px_size_from_text(svg) == (1290, 555)


def test_svg_px_size_falls_back_to_viewbox():
    # no width/height attrs -> use the viewBox's w/h (this is the wide-booth case
    # that qlmanage cropped: a 1290x555 layout must NOT be treated as square)
    svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1290 555">'
    assert render.svg_px_size_from_text(svg) == (1290, 555)


def test_svg_px_size_default_when_unknown():
    assert render.svg_px_size_from_text("<svg>no size here</svg>", default=(800, 600)) == (800, 600)


# ---- P0-16: correct file:// URLs, verified success, error-page rejection ----

def test_file_uri_is_absolute_and_percent_encodes_hash(tmp_path):
    p = tmp_path / "art #2 at 50%.html"
    p.write_text("<p>x</p>")
    uri = render.file_uri(str(p))
    assert uri.startswith("file:///")               # absolute
    assert "%23" in uri and "#" not in uri          # '#' never reaches Chrome raw
    assert "%25" in uri                             # '%' encoded too


def test_html_to_pdf_passes_encoded_url_to_chrome(tmp_path, monkeypatch):
    monkeypatch.setenv("SEE_CHROME", sys.executable)
    captured = {}
    out = tmp_path / "o.pdf"
    ok = render.html_to_pdf(str(tmp_path / "art #2.html"), str(out),
                            runner=make_runner(PDF_OK, rc=0, captured=captured))
    assert ok is True
    assert "%23" in captured["args"][-1]            # the URL Chrome gets is encoded


def test_success_when_output_appears_and_process_exits_zero(tmp_path, monkeypatch):
    monkeypatch.setenv("SEE_CHROME", sys.executable)
    out = tmp_path / "o.pdf"
    assert render.html_to_pdf(_html(tmp_path), str(out),
                              runner=make_runner(PDF_OK, rc=0)) is True


def test_failure_when_process_exits_nonzero_without_valid_file(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SEE_CHROME", sys.executable)
    out = tmp_path / "o.pdf"
    assert render.html_to_pdf(_html(tmp_path), str(out),
                              runner=make_runner(None, rc=1)) is False
    err = capsys.readouterr().err
    assert "returncode=1" in err                    # one-line diagnostic
    assert "fake chrome stderr" in err              # stderr tail surfaced


def test_truncated_pdf_without_eof_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("SEE_CHROME", sys.executable)
    out = tmp_path / "o.pdf"
    assert render.html_to_pdf(_html(tmp_path), str(out),
                              runner=make_runner(PDF_TRUNCATED, rc=0)) is False


def test_chrome_error_page_pdf_is_rejected(tmp_path, monkeypatch):
    # the fixture is a copy of the corrupted docs/ PDF this repo actually shipped:
    # Chrome's ERR_INVALID_URL page printed to PDF (structurally a valid PDF)
    payload = open(os.path.join(DATA, "chrome_error_page.pdf"), "rb").read()
    assert render.looks_like_chrome_error_page(os.path.join(DATA, "chrome_error_page.pdf")) is True
    monkeypatch.setenv("SEE_CHROME", sys.executable)
    out = tmp_path / "o.pdf"
    assert render.html_to_pdf(_html(tmp_path), str(out),
                              runner=make_runner(payload, rc=0)) is False


def test_never_exiting_chrome_with_stable_output_succeeds(tmp_path, monkeypatch):
    monkeypatch.setenv("SEE_CHROME", sys.executable)
    monkeypatch.setenv("SEE_RENDER_TIMEOUT", "5")
    out = tmp_path / "o.pdf"
    # rc=None -> poll() never reports an exit; the file is present and stable
    assert render.html_to_pdf(_html(tmp_path), str(out),
                              runner=make_runner(PDF_OK, rc=None)) is True


def test_never_exiting_chrome_without_output_times_out_false(tmp_path, monkeypatch):
    monkeypatch.setenv("SEE_CHROME", sys.executable)
    monkeypatch.setenv("SEE_RENDER_TIMEOUT", "1")   # env-overridable timeout
    out = tmp_path / "o.pdf"
    assert render.html_to_pdf(_html(tmp_path), str(out),
                              runner=make_runner(None, rc=None)) is False


def test_svg_to_png_verifies_iend(tmp_path, monkeypatch):
    monkeypatch.setenv("SEE_CHROME", sys.executable)
    svg = tmp_path / "a.svg"
    svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="100" height="50"></svg>')
    assert render.svg_to_png(str(svg), str(tmp_path / "a.png"),
                             runner=make_runner(PNG_OK, rc=0)) is True
    assert render.svg_to_png(str(svg), str(tmp_path / "b.png"),
                             runner=make_runner(PNG_OK[:-4], rc=0)) is False  # truncated


def test_completeness_predicates():
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
        f.write(PDF_OK); f.flush()
        assert render.pdf_complete(f.name) is True
    with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
        f.write(PDF_TRUNCATED); f.flush()
        assert render.pdf_complete(f.name) is False
    with tempfile.NamedTemporaryFile(suffix=".png") as f:
        f.write(PNG_OK); f.flush()
        assert render.png_complete(f.name) is True


# ---- P2-2: Chrome resolver (SEE_CHROME > mac bundles > PATH), cached ----

def test_find_chrome_env_var_wins_over_everything(monkeypatch, tmp_path):
    monkeypatch.setenv("SEE_CHROME", "/opt/custom/chrome")
    monkeypatch.setattr(render, "CHROME", sys.executable)   # would otherwise win
    assert render.find_chrome() == "/opt/custom/chrome"


def test_find_chrome_falls_back_to_existing_mac_bundle_alias(monkeypatch):
    monkeypatch.delenv("SEE_CHROME", raising=False)
    monkeypatch.setattr(render, "CHROME", sys.executable)   # "the app bundle" exists
    assert render.find_chrome() == sys.executable


def test_find_chrome_path_lookup_is_cached_and_refreshable(monkeypatch, tmp_path):
    monkeypatch.delenv("SEE_CHROME", raising=False)
    monkeypatch.setattr(render, "CHROME", str(tmp_path / "no_bundle"))
    calls = []

    def fake_which(name):
        calls.append(name)
        return "/usr/bin/chromium" if name == "chromium" else None

    monkeypatch.setattr(render.shutil, "which", fake_which)
    monkeypatch.setattr(render, "_path_chrome", render._UNRESOLVED)
    assert render.find_chrome() == "/usr/bin/chromium"
    n = len(calls)
    assert render.find_chrome() == "/usr/bin/chromium"
    assert len(calls) == n                       # cached: which not re-run
    monkeypatch.setattr(render.shutil, "which", lambda name: None)
    assert render.find_chrome(refresh=True) is None   # re-resolvable


def test_find_chrome_none_when_nothing_installed(monkeypatch, tmp_path):
    monkeypatch.delenv("SEE_CHROME", raising=False)
    monkeypatch.setattr(render, "CHROME", str(tmp_path / "no_bundle"))
    monkeypatch.setattr(render.shutil, "which", lambda name: None)
    monkeypatch.setattr(render, "_path_chrome", render._UNRESOLVED)
    assert render.find_chrome() is None
    assert render.chrome_available() is False


def test_chrome_available_requires_resolved_path_to_exist(monkeypatch, tmp_path):
    monkeypatch.setenv("SEE_CHROME", str(tmp_path / "ghost-chrome"))
    assert render.find_chrome() == str(tmp_path / "ghost-chrome")
    assert render.chrome_available() is False
    monkeypatch.setenv("SEE_CHROME", sys.executable)
    assert render.chrome_available() is True


@pytest.mark.skipif(not os.path.exists("/bin/false"), reason="no /bin/false")
def test_see_chrome_bin_false_resolves_and_fails_cleanly(monkeypatch, tmp_path):
    # a real (non-fake-runner) subprocess run: /bin/false exits 1 immediately,
    # so the render must return False with a diagnostic - never hang or raise
    monkeypatch.setenv("SEE_CHROME", "/bin/false")
    monkeypatch.setenv("SEE_RENDER_TIMEOUT", "10")
    assert render.find_chrome() == "/bin/false"
    assert render.html_to_pdf(_html(tmp_path), str(tmp_path / "o.pdf")) is False


# ---- tier-2 smoke (CI job with a real chromium; skipped when absent) ----

@pytest.mark.external
def test_real_chrome_renders_a_pdf_pypdf_can_open(monkeypatch, tmp_path):
    monkeypatch.delenv("SEE_CHROME", raising=False)      # opt out of the no-Chrome pin
    chrome = render.find_chrome(refresh=True)
    if not chrome or not os.path.exists(chrome):
        pytest.skip("no Chrome/Chromium installed on this machine")
    html = tmp_path / "smoke.html"
    html.write_text("<html><body><h1>SEE render smoke test</h1></body></html>")
    out = tmp_path / "smoke.pdf"
    assert render.html_to_pdf(str(html), str(out)) is True
    from pypdf import PdfReader
    assert len(PdfReader(str(out)).pages) == 1


def test_svg_px_size_reads_the_root_tag_only():
    # P3-6: a root width="100%" plus a numeric width on an INNER element used
    # to size the canvas from the inner element; the root viewBox must win.
    svg = ('<svg width="100%" height="100%" viewBox="0 0 1290 555" '
           'xmlns="http://www.w3.org/2000/svg">'
           '<rect width="400" height="300" fill="#fff"/></svg>')
    assert render.svg_px_size_from_text(svg) == (1290, 555)


# ---- P0-16: >64KB of Chrome stderr must never deadlock the render ----

def test_huge_stderr_success_no_deadlock(tmp_path, monkeypatch):
    # a runner that floods stderr past the old ~64KB pipe buffer still
    # succeeds (stderr lands in a temp file with no backpressure)
    import time as _time
    monkeypatch.setenv("SEE_CHROME", sys.executable)
    out = tmp_path / "o.pdf"
    t0 = _time.monotonic()
    ok = render.html_to_pdf(_html(tmp_path), str(out),
                            runner=make_runner(PDF_OK, rc=0,
                                               stderr_payload=b"e" * 262144))
    assert ok is True
    assert _time.monotonic() - t0 < 10


def test_huge_stderr_failure_surfaces_the_tail(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SEE_CHROME", sys.executable)
    out = tmp_path / "o.pdf"
    payload = b"n" * 262144 + b"THE-REAL-ERROR-AT-THE-END"
    ok = render.html_to_pdf(_html(tmp_path), str(out),
                            runner=make_runner(None, rc=1, stderr_payload=payload))
    assert ok is False
    err = capsys.readouterr().err
    assert "returncode=1" in err
    assert "THE-REAL-ERROR-AT-THE-END" in err          # tail, not the flood


def test_real_subprocess_flooding_stderr_finishes_promptly(tmp_path, monkeypatch):
    # end-to-end with a REAL child process: it writes 200KB to stderr, then
    # the output PDF, then exits 0. With the old stderr=PIPE the child blocked
    # at ~64KB and the render stalled to the timeout; now it must return True
    # well inside the generous 60s budget.
    import time as _time
    monkeypatch.setenv("SEE_RENDER_TIMEOUT", "60")
    out = tmp_path / "o.pdf"
    code = ("import sys; sys.stderr.write('e' * 200000); sys.stderr.flush(); "
            "open(sys.argv[1], 'wb').write(b'%PDF-1.4\\n' + b'0' * 2000 + b'\\n%%EOF\\n')")
    t0 = _time.monotonic()
    ok = render._run_chrome([sys.executable, "-c", code, str(out)],
                            str(out), render._pdf_ok)
    assert ok is True
    assert _time.monotonic() - t0 < 20
