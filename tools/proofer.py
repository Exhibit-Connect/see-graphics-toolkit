#!/usr/bin/env python3
"""
SEE AI Proofer (Phase 3) - automated preflight.

Checks a client's submitted artwork against the booth-spec JSON (the SAME
single source of truth the templates and spec sheet use) and reports
PASS / WARN / FAIL per check:

    size        finished size + bleed match the panel (full OR half scale)
    color       CMYK / Pantone (flags RGB)
    resolution  raster images 120-150 ppi at scale (flags low/over-res)
    fonts       converted to outlines (flags live text)
    marks       printer marks appear disabled
    spelling    flags possible misspellings (needs live text)

Usage:
    python3 proofer.py <artwork.pdf|.ai|.eps|.tif|.jpg|.png|.psd> [--spec booth_spec.json] [--panel NAME]

Free / zero-install: pypdf + Pillow + Ghostscript + system dictionary;
branded PDF report via headless Chrome. Network not required.
NOTE: spelling here uses the system word list as an offline stand-in - this
is exactly where an AI/LLM spell+grammar pass plugs in when keys are available.
"""
import json, sys, os, re, math, subprocess, html, base64
import branding
import render

RED = branding.RED
DICT = "/usr/share/dict/words"
TOL = 0.08  # inch tolerance on size checks
RASTER_EXT = (".tif", ".tiff", ".jpg", ".jpeg", ".png", ".psd", ".bmp", ".gif")
MAX_FORM_DEPTH = 16  # recursion cap when walking nested Form XObjects


# ---------- spec / panel matching ----------
def norm(s):
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def find_panel(spec, fname, panel_arg):
    panels = spec.get("panels", [])
    if panel_arg:
        for p in panels:
            if norm(p["name"]) == norm(panel_arg):
                return p, "named explicitly"
    stem = norm(os.path.splitext(os.path.basename(fname))[0])
    # longest panel-name that appears in the filename wins (avoids 'A' matching everything)
    best = None
    for p in panels:
        if norm(p["name"]) and norm(p["name"]) in stem:
            if best is None or len(norm(p["name"])) > len(norm(best["name"])):
                best = p
    if best:
        return best, "matched from filename"
    return None, None


def unverified_panels(spec):
    """Names of panels whose dimensions are NOT yet human-verified - e.g. seeded by
    AI/OCR from a visual handoff and still flagged `needs_confirm`. Print-critical,
    client-facing tools (spec sheet, proof approval) must refuse or loudly warn until
    a human signs these off, so an unconfirmed size can never reach production. Pure."""
    return [p.get("name", "?") for p in spec.get("panels", []) if p.get("needs_confirm")]


def expected_sizes(spec, p):
    """All acceptable (w,h) in inches: full/half scale, trim and bleed-box."""
    b = spec.get("settings", {}).get("bleed_per_side_in", 1.0)
    sc = spec.get("settings", {}).get("scale", 0.5)
    w, h = p["w"], p["h"]
    out = {
        "full trim": (w, h),
        "full + bleed": (w + 2 * b, h + 2 * b),
        "half trim": (w * sc, h * sc),
        "half + bleed": ((w + 2 * b) * sc, (h + 2 * b) * sc),
    }
    return out, b, sc


def size_match(w_in, h_in, expected):
    for label, (ew, eh) in expected.items():
        if abs(w_in - ew) <= TOL and abs(h_in - eh) <= TOL:
            return label
        if abs(w_in - eh) <= TOL and abs(h_in - ew) <= TOL:
            return label + " (rotated)"
    return None


# ---------- PDF analysis ----------
def resolve_cs(cs):
    try:
        if hasattr(cs, "get_object"):
            cs = cs.get_object()
    except Exception:
        pass
    s = str(cs)
    if isinstance(cs, list) or "ICCBased" in s:
        try:
            for el in cs:
                el = el.get_object() if hasattr(el, "get_object") else el
                n = None
                try:
                    n = int(el.get("/N"))
                except Exception:
                    pass
                if n == 4:
                    return "CMYK"
                if n == 3:
                    return "RGB"
                if n == 1:
                    return "Gray"
        except Exception:
            pass
    if "DeviceCMYK" in s:
        return "CMYK"
    if "DeviceRGB" in s or "CalRGB" in s:
        return "RGB"
    if "DeviceGray" in s or "CalGray" in s:
        return "Gray"
    if "Separation" in s or "DeviceN" in s:
        return "Spot/Separation"
    if "Indexed" in s:
        return "Indexed"
    return "Unknown"


def mat_mul(m, c):  # PDF: new_CTM = m . c  (m,c = [a,b,c,d,e,f])
    a, b, cc, d, e, f = m
    A, B, C, D, E, F = c
    return [a * A + b * C, a * B + b * D, cc * A + d * C, cc * B + d * D,
            e * A + f * C + E, e * B + f * D + F]


