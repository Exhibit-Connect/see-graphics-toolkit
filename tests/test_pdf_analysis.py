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


def test_userunit_scales_page_to_true_size(tmp_path):
    """A page can carry /UserUnit to encode its TRUE size (the PDF spec requires
    it for pages > 200in; design apps also use it for a half-scale build).
    analyze_pdf must read media_pt * UserUnit / 72 = true inches - otherwise a
    correctly-sized file reads ~1/UserUnit of its size and wrongly FAILs size.
    Regression for the real Uptool half-scale back-wall (UserUnit=10)."""
    objs = catalog_and_pages() + [
        # 734.4 x 1454.4 pt at /UserUnit 10 = 102 x 202 in (Wall A full + bleed)
        page((102 * 72 / 10, 202 * 72 / 10), "<< >>", "4 0 R", extra="/UserUnit 10 "),
        stream("", "1 0 0 0 k 0 0 734 1454 re f"),
    ]
    info = proofer.analyze_pdf(build_pdf(tmp_path / "userunit.pdf", objs))
    assert abs(info["media_in"][0] - 102) < 0.05    # true inches, not 10.2
    assert abs(info["media_in"][1] - 202) < 0.05
    assert proofer.check_size(info, SPEC, PANEL)[0] == "PASS"


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


# ---------- P0-9: matched scale threads into the resolution band ----------
def test_full_scale_match_relaxes_resolution_floor_end_to_end(tmp_path):
    """Full+bleed (full-scale) file with a 90-ppi CMYK image, spec scale 0.5:
    90 ppi used to false-FAIL the 120 floor documented for the 1/2-scale build."""
    objs = catalog_and_pages() + [
        page(FULL_BLEED_PT, "<< /XObject << /Im1 4 0 R >> >>", "5 0 R"),
        CMYK_IMAGE_1440,
        stream("", "q 1152 0 0 1152 0 0 cm /Im1 Do Q"),  # 1440px / 16in = 90 ppi
    ]
    res = proofer.run_checks(build_pdf(tmp_path / "Wall_A_full.pdf", objs), SPEC, "Wall A")
    assert res["results"]["size"][0] == "PASS"
    st, msg = res["results"]["resolution"]
    assert st == "PASS" and "relaxed to 60 ppi" in msg


def test_half_scale_match_keeps_full_floor_end_to_end(tmp_path):
    """Half+bleed (half-scale) file with the same 90-ppi image must still FAIL:
    the half-scale path is never relaxed."""
    half_bleed_pt = (51 * 72, 101 * 72)
    objs = catalog_and_pages() + [
        page(half_bleed_pt, "<< /XObject << /Im1 4 0 R >> >>", "5 0 R"),
        CMYK_IMAGE_1440,
        stream("", "q 1152 0 0 1152 0 0 cm /Im1 Do Q"),
    ]
    res = proofer.run_checks(build_pdf(tmp_path / "Wall_A_half.pdf", objs), SPEC, "Wall A")
    assert res["results"]["size"][0] == "PASS"
    assert res["results"]["resolution"][0] == "FAIL"


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


# ---------- P2-4: resolve_cs / mat_mul units ----------
def test_resolve_cs_iccbased_component_counts():
    # ICC profiles carry no space NAME - the component count /N decides
    assert proofer.resolve_cs(["/ICCBased", {"/N": 4}]) == "CMYK"
    assert proofer.resolve_cs(["/ICCBased", {"/N": 3}]) == "RGB"
    assert proofer.resolve_cs(["/ICCBased", {"/N": 1}]) == "Gray"


def test_resolve_cs_device_and_special_spaces():
    assert proofer.resolve_cs("/DeviceCMYK") == "CMYK"
    assert proofer.resolve_cs("/DeviceRGB") == "RGB"
    assert proofer.resolve_cs("/DeviceGray") == "Gray"
    assert proofer.resolve_cs(["/Separation", "/PANTONE 185 C"]) == "Spot/Separation"
    assert proofer.resolve_cs("/SomeExoticSpace") == "Unknown"


def test_mat_mul_identity_translation_and_scale_compose():
    ident = [1, 0, 0, 1, 0, 0]
    m = [2, 0, 0, 3, 10, 20]
    assert proofer.mat_mul(m, ident) == m
    assert proofer.mat_mul(ident, m) == m
    # scale placed inside a translated space: offsets add, scale kept
    assert proofer.mat_mul([2, 0, 0, 2, 0, 0], [1, 0, 0, 1, 5, 7]) == [2, 0, 0, 2, 5, 7]


def test_mat_mul_rotation_composes():
    rot90 = [0, 1, -1, 0, 0, 0]
    assert proofer.mat_mul(rot90, [1, 0, 0, 1, 5, 7]) == [0, 1, -1, 0, 5, 7]


def test_image_placements_rotated_placement_keeps_true_dims():
    # 90deg-rotated placement: column norms give the real placed size
    placed = proofer.image_placements("q 0 720 -720 0 720 0 cm /Im1 Do Q", {"Im1"})
    assert placed == {"Im1": (720.0, 720.0)}


