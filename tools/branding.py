#!/usr/bin/env python3
"""
Shared SEE branding for every generated document.

Single source for the logo + contact line + brand red, so the client spec
sheet, the artwork check report, and the proof all carry IDENTICAL branding.
Swap assets/see_logo.png (e.g. for Marc's official file) and every output
that uses this module updates at once.
"""
import os, base64, functools

# Official SEE brand red, sampled from the 2025 brand sources (SE_2025_Client_Presentation /
# SE_Artwork_Guidelines — the red title pills and headings all render as rgb(227,29,61)).
RED = "#E31D3D"
# Official deck typeface is Helvetica Neue (per the embedded fonts in the 2025 brand PDFs);
# fall back cleanly where it isn't installed.
FONT_STACK = "'Helvetica Neue', Helvetica, Arial, sans-serif"
CONTACT = ("Southeast Exhibits &amp; Events &nbsp;·&nbsp; Orlando | Las Vegas | Atlanta | NJ/NY | Dallas "
           "&nbsp;·&nbsp; SouthEastExhibit.com")


@functools.lru_cache(maxsize=1)
def logo_data_uri():
    """The SEE logo PNG as a data: URI, or '' if not found (callers fall back
    to a text wordmark). Searches ONLY the canonical brand filenames
    (assets/see_logo.png, assets/SEE_logo.png) in the two assets/ locations —
    next to tools/, and under cwd (same rule as brand_page_data_uri). The old
    wildcard `*[Ll]ogo*.png` glob over cwd / the repo root could pick up a
    client's own logo file (e.g. Client_Logo.png in a job folder) and embed
    it as SEE's brand mark on a client-facing document."""
    here = os.path.dirname(os.path.abspath(__file__))
    for d in (os.path.join(here, "..", "assets"), os.path.join(os.getcwd(), "assets")):
        for name in ("see_logo.png", "SEE_logo.png"):
            try:
                with open(os.path.join(d, name), "rb") as f:
                    return "data:image/png;base64," + base64.b64encode(f.read()).decode()
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


@functools.lru_cache(maxsize=None)
def brand_page_data_uri(name):
    """A pre-rendered official SEE brand page (PNG in the local-only assets/brand/
    folder) as a data: URI, or '' when that folder isn't present (e.g. a public-repo
    checkout — the caller then simply omits the page). These pages are rendered from
    SEE's copyright-protected brand sources (the 2025 client-presentation deck and the
    Artwork-Guidelines PDF) and are gitignored, never distributed. `name` is the file
    stem, e.g. 'who_we_are', 'thank_you', 'artwork_guidelines'."""
    here = os.path.dirname(os.path.abspath(__file__))
    for d in (os.path.join(here, "..", "assets", "brand"),
              os.path.join(os.getcwd(), "assets", "brand")):
        p = os.path.join(d, f"{name}.png")
        try:
            return "data:image/png;base64," + base64.b64encode(open(p, "rb").read()).decode()
        except OSError:
            continue
    return ""


def artwork_guidelines_data_uri():
    """SEE's official Artwork Guidelines one-pager as a data: URI (or '' if the brand
    assets aren't present). Thin wrapper over brand_page_data_uri for callers/tests."""
    return brand_page_data_uri("artwork_guidelines")


def header_html(pill_text):
    """A consistent branded header: the SEE logo (or a text wordmark fallback)
    on the left, the document-type pill on the right, then the contact line.
    Pair with BRAND_CSS in the document's <style>."""
    logo = logo_data_uri()
    mark = (f'<img class="see-logo" src="{logo}" alt="Southeast Exhibits & Events">'
            if logo else '<div class="see-wordmark">Southeast Exhibits &amp; Events</div>')
    return (f'<div class="see-brandhead">{mark}<span class="see-pill">{pill_text}</span></div>'
            f'<div class="see-contact">{CONTACT}</div>')
