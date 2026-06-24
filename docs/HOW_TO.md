# SEE Graphics Toolkit — How To

Five small tools, all driven by **one file per booth** — the **booth spec JSON** (the single source of
truth). Define the booth once; the templates, the client spec sheet, and the artwork checks always match.

> Run every command from the **top folder of the repo** (the one that holds `tools/`, `examples/`, `samples/`).
> The tools auto-find the example booth in `examples/`; for a real job, pass your own JSON (or drop it in this folder).

```
3D handoff (PDF/.ai) ──tools/intake.py──►  booth_spec_<job>.json   (the one source of truth)
                                               │   review + confirm, then it feeds:
   ├─►  tools/SEE_Wall_Template_Generator.jsx  →  the Illustrator wall templates
   ├─►  tools/generate_spec_packet.py          →  the client Spec Packet (PDF)
   └─►  tools/proofer.py <artwork>             →  auto-checks a client's file vs the spec
        └─►  tools/make_proof.py <artwork>     →  client proof sheet + sign-off (logs + locks)
```

---

## Start a booth from the 3D handoff (intake)

At job kickoff, turn the 3D team's placement file into a draft spec:
```
python3 tools/intake.py <handoff.pdf|.ai|.eps>  --job "Client - Show - Size"  [--ai]
```
- Pulls the panel names + sizes and writes a **draft** `booth_spec_<job>_DRAFT.json` plus a `<job>_intake_review.md` checklist.
- **Flags dimension disagreements between pages** and lists what a person must confirm (finishes, sided, door, zones, due date).
- `--ai` shows the rendered pages to the model to propose finishes/door/zones and flag any panel it can *see* that the text missed.
- A person reviews the checklist, fills the blanks, drops the `_DRAFT`, and that becomes the booth's source of truth.
- Native non-PDF files → export a PDF first (`.ai`/`.eps` work directly).

**AI setup (one time):** the AI step uses OpenRouter. Set your company key (and optionally the model):
```
export OPENROUTER_API_KEY="sk-or-..."
export OPENROUTER_MODEL="google/gemini-3.5-flash"   # this is the default
```
No key? `--ai` just writes the exact request to `_intake_ai_dryrun.json` to run later. Check setup: `python3 tools/ai_client.py --check`.

## 1) Make the wall templates (Illustrator)

1. Open **Adobe Illustrator** (no document needs to be open).
2. **File ▸ Scripts ▸ Other Script…** and pick **`tools/SEE_Wall_Template_Generator.jsx`**.
3. When asked, choose the booth's **`booth_spec_….json`** (the example is in `examples/`). *(Cancel = use the built-in example.)*
4. A new CMYK document appears — one named artboard per panel. Done.

**What's on each template** (each on its own layer):

| Color | Means |
|-------|-------|
| **Cyan** | Bleed — extend art to here |
| **Black** | Trim — the finished, cut size |
| **Magenta** | Visual Safe Area — keep logos/text inside |
| **Orange** (dashed) | Keep-clear — a fixture/fridge/TV/shelf sits here, **no artwork** |
| **Green** (dashed) | Live area — artwork actually shows here |
| **Red** | Door cut + handle/lock holes |

Place your art on the **"ARTWORK – place art here"** layer.

## 2) Make the client Spec Packet (PDF)
```
python3 tools/generate_spec_packet.py [your_booth_spec.json]
```
With no file given, it uses the example booth in `examples/`. Produces `<job>_Spec_Packet.pdf` (and `.html`) —
the sheet you send the client: every graphic's size, finish, what's visible, and the build rules. It reads the
**same JSON**, so it can never disagree with the templates.

## 3) Check a client's artwork (AI proofer)
```
python3 tools/proofer.py <their_file.pdf>   [--panel NAME]
```
It matches the file to a panel (by filename, or use `--panel`) and reports **PASS / NEEDS REVIEW / FAIL** on:
size · color (flags RGB) · resolution (120–150 ppi) · fonts outlined · printer marks · spelling.
Produces `<file>_preflight.pdf` (a report you can keep or send back) plus a `.json`. Handles PDF / AI / EPS
and raster (TIFF/JPG/PNG/PSD).
> **Tip:** to spell-check, run it on a copy **before** fonts are outlined — outlined files have no readable text.
> The spell step uses the system word list as a stand-in; it's where an AI spell/grammar pass plugs in later.

## 4) Proof + sign-off (SEE-owned)

Turn a checked file into a **client proof sheet** — artwork preview + the preflight results + a sign-off block:
```
python3 tools/make_proof.py <artwork>  [--panel NAME]  [--job "Name"]
```
Writes `<file>_PROOF.pdf` and logs it in `proof_log.xlsx`. When the client OKs it, **stamp + lock** the record:
```
python3 tools/make_proof.py <artwork>  --approve "Client Name"
```
That writes `<file>_PROOF_APPROVED.pdf` (a dated, locked record) and updates the log. It **refuses to approve a file
that FAILs preflight.** We hold the proof; the vendor gets our approved sheet and can run their own as a second check.

---

## Set up a NEW job
**Fastest:** run `tools/intake.py` (top) on the 3D handoff to draft the JSON, then confirm it. **Or** do it by hand:
1. **Copy** the example `examples/booth_spec_….json` and rename it for the new job (keep it in this top folder, or pass it with `--spec`).
2. Edit the values — you do **not** touch the scripts:
   - `job` — name, show, booth size, location, **due date**.
   - `panels[]` — one entry per surface: `name`, `w`, `h` (full-scale finished inches), `finish`, `sided` (`single`/`double`), optional `note`.
   - **Door:** add `"door": "left"` (or `"right"`) — draws SEE's standard door cut + handle/lock holes.
   - **Keep-clear / live (TVs, shelves, fridges, displays):** add a `zones` list. `x,y` = inches from the **trim bottom-left corner**:
     ```json
     "zones": [
       { "x": 0, "y": 95.20, "w": 78.12, "h": 39.06, "label": "LIVE GRAPHIC AREA", "kind": "live" },
       { "x": 0, "y": 0,     "w": 78.12, "h": 95.20, "label": "FRIDGE - NO art",  "kind": "keepclear" }
     ]
     ```
     > A **TV or shelf** is just one `keepclear` zone with its size and position.
3. Run the tools above.

**Settings** live in the JSON's `settings` block (rarely change): `scale: 0.5` (half scale, output 200%),
`bleed_per_side_in: 1.0` (1″/side = 2″ total — SEE standard), `safe_margin_in: 4.0`.

---

## Before sending files to print (SEE standard)
CMYK / Pantone · fonts → outlines · raster art 120–150 ppi at scale · **disable printer marks** · output at 200% if built at half scale.

## If something goes wrong
- **It doesn't ask for a JSON / uses the example** → you hit Cancel in Illustrator; re-run and pick the `booth_spec_….json`.
- **"CMYKColor is not defined"** → the `.jsx` was run somewhere other than Illustrator. It only runs via Illustrator's File ▸ Scripts.
- **A PDF didn't appear** (spec sheet / proof / report) → make sure Google Chrome is installed (the scripts use it to make PDFs); the `.html` is always produced and can be printed to PDF manually.
- **A panel is missing** → check the JSON for a missing comma between `{ … }` entries (any JSON checker will find it).