def _do_ctms(content, base=None):
    """[(xobject_name, ctm), ...] for every `/Name Do` in a content stream,
    tracking the graphics-state CTM (q / Q / cm). `base` seeds the CTM so a
    Form XObject's stream can be scanned in its placed coordinate space."""
    base = list(base) if base else [1, 0, 0, 1, 0, 0]
    # numbers may be leading-dot decimals (`.5`, `-.25`) - common in real exports
    toks = re.findall(r"/[^\s/<>\[\]()]+|-?(?:\d+\.?\d*|\.\d+)|[a-zA-Z*'\"]+", content)
    ctm = base[:]; stack = []; nums = []; last_name = None; out = []
    for t in toks:
        if re.match(r"^-?(?:\d+\.?\d*|\.\d+)$", t):
            nums.append(float(t)); continue
        if t.startswith("/"):
            last_name = t[1:]
        elif t == "cm" and len(nums) >= 6:
            ctm = mat_mul(nums[-6:], ctm); nums = []
        elif t == "q":
            stack.append(ctm[:]); nums = []
        elif t == "Q":
            ctm = stack.pop() if stack else base[:]; nums = []
        elif t == "Do":
            if last_name:
                out.append((last_name, ctm[:]))
            nums = []
        else:
            nums = []
    return out


def image_placements(content, img_names):
    """Return {name: (placed_w_pt, placed_h_pt)} by tracking the CTM to each `/Name Do`."""
    placed = {}
    for nm, ctm in _do_ctms(content):
        if nm in img_names:
            a, b, c, d = ctm[0], ctm[1], ctm[2], ctm[3]
            placed[nm] = (math.hypot(a, b), math.hypot(c, d))
    return placed


def _deref(o):
    return o.get_object() if hasattr(o, "get_object") else o


def _decoded_stream(s, label, gaps):
    """Decode a pypdf stream object, recording an analysis gap on failure.
    pypdf returns b'' (with only a logged warning) when a stream's filter
    can't decode the data - that silent failure must be surfaced, not treated
    as an empty (clean) stream."""
    def note(reason):
        if gaps is not None:
            gaps.append(f"{label} could not be decoded: {reason}")
    try:
        data = s.get_data()
    except Exception as e:
        note(e)
        return ""
    if not data:
        raw = getattr(s, "_data", b"") or b""
        flt = str(s.get("/Filter") or "")
        if raw and flt:
            genuinely_empty = False
            if "FlateDecode" in flt:
                try:
                    import zlib
                    genuinely_empty = zlib.decompress(raw) == b""
                except Exception:
                    genuinely_empty = False
            if not genuinely_empty:
                note("stream filter produced no data")
                return ""
    return data.decode("latin-1", "replace")


def page_content(page, gaps=None):
    """Decoded content stream, with a direct /Contents fallback (some writers,
    e.g. Chrome, return nothing from get_contents()). When `gaps` (a list) is
    given, a stream that exists but cannot be decoded records an analysis gap
    instead of silently vanishing."""
    try:
        d = page.get_contents()
        if d:
            t = d.get_data().decode("latin-1", "replace")
            if t.strip():
                return t
    except Exception:
        pass  # fall through to the direct /Contents path
    try:
        co = _deref(page.get("/Contents"))
        if co is None:
            return ""
        items = co if isinstance(co, list) else [co]
        out = ""
        for s in items:
            out += _decoded_stream(_deref(s), "content stream", gaps)
        return out
    except Exception as e:
        if gaps is not None:
            gaps.append(f"content stream could not be decoded: {e}")
        return ""


# matches an inline image (BI ... ID) - pypdf gives us no dims/colorspace for
# these, so their presence is recorded as an analysis gap
INLINE_IMG_RE = re.compile(r"(?<![A-Za-z0-9])BI(?![A-Za-z0-9])[\s\S]+?(?<![A-Za-z0-9])ID(?![A-Za-z0-9])")


