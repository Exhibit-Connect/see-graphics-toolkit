"""Fixture tests for the PDF-analysis path in tools/proofer.py (P0-1 .. P0-5).

PDFs are built in-test from raw objects (no committed binary artwork), per the
plan's fixture strategy: content inside Form XObjects, undecodable streams,
unknown colorspaces, multi-page files. pypdf + Pillow only - no Chrome/gs.
"""
import proofer


SPEC = {
    "settings": {"bleed_per_side_in": 1.0, "scale": 0.5, "safe_margin_in": 4.0},
    "panels": [{"name": "Wall A", "w": 100, "h": 200}],
}
PANEL = SPEC["panels"][0]

# 100x200in trim + 1in bleed per side, in points
FULL_BLEED_PT = (102 * 72, 202 * 72)


# ---------- raw-PDF builder ----------
def build_pdf(path, objects):
    """Assemble a minimal PDF from raw object bodies (object 1 must be the
    /Catalog). Computes the xref table so pypdf parses it strictly."""
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += (f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref}\n%%EOF\n").encode()
    path.write_bytes(bytes(out))
    return str(path)


def stream(dict_src, data):
    if isinstance(data, str):
        data = data.encode("latin-1")
    return (f"<< {dict_src} /Length {len(data)} >>\nstream\n".encode()
            + data + b"\nendstream")


def catalog_and_pages(kids=("3 0 R",)):
    kid_refs = " ".join(kids)
    return [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{kid_refs}] /Count {len(kids)} >>".encode(),
    ]


def page(media_pt, resources, contents_ref, extra=""):
    w, h = media_pt
    return (f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {w:g} {h:g}] "
            f"/Resources {resources} /Contents {contents_ref} {extra}>>").encode()


RGB_IMAGE = stream("/Type /XObject /Subtype /Image /Width 500 /Height 500 "
                   "/ColorSpace /DeviceRGB /BitsPerComponent 8", b"\x00" * 30)
CMYK_IMAGE_1440 = stream("/Type /XObject /Subtype /Image /Width 1440 /Height 1440 "
                         "/ColorSpace /DeviceCMYK /BitsPerComponent 8", b"\x00" * 30)
HELVETICA = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"


# ---------- P0-1: nested Form XObject content ----------
def rgb_in_form_pdf(tmp_path):
    """RGB raster + live font hidden inside a Form XObject; page itself clean."""
    objs = catalog_and_pages() + [
        page(FULL_BLEED_PT, "<< /XObject << /Fm1 4 0 R >> >>", "5 0 R"),
        # the form: places the 500px image at 720pt (10in) -> 50 ppi
        stream("/Type /XObject /Subtype /Form /BBox [0 0 7344 14544] "
               "/Resources << /XObject << /Im1 6 0 R >> /Font << /F1 7 0 R >> >>",
               "q 720 0 0 720 100 100 cm /Im1 Do Q"),
        stream("", "q 1 0 0 1 0 0 cm /Fm1 Do Q"),
        RGB_IMAGE,
        HELVETICA,
    ]
    return build_pdf(tmp_path / "form_rgb.pdf", objs)


def test_form_xobject_rgb_image_fails_color_and_grades_resolution(tmp_path):
    info = proofer.analyze_pdf(rgb_in_form_pdf(tmp_path))
    assert "RGB" in info["colors"]
    assert info["fonts"] >= 1
    assert info["images"] and info["images"][0]["ppi"] == 50
    assert info["analysis_gaps"] == []
    assert proofer.check_color(info)[0] == "FAIL"
    st, msg = proofer.check_resolution(info)
    assert st == "FAIL" and "50" in msg
    # live font inside the form -> fonts WARN
    assert proofer.check_fonts(info)[0] == "WARN"


