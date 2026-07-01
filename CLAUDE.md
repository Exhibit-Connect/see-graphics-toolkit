# CLAUDE.md — SEE Graphics Toolkit

Working guidance for Claude (and contributors) in this repo. The toolkit automates a trade-show
**booth-graphics workflow** — from a 3D handoff, through artwork checks, to a client proof — and is meant
to be run **with Claude in plain English** (see `docs/Instructions.md`): you hand Claude a file and say what
you want, and Claude runs the tools and hands back the results.

## Core idea: one booth file is the single source of truth
A booth is defined once in a small JSON **booth file** (see `examples/1_booth_spec_example.json`). The wall
templates, the client spec sheet, and the artwork checks are all generated **from that one file**, so they
can never disagree. Define the booth once → everything downstream stays consistent.

## Tools (`tools/`)
| Tool | Does | Run |
|------|------|-----|
| `intake.py` | 3D handoff PDF → draft booth file + a "confirm" checklist; flags page-to-page size conflicts. A **visual/slide-deck handoff** (no extractable text) is read by deterministic **tesseract OCR** of the graphic key; `--ai` adds finish / finishing-type best-guesses and catches surfaces present in the render but missing from the key. | `python3 tools/intake.py handoff.pdf --job "Client - Show - Size" [--ai]` |
| `SEE_Wall_Template_Generator.jsx` | The production wall templates (Illustrator artboards with bleed/trim/safe guides, door cuts, keep-clear/live zones), from the booth file. **Runs only inside Adobe Illustrator** (File ▸ Scripts ▸ Other Script). | in Illustrator |
| `preview_templates.py` | Quick PNG/SVG **preview** of all templates from the booth file — no Illustrator needed. Its per-panel guide drawing (`panel_guides_svg`) is shared with `client_templates.py`. | `python3 tools/preview_templates.py [booth.json]` |
| `client_templates.py` | **Client-ready design templates** (PDF) from the booth file — one page per panel with bleed/trim/safe/keep-clear/live/door guides + exact sizes, openable without Illustrator so clients design on the real layout. Oversized pieces show a tile/seam notice. `--per-panel` also emits one PDF each. | `python3 tools/client_templates.py [booth.json] [--per-panel]` |
| `generate_spec_packet.py` | Client submission spec sheet (PDF) from the booth file — per-panel size / material / finishing-type / qty / sided / visible area. Stamps an **UNVERIFIED-DIMENSIONS** banner on any unconfirmed panel. | `python3 tools/generate_spec_packet.py [booth.json]` |
| `proofer.py` | Checks returned client artwork vs the booth file: size, color (flags RGB), resolution, fonts, printer marks, spelling. Adds a plain-English **"what to change" fix list** + a marked-up preview, but **never alters the client's file**. | `python3 tools/proofer.py artwork.pdf [--panel NAME]` |
| `make_proof.py` | The client proof: a single item, or a **whole-job document** (cover/summary + one page per graphic). Structured spec block, status legend, disclaimer banner, the fix list, 3-way sign-off, prepped/QC footer; dated, **locked** sign-off + a log. Refuses to approve a FAIL, a placeholder/blank, or an **unverified** panel. | item: `make_proof.py art.pdf [...] [--approve "Name"]` · job: `make_proof.py a1 a2 …` |
| `dashboard.py` | **Job status dashboard** (HTML, `--pdf` for PDF): every active job + its stage (intake / awaiting confirm / in proof / approved), due date + countdown, and risk flags (unverified panels, failed checks, approaching deadline). Built from the booth files + `proof_log.xlsx`; degrades gracefully without them. | `python3 tools/dashboard.py [--jobs-dir DIR] [--pdf]` |
| `branding.py` | Shared SEE logo + contact header, so every generated document (spec sheet, check report, proof, dashboard, client templates) matches. | (imported by the others) |
| `render.py` | Shared HTML→PDF helper (poll-then-terminate headless Chrome) used by every PDF-producing tool. | (imported by the others) |
| `ai_client.py` | Shared OpenRouter client used by the AI steps. | `python3 tools/ai_client.py --check` |

Tools are **location-independent**: they auto-find `examples/*booth_spec*.json` (in cwd / `examples/`) or take a path / `--spec`.

## Locked specs / build conventions
- Build at **½ scale** (output 200%). **Bleed 1″/side (2″ total).** Safe margin **4″** (spec 3–5″).
- **CMYK / Pantone**; fonts → outlines; raster **120–150 ppi** at scale; **printer marks off**.
- **Door geometry** is baked into the generator (panel 39.125″×95.21″; two holes 4.3125″ in from the latch edge — handle 2.0″ dia @ 37.98″, lock 1.125″ dia @ 41.79″).
- Template guide colors: **cyan** = bleed · **black** = trim · **magenta** = safe area · **orange** = keep-clear · **green** = live art · **red** = door.

