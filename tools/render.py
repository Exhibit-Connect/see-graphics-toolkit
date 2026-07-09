#!/usr/bin/env python3
"""
Shared HTML->PDF rendering via headless Google Chrome.

ONE source for the run-and-verify logic every SEE document generator uses
(client spec sheet, artwork check report, proof, job dashboard, client
templates). Some Chrome builds write the output but never exit, so we poll for
the output file and then ALWAYS terminate Chrome — the call can't hang.
Success is verified, not assumed: the process must exit 0 with a real output
file (or the file must be present and size-stable while Chrome lingers), the
output must be structurally complete (PDF %%EOF / PNG IEND), and a PDF that is
actually Chrome's own error page ("This site can't be reached" / ERR_*) is
rejected — those used to ship as client-facing documents. Returns False if
Chrome isn't installed so callers fall back to "open the HTML and Print ->
Save as PDF".

The Chrome binary is RESOLVED, not hardcoded (P2-2): $SEE_CHROME wins, then
the macOS Chrome/Chromium app bundles, then a PATH lookup over the common
Linux/CI names — the old single mac path silently downgraded every generator
to "open the HTML" everywhere else. The render timeout is env-overridable via
SEE_RENDER_TIMEOUT (seconds, default 60 — image-heavy proofs can exceed the
old 20s budget).
"""
import os, pathlib, re, subprocess, sys, tempfile, shutil, time

# Compat alias: the historical (and still first-choice) macOS location. Kept
# as a module global because other code monkeypatched/read render.CHROME;
# find_chrome() consults it live, so an override still works.
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
_MAC_BUNDLES = ("/Applications/Chromium.app/Contents/MacOS/Chromium",)
_PATH_NAMES = ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser")
_UNRESOLVED = object()
_path_chrome = _UNRESOLVED          # cached PATH-lookup result
DEFAULT_TIMEOUT_S = 60.0
MIN_BYTES = 1500          # anything smaller is a stub, not a real document


def find_chrome(refresh=False):
    """Resolve the Chrome/Chromium binary to run, or None if there is none.

    Priority: $SEE_CHROME (always wins and is returned as-is, checked fresh on
    every call so tests/one-off runs can redirect or disable it), then the mac
    app-bundle paths (incl. the module CHROME alias), then `shutil.which` over
    the common Linux/CI names. Only the PATH lookup is cached — pass
    refresh=True to re-resolve after installing Chrome."""
    env = os.environ.get("SEE_CHROME")
    if env:
        return env
    for cand in (CHROME,) + _MAC_BUNDLES:
        if cand and os.path.exists(cand):
            return cand
    global _path_chrome
    if refresh or _path_chrome is _UNRESOLVED:
        _path_chrome = None
        for name in _PATH_NAMES:
            hit = shutil.which(name)
            if hit:
                _path_chrome = hit
                break
    return _path_chrome


def chrome_available():
    """True when a runnable Chrome binary resolves AND exists on disk — the
    one presence test callers should use for their fallback messaging
    ('Chrome not installed' vs 'render FAILED')."""
    c = find_chrome()
    return bool(c and os.path.exists(c))


def _timeout_s():
    try:
        return float(os.environ.get("SEE_RENDER_TIMEOUT", "") or DEFAULT_TIMEOUT_S)
    except ValueError:
        return DEFAULT_TIMEOUT_S


def file_uri(path):
    """A correctly percent-encoded, absolute file:// URL for a local path.
    The old f"file://{path}" was neither absolute nor encoded, so a '#' or '%'
    in a client artwork's filename made Chrome print its ERROR PAGE to the
    output — which then shipped as the 'report'."""
    return pathlib.Path(path).resolve().as_uri()


def pdf_complete(path):
    """True if the file ends like a whole PDF (%%EOF within the last 1KB)."""
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            f.seek(max(0, size - 1024))
            return b"%%EOF" in f.read()
    except OSError:
        return False


def png_complete(path):
    """True if the file ends with PNG's IEND chunk (a truncated write doesn't)."""
    try:
        with open(path, "rb") as f:
            f.seek(max(0, os.path.getsize(path) - 12))
            return f.read().endswith(b"IEND\xaeB\x60\x82")
    except OSError:
        return False


def looks_like_chrome_error_page(pdf_path):
    """True if the 'rendered' PDF is actually Chrome's own error page (e.g.
    ERR_INVALID_URL / ERR_FILE_NOT_FOUND printed to PDF). Both corrupted PDFs
    committed under docs/ were exactly this. Needs pypdf; when pypdf is absent
    or the text can't be extracted the check is skipped (returns False)."""
    try:
        from pypdf import PdfReader
        txt = PdfReader(pdf_path).pages[0].extract_text() or ""
    except Exception:
        return False
    return ("ERR_" in txt) or ("This site can" in txt)


def _pdf_ok(path):
    return pdf_complete(path) and not looks_like_chrome_error_page(path)


