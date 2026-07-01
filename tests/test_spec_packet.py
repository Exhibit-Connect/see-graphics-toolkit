"""Tests for the client spec-packet builder (tools/generate_spec_packet.py) —
specifically the optional labeled-rendering section (Marc's request: show the
booth rendering with each wall labeled alongside the size list)."""
import generate_spec_packet as gsp

BASE = {"job": {"name": "Test", "job_number": "123"},
        "settings": {"scale": 0.5, "bleed_per_side_in": 1.0},
        "panels": [{"name": "A", "w": 10, "h": 20, "finish": "fabric", "sided": "single"}]}


def test_spec_packet_embeds_rendering_when_present():
    html = gsp.build_html(dict(BASE, __rendering_uri="data:image/png;base64,ABC123"))
    assert "Graphic placement" in html
    assert "data:image/png;base64,ABC123" in html


def test_spec_packet_omits_rendering_section_when_absent():
    assert "Graphic placement" not in gsp.build_html(dict(BASE))


def test_img_data_uri_missing_or_blank_is_empty():
    assert gsp.img_data_uri("/no/such/file.png") == ""
    assert gsp.img_data_uri("") == ""


def test_rendering_data_uri_missing_is_empty():
    assert gsp.rendering_data_uri("/no/such/file.png") == ""
    assert gsp.rendering_data_uri("") == ""


def test_rendering_data_uri_trims_surrounding_white(tmp_path):
    import base64, io
    from PIL import Image
    im = Image.new("RGB", (400, 300), (255, 255, 255))          # mostly white
    for x in range(150, 250):                                   # a small black block
        for y in range(120, 180):
            im.putpixel((x, y), (0, 0, 0))
    p = tmp_path / "render.png"
    im.save(p)
    uri = gsp.rendering_data_uri(str(p))
    assert uri.startswith("data:image/png;base64,")
    out = Image.open(io.BytesIO(base64.b64decode(uri.split(",", 1)[1])))
    assert out.width < 400 and out.height < 300                 # white margins trimmed away
