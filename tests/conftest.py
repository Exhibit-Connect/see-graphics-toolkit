"""Make the modules in tools/ importable from the tests without installing
the package (e.g. `import intake`, `import proofer`)."""
import os
import sys

import pytest

TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)


@pytest.fixture(autouse=True)
def _isolate_proof_log(tmp_path, monkeypatch):
    """The proof log now defaults to a FIXED path at the repo root (P1-4).
    Point every test at its own tmp file so no test can write into the
    checkout; tests that need another location override SEE_PROOF_LOG."""
    monkeypatch.setenv("SEE_PROOF_LOG", str(tmp_path / "proof_log.xlsx"))