def _run_chrome(args, out_path, complete_predicate, runner=subprocess.Popen):
    """Run a headless-Chrome command that should produce `out_path`; verify it.

    Success requires EITHER the process to have exited with returncode 0 and a
    real (> MIN_BYTES) output file, OR — for Chrome builds that write the file
    but never exit — the output to exist with a nonzero size that is stable
    across two consecutive 0.5s polls. Either way the output must then pass
    `complete_predicate` (structural completeness / not-an-error-page). The
    process is ALWAYS terminated (can't hang); on failure one line with the
    returncode and the tail of Chrome's stderr goes to stderr. `runner` is
    injectable for tests (no Chrome needed).

    Chrome's stderr goes to an unnamed TEMP FILE, not a pipe (P0-16): the pipe
    was only drained AFTER the poll loop, so once Chrome chattered past the
    ~64KB pipe buffer it blocked on the write and a render that would have
    succeeded sat there until our timeout. A file has no backpressure; its
    tail is read for the failure diagnostic and it is deleted on close."""
    with tempfile.TemporaryFile(prefix="see_chrome_err_") as err_f:
        proc = runner(args, stdout=subprocess.DEVNULL, stderr=err_f)
        deadline = time.monotonic() + _timeout_s()
        ok = False
        prev_size = None
        while True:
            rc = proc.poll()
            if rc is not None:
                ok = (rc == 0 and os.path.exists(out_path)
                      and os.path.getsize(out_path) > MIN_BYTES)
                break
            size = os.path.getsize(out_path) if os.path.exists(out_path) else 0
            if size > 0 and size == prev_size:
                ok = True          # never-exiting Chrome: output present and stable
                break
            prev_size = size if size > 0 else None
            if time.monotonic() >= deadline:
                break
            time.sleep(0.5)

        try:
            proc.terminate()
            try:
                proc.communicate(timeout=3)     # reap only; stderr is the temp file
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.communicate()
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

        stderr_tail = b""
        try:
            end = err_f.seek(0, os.SEEK_END)
            err_f.seek(max(0, end - 500))
            stderr_tail = err_f.read()
        except Exception:
            pass

    if ok and not complete_predicate(out_path):
        ok = False
    if not ok:
        print(f"render: Chrome did not produce a valid {os.path.basename(out_path)} "
              f"(returncode={proc.returncode}): "
              f"{stderr_tail[-500:].decode('utf-8', 'replace').strip()}",
              file=sys.stderr)
    return ok


def html_to_pdf(html_path, pdf_path, runner=subprocess.Popen):
    """Render html_path -> pdf_path with headless Chrome. Returns True only if
    a complete, non-error-page PDF was produced. Never hangs."""
    chrome = find_chrome()
    if not chrome or not os.path.exists(chrome):
        return False
    try:
        os.remove(pdf_path)
    except OSError:
        pass
    prof = tempfile.mkdtemp(prefix="see_chrome_")
    try:
        # --no-sandbox kept deliberately: removal could not be verified on this
        # machine (no Chrome), and CI runners execute Chrome as root where the
        # sandbox refuses to start. The input is our OWN generated HTML (with
        # validated/escaped interpolations - see spec_validate), not the web.
        return _run_chrome([chrome, "--headless=new", "--disable-gpu", "--no-sandbox",
                            "--no-pdf-header-footer", "--virtual-time-budget=2000",
                            f"--user-data-dir={prof}", f"--print-to-pdf={pdf_path}",
                            file_uri(html_path)],
                           pdf_path, _pdf_ok, runner=runner)
    finally:
        shutil.rmtree(prof, ignore_errors=True)


def svg_px_size_from_text(svg_text, default=(1600, 900)):
    """(width, height) in px for an SVG — from the ROOT <svg> tag's
    width/height attrs, else its viewBox's w/h, else `default`. Pure: this is
    the testable core of sizing the PNG canvas to the SVG's OWN aspect ratio
    (so wide layouts aren't cropped). Scoped to the root tag (P3-6): a root
    width="100%" plus any numeric width= on an inner element (e.g. a <rect>)
    used to size the canvas from that inner element."""
    root = re.search(r"<svg\b[^>]*>", svg_text)
    tag = root.group(0) if root else svg_text
    mw = re.search(r'\bwidth="(\d+(?:\.\d+)?)(?:px)?"', tag)
    mh = re.search(r'\bheight="(\d+(?:\.\d+)?)(?:px)?"', tag)
    if mw and mh:
        return max(1, round(float(mw.group(1)))), max(1, round(float(mh.group(1))))
    vb = re.search(r'viewBox="\s*[-\d.]+\s+[-\d.]+\s+([\d.]+)\s+([\d.]+)', tag)
    if vb:
        return max(1, round(float(vb.group(1)))), max(1, round(float(vb.group(2))))
    return default


def svg_to_png(svg_path, png_path, scale=2, runner=subprocess.Popen):
    """Rasterize an SVG to PNG via headless Chrome, sized to the SVG's OWN
    aspect ratio (qlmanage force-fits a square canvas and crops wide art). `scale`
    is the device pixel ratio for crispness. Returns True only on a verified,
    complete PNG; False if Chrome is unavailable (callers can fall back)."""
    chrome = find_chrome()
    if not chrome or not os.path.exists(chrome):
        return False
    try:
        w, h = svg_px_size_from_text(open(svg_path, encoding="utf-8", errors="replace").read(4000))
    except OSError:
        w, h = 1600, 900
    try:
        os.remove(png_path)
    except OSError:
        pass
    prof = tempfile.mkdtemp(prefix="see_chrome_")
    try:
        return _run_chrome([chrome, "--headless=new", "--disable-gpu", "--no-sandbox",
                            "--hide-scrollbars", f"--force-device-scale-factor={scale}",
                            f"--window-size={w},{h}", f"--user-data-dir={prof}",
                            f"--screenshot={png_path}", file_uri(svg_path)],
                           png_path, png_complete, runner=runner)
    finally:
        shutil.rmtree(prof, ignore_errors=True)