def test_nested_form_ctm_composes_with_placing_matrix(tmp_path):
    """Form-in-form: outer places inner at 0.5 scale; inner places a 720px
    image at 720pt -> effective 360pt = 5in -> 144 ppi."""
    img = stream("/Type /XObject /Subtype /Image /Width 720 /Height 720 "
                 "/ColorSpace /DeviceCMYK /BitsPerComponent 8", b"\x00" * 10)
    objs = catalog_and_pages() + [
        page(FULL_BLEED_PT, "<< /XObject << /Fm1 4 0 R >> >>", "6 0 R"),
        stream("/Type /XObject /Subtype /Form /BBox [0 0 7344 14544] "
               "/Resources << /XObject << /Fm2 5 0 R >> >>",
               "q 0.5 0 0 0.5 0 0 cm /Fm2 Do Q"),
        stream("/Type /XObject /Subtype /Form /BBox [0 0 7344 14544] "
               "/Resources << /XObject << /Im1 7 0 R >> >>",
               "q 720 0 0 720 0 0 cm /Im1 Do Q"),
        stream("", "q 1 0 0 1 0 0 cm /Fm1 Do Q"),
        img,
    ]
    info = proofer.analyze_pdf(build_pdf(tmp_path / "nested.pdf", objs))
    assert info["images"][0]["ppi"] == 144
    assert "CMYK" in info["colors"]


def test_self_referencing_form_terminates(tmp_path):
    objs = catalog_and_pages() + [
        page(FULL_BLEED_PT, "<< /XObject << /Fm1 4 0 R >> >>", "5 0 R"),
        # form references itself AND an RGB image - must not loop forever
        stream("/Type /XObject /Subtype /Form /BBox [0 0 100 100] "
               "/Resources << /XObject << /Fm1 4 0 R /Im1 6 0 R >> >>",
               "q 72 0 0 72 0 0 cm /Im1 Do Q /Fm1 Do"),
        stream("", "/Fm1 Do"),
        RGB_IMAGE,
    ]
    info = proofer.analyze_pdf(build_pdf(tmp_path / "cycle.pdf", objs))
    assert "RGB" in info["colors"]


def test_undecodable_stream_warns_never_passes(tmp_path):
    objs = catalog_and_pages() + [
        page(FULL_BLEED_PT, "<< /ColorSpace << /CS0 /DeviceCMYK >> >>", "4 0 R"),
        stream("/Filter /FlateDecode", b"this is not valid flate data"),
    ]
    info = proofer.analyze_pdf(build_pdf(tmp_path / "badstream.pdf", objs))
    assert info["analysis_gaps"], "undecodable stream must record an analysis gap"
    st, msg = proofer.check_resolution(info)
    assert st == "WARN" and "could not fully analyze" in msg
    assert proofer.check_color(info)[0] == "WARN"
    # gap text must reach the client-facing report
    html_doc = proofer.build_report_html(
        "badstream.pdf", "Wall A", "named explicitly",
        {"resolution": (st, msg)}, "WARN", gaps=info["analysis_gaps"])
    assert "Analysis gaps" in html_doc
    assert "content stream could not be decoded" in html_doc


def test_unreadable_form_stream_blocks_fonts_pass(tmp_path):
    objs = catalog_and_pages() + [
        page(FULL_BLEED_PT, "<< /XObject << /Fm1 4 0 R >> >>", "5 0 R"),
        stream("/Type /XObject /Subtype /Form /BBox [0 0 100 100] "
               "/Filter /FlateDecode", b"garbage-not-flate"),
        stream("", "/Fm1 Do"),
    ]
    info = proofer.analyze_pdf(build_pdf(tmp_path / "badform.pdf", objs))
    assert any(g.startswith("form") for g in info["analysis_gaps"])
    st, msg = proofer.check_fonts(info)
    assert st == "WARN" and "cannot confirm text is outlined" in msg


def test_inline_image_records_gap(tmp_path):
    content = ("q 72 0 0 72 0 0 cm BI /W 2 /H 2 /CS /RGB /BPC 8 ID "
               "\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00 EI Q 1 0 0 0 k")
    objs = catalog_and_pages() + [
        page(FULL_BLEED_PT, "<< >>", "4 0 R"),
        stream("", content),
    ]
    info = proofer.analyze_pdf(build_pdf(tmp_path / "inline.pdf", objs))
    assert any("inline image" in g for g in info["analysis_gaps"])
    assert proofer.check_resolution(info)[0] == "WARN"


