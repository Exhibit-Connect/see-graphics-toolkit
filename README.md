# SEE Graphics Toolkit

Tools that automate Southeast Exhibits & Events' trade-show graphics workflow — from a won job's
kickoff through final render. One **booth file** (a small JSON) is the single source of truth;
everything else is generated from it, so the templates, the client spec sheet, and the artwork
checks can never disagree.

## What's in here
```
see-graphics-toolkit/
├─ tools/       the programs you run (Python + the Illustrator script)
├─ docs/        read these — the overview, the AI brief, the instructions
├─ examples/    a finished example booth, numbered 1->6 in workflow order
├─ README.md    you are here
└─ LICENSE
```

## New here? Start with these (in `docs/`)
1. **`How_It_Works_Overview.pdf`** — one-page picture of the whole flow.
2. **`Graphics_Design_AI_Brief.pdf`** — what each stage fixes, live vs. coming.
3. **`Instructions.md`** — plain-language, step-by-step (written assuming Claude is helping).

## The flow (and the tool for each step)
| Step | Tool (`tools/`) | What it does |
|------|------|--------------|
| Capture the key | `intake.py` | Reads a 3D handoff (PDF/`.ai`) → drafts the booth file + a confirm checklist. |
| Build templates | `SEE_Wall_Template_Generator.jsx` | Illustrator script → every wall template, from the booth file. |
| Preview templates | `preview_templates.py` | Quick PNG/SVG picture of every panel's layout from the booth file — no Illustrator needed. |
| Tell the client | `generate_spec_packet.py` | The client submission spec sheet (PDF), from the same booth file. |
| Check artwork | `proofer.py` | Auto-checks a returned file: size, color, resolution, fonts, spelling. |
| Proof & sign-off | `make_proof.py` | Branded proof sheet + dated, locked client approval; logs each one. |
| (shared) | `ai_client.py` | OpenRouter client used by the AI steps. |

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
```
Full detail is in `docs/Instructions.md`.

## AI setup (one time)
The AI steps use OpenRouter. Set your key (and optionally the model):
```sh
export OPENROUTER_API_KEY="sk-or-..."
export OPENROUTER_MODEL="google/gemini-3.5-flash"   # default
```
Check it: `python3 tools/ai_client.py --check`. Without a key, the AI step writes a dry-run request instead of failing.

## Requirements
- Adobe Illustrator (for the `.jsx` template generator)
- Python 3 with `pypdf`, `Pillow`, `openpyxl`
- Ghostscript and Google Chrome (used to render the PDFs)

## Running tests
A small pytest suite covers the offline parsing/check helpers in `intake.py` and `proofer.py`.
```sh
pip install -r requirements-dev.txt
pytest
```
Run it after editing those scripts to catch regressions before shipping.

## Not included (by design)
Client artwork, the proprietary door-template `.ai` files, and internal SEE documents are kept out
of this repo. The door geometry is already baked into the code, and the `examples/` files demonstrate
every tool — so nothing is lost.

---
© 2026 Southeast Exhibits & Events — internal use.
