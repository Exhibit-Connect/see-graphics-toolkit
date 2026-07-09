"""P2-1: the runtime dependencies are declared, pinned, and importable.

pypdf / Pillow / openpyxl used to be imported lazily and declared nowhere -
`pip install -r requirements-dev.txt` on a bare machine left the suite (and
the tools) broken, and an unpinned upgrade could silently shift analyze_pdf
behavior behind its guarded excepts. These tests fail loudly when a dep is
missing, when its MAJOR version drifts from the validated pin, or when
requirements.txt stops declaring it.
"""
import os
import re

# (import name, requirements.txt name, validated major version)
DEPS = [
    ("pypdf", "pypdf", 6),
    ("PIL", "Pillow", 12),
    ("openpyxl", "openpyxl", 3),
]

REQS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "requirements.txt")


def _major(version):
    return int(re.match(r"(\d+)", version).group(1))


def test_runtime_deps_import_at_validated_majors():
    import importlib
    for import_name, pip_name, major in DEPS:
        mod = importlib.import_module(import_name)
        ver = getattr(mod, "__version__", None)
        assert ver, f"{pip_name} has no __version__"
        assert _major(ver) == major, (
            f"{pip_name} {ver} is not the validated major {major} - "
            f"re-validate the suite and update requirements.txt + this test together")


def test_requirements_txt_pins_every_runtime_dep_exactly():
    text = open(REQS, encoding="utf-8").read()
    for _, pip_name, major in DEPS:
        m = re.search(rf"^{pip_name}==(\d+)\.[\w.]+", text, re.M | re.I)
        assert m, f"requirements.txt must pin {pip_name} exactly (==X.Y.Z)"
        assert int(m.group(1)) == major, (
            f"requirements.txt pins {pip_name} at major {m.group(1)}, "
            f"but the suite validates major {major}")


def test_openpyxl_minor_is_the_validated_band():
    # the proof-log round-trip (P1-4/P2-5) is validated against 3.1.x
    import openpyxl
    assert openpyxl.__version__.startswith("3.1."), openpyxl.__version__


def test_dev_requirements_include_runtime_requirements():
    dev = os.path.join(os.path.dirname(REQS), "requirements-dev.txt")
    text = open(dev, encoding="utf-8").read()
    assert re.search(r"^-r requirements\.txt", text, re.M), (
        "requirements-dev.txt must include the runtime pins - "
        "tests import pypdf/Pillow/openpyxl")
    assert re.search(r"^pytest", text, re.M)
