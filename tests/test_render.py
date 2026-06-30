"""Tests for the shared HTML->PDF helper in tools/render.py.

It shells out to headless Chrome, so its real output is exercised by the tools'
PDF paths. Here we just pin the contract: the function exists, and a missing
Chrome is handled gracefully (returns False, never raises) so callers can fall
back to "open the HTML and print to PDF". No Chrome is launched.
"""
import render


def test_html_to_pdf_is_callable():
    assert callable(render.html_to_pdf)


def test_missing_chrome_returns_false(monkeypatch, tmp_path):
    # point CHROME at a path that doesn't exist -> graceful False, no exception
    monkeypatch.setattr(render, "CHROME", str(tmp_path / "no_such_chrome"))
    html = tmp_path / "x.html"
    html.write_text("<p>hi</p>")
    assert render.html_to_pdf(str(html), str(tmp_path / "x.pdf")) is False


def test_proofer_render_pdf_is_the_shared_helper():
    # make_proof.py and the proofer CLI call proofer.render_pdf — keep it wired
    import proofer
    assert proofer.render_pdf is render.html_to_pdf
