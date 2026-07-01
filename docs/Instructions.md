# Instructions

**You don't need to know any code.** You work with **Claude** (the AI assistant): you hand it a file
and tell it what you want in plain English, and it runs the tools and gives you the results back.
Your job is to **provide the files and check the results** — not to operate anything.

> One‑time setup (a key) is done once by your AI lead — see the README. After that, just ask Claude.
> Tip: if you're ever unsure, type exactly what you want in plain words. Claude will figure out the rest.

---

## A whole job, in 5 steps

### 1 · A job is won → make the "booth file"
The **booth file** is one small file that lists every wall and its size. Everything else is built from it.

- **Give Claude:** the 3D team's placement drawings — **send every file they give you** (for example a "details" deck *and* a "renders" deck), not just one, so nothing gets missed.
- **Say:** *"Make the booth file for [Client – Show – Size] from this handoff."*
- **You get back:** a draft booth file **+ a short checklist** of things to confirm — finishes (fabric, vinyl…), which wall has the door, any TV/shelf spots, the due date.
- **If the handoff is a *picture* (a slide deck with the sizes drawn on, not typed):** Claude reads the sizes right off the images at high resolution — catching even small labels — and fills the draft for you. Each one is marked to **confirm**, and anything it can't read clearly (or that has no printed size) is flagged to **measure**, never guessed.
- **Your job:** answer the checklist (ask Marc or the 3D team if unsure) and tell Claude the answers. Done — that file now drives every step below.

### 2 · Make the wall templates (in Illustrator)
This is the one hands‑on step, done by a designer in Adobe Illustrator:

1. Open **Adobe Illustrator**.
2. **File → Scripts → Other Script…** and choose **`tools/SEE_Wall_Template_Generator.jsx`**.
3. When it asks, pick the **booth file**.

You'll get one ready‑to‑design template per wall (the colored guide lines are explained at the bottom).
*Not a designer? Ask Claude to walk you through it.*

> **One exception — very large pieces.** If a graphic is bigger than Illustrator can fit on a single canvas (roughly **37 feet — about 450 inches — on a side**, e.g. a full-circumference hanging sign), it's **flagged to "tile/seam separately"** instead of built as one template. That's the right call, not a gap: a piece that size is printed in sections and seamed together anyway, so there was never one single sheet to make. It still appears on the client spec sheet, still gets checked, and still shows on the proof — only that one oversized template is skipped. Every normal wall, counter, and panel is well under the limit and templates as usual.

**Quick look without Illustrator:** ask Claude — *"show me what the wall templates will look like"* — and it generates a preview image of all the panels straight from the booth file.

### 3 · Tell the client what to send
- **Say:** *"Make the client spec sheet from the booth file."*
- **You get back:** a clean PDF — the sheet you email the client — listing every graphic's **size, material, finishing type, and quantity**, the build rules, the **job number**, and the due date.
- **Want to go further than a list?** Say: *"Make the client design templates."* You get **one PDF with a page per graphic**, each showing the exact artboard with the bleed, trim, safe and keep‑clear guides drawn on it, plus the true sizes — so the client designs **right on the guides** (no Illustrator needed). It heads off wrong‑size and missing‑bleed files at the source. *(A piece too big for one sheet is marked "tile/seam" — our team handles the seaming.)*

### 4 · Client sends artwork back → check it
- **Give Claude:** the client's file(s).
- **Say:** *"Check this artwork against the booth file."*
- **You get back:** a **PASS / NEEDS REVIEW / FAIL** report that catches wrong size, low resolution, RGB‑instead‑of‑CMYK, fonts not outlined, and spelling — with notes on what to fix.
- **Plus a plain‑English fix list.** When something's off, the report adds a **"What to change"** list written for the client — for example *"Resize to 78.12″ × 134.26″ and add 1″ bleed on every side,"* or *"Convert the file to CMYK"* — and a **marked‑up preview**. Claude **never edits the client's file** (an automatic color or size change could ruin a print run); it tells them exactly what to fix, so you can forward it as‑is. The same fix list also appears on the proof.

### 5 · Send a proof and get sign‑off
- **Say:** *"Make a proof sheet for this artwork."*
- **You get back:** one standardized proof — the artwork, a full **spec list** (size, material, finishing, quantity, sides, seams, revision), the automated checks with a color key, a clear **review notice**, a **three‑way sign‑off** (approve as‑is / approve with changes / resubmit), and a footer showing who prepped and QC'd it.
- **Helpful to add:** *"prepped by [name], QC'd by [name], for delivery"* — Claude puts those on the sheet (a real name, never a placeholder).
- When the client approves it, **say:** *"Mark it approved by [client name]."*
- **You get back:** a dated, **locked** approval record (and it's logged). Claude won't finalize an approval if the file still **fails a check** *or* if anything is still marked **"to be confirmed"** — so no half‑finished proof reaches a client.
- **For a whole job at once:** give Claude **all** the graphics files together and say *"Make the full proof document for this job."* You get **one PDF** — a **cover page** that lists every graphic (size, material, quantity) and then one page per graphic for the client to review and sign.

---

## See every job at a glance
- **Say:** *"Show me the job dashboard."*
- **You get back:** one page listing **every active job** and where it stands — **Intake → Awaiting confirm → In proof → Approved** — with the due date, a countdown, and **risk flags** (a size still unconfirmed, a failed check, or a deadline coming up). It reads straight from the booth files and the proof log, so it always matches the other tools. *(Point Claude at your jobs folder once and it tracks them all.)*

---

## What the template colors mean
| Color | Means |
|-------|-------|
| **Cyan** | Bleed — extend artwork out to here |
| **Black** | Trim — the finished, cut size |
| **Magenta** | Safe area — keep logos & text inside this |
| **Orange** | Keep‑clear — a fridge / TV / shelf sits here, **no artwork** |
| **Green** | Live area — where the artwork actually shows |
| **Red** | A door — the cut and its handle/lock holes |

---

## If anything looks off
Just **tell Claude what you see** in plain words — for example:
- *"The spec sheet is missing wall F2."*
- *"This proof says FAIL on color — what does that mean?"*
- *"Change the due date on the booth file to July 10."*

Claude will explain it and fix it. You never edit the files by hand.