def _scan_context(res, content, base_ctm, info, images, visited, depth):
    """Collect fonts / colorspaces / images from one content context (a page or
    a Form XObject) into `info` and `images`, recursing into nested Form
    XObjects with their /Matrix composed onto the placing CTM. Any object that
    cannot be read is recorded in info['analysis_gaps'] - analysis failures
    must never look like a clean file."""
    gaps = info["analysis_gaps"]
    res = _deref(res) or {}
    fonts = _deref(res.get("/Font"))
    if fonts:
        info["fonts"] += len(fonts)
    csres = _deref(res.get("/ColorSpace"))
    if csres:
        for v in csres.values():
            info["colors"].add(resolve_cs(v))
    shres = _deref(res.get("/Shading"))
    if shres:
        for v in shres.values():
            try:
                info["colors"].add(resolve_cs(_deref(v).get("/ColorSpace")))
            except Exception as e:
                gaps.append(f"shading resource could not be parsed: {e}")
    patres = _deref(res.get("/Pattern"))
    if patres:
        for v in patres.values():
            try:
                sh = _deref(_deref(v).get("/Shading"))
                if sh:
                    info["colors"].add(resolve_cs(sh.get("/ColorSpace")))
            except Exception as e:
                gaps.append(f"pattern resource could not be parsed: {e}")
    xo = _deref(res.get("/XObject"))
    img_dims, forms = {}, {}
    if xo:
        for name, ref in xo.items():
            key = (ref.idnum, ref.generation) if hasattr(ref, "idnum") else None
            try:
                o = _deref(ref)
                sub = str(o.get("/Subtype"))
                if sub == "/Image":
                    w = int(o["/Width"]); h = int(o["/Height"])
                    img_dims[name.lstrip("/")] = (w, h)
                    info["colors"].add(resolve_cs(o.get("/ColorSpace")))
                elif sub == "/Form":
                    forms[name.lstrip("/")] = (o, key)
            except Exception as e:
                gaps.append(f"XObject '{name}' could not be parsed: {e}")
    dos = _do_ctms(content, base_ctm) if content else []
    if content:
        # inline fill/stroke colour operators (catches RGB/CMYK in vector art, not just images)
        ops = set(re.findall(r"(?<![A-Za-z0-9])(rg|RG|k|K)(?![A-Za-z0-9])", content))
        if "rg" in ops or "RG" in ops:
            info["colors"].add("RGB")
        if "k" in ops or "K" in ops:
            info["colors"].add("CMYK")
        if INLINE_IMG_RE.search(content):
            gaps.append("inline image (BI/ID/EI) present - not analyzed")
    placed = {}
    for nm, ctm in dos:
        if nm in img_dims:
            a, b, c, d = ctm[0], ctm[1], ctm[2], ctm[3]
            placed[nm] = (math.hypot(a, b), math.hypot(c, d))
    for nm, (pw, ph) in img_dims.items():
        images.append({"px": (pw, ph), "placed_pt": placed.get(nm)})
    # recurse into Form XObjects (Illustrator/InDesign exports wrap most
    # content in Forms - their fonts/images were previously invisible)
    form_place = {nm: ctm for nm, ctm in dos if nm in forms}
    for nm, (o, key) in forms.items():
        if key is not None:
            if key in visited:
                continue  # cycle (or an already-scanned shared form)
            visited.add(key)
        if depth >= MAX_FORM_DEPTH:
            gaps.append(f"form nesting deeper than {MAX_FORM_DEPTH} - not fully analyzed")
            continue
        place = form_place.get(nm, list(base_ctm) if base_ctm else [1, 0, 0, 1, 0, 0])
        try:
            mtx = [float(x) for x in (o.get("/Matrix") or [1, 0, 0, 1, 0, 0])]
        except Exception:
            mtx = [1, 0, 0, 1, 0, 0]
        eff = mat_mul(mtx, place)
        fcontent = _decoded_stream(o, f"form XObject '{nm}' stream", gaps)
        try:
            _scan_context(o.get("/Resources"), fcontent, eff, info, images, visited, depth + 1)
        except Exception as e:
            gaps.append(f"form XObject '{nm}' could not be analyzed: {e}")


def analyze_pdf(path):
    """Analyze EVERY page of the PDF (multi-page submissions used to have
    pages 2+ completely unchecked). Colors / fonts / images / text aggregate
    across pages; per-page sizes are recorded in info['page_sizes'] so
    check_size can flag a page that matches no expected size. media_in /
    trim_in / marks_margin_in stay page-1-based for backward compatibility."""
    from pypdf import PdfReader
    r = PdfReader(path)
    info = {"kind": "pdf", "pages": len(r.pages),
            "media_in": None, "trim_in": None, "fonts": 0, "colors": set(),
            "images": [], "min_ppi": None, "text": "", "marks_margin_in": None,
            "analysis_gaps": [], "page_sizes": []}
    visited = set()
    texts = []
    for pno, page in enumerate(r.pages, 1):
        mb = page.mediabox
        media_in = (float(mb.width) / 72.0, float(mb.height) / 72.0)
        trim_in = None
        if "/TrimBox" in page:
            tb = page.trimbox
            trim_in = (float(tb.width) / 72.0, float(tb.height) / 72.0)
        if pno == 1:
            info["media_in"], info["trim_in"] = media_in, trim_in
        info["page_sizes"].append({"page": pno, "media_in": media_in, "trim_in": trim_in})
        content = page_content(page, info["analysis_gaps"])
        raw_images = []
        _scan_context(page.get("/Resources"), content, None, info, raw_images,
                      visited=visited, depth=0)
        trim_w = (trim_in or media_in)[0]
        for im in raw_images:
            pw, ph = im["px"]
            placed = im["placed_pt"]
            if placed and placed[0] > 1 and placed[1] > 1:
                # grade the WORST axis - vertical stretch degrades print too
                ppi = min(pw / (placed[0] / 72.0), ph / (placed[1] / 72.0))
                how = "placed"
            elif placed and placed[0] > 1:
                ppi = pw / (placed[0] / 72.0)
                how = "placed"
            else:
                ppi = pw / trim_w if trim_w else 0  # fallback: assume full-width placement
                how = "assumed full-width"
            info["images"].append({"px": (pw, ph), "ppi": round(ppi), "how": how})
        try:
            t = (page.extract_text() or "").strip()
            if t:
                texts.append(t)
        except Exception:
            pass
    info["text"] = "\n".join(texts)
    if info["images"]:
        info["min_ppi"] = min(i["ppi"] for i in info["images"])
    if info["trim_in"]:
        mw, tw = info["media_in"][0], info["trim_in"][0]
        info["marks_margin_in"] = round((mw - tw) / 2.0, 3)
    if "Unknown" in info["colors"]:
        info["colors"].discard("Unknown")
        info["analysis_gaps"].append("unidentified colorspace could not be resolved")
    return info


