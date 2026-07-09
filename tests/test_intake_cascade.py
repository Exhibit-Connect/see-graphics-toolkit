"""P2-9: the intake panel-seeding cascade, pinned with fakes.

`intake.seed_panels` (extracted verbatim from main()) decides where a draft
booth's panels come from: extractable TEXT is the reliable floor; a visual
handoff falls back to DETERMINISTIC OCR of the graphic key; the AI vision
result seeds only when OCR recovers nothing; and an unreadable handoff yields
an EMPTY draft — never invented panels. These tests pin that priority order
and the needs_confirm/_source flagging that keeps fallback panels from being
mistaken for verified data.

No test can go live: the autouse fixture blanks the OpenRouter key (the AI
input here is always a canned dict anyway), and the OCR step is an injected
fake everywhere except the tier-2 external smoke test at the bottom.
"""
import pytest

import ai_client
import intake


@pytest.fixture(autouse=True)
def _no_live_network(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    monkeypatch.setenv("HOME", str(tmp_path / "no-home"))
    assert ai_client.available() is False


def _no_ocr(*a, **k):
    raise AssertionError("OCR must not run when the text pass found panels")


AI_LIVE = {"_status": "live",
           "panels": [{"name": "Back Wall", "w": 96.0, "h": 89.5, "dims_shown": True,
                       "finish": "fabric", "sided": "single"},
                      {"name": "Counter Front", "dims_shown": False}]}


# ---------- priority 1: extractable text wins, OCR never called ----------
def test_text_panels_present_source_text_and_ocr_never_called():
    text_panels = [{"name": "Wall A", "w": 48.0, "h": 96.0}]
    panels, source, undim, conflicts, warnings = intake.seed_panels(
        "handoff.pdf", 3, text_panels, AI_LIVE, ocr_text_fn=_no_ocr)
    assert source == "text"
    assert panels == [{"name": "Wall A", "w": 48.0, "h": 96.0,
                       "finish": "TBD", "sided": "single"}]
    assert undim == [] and conflicts == [] and warnings == []
    # text-pass panels are NOT auto-flagged needs_confirm (a human review file
    # still gates them) and never carry a fallback _source tag
    assert "needs_confirm" not in panels[0] and "_source" not in panels[0]


# ---------- priority 2: OCR of the graphic key ----------
def test_empty_text_ocr_panels_source_ocr_all_needs_confirm():
    ocr = lambda src, n, mp: ('Graphic Key\nH1-H2 39.0625"w x 153.8125"h', [])
    panels, source, undim, conflicts, warnings = intake.seed_panels(
        "visual.pdf", 3, [], AI_LIVE, ocr_text_fn=ocr)
    assert source == "ocr"
    assert [p["name"] for p in panels] == ["H1", "H2"]
    assert all(p["needs_confirm"] is True for p in panels)
    assert all("OCR" in p["_source"] for p in panels)
    assert undim == []                      # the AI result was never consulted


def test_ocr_warnings_propagate_alongside_recovered_panels():
    ocr = lambda src, n, mp: ('H1 39"w x 153"h', ["page 2: Ghostscript render failed (rc 1)"])
    panels, source, undim, conflicts, warnings = intake.seed_panels(
        "visual.pdf", 2, [], None, ocr_text_fn=ocr)
    assert source == "ocr" and len(panels) == 1
    assert warnings == ["page 2: Ghostscript render failed (rc 1)"]


# ---------- priority 3: AI vision, flagged and never inventing sizes ----------
def test_empty_ocr_ai_seeds_source_ai_vision():
    ocr = lambda src, n, mp: ("", [])
    panels, source, undim, conflicts, warnings = intake.seed_panels(
        "visual.pdf", 3, [], AI_LIVE, ocr_text_fn=ocr)
    assert source == "ai-vision"
    assert [p["name"] for p in panels] == ["Back Wall"]
    assert panels[0]["needs_confirm"] is True and "AI vision" in panels[0]["_source"]
    # the AI saw Counter Front with NO printed size: listed to measure, not invented
    assert undim == ["Counter Front"]


def test_non_live_ai_payload_never_seeds():
    ocr = lambda src, n, mp: ("", [])
    panels, source, undim, conflicts, warnings = intake.seed_panels(
        "visual.pdf", 3, [], {"_status": "dry-run", "panels": AI_LIVE["panels"]},
        ocr_text_fn=ocr)
    assert source == "text" and panels == []


# ---------- everything empty: an EMPTY draft, not a made-up one ----------
def test_all_sources_empty_yields_empty_draft():
    ocr = lambda src, n, mp: ("", ["tesseract not installed — OCR of the visual handoff skipped"])
    panels, source, undim, conflicts, warnings = intake.seed_panels(
        "visual.pdf", 3, [], None, ocr_text_fn=ocr)
    assert panels == [] and source == "text" and undim == []
    assert warnings and "tesseract" in warnings[0]


# ---------- OCR conflicts are kept, not discarded ----------
def test_ocr_repeated_key_at_two_sizes_surfaces_a_conflict():
    ocr = lambda src, n, mp: ('H1 39"w x 153"h\nH1 40"w x 153"h', [])
    panels, source, undim, conflicts, warnings = intake.seed_panels(
        "visual.pdf", 1, [], None, ocr_text_fn=ocr)
    assert source == "ocr" and len(panels) == 1
    assert conflicts, "the second size for H1 must surface as a conflict"


# ---------- tier-2: the real gs + tesseract path (CI installs them) ----------
@pytest.mark.external
def test_real_gs_tesseract_ocr_of_generated_pdf_is_deterministic(tmp_path):
    if not (intake.GS and intake.TESSERACT):
        pytest.skip("ghostscript/tesseract not installed (tier-2 only)")
    from PIL import Image, ImageDraw, ImageFont
    im = Image.new("RGB", (1700, 800), "white")
    d = ImageDraw.Draw(im)
    try:
        font = ImageFont.load_default(size=80)
    except TypeError:            # older Pillow: fixed-size bitmap default font
        font = ImageFont.load_default()
    d.text((100, 300), 'WALL A 48"w x 96"h', fill="black", font=font)
    pdf = tmp_path / "visual_handoff.pdf"
    im.save(str(pdf), resolution=100.0)

    text, pages, n = intake.read_pdf_text(str(pdf))
    assert n == 1 and len(pages) == 1        # image-only PDF: no crash, no text layer

    t1, w1 = intake.ocr_pages(str(pdf), n)
    t2, w2 = intake.ocr_pages(str(pdf), n)
    assert isinstance(t1, str)
    assert (t1, w1) == (t2, w2), "OCR of the same page must be deterministic"
    assert w1 == [], f"clean gs+tesseract run must not warn: {w1}"