def test_unknown_colorspace_discard_warns_color(tmp_path):
    objs = catalog_and_pages() + [
        page(FULL_BLEED_PT, "<< /ColorSpace << /CS0 /SomeExoticSpace >> >>", "4 0 R"),
        stream("", "1 0 0 0 k 0 0 100 100 re f"),
    ]
    info = proofer.analyze_pdf(build_pdf(tmp_path / "unknowncs.pdf", objs))
    assert "Unknown" not in info["colors"] and "CMYK" in info["colors"]
    assert any("colorspace" in g for g in info["analysis_gaps"])
    st, msg = proofer.check_color(info)
    assert st == "WARN" and "could not be analyzed" in msg


def test_clean_vector_pdf_still_passes(tmp_path):
    """Genuinely vector, no gaps -> vector-only resolution PASS retained."""
    objs = catalog_and_pages() + [
        page(FULL_BLEED_PT, "<< >>", "4 0 R"),
        stream("", "1 0 0 0 k 0 0 7344 14544 re f"),
    ]
    info = proofer.analyze_pdf(build_pdf(tmp_path / "vector.pdf", objs))
    assert info["analysis_gaps"] == []
    assert proofer.check_resolution(info)[0] == "PASS"
    assert proofer.check_color(info) == ("PASS", "CMYK")
    assert proofer.check_fonts(info)[0] == "PASS"


def clean_cmyk_pdf(tmp_path):
    """Full + bleed size, CMYK image at 144 ppi, no fonts, no gaps."""
    objs = catalog_and_pages() + [
        page(FULL_BLEED_PT, "<< /XObject << /Im1 4 0 R >> >>", "5 0 R"),
        CMYK_IMAGE_1440,
        stream("", "q 720 0 0 720 0 0 cm /Im1 Do Q"),
    ]
    return build_pdf(tmp_path / "Wall_A_clean.pdf", objs)


# ---------- P0-3: CTM tokenizer (leading-dot decimals) + worst-axis ppi ----------
def test_image_placements_leading_dot_decimals():
    placed = proofer.image_placements("q .5 0 0 .5 0 0 cm /Im1 Do Q", {"Im1"})
    assert placed == {"Im1": (0.5, 0.5)}


def test_image_placements_negative_leading_dot():
    placed = proofer.image_placements("q -.25 0 0 .25 0 0 cm /Im1 Do Q", {"Im1"})
    assert placed == {"Im1": (0.25, 0.25)}


def test_image_placements_plain_numbers_unchanged():
    placed = proofer.image_placements("q 144 0 0 288 10 20 cm /Im1 Do Q", {"Im1"})
    assert placed == {"Im1": (144.0, 288.0)}


def test_resolution_grades_worst_axis(tmp_path):
    """720px square image placed 720pt wide x 1440pt tall: x-axis 72 ppi,
    y-axis 36 ppi -> must grade 36 (vertical stretch used to be invisible)."""
    img = stream("/Type /XObject /Subtype /Image /Width 720 /Height 720 "
                 "/ColorSpace /DeviceCMYK /BitsPerComponent 8", b"\x00" * 10)
    objs = catalog_and_pages() + [
        page(FULL_BLEED_PT, "<< /XObject << /Im1 4 0 R >> >>", "5 0 R"),
        img,
        stream("", "q 720 0 0 1440 0 0 cm /Im1 Do Q"),
    ]
    info = proofer.analyze_pdf(build_pdf(tmp_path / "stretch.pdf", objs))
    assert info["images"][0]["ppi"] == 36
    assert proofer.check_resolution(info)[0] == "FAIL"


