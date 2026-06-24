# SEE Graphics Toolkit

Tools that automate Southeast Exhibits & Events' trade-show graphics process — from a
won job's kickoff through final render. One **booth file** (a small JSON) is the single
source of truth; everything else is generated from it, so the templates, the client spec
sheet, and the artwork checks can never disagree.

## Start here
- **`How_It_Works_Overview.pdf`** — one-page picture of the whole flow (best quick look).
- **`Leadership_Brief.pdf`** — what each stage fixes, and what's live vs. coming.
- **`HOW_TO_Wall_Template_Generator.md`** — step-by-step for running each tool.

## The tools
| File | What it does |
|------|--------------|
| `intake.py` | Reads a 3D handoff (PDF / `.ai`) → drafts the booth file + a confirm checklist; flags page-to-page size conflicts. |
| `SEE_Wall_Template_Generator.jsx` | Adobe Illustrator script → builds every wall/panel template from the booth file. |
| `generate_spec_packet.py` | Builds the client submission spec sheet (PDF) from the same booth file. |
| `proofer.py` | Auto-checks a client's artwork vs. the booth file (size, color, resolution, fonts, spelling). |
| `make_proof.py` | Branded client proof sheet + dated, locked sign-off; logs every proof. |
| `ai_client.py` | Shared OpenRouter client for the AI steps. |

`booth_spec_Mamas_Creations_IDDBA_2026.json` is a worked example booth. The `EXAMPLE_*`
files show what each tool produces.

## Quick start
```sh
# 1. draft a booth file from the 3D handoff
python3 intake.py <handoff.pdf> --job "Client - Show - Size" --ai
# 2. templates: open Illustrator -> File > Scripts > Other Script -> SEE_Wall_Template_Generator.jsx -> pick the JSON
# 3. client spec sheet
python3 generate_spec_packet.py booth_spec_<job>.json
# 4. check a returned artwork file
python3 proofer.py <artwork.pdf>
# 5. proof + sign-off
python3 make_proof.py <artwork.pdf>            # then, once OK'd:  --approve "Client Name"
```
Full detail is in the How-To.

## AI setup (one time)
The AI steps use OpenRouter. Set your key (and optionally the model):
```sh
export OPENROUTER_API_KEY="sk-or-..."
export OPENROUTER_MODEL="google/gemini-3.5-flash"   # default
```
Check it with `python3 ai_client.py --check`. Without a key, the AI step writes a dry-run request instead of failing.

## Requirements
- Adobe Illustrator (for the `.jsx` template generator)
- Python 3 with `pypdf`, `Pillow`, `openpyxl`
- Ghostscript and Google Chrome (used to render the PDFs)

## Not included (by design)
Client artwork, the proprietary door-template `.ai` files, and internal SEE documents are
kept out of this repo. The door geometry is already baked into the code, and the `EXAMPLE_`
files demonstrate every tool — so nothing is lost.

---
© 2026 Southeast Exhibits & Events — internal use.
