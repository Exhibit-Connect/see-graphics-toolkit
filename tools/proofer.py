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
import json, sys, os, re, math, subprocess, html, base64, tempfile
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


def _token_span_match(n, toks):
    """True when normalized name `n` equals the concatenation of one or more
    CONSECUTIVE whole filename tokens - i.e. the panel name appears at token
    boundaries of the stem ('wall_a_final' matches 'Wall A'; 'revised' never
    matches panel 'D'). Pure."""
    for i in range(len(toks)):
        acc = ""
        for t in toks[i:]:
            acc += t
            if acc == n:
                return True
            if len(acc) >= len(n):
                break
    return False


def find_panel(spec, fname, panel_arg):
    """Match an artwork file to a spec panel.

    Returns (panel, how) on a match. On failure returns (None, reason):
    reason is an actionable error message when an explicit --panel matched
    nothing (NEVER falls through to filename matching - the operator asked
    for a specific panel) or when the filename matches several panels with
    equal specificity; reason is None when the filename simply matches no
    panel."""
    panels = spec.get("panels", [])
    if panel_arg:
        for p in panels:
            if norm(p["name"]) == norm(panel_arg):
                return p, "named explicitly"
        avail = ", ".join(str(p.get("name", "?")) for p in panels) or "(none)"
        return None, f'no panel named "{panel_arg}" in the booth spec - available: {avail}'
    stem = os.path.splitext(os.path.basename(fname))[0]
    toks = [t.lower() for t in re.split(r"[^A-Za-z0-9]+", stem) if t]
    matches = []
    for p in panels:
        n = norm(p["name"])
        if not n:
            continue
        # 1-2 char names (e.g. 'A', 'F1'... normalized) demand an exact token;
        # longer names may span consecutive tokens ('wall' + 'ab')
        if (n in toks) if len(n) <= 2 else _token_span_match(n, toks):
            matches.append(p)
    if not matches:
        return None, None
    best_len = max(len(norm(p["name"])) for p in matches)
    best = [p for p in matches if len(norm(p["name"])) == best_len]
    if len(best) > 1:
        names = ", ".join(str(p["name"]) for p in best)
        return None, (f"filename matches multiple panels with equal specificity ({names}) "
                      f"- re-run with --panel NAME")
    return best[0], "matched from filename"


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
        info["size_match_label"] = m  # threaded to check_marks via run_checks
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
            info["size_match_label"] = m
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


def resolution_band(spec):
    """(min, max) ppi from the booth JSON's settings.resolution_ppi - the SAME
    keys the client-facing spec packet prints, so the packet's promise and the
    proofer's enforcement can never diverge. Defaults 120/150. Pure."""
    band = (spec or {}).get("settings", {}).get("resolution_ppi") or {}
    return band.get("min", 120), band.get("max", 150)


def check_resolution(info, spec=None, matched_scale=None):
    """Grade raster ppi against the spec's resolution band. The band is
    defined AT BUILD SCALE (clients build at settings.scale, usually 1/2);
    when the file matched a FULL-scale size candidate and scale < 1, the floor
    relaxes to min*scale (same printed quality) - RELAX ONLY, the half-scale
    path is never tightened. The applied threshold is stated in the detail."""
    lo, hi = resolution_band(spec)
    scale = (spec or {}).get("settings", {}).get("scale", 0.5)
    floor, norm_note = lo, ""
    if matched_scale is not None and matched_scale >= 1 and scale and scale < 1:
        floor = lo * scale
        norm_note = (f" [full-scale file: {lo:g} ppi at {scale:g}-scale build "
                     f"= floor relaxed to {floor:g} ppi]")
    req = f"required {floor:g}-{hi:g} ppi at build scale{norm_note}"
    if info["kind"] == "raster":
        d = info["dpi"]
        if not d:
            return "WARN", "no DPI tag - cannot verify resolution at print size"
        if d < floor:
            return "FAIL", f"{d} ppi (< {floor:g}){norm_note}"
        if d > hi:
            return "WARN", f"{d} ppi (> {hi:g}, more than needed)"
        return "PASS", f"{d} ppi ({req})"
    if not info["images"]:
        gaps = info.get("analysis_gaps") or []
        if gaps:
            return "WARN", (f"could not fully analyze {len(gaps)} object(s) - unable to confirm "
                            f"the file is vector-only, so resolution is unverified")
        return "PASS", "no raster images (vector) - resolution not a factor"
    lo_img = min(i["ppi"] for i in info["images"])
    hi_img = max(i["ppi"] for i in info["images"])
    detail = ", ".join(f'{i["px"][0]}x{i["px"][1]}px -> {i["ppi"]}ppi ({i["how"]})' for i in info["images"][:6])
    if lo_img < floor:
        return "FAIL", f"lowest image {lo_img} ppi (< {floor:g}){norm_note}. {detail}"
    if hi_img > hi:
        return "WARN", f"highest image {hi_img} ppi (> {hi:g}, more than needed). {detail}"
    return "PASS", f"{lo_img}-{hi_img} ppi ({req}). {detail}"


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


