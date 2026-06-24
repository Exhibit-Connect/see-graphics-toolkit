# Intake review — Mamas Creations IDDBA 2026

Source handoff: `Mamas-Creations_IDDBA_Graphic_Dimensions_042126.1.pdf`  ·  **DRAFT — a person must confirm this before it feeds production.**

## Panels found by the text pass (15)

| Panel | W | H |
|---|---|---|
| A | 78.12" | 173.32" |
| B | 78.12" | 173.32" |
| C | 78.12" | 173.32" |
| D | 78.12" | 173.32" |
| E1 | 117.18" | 114.7" |
| E2 | 117.18" | 114.7" |
| E Soffit | 117.0" | 9.76" |
| F1 | 78.12" | 39.06" |
| F2 | 41.31" | 134.26" |
| F3 | 78.12" | 134.26" |
| F4 | 41.31" | 134.26" |
| Counter Graphic 1 | 58.5" | 37.5" |
| Counter Graphic 2 | 58.5" | 37.5" |
| L Shape Counter Front | 100.0" | 37.5" |
| L Shape Counter Side | 59.5" | 37.5" |

Per-wall "Full Scale Trim" confirmations found: 2

## Confirm / fill before use

- [ ] **Finish / substrate** per panel (text pass can't see it — currently TBD)
- [ ] **Single vs double-sided** per structure (defaulted to single)
- [ ] **Door** — which wall + side (lift hardware from the 1Mx8 templates)
- [ ] **Keep-clear zones** — TVs, shelves, fridges, displays: size + position
- [ ] **Due date**

### ⚠ Dimension conflicts (same panel, two sizes)
- **L Shape Counter Side**: 59.5x37.5 vs 59.0x37.5 — pick one

### Notes pulled from the package
- Hanging Sign present — uses a vendor template (exclude from generation).
- Interior fridge-display fabric referenced (sizes by the note: 39.06x134.26, 78.12x134.26) — confirm + add fabric panels.
- Shelves referenced ('shelfs can be placed on this wall') — confirm wall, size, position; add as keep-clear zones.

## AI enrichment pass
- **dry-run** (no API key). Model `google/gemini-3.5-flash`. Request written to `_intake_ai_dryrun.json` — set `OPENROUTER_API_KEY` and re-run with `--ai` to execute.