def analyze_raster(path):
    from PIL import Image
    im = Image.open(path)
    dpi = im.info.get("dpi")
    return {"kind": "raster", "px": im.size, "mode": im.mode,
            "dpi": (round(dpi[0]) if dpi else None)}


# ---------- checks ----------
def _bare_trim_scale(label, sc):
    """(is_bare_trim, matched_scale) for a size_match label. Bare-trim labels
    ('full trim' / 'half trim', possibly '(rotated)') mean the file is exactly
    finished size - i.e. it contains NO bleed unless the boxes prove otherwise."""
    base = (label or "").split(" (")[0]
    if base == "full trim":
        return True, 1.0
    if base == "half trim":
        return True, sc
    return False, (sc if base.startswith("half") else 1.0)


def check_size(info, spec, p):
    expected, b, sc = expected_sizes(spec, p)
    if info["kind"] == "pdf":
        tw, th = (info["trim_in"] or info["media_in"])
        m = size_match(tw, th, expected)
        size_txt = f'{tw:.2f}" x {th:.2f}" ({"trim" if info["trim_in"] else "media (no TrimBox)"})'
        # every page must match an expected size, not just page 1
        bad_pages = []
        for ps in info.get("page_sizes", [])[1:]:
            pw2, ph2 = (ps["trim_in"] or ps["media_in"])
            if not size_match(pw2, ph2, expected):
                bad_pages.append(f'page {ps["page"]} is {pw2:.2f}" x {ph2:.2f}"')
        if bad_pages:
            return "FAIL", (f'{size_txt}{" matches " + m if m else ""}, but ' + "; ".join(bad_pages) +
                            ' - no expected size matches (submit one panel per file)')
        if m:
            bare, mscale = _bare_trim_scale(m, sc)
            if bare:
                eb = b * mscale
                margin = info.get("marks_margin_in")
                # evidence of bleed = a TrimBox whose media margin covers the
                # expected (scaled) bleed; otherwise the cut will show white edges
                if margin is None or margin < eb - TOL:
                    why = (f'media extends only {margin:g}" past trim' if margin is not None
                           else "no TrimBox set")
                    return "WARN", (f'{size_txt} matches trim size ({m}) but no bleed detected '
                                    f'({why}) — add {eb:g}" bleed per side')
            extra = "" if info["trim_in"] else "  - no TrimBox set, could not isolate bleed"
            return "PASS", f'{size_txt} matches {m}{extra}'
        return "FAIL", f'{size_txt} - expected one of: ' + "; ".join(f'{k} {w:.2f}x{h:.2f}' for k, (w, h) in expected.items())
    else:
        px, py = info["px"]
        if info["dpi"]:
            w_in, h_in = px / info["dpi"], py / info["dpi"]
            m = size_match(w_in, h_in, expected)
            if m:
                bare, mscale = _bare_trim_scale(m, sc)
                if bare:
                    eb = b * mscale
                    return "WARN", (f'{w_in:.2f}" x {h_in:.2f}" at {info["dpi"]} dpi matches trim '
                                    f'size ({m}) but no bleed detected (raster canvas is exactly '
                                    f'finished size) — add {eb:g}" bleed per side')
                return "PASS", f'{w_in:.2f}" x {h_in:.2f}" at {info["dpi"]} dpi matches {m}'
            return "FAIL", f'{w_in:.2f}" x {h_in:.2f}" at {info["dpi"]} dpi - no panel-size match'
        return "WARN", f'{px}x{py}px, no embedded size/DPI - cannot verify finished size (ask for a sized PDF)'


def check_color(info):
    if info["kind"] == "raster":
        mode = info["mode"]
        if mode == "CMYK":
            return "PASS", "CMYK"
        if mode in ("RGB", "RGBA"):
            return "FAIL", f"{mode} - convert to CMYK"
        if mode in ("L", "1", "LA"):
            return "WARN", f"{mode} (grayscale)"
        return "WARN", f"mode {mode}"
    colors = info["colors"]
    gaps = info.get("analysis_gaps") or []
    if not colors:
        if gaps:
            return "WARN", (f"no color spaces detected, and {len(gaps)} object(s) could not be "
                            f"analyzed - color cannot be confirmed")
        return "WARN", "no color spaces detected"
    if "RGB" in colors:
        return "FAIL", "contains RGB - " + ", ".join(sorted(colors))
    if "CMYK" in colors or "Spot/Separation" in colors:
        if gaps:
            return "WARN", (", ".join(sorted(colors)) +
                            f" - but {len(gaps)} object(s)/colorspace(s) could not be analyzed, "
                            f"so color cannot be fully confirmed")
        return "PASS", ", ".join(sorted(colors))
    return "WARN", ", ".join(sorted(colors))