def check_marks(info, spec=None, size_label=None):
    """Compare the media-beyond-trim margin against the bleed the spec expects
    (scaled to the build scale check_size matched). Typical crop/registration
    marks add ~0.25-0.5\" beyond the bleed, so any margin clearly over the
    expected bleed is flagged. Without a spec, falls back to the legacy 2.5\"
    heuristic (kept for backward compatibility)."""
    if info["kind"] != "pdf" or info["marks_margin_in"] is None:
        return "NA", "no TrimBox - cannot assess printer marks"
    margin = info["marks_margin_in"]
    if spec is not None:
        st = spec.get("settings", {})
        b = st.get("bleed_per_side_in", 1.0)
        sc = st.get("scale", 0.5)
        _, mscale = _bare_trim_scale(size_label, sc)
        expected = b * mscale
        if margin > expected + 0.15:
            return "WARN", (f'{margin}" beyond trim per side exceeds the expected {expected:g}" '
                            f'bleed - possible crop/registration marks or oversized media')
        return "PASS", (f'{margin}" beyond trim per side - consistent with the expected '
                        f'{expected:g}" bleed, no obvious marks')
    if margin > 2.5:
        return "WARN", f'{margin}" beyond trim per side - possible crop/registration marks'
    return "PASS", f'{margin}" beyond trim per side - no obvious marks'


def check_spelling(info, dict_path=None):
    """Dictionary-based spell advisory. ALL-CAPS display type IS checked
    (booth headlines are predominantly all-caps - 'EXIBIT SOLUTIONS' used to
    sail through on the blanket isupper() skip); only short all-caps tokens
    (<= 4 chars, likely acronyms like NASA) are skipped, and flagged caps
    words are labeled 'may be an acronym'. The dictionary resolves as
    `dict_path` arg > $SEE_DICT > the system word list; a MISSING dictionary
    is a WARN (the check was silently NA before - a skipped check must be
    visible on the report)."""
    text = info.get("text", "")
    if not text:
        if info["kind"] == "pdf" and info.get("fonts", 0) == 0:
            return "NA", "no readable text (already outlined) - send a pre-outline copy to spell-check"
        return "NA", "no readable text"
    path = dict_path or os.environ.get("SEE_DICT") or DICT
    if not os.path.exists(path):
        return "WARN", (f"spelling NOT checked — dictionary unavailable ({path}); "
                        f"install a word list or set SEE_DICT, and proofread manually")
    words = set(w.strip().lower() for w in open(path, encoding="latin-1"))
    seen, bad, checked = set(), [], 0
    for tok in re.findall(r"[A-Za-z][A-Za-z'\-]{2,}", text):
        low = tok.lower().strip("'-")
        if low in seen:
            continue
        seen.add(low)
        if tok.isupper() and len(tok) <= 4:   # short all-caps: likely an acronym
            continue
        checked += 1
        cands = {low, low.replace("'", ""), low.rstrip("s"), low + "s"}
        for suf in ("ed", "ing", "ly", "er", "es", "d"):   # tolerate common inflections
            if low.endswith(suf) and len(low) - len(suf) >= 3:
                cands.add(low[:-len(suf)])
                cands.add(low[:-len(suf)] + "e")
        if any(c in words for c in cands):
            continue
        bad.append(tok + (" (may be an acronym)" if tok.isupper() else ""))
    if bad:
        return "WARN", f'{len(bad)} word(s) to review (may include brand/proper names): ' + ", ".join(bad[:25])
    return "PASS", f"no obvious misspellings ({checked} distinct word(s) checked)"


