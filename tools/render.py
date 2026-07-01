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
import os, re, subprocess, tempfile, shutil, time

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


def svg_px_size_from_text(svg_text, default=(1600, 900)):
    """(width, height) in px for an SVG — from its width/height attrs, else its
    viewBox's w/h, else `default`. Pure: this is the testable core of sizing the
    PNG canvas to the SVG's OWN aspect ratio (so wide layouts aren't cropped)."""
    mw = re.search(r'\bwidth="(\d+(?:\.\d+)?)(?:px)?"', svg_text)
    mh = re.search(r'\bheight="(\d+(?:\.\d+)?)(?:px)?"', svg_text)
    if mw and mh:
        return max(1, round(float(mw.group(1)))), max(1, round(float(mh.group(1))))
    vb = re.search(r'viewBox="\s*[-\d.]+\s+[-\d.]+\s+([\d.]+)\s+([\d.]+)', svg_text)
    if vb:
        return max(1, round(float(vb.group(1)))), max(1, round(float(vb.group(2))))
    return default


def svg_to_png(svg_path, png_path, scale=2):
    """Rasterize an SVG to PNG via headless Chrome, sized to the SVG's OWN
    aspect ratio (qlmanage force-fits a square canvas and crops wide art). `scale`
    is the device pixel ratio for crispness. Returns True on success, False if
    Chrome is unavailable (callers can fall back). Poll-then-terminate, can't hang."""
    if not os.path.exists(CHROME):
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
    proc = subprocess.Popen([CHROME, "--headless=new", "--disable-gpu", "--no-sandbox",
                             "--hide-scrollbars", f"--force-device-scale-factor={scale}",
                             f"--window-size={w},{h}", f"--user-data-dir={prof}",
                             f"--screenshot={png_path}", f"file://{os.path.abspath(svg_path)}"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    ok = False
    for _ in range(40):  # up to ~20s
        time.sleep(0.5)
        if os.path.exists(png_path) and os.path.getsize(png_path) > 1500:
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
    return ok or (os.path.exists(png_path) and os.path.getsize(png_path) > 1500)
