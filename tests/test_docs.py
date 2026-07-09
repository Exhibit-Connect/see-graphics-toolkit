"""P3-1: docs/ must never ship a Chrome-error-page PDF again.

The two original onboarding PDFs (How_It_Works_Overview.pdf,
Graphics_Design_AI_Brief.pdf) were Chrome ERR_INVALID_URL error pages printed
to PDF (the P0-16 defect); they were deleted and the README repointed at
docs/Workflow_Map + Instructions.md. This guard scans every PDF that ever
lands back under docs/ with the same detector render.py uses.
"""
import glob
import os

import render

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(REPO, "docs")


def test_corrupted_onboarding_pdfs_are_gone():
    assert not os.path.exists(os.path.join(DOCS, "How_It_Works_Overview.pdf"))
    assert not os.path.exists(os.path.join(DOCS, "Graphics_Design_AI_Brief.pdf"))


def test_no_chrome_error_page_pdfs_in_docs():
    for pdf in glob.glob(os.path.join(DOCS, "*.pdf")):
        assert not render.looks_like_chrome_error_page(pdf), (
            f"{pdf} is a Chrome error page printed to PDF — regenerate it "
            "from its source HTML with render.html_to_pdf (which now rejects "
            "error pages) instead of committing it")


def test_readme_points_at_live_docs():
    with open(os.path.join(REPO, "README.md"), encoding="utf-8") as f:
        readme = f.read()
    assert "How_It_Works_Overview.pdf" not in readme
    assert "Graphics_Design_AI_Brief.pdf" not in readme
    assert "Workflow_Map" in readme
    assert "Instructions.md" in readme