def test_image_placements_nested_q_restores_ctm():
    content = "q 2 0 0 2 0 0 cm q 360 0 0 360 0 0 cm /Im1 Do Q /Im2 Do Q"
    placed = proofer.image_placements(content, {"Im1", "Im2"})
    assert placed["Im1"] == (720.0, 720.0)   # inner scale times outer 2x
    assert placed["Im2"] == (2.0, 2.0)       # Q restored the outer CTM


# ---------- P2-4: Pillow-built fixtures (real writer streams) ----------
# A smaller booth than SPEC so the Pillow bitmaps stay tiny.
PILLOW_SPEC = {
    "settings": {"bleed_per_side_in": 1.0, "scale": 0.5},
    "panels": [{"name": "Wall A", "w": 10, "h": 20}],
}


def pillow_pdf(tmp_path, name, mode, px, dpi, color):
    from PIL import Image
    p = tmp_path / name
    Image.new(mode, px, color).save(str(p), resolution=dpi)
    return str(p)


def test_pillow_rgb_pdf_fails_color_and_grades_ppi(tmp_path):
    # 1440x2640 at 120 dpi = 12x22in = full + bleed
    p = pillow_pdf(tmp_path, "rgb.pdf", "RGB", (1440, 2640), 120, (200, 10, 10))
    res = proofer.run_checks(p, PILLOW_SPEC, "Wall A")
    assert res["results"]["size"][0] == "PASS"
    assert res["results"]["color"][0] == "FAIL"
    assert res["info"]["images"][0]["ppi"] == 120
    assert res["info"]["analysis_gaps"] == []
    assert res["verdict"] == "FAIL"


def test_pillow_cmyk_pdf_passes_all_checks(tmp_path):
    p = pillow_pdf(tmp_path, "cmyk.pdf", "CMYK", (1440, 2640), 120, (0, 255, 255, 0))
    res = proofer.run_checks(p, PILLOW_SPEC, "Wall A")
    assert res["results"]["size"][0] == "PASS"
    assert res["results"]["color"] == ("PASS", "CMYK")
    assert res["results"]["resolution"][0] == "PASS"
    assert res["verdict"] == "PASS"


def test_pillow_low_res_half_scale_pdf_fails_resolution(tmp_path):
    # 360x660 at 60 dpi = 6x11in = half + bleed; the half-scale floor (120)
    # is never relaxed, so 60 ppi FAILs
    p = pillow_pdf(tmp_path, "low.pdf", "CMYK", (360, 660), 60, (0, 255, 255, 0))
    res = proofer.run_checks(p, PILLOW_SPEC, "Wall A")
    assert res["results"]["size"][0] == "PASS"
    st, msg = res["results"]["resolution"]
    assert st == "FAIL" and "60" in msg


def test_pillow_half_trim_no_bleed_warns_with_scaled_instruction(tmp_path):
    # 600x1200 at 120 dpi = 5x10in = bare half trim, no TrimBox
    p = pillow_pdf(tmp_path, "half.pdf", "CMYK", (600, 1200), 120, (0, 255, 255, 0))
    res = proofer.run_checks(p, PILLOW_SPEC, "Wall A")
    st, msg = res["results"]["size"]
    assert st == "WARN" and "no bleed detected" in msg
    assert 'add 0.5" bleed per side' in msg              # scaled, not the full 1"
    assert res["verdict"] == "REVIEW"


def test_pillow_rotated_landscape_file_still_matches(tmp_path):
    # 2640x1440 at 120 dpi = 22x12in: the rotated full+bleed candidate
    p = pillow_pdf(tmp_path, "rot.pdf", "CMYK", (2640, 1440), 120, (0, 255, 255, 0))
    res = proofer.run_checks(p, PILLOW_SPEC, "Wall A")
    st, msg = res["results"]["size"]
    assert st == "PASS" and "rotated" in msg


def _set_trimbox(src, dst, inset_pt):
    """pypdf post-edit: give a Pillow PDF a TrimBox inset by `inset_pt`."""
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import RectangleObject
    w = PdfWriter()
    w.append(PdfReader(src))
    pg = w.pages[0]
    mb = pg.mediabox
    pg.trimbox = RectangleObject([inset_pt, inset_pt,
                                  float(mb.width) - inset_pt,
                                  float(mb.height) - inset_pt])
    with open(dst, "wb") as f:
        w.write(f)
    return str(dst)


def test_pillow_pypdf_trimbox_marks_margin_warns(tmp_path):
    # media 12.8x22.8in, TrimBox inset 1.4in -> trim 10x20 (full trim match).
    # Bleed is present (size PASS) but the 1.4in margin exceeds the expected
    # 1.0in bleed -> crop/registration marks are probably included -> WARN.
    src = pillow_pdf(tmp_path, "marks_src.pdf", "CMYK", (1536, 2736), 120, (0, 255, 255, 0))
    p = _set_trimbox(src, tmp_path / "marks.pdf", 1.4 * 72)
    res = proofer.run_checks(p, PILLOW_SPEC, "Wall A")
    assert res["results"]["size"][0] == "PASS"
    st, msg = res["results"]["marks"]
    assert st == "WARN" and "crop/registration marks" in msg


