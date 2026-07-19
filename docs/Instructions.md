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
- **If the handoff is a *picture* (a slide deck with the sizes drawn on, not typed):** Claude reads the sizes right off the images at high resolution — catching even small labels — and fills the draft for you. Each one is marked to **confirm**, and anything it can't read clearly (or that has no printed size) is flagged to **measure** — every size read this way is always flagged for your confirmation before it drives anything downstream.
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
- **You get back:** a polished, **fully branded slide deck** (a PDF, every page **16″ × 9″**) built to match SEE's official 2025 client presentation — the packet you email the client. It runs: a **cover** (client name + show + booth size, on SEE's signature geometric background), a **Who We Are** page, a **project‑info** page (version, designer, account rep, job #, graphic due date, location), an **overall 3D booth rendering** on its own page, one or more **graphic‑placement** pages (the labeled drawings that show *where each graphic goes* — if the booth has several placement views, like a separate one per wall group, each gets its own page so all the callouts show), a **Graphics to Submit** section (every graphic's size, material, finishing type, quantity — which automatically runs onto **as many pages as it takes**, so even a big booth with dozens of graphics never drops one off the sheet), an **Artwork Guidelines** page (the build rules laid out cleanly with the accepted file‑format icons), and a **Thank You** close. Same SEE logo, brand red, and fonts throughout.
- **Renderings, if you have them:** the booth file can point to two images — a **`rendering_3d`** (the photoreal 3D view of the finished booth) becomes the 3D Booth Rendering page, and a **`rendering`** (the labeled placement view showing which graphic goes where) becomes the Graphic‑Placement page. Both come straight from the 3D handoff/intake files. Either can be omitted and its page is simply skipped.
- **The official branded pages** (Who We Are, Thank You) come from SEE's real brand deck and appear automatically when the brand assets are on the machine (the local‑only `assets/brand/` folder). On a public checkout without that folder, those two image pages are skipped; the cover, info, graphics, and Artwork Guidelines pages always render.
- **Want to go further than a list?** Say: *"Make the client design templates."* You get **one PDF with a page per graphic**, each showing the exact artboard with the bleed, trim, safe and keep‑clear guides drawn on it, plus the true sizes **and the ½‑scale build size** (SEE builds at half scale and prints at 200%) — so the client designs **right on the guides** (no Illustrator needed). It heads off wrong‑size and missing‑bleed files at the source. *(A piece too big for one sheet is normally marked "tile/seam" — our team handles the seaming; but a graphic meant to print in one continuous piece is drawn whole with the **door openings marked** on it.)*

### 4 · Client sends artwork back → check it
- **Give Claude:** the client's file(s).
- **Say:** *"Check this artwork against the booth file."*
- **You get back:** a **PASS / NEEDS REVIEW / FAIL** report that catches wrong size or missing bleed, low resolution, RGB‑instead‑of‑CMYK, fonts not outlined, and misspellings — with notes on what to fix. *(The spelling check is a dictionary‑based advisory: it needs live, selectable text, so a file with all type outlined — which is what we ask for — reports "no readable text (already outlined)" rather than a spelling result. It flags words for a human to look at; it isn't an AI proofread.)*
- **Plus a plain‑English fix list.** When something's off, the report adds a **"What to change"** list written for the client — for example *"Resize to 78.12″ × 134.26″ and add 1″ bleed on every side,"* or *"Convert the file to CMYK"* — and a **marked‑up preview**. Claude **never edits the client's file** (an automatic color or size change could ruin a print run); it tells them exactly what to fix, so you can forward it as‑is. The same fix list also appears on the proof.

### 5 · Send a proof and get sign‑off
- **Say:** *"Make a proof sheet for this artwork."*
- **You get back:** one standardized proof — the artwork, a full **spec list** (size, material, finishing, quantity, sides, seams, revision), the automated checks with a color key, a clear **review notice**, a **three‑way sign‑off** (approve as‑is / approve with changes / resubmit), and a footer showing who prepped and QC'd it.
- **Helpful to add:** *"prepped by [name], QC'd by [name], for delivery"* — Claude puts those on the sheet (a real name, never a placeholder).
- When the client approves it, **say:** *"Mark it approved by [client name]."*
- **You get back:** a dated approval, **stamped on the proof and logged**. Claude won't finalize an approval if the file still **fails a check**, if the size couldn't be verified, or if anything is still marked **"to be confirmed"** — so no half‑finished proof reaches a client. If the checks say **NEEDS REVIEW**, Claude asks you to acknowledge the flagged items with a short reason (e.g. *"checked the spelling flag manually — it's a brand name"*); the reason is recorded on the proof and in the log. And if the approval can't be written to the log, it isn't stamped at all.
- **For a whole job at once:** give Claude **all** the graphics files together and say *"Make the full proof document for this job."* You get **one PDF** — a **cover page** that lists every graphic (size, material, quantity) and carries the job details (prepped by, QC'd by, job #, version, fulfillment) **once**, then one page per graphic — each graphic on its **own single page** — for the client to review and sign.

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
