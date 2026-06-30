#!/usr/bin/env python3
"""
Shared HTML->PDF rendering via headless Google Chrome.

ONE source for the poll-then-terminate logic every SEE document generator uses
(client spec sheet, artwork check report, proof, job dashboard, client
templates). Some Chrome builds write the PDF but never exit, so we poll for the
output file and then ALWAYS terminate Chrome — the call can't hang. Mac-centric
(uses the Google Chrome app bundle); returns False if Chrome isn't installed so
callers fall back to "open the HTML and Print -> Save as PDF".
"""
import os, subprocess, tempfile, shutil, time

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def html_to_pdf(html_path, pdf_path):
    """Render html_path -> pdf_path with headless Chrome. Returns True if a
    non-trivial PDF was produced. Never hangs (polls, then always terminates)."""
    if not os.path.exists(CHROME):
        return False
    try:
        os.remove(pdf_path)
    except OSError:
        pass
    prof = tempfile.mkdtemp(prefix="see_chrome_")
    proc = subprocess.Popen([CHROME, "--headless=new", "--disable-gpu", "--no-sandbox",
                             "--no-pdf-header-footer", "--virtual-time-budget=2000",
                             f"--user-data-dir={prof}", f"--print-to-pdf={pdf_path}", f"file://{html_path}"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    ok = False
    for _ in range(40):  # up to ~20s
        time.sleep(0.5)
        if os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 1500:
            ok = True
            break
        if proc.poll() is not None:
            break
    try:
        proc.terminate(); proc.wait(timeout=3)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass
    shutil.rmtree(prof, ignore_errors=True)
    return ok or (os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 1500)
