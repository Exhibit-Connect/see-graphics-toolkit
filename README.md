# SEE Graphics Toolkit

Tools that automate Southeast Exhibits & Events' trade-show graphics workflow — from a won job's
kickoff through final render. One **booth file** (a small JSON) is the single source of truth;
everything else is generated from it, so the templates, the client spec sheet, and the artwork
checks can never disagree.

## What's in here
```
see-graphics-toolkit/
├─ tools/       the programs you run (Python + the Illustrator script)
├─ docs/        read these — the workflow map and the instructions
├─ examples/    a finished example booth, numbered 1->7 in workflow order
├─ README.md    you are here
└─ LICENSE
```

## New here? Start with these (in `docs/`)
1. **`Workflow_Map.png`** — the whole flow as one diagram, with the tool used at each step and where each `examples/` file fits.
2. **`Instructions.md`** — plain-language, step-by-step (written assuming Claude is helping).

## The flow (and the tool for each step)
| Step | Tool (`tools/`) | What it does |
|------|------|--------------|
| Capture the key | `intake.py` | Reads a 3D handoff (PDF/`.ai`) → drafts the booth file + a confirm checklist. |
| Build templates | `SEE_Wall_Template_Generator.jsx` | Illustrator script → every wall template, from the booth file. |
| Preview templates | `preview_templates.py` | Quick PNG/SVG picture of every panel's layout from the booth file — no Illustrator needed. |
| Tell the client | `generate_spec_packet.py` | The client submission spec sheet (PDF), from the same booth file. |
| Check artwork | `proofer.py` | Auto-checks a returned file: size + bleed, color, resolution, fonts, printer marks, and spelling (a dictionary-based advisory — needs live text, so outlined type isn't spell-checked). |
| Proof & sign-off | `make_proof.py` | Branded proof — one item, or a whole-job multi-page document (cover/summary page + one page per graphic); dated client approval, stamped on the proof and logged. |
| (shared) | `ai_client.py` | OpenRouter client used by the AI steps. |
| (shared) | `branding.py` | Shared SEE logo + contact header, so every generated document carries the same branding. |

## Quick start
Run from this top folder. The tools auto-find the example booth in `examples/`.
```sh
# 1. draft a booth file from a 3D handoff
python3 tools/intake.py path/to/handoff.pdf --job "Client - Show - Size" --ai
# 2. templates: Illustrator -> File > Scripts > Other Script -> tools/SEE_Wall_Template_Generator.jsx -> pick your booth_spec JSON
# 2b. (optional) a quick visual preview of the templates, no Illustrator:
python3 tools/preview_templates.py examples/1_booth_spec_example.json
# 3. client spec sheet
python3 tools/generate_spec_packet.py examples/1_booth_spec_example.json
# 4. check a returned artwork file
python3 tools/proofer.py path/to/client_artwork.pdf
# 5. proof + sign-off
python3 tools/make_proof.py path/to/client_artwork.pdf       # then, once OK'd:  --approve "Client Name"
#    (approving a NEEDS-REVIEW result additionally requires --ack-review "reason" — the
#     acknowledgment is recorded on the proof and in the log)
```
Full detail is in `docs/Instructions.md`.

## AI setup (one time)
The AI steps use OpenRouter. Set your key (and optionally the model):
```sh
export OPENROUTER_API_KEY="sk-or-..."
export OPENROUTER_MODEL="anthropic/claude-opus-4.8"   # default
```
Check it: `python3 tools/ai_client.py --check`. Without a key, the AI step writes a dry-run request instead of failing.

## Requirements
- Adobe Illustrator (for the `.jsx` template generator)
- Python 3 with the pinned runtime deps (`pypdf`, `Pillow`, `openpyxl`):
  ```sh
  pip install -r requirements.txt
  ```
- Ghostscript and Google Chrome (or Chromium — set `SEE_CHROME` to point at it; used to render the PDFs)
- tesseract (optional — OCR of visual/slide-deck handoffs in `intake.py`; without it, intake still
  works on text-based handoffs)

## Running tests
The pytest suite (420+ tests) covers every Python tool — intake parsing and the
seeding cascade, the PDF-analysis path (`proofer.py`), the approval gate and
proof-log round-trip (`make_proof.py`/`dashboard.py`), the client-facing
generators (`generate_spec_packet.py`, `client_templates.py`,
`preview_templates.py`), branding, spec validation, the render helpers, the
AI client (network faked), and drift guards tying the `.jsx` constants to the
Python side. The default tier needs no Chrome/Ghostscript/tesseract; the few
tests marked `external` exercise those binaries when present.
```sh
pip install -r requirements-dev.txt   # runtime pins + pytest
pytest
```
Run it after editing the scripts to catch regressions before shipping.

## Not included (by design)
Client artwork, the proprietary door-template `.ai` files, and internal SEE documents are kept out
of this repo. The door geometry is already baked into the code, and the `examples/` files demonstrate
every tool — so nothing is lost.

---
© 2026 Southeast Exhibits & Events — internal use.