def run_checks(path, spec, panel_arg=None):
    """Match file -> panel, analyze, run every check. Returns
    {panel, how, info, results, verdict}; or {"error": msg} when the match
    failed for a reason the operator must act on (explicit --panel not found,
    ambiguous filename) - no checks are run in that case; or None when the
    filename simply matched no panel.
    Shared by the CLI and by make_proof.py so the checks never diverge."""
    panel, how = find_panel(spec, path, panel_arg)
    if not panel:
        return {"error": how} if how else None
    ext = os.path.splitext(path)[1].lower()
    info = analyze_raster(path) if ext in RASTER_EXT else analyze_pdf(path)
    results = {"size": check_size(info, spec, panel), "color": check_color(info)}
    # thread the scale check_size matched (P0-5 plumbing) into the resolution
    # band so a full-scale file gets the relax-only normalization (P0-9)
    label = info.get("size_match_label")
    sc = spec.get("settings", {}).get("scale", 0.5)
    matched_scale = _bare_trim_scale(label, sc)[1] if label else None
    rc = check_resolution(info, spec, matched_scale)
    if rc:
        results["resolution"] = rc
    results["fonts"] = check_fonts(info)
    results["marks"] = check_marks(info, spec, info.get("size_match_label"))
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
    rlo, rhi = resolution_band(spec)               # spec-driven band (P0-9)
    ppi = info.get("min_ppi") or info.get("dpi")   # PDFs carry min_ppi; rasters carry dpi
    if st == "FAIL":
        howlow = f"the lowest image is about {ppi} ppi" if ppi else f"an image is under {rlo:g} ppi"
        add("resolution", st,
            f'Increase image resolution — {howlow} at build scale, and print needs {rlo:g}–{rhi:g}. Use a '
            f'higher-resolution original, or place the image smaller, so every image is at least {rlo:g} ppi '
            f'at build scale.')
    elif st == "WARN" and ppi and ppi > rhi:
        add("resolution", st,
            f'Resolution is higher than needed (~{ppi} ppi). {rhi:g} ppi at build scale is plenty — you can '
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
        if "dictionary unavailable" in smsg:
            add("spelling", st,
                "Spelling was NOT checked on this file (no dictionary available on the "
                "checking machine) — proofread all text manually before approval.")
        else:
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
    can be made. Writes only a throwaway UNIQUE temp PNG (a fixed cwd name was
    racy across concurrent runs - a stale file could become the wrong artwork's
    preview); the client's file is untouched. Box math lives in `overlay_boxes`
    (pure + tested)."""
    ext = os.path.splitext(path)[1].lower()
    fd, tmp = tempfile.mkstemp(prefix="_proof_mark_", suffix=".png")
    os.close(fd)
    try:
        from PIL import Image, ImageDraw
        if ext in RASTER_EXT:
            im = Image.open(path)
            if im.mode != "RGB":
                im = im.convert("RGB")
        else:
            os.remove(tmp)  # gs must CREATE the file - never trust a pre-existing one
            p = subprocess.run(["gs", "-q", "-sDEVICE=png16m", "-r60", "-dFirstPage=1",
                                "-dLastPage=1", "-o", tmp, path], capture_output=True)
            if p.returncode != 0 or not os.path.exists(tmp) or os.path.getsize(tmp) == 0:
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
# REVIEW is a whole-file verdict (any WARN, no FAIL); the rest are per-check too
BADGE = {"PASS": "#2E9E40", "WARN": "#F7941E", "FAIL": RED, "NA": "#9a9a9a",
         "REVIEW": "#F7941E"}
# display label for a verdict (REVIEW reads as NEEDS REVIEW on the report)
VERDICT_LABEL = {"REVIEW": "NEEDS REVIEW"}


# HTML->PDF lives in render.py now; kept as proofer.render_pdf so callers
# (make_proof.py, this module's CLI) don't change.
render_pdf = render.html_to_pdf


def build_report_html(fname, panel, how, results, verdict, fixes=None, preview_b64=None,
                      gaps=None):
    """`verdict` is the RAW verdict (PASS/REVIEW/FAIL/...); the display label
    and badge color are mapped here (a pre-mapped 'NEEDS REVIEW' used to
    KeyError on the badge lookup and kill the whole batch)."""
    label = VERDICT_LABEL.get(verdict, verdict)
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
      <div class="verdict">{label}</div>
      {fix_html}
      {gaps_html}
      {mark_html}
      <table><thead><tr><th>Check</th><th>Result</th><th>Detail</th></tr></thead><tbody>{rows}</tbody></table>
      <footer>SEE AI Proofer · automated preflight against the single-source booth spec · WARN/FAIL items need a human's eyes before approval.</footer>
    </body></html>"""


def find_default_spec():
    """Locate the booth_spec*.json when --spec isn't given - CLIENT-FACING
    rules (proofer + make_proof share this): only the current directory is
    searched, the chosen file is always announced, ambiguity refuses, and
    there is NO examples/ fallback. The old silent alphabetically-first pick
    (falling back to the tracked example booth) meant artwork could be
    preflighted - and PASS - against the WRONG booth."""
    import glob
    hits = sorted(glob.glob(os.path.join(os.getcwd(), "*booth_spec*.json")))
    if len(hits) > 1:
        print("Multiple booth specs found here — pass --spec to pick one explicitly:",
              file=sys.stderr)
        for h in hits:
            print(f"  {h}", file=sys.stderr)
        sys.exit(2)
    if not hits:
        print("No booth spec found in the current directory — pass "
              "--spec path/to/booth_spec.json", file=sys.stderr)
        sys.exit(2)
    print(f"Using booth spec: {hits[0]}")
    return hits[0]


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

    had_match_error = False
    for fname in files:
        # one try around checks AND report building: one file's failure must
        # never abort the batch (it used to silently drop every later file)
        try:
            r = run_checks(fname, spec, panel_arg)
            if r and r.get("error"):
                print(f"\n[{fname}] {r['error']}")
                had_match_error = True
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
            open(hp, "w").write(build_report_html(fname, panel["name"], how, results, verdict,
                                fixes=fixes, preview_b64=preview, gaps=gaps))
            if render_pdf(hp, os.path.abspath(f"{base}_preflight.pdf")):
                print(f"  report: {base}_preflight.pdf")
            else:
                print(f"  report: {base}_preflight.html (open + print to PDF)")
        except Exception as e:
            print(f"\n[{fname}] could not process: {e} (continuing with remaining files)")
            continue
    if had_match_error:
        sys.exit(2)


if __name__ == "__main__":
    main()
