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


def _read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


def test_readme_example_numbering_matches_examples_dir():
    """P3-2: the README's 'numbered 1->N' claim tracks the actual files."""
    numbered = {f.split("_")[0] for f in os.listdir(os.path.join(REPO, "examples"))
                if f[0].isdigit()}
    hi = max(int(n) for n in numbered)
    assert f"1->{hi}" in _read("README.md")


def test_docs_document_ack_review_next_to_approve():
    """P3-2: everywhere --approve is documented, the NEEDS-REVIEW
    acknowledgment (--ack-review, from P0-8) is documented too."""
    for name in ("README.md", "CLAUDE.md"):
        txt = _read(name)
        assert "--approve" in txt and "--ack-review" in txt, name
    assert "acknowledge" in _read("docs", "Instructions.md")


def test_no_stale_or_overreaching_claims():
    """P3-2: no stale test count; the intake wording promises 'flagged for
    confirmation' (the real enforcement) and the approval is described as
    stamped+logged, not 'locked'."""
    assert "104 tests" not in _read("CLAUDE.md")
    instructions = _read("docs", "Instructions.md")
    assert "never guessed" not in instructions
    assert "flagged for your confirmation" in instructions
    assert "**locked**" not in instructions
    assert "logged" in instructions
