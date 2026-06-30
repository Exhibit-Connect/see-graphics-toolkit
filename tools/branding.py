#!/usr/bin/env python3
"""
Shared SEE branding for every generated document.

Single source for the logo + contact line + brand red, so the client spec
sheet, the artwork check report, and the proof all carry IDENTICAL branding.
Swap assets/see_logo.png (e.g. for Marc's official file) and every output
that uses this module updates at once.
"""
import os, glob, base64, functools

RED = "#ED1C24"
CONTACT = ("Southeast Exhibits &amp; Events &nbsp;·&nbsp; Orlando | Las Vegas | Atlanta | NJ/NY | Dallas "
           "&nbsp;·&nbsp; SouthEastExhibit.com")


@functools.lru_cache(maxsize=1)
def logo_data_uri():
    """The SEE logo PNG as a data: URI, or '' if not found (callers fall back
    to a text wordmark). Looks in assets/ next to tools/, the repo root, and
    cwd, so it works regardless of where a tool is run."""
    here = os.path.dirname(os.path.abspath(__file__))
    seen = []
    for d in (os.path.join(here, "..", "assets"), os.path.join(os.getcwd(), "assets"),
              here, os.path.join(here, ".."), os.getcwd()):
        seen += sorted(glob.glob(os.path.join(d, "see_logo.png")))
        seen += sorted(glob.glob(os.path.join(d, "*[Ll]ogo*.png")))
    for p in seen:
        try:
            return "data:image/png;base64," + base64.b64encode(open(p, "rb").read()).decode()
        except OSError:
            continue
    return ""


# CSS for the shared header — inject into a document's <style> alongside header_html().
BRAND_CSS = f"""
  .see-brandhead {{ display:flex; align-items:center; justify-content:space-between; gap:16px; margin:0 0 2px; }}
  .see-logo {{ height:46px; width:auto; display:block; }}
  .see-wordmark {{ font-weight:800; font-size:18px; color:#1a1a1a; }}
  .see-pill {{ background:{RED}; color:#fff; padding:6px 18px; border-radius:18px; font-weight:700; font-size:14px; white-space:nowrap; }}
  .see-contact {{ color:#777; font-size:10.5px; margin:0 0 12px; }}
"""


def header_html(pill_text):
    """A consistent branded header: the SEE logo (or a text wordmark fallback)
    on the left, the document-type pill on the right, then the contact line.
    Pair with BRAND_CSS in the document's <style>."""
    logo = logo_data_uri()
    mark = (f'<img class="see-logo" src="{logo}" alt="Southeast Exhibits & Events">'
            if logo else '<div class="see-wordmark">Southeast Exhibits &amp; Events</div>')
    return (f'<div class="see-brandhead">{mark}<span class="see-pill">{pill_text}</span></div>'
            f'<div class="see-contact">{CONTACT}</div>')