def test_pillow_pypdf_trimbox_exact_bleed_margin_passes(tmp_path):
    # media 12x22in, TrimBox inset exactly the 1.0in bleed -> PASS both
    src = pillow_pdf(tmp_path, "bleed_src.pdf", "CMYK", (1440, 2640), 120, (0, 255, 255, 0))
    p = _set_trimbox(src, tmp_path / "bleed.pdf", 72)
    res = proofer.run_checks(p, PILLOW_SPEC, "Wall A")
    assert res["results"]["size"][0] == "PASS"
    assert res["results"]["marks"][0] == "PASS"


# ---------- P0-1/P0-3 corner cases: repeated placements + image masks ----------
def _repeat_placement_pdf(tmp_path, content, name="repeat.pdf"):
    objs = catalog_and_pages() + [
        page(FULL_BLEED_PT, "<< /XObject << /Im1 5 0 R >> >>", "4 0 R"),
        stream("", content),
        CMYK_IMAGE_1440,
    ]
    return build_pdf(tmp_path / name, objs)


def test_image_placed_large_then_tiny_grades_the_worst_placement(tmp_path):
    """The 1440px image placed at 1440pt (20in -> 72 ppi, FAIL) and then tiny
    at 72pt (1in -> 1440 ppi). The last CTM used to win, so the low-res
    placement was invisible; the WORST placement must be graded."""
    p = _repeat_placement_pdf(tmp_path,
                              "q 1440 0 0 1440 0 0 cm /Im1 Do Q "
                              "q 72 0 0 72 0 0 cm /Im1 Do Q")
    info = proofer.analyze_pdf(p)
    assert len(info["images"]) == 1
    assert info["images"][0]["ppi"] == 72
    st, msg = proofer.check_resolution(info, SPEC)
    assert st == "FAIL" and "72" in msg


def test_image_placed_tiny_then_large_grades_the_same_worst_placement(tmp_path):
    # order-independent: the worst placement wins either way
    p = _repeat_placement_pdf(tmp_path,
                              "q 72 0 0 72 0 0 cm /Im1 Do Q "
                              "q 1440 0 0 1440 0 0 cm /Im1 Do Q",
                              name="repeat2.pdf")
    info = proofer.analyze_pdf(p)
    assert info["images"][0]["ppi"] == 72
    assert proofer.check_resolution(info, SPEC)[0] == "FAIL"


def test_image_placements_keeps_the_worst_of_repeated_dos():
    placed = proofer.image_placements(
        "q 720 0 0 720 0 0 cm /Im1 Do Q q 10 0 0 10 0 0 cm /Im1 Do Q", {"Im1"})
    assert placed == {"Im1": (720.0, 720.0)}


def test_image_mask_is_not_an_unidentified_colorspace_gap(tmp_path):
    """/ImageMask true images legitimately carry NO /ColorSpace (they paint
    with the current fill color) - a clean CMYK file with a stencil mask must
    stay color-PASS with no analysis gap, not flip to REVIEW."""
    mask = stream("/Type /XObject /Subtype /Image /Width 1440 /Height 1440 "
                  "/ImageMask true /BitsPerComponent 1", b"\x00" * 30)
    objs = catalog_and_pages() + [
        page(FULL_BLEED_PT, "<< /XObject << /Im1 5 0 R /Msk1 6 0 R >> >>", "4 0 R"),
        stream("", "0 0 0 1 k q 720 0 0 720 0 0 cm /Im1 Do Q "
                   "q 720 0 0 720 0 0 cm /Msk1 Do Q"),
        CMYK_IMAGE_1440,
        mask,
    ]
    info = proofer.analyze_pdf(build_pdf(tmp_path / "mask.pdf", objs))
    assert info["analysis_gaps"] == []
    assert info["colors"] == {"CMYK"}
    st, msg = proofer.check_color(info)
    assert st == "PASS" and "CMYK" in msg
    # the mask still counts for resolution (1440px at 10in = 144 ppi)
    assert sorted(i["ppi"] for i in info["images"]) == [144, 144]


def test_image_without_colorspace_and_not_a_mask_still_gaps(tmp_path):
    # a NON-mask image missing /ColorSpace stays an unidentified-colorspace
    # gap - the mask exemption must not swallow genuinely broken images
    weird = stream("/Type /XObject /Subtype /Image /Width 1440 /Height 1440 "
                   "/BitsPerComponent 8", b"\x00" * 30)
    objs = catalog_and_pages() + [
        page(FULL_BLEED_PT, "<< /XObject << /Im1 5 0 R >> >>", "4 0 R"),
        stream("", "0 0 0 1 k q 720 0 0 720 0 0 cm /Im1 Do Q"),
        weird,
    ]
    info = proofer.analyze_pdf(build_pdf(tmp_path / "nocs.pdf", objs))
    assert any("unidentified colorspace" in g for g in info["analysis_gaps"])