## Key principles
- **Dimensions are NEVER guessed.** If a handoff doesn't print a size, intake flags it to measure rather than inventing one. Finishes / finishing-types *may* be AI best-guessed (low-risk) but are always flagged to confirm.
- **Confirm-gate.** Panels recovered from a visual handoff are flagged `needs_confirm` (OCR/AI-sourced). `generate_spec_packet` stamps an "UNVERIFIED DIMENSIONS" banner and `make_proof` refuses to approve such a panel, until a human clears the flag — so an unconfirmed size can never reach a client or print.
- **Oversized pieces.** A panel too big for one Illustrator artboard (about 227″ at build scale — e.g. a full-circumference hanging sign) is **skipped and flagged to tile/seam separately** rather than crashing the run; it still appears on the spec sheet, the client templates, the checks, and the proof.
- **Never alter the client's file.** `proofer.py` produces precise fix instructions + a marked-up preview, but it never rewrites the artwork — an automatic RGB→CMYK or resize could silently ruin a print. We say exactly what to change and let a human act.
- **Read messy handoffs at full resolution.** Intake OCRs visual handoffs at **300 ppi** (deterministic) and `--ai` reads them at **150 ppi** (both in `intake.py`). Graphic-key text on these decks is often **outlined/vector** — *not* selectable text, and easy to lose in a thumbnail — so a low-res view or a PDF text-extraction can wrongly look "blank." When verifying (or a key looks empty), **render that page at high DPI and read it directly** (e.g. `gs -q -r220 -sDEVICE=png16m -dFirstPage=N -dLastPage=N -o key.png file.pdf`); never conclude "no sizes" from a thumbnail or text-extraction alone. **Always process every handoff file** the client provides (a details deck *and* a renders deck), not just one. Still never guess a size — flag `needs_confirm`.

## Example job
`examples/` is a finished, worked example (Mama's Creations), numbered `1 → 7` in workflow order — the booth
file, intake checklist, template preview, client spec sheet, artwork check report, and the proofs. The tools
default to it, so every step can be demonstrated end to end without any private data.

## Real jobs vs. the example
`examples/` is the **only** booth data in the repo — it's fake/public, and the tools default to it when
given no path. **Real client jobs live in a gitignored `jobs/<job>/` folder** (that job's booth file + the
3D handoff + the generated deliverables) and are **never committed**. Run a tool against the job's booth
file — e.g. `python3 tools/generate_spec_packet.py jobs/<job>/booth_spec_<job>.json` — and point the
dashboard at all of them with `python3 tools/dashboard.py --jobs-dir jobs`. Keeping each job in its own
folder (rather than loose in the repo root) also stops the dashboard's auto-discovery from mixing drafts,
confirmed files, and the example together.

## AI setup
The AI steps use **OpenRouter** (model via the `OPENROUTER_MODEL` env var; defaults to an Anthropic Claude
model). Provide your key in `OPENROUTER_API_KEY` **or** a local, gitignored `.openrouter_key` file. Without a
key, the AI steps write a dry-run request instead of failing. Check it: `python3 tools/ai_client.py --check`.

## Rendering / platform
PDFs render via **headless Google Chrome** (a poll-then-terminate helper, so it can't hang); the template
preview rasterizes via that same Chrome helper (`render.svg_to_png`, sized to the SVG's own aspect ratio so
wide booths aren't cropped; falls back to **qlmanage** only if Chrome is absent); **Ghostscript** rasterizes PDFs for OCR. **Mac-centric.** The `.jsx`
runs only inside Illustrator (a `CMYKColor is not defined` error anywhere else is expected).

## Tests + definition of done
Run `pip install -r requirements-dev.txt && pytest` (66 tests; covers the pure helpers in `intake.py` /
`proofer.py` / `make_proof.py` / `branding.py` / `dashboard.py` / `client_templates.py` / `render.py`).
**Extend the suite whenever you add or change logic** in a tool. A behavior
change isn't "done" until the tests pass *and* the living docs (`docs/Instructions.md` + the two overview
PDFs in `docs/`) are updated to match.

## Critical rules
- **Never commit secrets or large binaries.** `.openrouter_key`, `*.zip`, and the tools' runtime outputs are
  gitignored. Always run `git status` before committing, and prefer targeted `git add <path>` over `git add -A`.
- **Keep client artwork and internal files out of the repo.** Real jobs live in the gitignored `jobs/<job>/`
  folder; the door templates' proprietary source and any client/internal documents stay local; the
  `examples/` files (fake/public) demonstrate every tool, so nothing is lost.
- `.jsx` changes can only be verified inside Adobe Illustrator; the Python tools are covered by `pytest`.