def check_resolution(info):
    if info["kind"] == "raster":
        d = info["dpi"]
        if not d:
            return "WARN", "no DPI tag - cannot verify resolution at print size"
        if d < 120:
            return "FAIL", f"{d} ppi (< 120)"
        if d > 150:
            return "WARN", f"{d} ppi (> 150, more than needed)"
        return "PASS", f"{d} ppi"
    if not info["images"]:
        gaps = info.get("analysis_gaps") or []
        if gaps:
            return "WARN", (f"could not fully analyze {len(gaps)} object(s) - unable to confirm "
                            f"the file is vector-only, so resolution is unverified")
        return "PASS", "no raster images (vector) - resolution not a factor"
    lo = min(i["ppi"] for i in info["images"])
    hi = max(i["ppi"] for i in info["images"])
    detail = ", ".join(f'{i["px"][0]}x{i["px"][1]}px -> {i["ppi"]}ppi ({i["how"]})' for i in info["images"][:6])
    if lo < 120:
        return "FAIL", f"lowest image {lo} ppi (< 120). {detail}"
    if hi > 150:
        return "WARN", f"highest image {hi} ppi (> 150, more than needed). {detail}"
    return "PASS", f"{lo}-{hi} ppi. {detail}"


def check_fonts(info):
    if info["kind"] == "raster":
        return "NA", "raster file - no fonts"
    if info["fonts"] > 0:
        return "WARN", f'{info["fonts"]} live font(s) - NOT outlined (enables spell-check, but outline before final print)'
    form_gaps = [g for g in info.get("analysis_gaps", []) if g.startswith("form")]
    if form_gaps:
        return "WARN", (f"no live fonts found, but {len(form_gaps)} form object(s) could not be "
                        f"fully analyzed - cannot confirm text is outlined")
    return "PASS", "no live fonts - text is outlined"


def check_marks(info):
    if info["kind"] != "pdf" or info["marks_margin_in"] is None:
        return "NA", "no TrimBox - cannot assess printer marks"
    if info["marks_margin_in"] > 2.5:
        return "WARN", f'{info["marks_margin_in"]}" beyond trim per side - possible crop/registration marks'
    return "PASS", f'{info["marks_margin_in"]}" beyond trim per side - no obvious marks'


def check_spelling(info):
    text = info.get("text", "")
    if not text:
        if info["kind"] == "pdf" and info.get("fonts", 0) == 0:
            return "NA", "no readable text (already outlined) - send a pre-outline copy to spell-check"
        return "NA", "no readable text"
    if not os.path.exists(DICT):
        return "NA", "system dictionary unavailable"
    words = set(w.strip().lower() for w in open(DICT, encoding="latin-1"))
    seen, bad = set(), []
    for tok in re.findall(r"[A-Za-z][A-Za-z'\-]{2,}", text):
        low = tok.lower().strip("'-")
        if low in seen:
            continue
        seen.add(low)
        if tok.isupper():            # skip acronyms / all-caps display type
            continue
        cands = {low, low.replace("'", ""), low.rstrip("s"), low + "s"}
        for suf in ("ed", "ing", "ly", "er", "es", "d"):   # tolerate common inflections
            if low.endswith(suf) and len(low) - len(suf) >= 3:
                cands.add(low[:-len(suf)])
                cands.add(low[:-len(suf)] + "e")
        if any(c in words for c in cands):
            continue
        bad.append(tok)
    if bad:
        return "WARN", f'{len(bad)} word(s) to review (may include brand/proper names): ' + ", ".join(bad[:25])
    return "PASS", "no obvious misspellings"


def run_checks(path, spec, panel_arg=None):
    """Match file -> panel, analyze, run every check. Returns
    {panel, how, info, results, verdict} or None if no panel matched.
    Shared by the CLI and by make_proof.py so the checks never diverge."""
    panel, how = find_panel(spec, path, panel_arg)
    if not panel:
        return None
    ext = os.path.splitext(path)[1].lower()
    info = analyze_raster(path) if ext in RASTER_EXT else analyze_pdf(path)
    results = {"size": check_size(info, spec, panel), "color": check_color(info)}
    rc = check_resolution(info)
    if rc:
        results["resolution"] = rc
    results["fonts"] = check_fonts(info)
    results["marks"] = check_marks(info)
    results["spelling"] = check_spelling(info)
    statuses = [s for s, _ in results.values()]
    verdict = "FAIL" if "FAIL" in statuses else ("REVIEW" if "WARN" in statuses else "PASS")
    fixes = fix_instructions(results, info, spec, panel)
    return {"panel": panel, "how": how, "info": info, "results": results,
            "verdict": verdict, "fixes": fixes}


