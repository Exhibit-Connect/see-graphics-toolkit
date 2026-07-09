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


@pytest.fixture(autouse=True)
def _isolate_chrome(tmp_path, monkeypatch):
    """Chrome is now RESOLVED (SEE_CHROME > mac bundles > PATH, P2-2), so a
    developer machine's real Chrome/chromium could be launched by tests that
    merely expect 'Chrome absent'. Pin every test to a deterministic
    no-Chrome default; tests that want a (fake or real) Chrome set SEE_CHROME
    themselves — it always wins the resolution. The tier-2 external smoke
    test opts back into the machine's real Chrome explicitly."""
    monkeypatch.setenv("SEE_CHROME", str(tmp_path / "chrome-not-installed"))