# ---------- P0-4: bleed presence (end-to-end) ----------
def test_zero_bleed_trim_size_pdf_gets_review_and_fix_entry(tmp_path):
    objs = catalog_and_pages() + [
        page((100 * 72, 200 * 72), "<< >>", "4 0 R"),  # media == exact trim size
        stream("", "1 0 0 0 k 0 0 7200 14400 re f"),
    ]
    res = proofer.run_checks(build_pdf(tmp_path / "Wall_A_notrim.pdf", objs), SPEC, "Wall A")
    st, msg = res["results"]["size"]
    assert st == "WARN" and "no bleed detected" in msg
    assert res["verdict"] == "REVIEW"
    size_fixes = [f for f in res["fixes"] if f["check"] == "size"]
    assert size_fixes and "bleed" in size_fixes[0]["text"]


# ---------- P0-5: marks margin vs expected bleed (end-to-end threading) ----------
def test_crop_mark_margin_fixture_warns_marks(tmp_path):
    """TrimBox 100x200in, media extends 1.4in per side (bleed 1.0 + marks):
    size PASSes (bleed present) but marks must WARN - the old 2.5in threshold
    made this unreachable for realistic exports."""
    media = (102.8 * 72, 202.8 * 72)
    trim_box = "/TrimBox [100.8 100.8 7300.8 14500.8] "
    objs = catalog_and_pages() + [
        page(media, "<< >>", "4 0 R", extra=trim_box),
        stream("", "1 0 0 0 k 0 0 7401.6 14601.6 re f"),
    ]
    res = proofer.run_checks(build_pdf(tmp_path / "Wall_A_marks.pdf", objs), SPEC, "Wall A")
    assert res["results"]["size"][0] == "PASS"
    st, msg = res["results"]["marks"]
    assert st == "WARN" and "crop/registration marks" in msg


# ---------- P0-2: all pages analyzed, not just page 1 ----------
def two_page_pdf(tmp_path):
    """Page 1: clean CMYK at full+bleed size. Page 2: wrong-sized with an RGB
    colorspace resource - previously invisible to every check."""
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R 5 0 R] /Count 2 >>",
        page(FULL_BLEED_PT, "<< >>", "4 0 R"),
        stream("", "1 0 0 0 k 0 0 7344 14544 re f"),
        page((50 * 72, 60 * 72), "<< /ColorSpace << /CS0 /DeviceRGB >> >>", "6 0 R"),
        stream("", "1 0 0 rg 0 0 3600 4320 re f"),
    ]
    return build_pdf(tmp_path / "twopage.pdf", objs)


def test_multipage_bad_page2_is_not_pass(tmp_path):
    res = proofer.run_checks(two_page_pdf(tmp_path), SPEC, "Wall A")
    assert res is not None
    st, msg = res["results"]["size"]
    assert st == "FAIL" and "page 2" in msg
    # page 2's RGB is aggregated into the color check
    assert res["results"]["color"][0] == "FAIL"
    assert res["verdict"] != "PASS"


def test_multipage_all_pages_matching_still_passes(tmp_path):
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R 5 0 R] /Count 2 >>",
        page(FULL_BLEED_PT, "<< >>", "4 0 R"),
        stream("", "1 0 0 0 k 0 0 7344 14544 re f"),
        page(FULL_BLEED_PT, "<< >>", "6 0 R"),
        stream("", "0 1 0 0 k 0 0 7344 14544 re f"),
    ]
    info = proofer.analyze_pdf(build_pdf(tmp_path / "twopage_ok.pdf", objs))
    assert info["pages"] == 2 and len(info["page_sizes"]) == 2
    assert proofer.check_size(info, SPEC, PANEL)[0] == "PASS"


def test_clean_cmyk_fixture_passes_all_checks(tmp_path):
    res = proofer.run_checks(clean_cmyk_pdf(tmp_path), SPEC, "Wall A")
    assert res is not None
    assert res["results"]["size"][0] == "PASS"
    assert res["results"]["color"][0] == "PASS"
    assert res["results"]["resolution"][0] == "PASS"
    assert res["results"]["fonts"][0] == "PASS"
    assert res["verdict"] == "PASS"
    assert res["info"]["analysis_gaps"] == []