# ---------- fix-it instructions + marked-up preview (never alters the file) ----------
def fix_instructions(results, info, spec, panel):
    """Translate each non-PASS check into a precise, plain-English instruction a
    client can act on (the exact target size, the CMYK step, the ppi threshold,
    etc.). We NEVER change the artwork — we only say exactly what to fix.
    Deterministic + pure: reads the already-computed `results`/`info` + the booth
    spec. Returns [{check, severity, text}, ...] — empty when everything PASSES."""
    exp, bleed, sc = expected_sizes(spec, panel)
    fixes = []

    def add(check, status, text):
        fixes.append({"check": check, "severity": status, "text": text})

    st, sdetail = results.get("size", ("PASS", ""))
    if st == "FAIL":
        ftw, fth = exp["full trim"]
        fbw, fbh = exp["full + bleed"]
        hbw, hbh = exp["half + bleed"]
        add("size", st,
            f'Resize to the panel. Finished (trim) size is {ftw:g}" × {fth:g}"; add {bleed:g}" bleed on every '
            f'side and deliver {fbw:g}" × {fbh:g}". (Half scale — {hbw:g}" × {hbh:g}" — is also accepted.)')
    elif st == "WARN" and "no bleed detected" in sdetail:
        fbw, fbh = exp["full + bleed"]
        hbw, hbh = exp["half + bleed"]
        add("size", st,
            f'Add {bleed:g}" bleed on every side — the file matches the finished (trim) size but includes '
            f'no bleed, which risks white edges at the cut. Extend the artwork past the trim and deliver '
            f'{fbw:g}" × {fbh:g}" (half-scale files: {hbw:g}" × {hbh:g}").')

    st, cmsg = results.get("color", ("PASS", ""))
    if st == "FAIL":
        add("color", st,
            "Convert the file to CMYK — it currently contains RGB. Set the document color mode to CMYK and "
            "re-export; check that reds and blues still look right afterward, and use Pantone/spot colors "
            "where exact brand color matters.")
    elif st == "WARN":
        if "gray" in cmsg.lower():
            add("color", st, "This file is grayscale (black & white). If it should be full color, re-export "
                             "in CMYK; if black & white is intended, no change is needed.")
        else:
            add("color", st, "Color space couldn't be confirmed. Export as CMYK (or CMYK/Pantone) so colors "
                             "print as intended.")

    st = results.get("resolution", ("PASS", ""))[0]
    ppi = info.get("min_ppi") or info.get("dpi")   # PDFs carry min_ppi; rasters carry dpi
    if st == "FAIL":
        howlow = f"the lowest image is about {ppi} ppi" if ppi else "an image is under 120 ppi"
        add("resolution", st,
            f'Increase image resolution — {howlow} at final size, and print needs 120–150. Use a '
            f'higher-resolution original, or place the image smaller, so every image is at least 120 ppi '
            f'at the printed size.')
    elif st == "WARN" and ppi and ppi > 150:
        add("resolution", st,
            f'Resolution is higher than needed (~{ppi} ppi). 150 ppi at final size is plenty — you can '
            f'downsample to shrink the file (optional, not required).')

    if results.get("fonts", ("PASS", ""))[0] == "WARN":
        add("fonts", "WARN",
            "Convert all text to outlines (vector) before sending the final file, so fonts can't reflow or "
            "substitute. Keep a copy with live text for spell-checking.")

    if results.get("marks", ("PASS", ""))[0] == "WARN":
        add("marks", "WARN",
            "Turn OFF printer marks (crop, registration and color bars) in your export settings — submit the "
            "artwork with bleed but no marks.")

    st, smsg = results.get("spelling", ("PASS", ""))
    if st == "WARN":
        words = smsg.split(": ", 1)[-1] if ": " in smsg else ""
        text = "Double-check spelling on the flagged words (some may be brand or proper names, which are fine)."
        if words:
            text += " Words to review: " + words
        add("spelling", st, text)

    return fixes


def overlay_boxes(w_px, h_px, frac_w, frac_h):
    """Pixel rectangle (x0, y0, x1, y1) for the safe-area inset on a w×h
    thumbnail, given the safe margin as a fraction of the panel's width/height.
    Pure — the testable geometry behind the marked-up preview."""
    x0 = round(w_px * frac_w)
    y0 = round(h_px * frac_h)
    x1 = round(w_px * (1 - frac_w))
    y1 = round(h_px * (1 - frac_h))
    return x0, y0, x1, y1


def marked_preview(path, info, spec, panel, fixes):
    """Best-effort marked-up PNG (base64 data URI) of the artwork: a ribbon with
    the fix summary, plus — when the size is correct — the safe-area outline so a
    client sees where text must stay. Returns the data URI, or None if no preview
    can be made. Writes only a throwaway temp PNG; the client's file is untouched.
    Box math lives in `overlay_boxes` (pure + tested)."""
    ext = os.path.splitext(path)[1].lower()
    tmp = os.path.abspath("_proof_mark.png")
    try:
        from PIL import Image, ImageDraw
        if ext in RASTER_EXT:
            im = Image.open(path)
            if im.mode != "RGB":
                im = im.convert("RGB")
        else:
            subprocess.run(["gs", "-q", "-sDEVICE=png16m", "-r60", "-dFirstPage=1",
                            "-dLastPage=1", "-o", tmp, path], capture_output=True)
            if not os.path.exists(tmp):
                return None
            im = Image.open(tmp).convert("RGB")
        im.thumbnail((900, 900))
        W, H = im.size
        draw = ImageDraw.Draw(im, "RGBA")
        size_bad = any(f.get("check") == "size" for f in (fixes or []))
        if not size_bad and panel.get("w") and panel.get("h"):
            sm = spec.get("settings", {}).get("safe_margin_in", 4.0)
            fw = min(0.45, sm / panel["w"])
            fh = min(0.45, sm / panel["h"])
            x0, y0, x1, y1 = overlay_boxes(W, H, fw, fh)
            draw.rectangle([x0, y0, x1, y1], outline=(236, 0, 140, 255), width=2)
        labels = list(dict.fromkeys(f.get("check", "").upper() for f in (fixes or [])))
        ribbon = ("FIX: " + ", ".join(labels)) if labels else "PASS — no changes needed"
        rh = max(16, H // 24)
        draw.rectangle([0, 0, W, rh], fill=((237, 28, 36, 235) if labels else (46, 158, 64, 235)))
        draw.text((6, max(1, rh // 2 - 6)), ribbon, fill=(255, 255, 255, 255))
        im.save(tmp)
        return "data:image/png;base64," + base64.b64encode(open(tmp, "rb").read()).decode()
    except Exception:
        return None
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


# ---------- report ----------
ORDER = ["size", "color", "resolution", "fonts", "marks", "spelling"]
BADGE = {"PASS": "#2E9E40", "WARN": "#F7941E", "FAIL": RED, "NA": "#9a9a9a"}


# HTML->PDF lives in render.py now; kept as proofer.render_pdf so callers
# (make_proof.py, this module's CLI) don't change.
render_pdf = render.html_to_pdf


def build_report_html(fname, panel, how, results, verdict, fixes=None, preview_b64=None,
                      gaps=None):
    rows = ""
    for k in ORDER:
        if k not in results:
            continue
        st, msg = results[k]
        rows += f"""<tr><td class="ck">{k.title()}</td>
          <td><span class="b" style="background:{BADGE[st]}">{st}</span></td>
          <td class="msg">{html.escape(msg)}</td></tr>"""
    vcol = BADGE[verdict]
    fix_html = ""
    if fixes:
        lis = "".join(f'<li><b>{html.escape(f["check"].title())}:</b> {html.escape(f["text"])}</li>'
                      for f in fixes)
        fix_html = (f'<div class="fixes"><div class="fixhd">What to change — give this to the client</div>'
                    f'<ol>{lis}</ol></div>')
    gaps_html = ""
    if gaps:
        gl = "".join(f"<li>{html.escape(g)}</li>" for g in gaps)
        gaps_html = (f'<div class="gaps"><div class="gaphd">Analysis gaps — parts of this file '
                     f'could not be fully checked</div><ul>{gl}</ul></div>')
    mark_html = (f'<div class="mark"><img src="{preview_b64}" alt="marked-up preview">'
                 f'<div class="markcap">Marked-up preview (the file itself is unchanged)</div></div>'
                 if preview_b64 else "")
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
      @page {{ size: letter portrait; margin: 0.6in; }}
      body {{ font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; color:#1a1a1a; font-size:12px; }}
      .pill {{ background:{RED}; color:#fff; display:inline-block; padding:6px 16px; border-radius:16px; font-weight:700; }}
      h1 {{ font-size:20px; margin:10px 0 0; }}
      .meta {{ color:#555; font-size:11.5px; margin:2px 0 12px; }}
      .verdict {{ display:inline-block; color:#fff; background:{vcol}; padding:6px 16px; border-radius:8px; font-weight:700; font-size:15px; margin:6px 0 14px; }}
      table {{ width:100%; border-collapse:collapse; }}
      th {{ background:#f3f3f3; text-align:left; padding:7px 9px; border-bottom:2px solid #ccc; font-size:10.5px; text-transform:uppercase; }}
      td {{ padding:8px 9px; border-bottom:1px solid #e8e8e8; vertical-align:top; }}
      td.ck {{ font-weight:700; width:14%; }}
      .b {{ color:#fff; padding:2px 10px; border-radius:11px; font-weight:700; font-size:10.5px; }}
      .msg {{ font-size:11.5px; }}
      .fixes {{ margin:12px 0; padding:10px 14px; background:#FFF4E5; border:1px solid #F7941E; border-left:6px solid #F7941E; border-radius:5px; }}
      .fixhd {{ font-weight:700; color:#7a4a00; margin-bottom:5px; }}
      .fixes ol {{ margin:0; padding-left:20px; }}
      .fixes li {{ margin:4px 0; font-size:11.5px; color:#5a3800; }}
      .gaps {{ margin:12px 0; padding:10px 14px; background:#FFF4E5; border:1px dashed #F7941E; border-radius:5px; }}
      .gaphd {{ font-weight:700; color:#7a4a00; margin-bottom:5px; }}
      .gaps ul {{ margin:0; padding-left:20px; }}
      .gaps li {{ margin:3px 0; font-size:11px; color:#5a3800; }}
      .mark {{ margin:10px 0; text-align:center; }}
      .mark img {{ max-width:100%; max-height:340px; border:1px solid #ddd; border-radius:6px; }}
      .markcap {{ color:#999; font-size:9.5px; margin-top:4px; }}
      footer {{ margin-top:16px; color:#888; font-size:9.5px; border-top:1px solid #ddd; padding-top:6px; }}
      {branding.BRAND_CSS}
    </style></head><body>
      {branding.header_html("Artwork Preflight Report")}
      <h1>{html.escape(os.path.basename(fname))}</h1>
      <div class="meta">Panel: <b>{html.escape(panel)}</b> ({how}) &nbsp;·&nbsp; checked against the booth spec</div>
      <div class="verdict">{verdict}</div>
      {fix_html}
      {gaps_html}
      {mark_html}
      <table><thead><tr><th>Check</th><th>Result</th><th>Detail</th></tr></thead><tbody>{rows}</tbody></table>
      <footer>SEE AI Proofer · automated preflight against the single-source booth spec · WARN/FAIL items need a human's eyes before approval.</footer>
    </body></html>"""


def find_default_spec():
    """Locate a booth_spec*.json when --spec isn't given: cwd first, then an
    examples/ folder next to or above this script. Lets the tools work from
    the repo root regardless of where the spec lives."""
    import glob
    here = os.path.dirname(os.path.abspath(__file__))
    for d in (os.getcwd(), os.path.join(here, "..", "examples"),
              os.path.join(os.getcwd(), "examples"), here):
        hits = sorted(glob.glob(os.path.join(d, "*booth_spec*.json")))
        if hits:
            return hits[0]
    return "booth_spec.json"


def main():
    args = sys.argv[1:]
    spec_path = None
    panel_arg = None
    files = []
    i = 0
    while i < len(args):
        if args[i] == "--spec":
            spec_path = args[i + 1]; i += 2
        elif args[i] == "--panel":
            panel_arg = args[i + 1]; i += 2
        else:
            files.append(args[i]); i += 1
    if not files:
        print("usage: python3 proofer.py <artwork file> [--spec booth_spec.json] [--panel NAME]")
        return
    spec = json.load(open(spec_path or find_default_spec()))

    for fname in files:
        try:
            r = run_checks(fname, spec, panel_arg)
        except Exception as e:
            print(f"\n[{fname}] could not read file: {e}")
            continue
        if not r:
            print(f"\n[{fname}] could not match to a panel - re-run with --panel NAME")
            continue
        panel, how, info, results, verdict = r["panel"], r["how"], r["info"], r["results"], r["verdict"]

        print(f"\n=== {os.path.basename(fname)}  ->  panel {panel['name']} ({how})  ::  {verdict} ===")
        for k in ORDER:
            if k in results:
                st, msg = results[k]
                print(f"  [{st:4}] {k:11} {msg}")
        fixes = r.get("fixes")
        if fixes:
            print("  what to change (client-ready):")
            for f in fixes:
                print(f"    - {f['check']}: {f['text']}")
        gaps = info.get("analysis_gaps") or []
        if gaps:
            print("  analysis gaps (parts of the file could not be fully checked):")
            for g in gaps:
                print(f"    - {g}")

        base = os.path.splitext(os.path.basename(fname))[0]
        json.dump({"file": fname, "panel": panel["name"], "verdict": verdict,
                   "results": {k: {"status": v[0], "detail": v[1]} for k, v in results.items()},
                   "fixes": fixes or [], "analysis_gaps": gaps},
                  open(f"{base}_preflight.json", "w"), indent=2)
        preview = marked_preview(fname, info, spec, panel, fixes)
        hp = os.path.abspath(f"{base}_preflight.html")
        open(hp, "w").write(build_report_html(fname, panel["name"], how, results,
                            "PASS" if verdict == "PASS" else ("NEEDS REVIEW" if verdict == "REVIEW" else "FAIL"),
                            fixes=fixes, preview_b64=preview, gaps=gaps))
        if render_pdf(hp, os.path.abspath(f"{base}_preflight.pdf")):
            print(f"  report: {base}_preflight.pdf")
        else:
            print(f"  report: {base}_preflight.html (open + print to PDF)")


if __name__ == "__main__":
    main()
