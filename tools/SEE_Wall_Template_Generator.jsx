/* =====================================================================
   SOUTHEAST EXHIBITS & EVENTS - WALL TEMPLATE GENERATOR
   ---------------------------------------------------------------------
   What it does:
   Builds one named Illustrator artboard for every panel in a booth, each
   with Bleed / Trim / Visual Safe Area guides already in place, in CMYK,
   built at the chosen scale. It also marks door cuts, keep-clear / live
   zones, and each panel's finish/substrate. Run it once and you get the
   whole booth's templates instead of building each wall by hand.

   NEW: this is now a FIXED tool. The booth itself lives in a separate
   "booth spec" JSON file (the single source of truth). The same JSON
   also feeds the client spec sheet and the AI proofer - define the booth
   once, everything stays consistent.

   How a designer runs it:
   1. Open Adobe Illustrator (no document needs to be open).
   2. File > Scripts > Other Script...  and pick this file.
   3. When asked, choose the booth's  *.json  spec file.
      (Cancel = use the built-in example, Mama's Creations.)
   4. A new CMYK document is created with one artboard per panel.

   For a NEW job: copy the example JSON, edit its values, and load it.
   You do NOT edit this script.
   ===================================================================== */

// ===================== JSON LOADER (do not edit) =====================
function parseJSONsafe(text) {
  text = String(text);
  // Strip a UTF-8 BOM and surrounding whitespace first - a BOM'd spec file is
  // valid JSON to a human but would fail the Crockford validation regex below.
  text = text.replace(/^\uFEFF/, "").replace(/^\s+|\s+$/g, "");
  if (typeof JSON !== "undefined" && JSON.parse) {
    try { return JSON.parse(text); }
    catch (e) { throw new Error("Booth spec is not valid JSON: " + e); }
  }
  // Crockford safe-eval fallback for older ExtendScript engines
  if (/^[\],:{}\s]*$/.test(
        text.replace(/\\(?:["\\\/bfnrt]|u[0-9a-fA-F]{4})/g, "@")
            .replace(/"[^"\\\n\r]*"|true|false|null|-?\d+(?:\.\d*)?(?:[eE][+\-]?\d+)?/g, "]")
            .replace(/(?:^|:|,)(?:\s*\[)+/g, ""))) {
    try { return eval("(" + text + ")"); }
    catch (e2) { throw new Error("Booth spec is not valid JSON: " + e2); }
  }
  throw new Error("Booth spec is not valid JSON (failed safe-eval validation).");
}

// Built-in EXAMPLE booth (used only if you cancel the file picker).
// For real jobs, load the booth's JSON instead of editing this.
var DEFAULT_SPEC = {
  job: { name: "Mama's Creations - IDDBA 2026 - 20x20 (built-in example)" },
  settings: { scale: 0.5, bleed_per_side_in: 1.0, safe_margin_in: 4.0 },
  door_standard: {
    panel_w_in: 39.125, panel_h_in: 95.21, edge_offset_in: 4.3125,
    handle: { dia_in: 2.0, y_from_floor_in: 37.98 },
    lock:   { dia_in: 1.125, y_from_floor_in: 41.79 }
  },
  panels: [
    { name: "A", w: 78.12, h: 173.32, finish: "TBD", sided: "single", interior_finish: "TBD", door: "left", note: "Closet wall - has the DOOR (handle on the left)" },
    { name: "B", w: 78.12, h: 173.32, finish: "TBD", sided: "single", interior_finish: "TBD", note: "Closet wall" },
    { name: "C", w: 78.12, h: 173.32, finish: "TBD", sided: "single", interior_finish: "TBD", note: "Closet wall" },
    { name: "D", w: 78.12, h: 173.32, finish: "TBD", sided: "single", interior_finish: "TBD", note: "Closet wall" },
    { name: "E1", w: 117.18, h: 114.7, finish: "TBD", sided: "single", note: "Curved glass display sits at the bottom - keep art clear of it",
      zones: [ { x: 7.7775, y: 0, w: 101.625, h: 52.5, label: "CURVED GLASS DISPLAY / refrigerated storage - KEEP CLEAR (101.625 x 52.5)", kind: "keepclear" } ] },
    { name: "E2", w: 117.18, h: 114.7, finish: "TBD", sided: "single" },
    { name: "E_Soffit", w: 117.18, h: 9.76, finish: "TBD", sided: "single", note: "Soffit wrap strip" },
    { name: "F1", w: 78.12, h: 134.26, finish: "TBD", sided: "single", note: "FRONT: artwork shows in the TOP strip only; fridge fills the rest",
      zones: [ { x: 0, y: 95.20, w: 78.12, h: 39.06, label: "LIVE GRAPHIC AREA (78.12 x 39.06)", kind: "live" },
               { x: 0, y: 0,     w: 78.12, h: 95.20, label: "FRIDGE DISPLAY AREA - NO artwork", kind: "keepclear" } ] },
    { name: "F2", w: 41.31, h: 134.26, finish: "TBD", sided: "single" },
    { name: "F3", w: 78.12, h: 134.26, finish: "TBD", sided: "single", note: "BACK panel - full height. Shelves may be placed here (sizes TBD)." },
    { name: "F4", w: 41.31, h: 134.26, finish: "TBD", sided: "single", note: "Shelves may be placed here (sizes TBD)." },
    { name: "Counter_1", w: 58.5, h: 37.5, finish: "TBD", sided: "single" },
    { name: "Counter_2", w: 58.5, h: 37.5, finish: "TBD", sided: "single" },
    { name: "LCounter_Front", w: 100.0, h: 37.5, finish: "TBD", sided: "single" },
    { name: "LCounter_Side", w: 59.0, h: 37.5, finish: "TBD", sided: "single" },
    { name: "Fridge_Fabric_A", w: 39.06, h: 134.26, finish: "white fabric", sided: "single", note: "Interior white fabric" },
    { name: "Fridge_Fabric_B", w: 39.06, h: 134.26, finish: "white fabric", sided: "single", note: "Interior white fabric" },
    { name: "Fridge_Fabric_C", w: 78.12, h: 134.26, finish: "white fabric", sided: "single", note: "Interior white fabric" }
  ]
};

// Returns the parsed spec, DEFAULT_SPEC ONLY on an explicit Cancel, or null on
// ANY failure (missing file, unreadable file, bad JSON). A failure must ABORT
// the run - falling back to the example here used to build 18 plausible
// artboards for the WRONG booth, which is far worse than building nothing.
function loadSpec() {
  var f = null;
  try {
    // A preset SEE_SPEC_PATH lets the script run head-less (no dialog) for
    // automation/testing; when it's undefined the normal file picker shows.
    f = (typeof SEE_SPEC_PATH !== "undefined" && SEE_SPEC_PATH)
          ? new File(SEE_SPEC_PATH)
          : File.openDialog("Select the booth spec JSON  (Cancel = use built-in example)");
  } catch (ePick) {
    alert("Could not open a booth spec:\r" + ePick + "\r\rNothing was built.");
    return null;
  }
  if (f == null) {
    // Explicit Cancel is the ONLY path to the built-in example.
    DEFAULT_SPEC.__source = "built-in example (Mama's Creations)";
    return DEFAULT_SPEC;
  }
  try {
    if (!f.exists) {
      alert("Booth spec not found:\r" + f.fsName + "\r\rNothing was built.");
      return null;
    }
    f.encoding = "UTF-8";
    if (!f.open("r")) {
      alert("Could not open the booth spec for reading:\r" + f.fsName +
            "\r(" + f.error + ")\r\rNothing was built.");
      return null;
    }
    var txt = f.read();
    f.close();
    var spec = parseJSONsafe(txt);
    spec.__source = decodeURI(f.name);
    return spec;
  } catch (e) {
    alert("Could not read that booth spec:\r" + f.fsName + "\r\r" + e +
          "\r\rNothing was built. (The built-in example is used only when you press Cancel.)");
    return null;
  }
}

// --------------------------- SETTINGS (from spec) -------------------
var SPEC          = loadSpec();   // null = abort (loadSpec already alerted why)
var JOB_NAME      = (SPEC && SPEC.job && SPEC.job.name) ? SPEC.job.name : "Untitled job";
var ST            = (SPEC && SPEC.settings) || {};
var SCALE         = (ST.scale != null) ? ST.scale : 0.5;
var BLEED_PER_SIDE = (ST.bleed_per_side_in != null) ? ST.bleed_per_side_in : 1.0;
var SAFE_MARGIN   = (ST.safe_margin_in != null) ? ST.safe_margin_in : 4.0;
var PANELS        = (SPEC && SPEC.panels) || [];
var DOOR          = (SPEC && SPEC.door_standard) || {
  panel_w_in: 39.125, panel_h_in: 95.21, edge_offset_in: 4.3125,
  handle: { dia_in: 2.0, y_from_floor_in: 37.98 },
  lock:   { dia_in: 1.125, y_from_floor_in: 41.79 }
};

// =====================================================================
var PT       = 72;                 // points per inch
var GAP_IN   = 6;                  // spacing between artboards (inches, scaled)
var MAX_AB_PT = 226 * 72;          // Illustrator's max artboard side is ~227.5"; guard just under it
var MAX_ROW_W_PT = 200 * PT;       // wrap to a new row before hitting Illustrator's canvas limit

function inToPt(v)   { return v * PT; }
function sPt(v)      { return inToPt(v * SCALE); }    // scaled inches -> points

function cmyk(c, m, y, k) {
  var col = new CMYKColor();
  col.cyan = c; col.magenta = m; col.yellow = y; col.black = k;
  return col;
}
var C_BLEED = cmyk(70, 0, 0, 0);    // cyan   - bleed
var C_TRIM  = cmyk(0, 0, 0, 100);   // black  - trim (finished size)
var C_SAFE  = cmyk(0, 100, 0, 0);   // magenta- visual safe area
var C_KEEP  = cmyk(0, 55, 100, 0);  // orange - keep-clear (fixture / TV / shelf / fridge)
var C_LIVE  = cmyk(75, 0, 100, 0);  // green  - live artwork area
var C_DOOR  = cmyk(0, 100, 100, 0); // red    - door cut + hardware
var C_TEXT  = cmyk(0, 0, 0, 100);

function getLayer(doc, name) {
  try { return doc.layers.getByName(name); }
  catch (e) { var l = doc.layers.add(); l.name = name; return l; }
}

function strokeRect(layer, top, left, wPt, hPt, color, weight, dashed) {
  var r = layer.pathItems.rectangle(top, left, wPt, hPt);
  r.filled = false;
  r.stroked = true;
  r.strokeColor = color;
  r.strokeWidth = weight;
  if (dashed) { try { r.strokeDashes = [8, 5]; } catch (e) {} }
  return r;
}

function smallText(layer, xPt, yPt, str, sizePt, color) {
  var t = layer.textFrames.add();
  t.contents = str;
  t.position = [xPt, yPt];
  try {
    t.textRange.characterAttributes.fillColor = color;
    t.textRange.characterAttributes.size = sizePt;
  } catch (e) {}
  return t;
}

function drawHole(layer, cxPt, cyPt, diaPt) {
  var e = layer.pathItems.ellipse(cyPt + diaPt / 2, cxPt - diaPt / 2, diaPt, diaPt);
  e.filled = false; e.stroked = true; e.strokeColor = C_DOOR; e.strokeWidth = 1.5;
  return e;
}

// Door cut + the two real handle/lock holes (geometry from the booth spec).
function drawDoor(layer, labelLayer, side, panel, trimLeftXpt, trimBottomYpt) {
  var dW = sPt(DOOR.panel_w_in);
  var dH = sPt(DOOR.panel_h_in);
  var panelWpt = sPt(panel.w);
  var dLeft   = (side === "right") ? (trimLeftXpt + panelWpt - dW) : trimLeftXpt;
  var dBottom = trimBottomYpt;          // door sits on the floor
  var dTop    = dBottom + dH;
  strokeRect(layer, dTop, dLeft, dW, dH, C_DOOR, 2, true);
  var holeCx = (side === "right") ? (dLeft + dW - sPt(DOOR.edge_offset_in)) : (dLeft + sPt(DOOR.edge_offset_in));
  drawHole(layer, holeCx, dBottom + sPt(DOOR.handle.y_from_floor_in), sPt(DOOR.handle.dia_in)); // handle (lower)
  drawHole(layer, holeCx, dBottom + sPt(DOOR.lock.y_from_floor_in),   sPt(DOOR.lock.dia_in));   // lock (upper)
  smallText(labelLayer, dLeft + sPt(2), dTop - sPt(2), "DOOR (" + side + ") - cut + handle/lock holes", 18, C_DOOR);
}

// Keep-clear / live-area rectangles marked on the panel. `mirrored` (Side B of
// a double-sided panel, seen from the back) flips each zone's x to w - x - zw.
// Interior zones (fridge/shelf keep-clears) are mirrored onto Side B by DEFAULT:
// over-marking a keep-clear beats printing art over hardware. Follow-up noted:
// a per-zone `sides` field could let a zone opt out of one side.
function drawZones(zoneLayer, labelLayer, panel, trimLeftXpt, trimBottomYpt, mirrored) {
  if (!panel.zones) return;
  for (var z = 0; z < panel.zones.length; z++) {
    var zn  = panel.zones[z];
    var col = (zn.kind === "live") ? C_LIVE : C_KEEP;
    var znXin = mirrored ? (panel.w - zn.x - zn.w) : zn.x;
    var zLeft = trimLeftXpt + sPt(znXin);
    var zTop  = trimBottomYpt + sPt(zn.y) + sPt(zn.h);
    strokeRect(zoneLayer, zTop, zLeft, sPt(zn.w), sPt(zn.h), col, 2, true);
    if (zn.label) smallText(labelLayer, zLeft + sPt(1.5), zTop - sPt(1.5), zn.label, 18, col);
  }
}

// Multiple marked door openings along ONE long graphic (e.g. a conference-room
// run): each door_marks entry is {x, w, label[, side]} in trim inches from the
// panel's left, drawn at full trim height. `side` (optional) adds the handle/
// lock holes at DOOR.edge_offset_in from that latch edge; without it only the
// opening is marked ("leave it one graphic, mark where the doors are").
// Geometry mirrors preview_templates.py's door_marks loop term-for-term so the
// production template can never disagree with the client template. `mirrored`
// (Side B) flips each opening's x to w - x - dmw and swaps the latch side.
function drawDoorMarks(doorLayer, labelLayer, panel, trimLeftXpt, trimBottomYpt, mirrored) {
  if (!panel.door_marks) return;
  var hTrimPt = sPt(panel.h);
  for (var d = 0; d < panel.door_marks.length; d++) {
    var dm = panel.door_marks[d];
    var dmWin  = (dm.w != null) ? dm.w : DOOR.panel_w_in;
    var dmXin  = (dm.x != null) ? dm.x : 0;
    var dmSide = dm.side;
    if (mirrored) {
      dmXin = panel.w - dmXin - dmWin;
      if (dmSide === "left") dmSide = "right";
      else if (dmSide === "right") dmSide = "left";
    }
    var dmLeft = trimLeftXpt + sPt(dmXin);
    var dmW    = sPt(dmWin);
    var dmTop  = trimBottomYpt + hTrimPt;
    strokeRect(doorLayer, dmTop, dmLeft, dmW, hTrimPt, C_DOOR, 2, true);
    smallText(labelLayer, dmLeft + sPt(1.5), dmTop - sPt(1.5), dm.label || "DOOR", 18, C_DOOR);
    if (dmSide === "left" || dmSide === "right") {
      var cx = (dmSide === "right") ? (dmLeft + dmW - sPt(DOOR.edge_offset_in))
                                    : (dmLeft + sPt(DOOR.edge_offset_in));
      drawHole(doorLayer, cx, trimBottomYpt + sPt(DOOR.handle.y_from_floor_in), sPt(DOOR.handle.dia_in));
      drawHole(doorLayer, cx, trimBottomYpt + sPt(DOOR.lock.y_from_floor_in),   sPt(DOOR.lock.dia_in));
    }
  }
}

function addLabel(layer, xPt, yPt, panel, displayName, maxWidthPt, maxHeightPt) {
  var t = layer.textFrames.add();
  var details = "Trim " + panel.w + '" x ' + panel.h + '"   |   Bleed ' + BLEED_PER_SIDE +
                '"/side (' + (BLEED_PER_SIDE * 2) + '" total)   |   Built at ' + (SCALE * 100) +
                "% (output " + Math.round(100 / SCALE) + "%)";
  var line2 = [];
  if (panel.finish)          line2.push("Finish: " + panel.finish);
  if (panel.sided)           line2.push((panel.sided === "double") ? "DOUBLE-SIDED" : "single-sided");
  if (panel.interior_finish) line2.push("Interior: " + panel.interior_finish);
  if (line2.length) details += "\r" + line2.join("   |   ");
  if (panel.note) details += "\r" + panel.note;
  t.contents = displayName + "\r" + details;
  t.position = [xPt, yPt];
  var nameSize = 56, bodySize = 30;   // base sizes for a normal panel
  try {
    // Fit the label by CALCULATION — no width-measuring and no app.redraw().
    // (Forcing redraws during a scripted build can crash Illustrator, which is
    // what happened on the narrow plexi panel.) Estimate each line's width from
    // its character count and shrink the whole block once, so a narrow panel
    // can't clip the title and a short one can't overrun its height.
    var R = 0.62, LH = 1.25;   // ~glyph-width/font-size and ~line-height/font-size
    var lines = (displayName + "\r" + details).split("\r");
    var widest = 1;
    for (var k = 0; k < lines.length; k++) {
      var sz = (k === 0) ? nameSize : bodySize;   // first line is the big name
      var w = lines[k].length * sz * R;
      if (w > widest) widest = w;
    }
    var f = 1;
    if (maxWidthPt)  f = Math.min(f, maxWidthPt / widest);
    var blockH = nameSize * LH + (lines.length - 1) * bodySize * LH;
    if (maxHeightPt) f = Math.min(f, maxHeightPt / blockH);
    if (f < 8 / nameSize) f = 8 / nameSize;        // readability floor (~8pt name)
    if (f < 1) { nameSize *= f; bodySize *= f; }
    t.textRange.characterAttributes.fillColor = C_TEXT;
    t.textRange.characterAttributes.size = bodySize;
    t.paragraphs[0].characterAttributes.size = nameSize;   // big panel name
  } catch (e) {}
  return t;
}

// --------------------------- BUILD ----------------------------------
if (!SPEC) {
  // Bad/unreadable spec: loadSpec already alerted the real error. Build NOTHING
  // rather than templates for the wrong booth.
} else if (!PANELS || PANELS.length === 0) { alert("No panels found in the booth spec. Check the JSON's 'panels' list."); }
else {
  var doc = app.documents.add(DocumentColorSpace.CMYK, 1000, 1000);
  try { doc.rulerUnits = RulerUnits.Inches; } catch (e) {}

  var lBleed  = getLayer(doc, "BLEED (cyan)");
  var lTrim   = getLayer(doc, "TRIM (black)");
  var lSafe   = getLayer(doc, "SAFE AREA (magenta)");
  var lZone   = getLayer(doc, "ZONES (keep-clear / live)");
  var lDoor   = getLayer(doc, "DOOR (cut + hardware)");
  var lLabel  = getLayer(doc, "LABELS");
  var lArt    = getLayer(doc, "ARTWORK - place art here");

  var gapPt = sPt(GAP_IN);
  var xCursor = 0;
  var yTop = 0;
  var rowMaxH = 0;
  var built = 0;
  var oversized = [];   // panels too large for a single Illustrator artboard at this scale

  for (var i = 0; i < PANELS.length; i++) {
    var p = PANELS[i];

    // double-sided panels get two artboards (Side A / Side B); single = one
    var sides = (p.sided === "double") ? ["Side A", "Side B"] : [""];

    for (var sIdx = 0; sIdx < sides.length; sIdx++) {
      var sideName = sides[sIdx];
      var displayName = p.name + (sideName ? " - " + sideName : "");
      // Side B is the same physical wall seen from the BACK: door hand, zone x
      // positions, and door_marks all mirror left<->right (x -> w - x - zw).
      var mirrored = (sIdx === 1);

      var wTrimPt = sPt(p.w);
      var hTrimPt = sPt(p.h);
      var bleedPt = sPt(BLEED_PER_SIDE);
      var safePt  = sPt(SAFE_MARGIN);
      var abWpt = wTrimPt + 2 * bleedPt;   // full bleed box
      var abHpt = hTrimPt + 2 * bleedPt;

      // Skip panels too big for one Illustrator artboard (e.g. a 603" hanging
      // sign — even at half-scale it's ~302", past the ~227" limit). A panel
      // flagged oversize_mode:"continuous" is printed as ONE piece by the
      // vendor (doors marked on the client template); everything else is
      // flagged to tile/seam separately. Either way, don't crash the run.
      if (abWpt > MAX_AB_PT || abHpt > MAX_AB_PT) {
        var ovDims = "  (" + p.w + '" x ' + p.h + '" = ' +
                     Math.round(abWpt / PT) + '" x ' + Math.round(abHpt / PT) +
                     '" at ' + (SCALE * 100) + "% — past Illustrator's ~227\" artboard limit; ";
        if (p.oversize_mode === "continuous") {
          oversized.push(displayName + ovDims +
                         "printed as ONE continuous piece — build at full size outside Illustrator; " +
                         "door openings marked on the client template)");
        } else {
          oversized.push(displayName + ovDims + "tile/seam separately)");
        }
        continue;
      }

      // wrap to next row if this artboard would overflow the canvas width
      if (xCursor > 0 && (xCursor + abWpt) > MAX_ROW_W_PT) {
        xCursor = 0;
        yTop = yTop - (rowMaxH + gapPt);
        rowMaxH = 0;
      }

      var abLeft = xCursor;
      var abTop  = yTop;
      var abRect = [abLeft, abTop, abLeft + abWpt, abTop - abHpt];

      try {
        if (built === 0) {                      // reuse the document's first artboard
          doc.artboards[0].artboardRect = abRect;
          doc.artboards[0].name = displayName;
        } else {
          var ab = doc.artboards.add(abRect);
          ab.name = displayName;
        }
      } catch (eAdd) {
        oversized.push(displayName + "  (artboard could not be created: " + eAdd + ")");
        continue;
      }

      // Bleed box (= artboard edge)
      strokeRect(lBleed, abTop, abLeft, abWpt, abHpt, C_BLEED, 2);
      // Trim box (finished size)
      strokeRect(lTrim, abTop - bleedPt, abLeft + bleedPt, wTrimPt, hTrimPt, C_TRIM, 2);
      // Safe area
      var safeW = wTrimPt - 2 * safePt;
      var safeH = hTrimPt - 2 * safePt;
      if (safeW > 0 && safeH > 0) {
        strokeRect(lSafe, abTop - bleedPt - safePt, abLeft + bleedPt + safePt, safeW, safeH, C_SAFE, 1.5);
      }

      // Trim bottom-left corner (used by zones + door)
      var trimLeftXpt   = abLeft + bleedPt;
      var trimBottomYpt = abTop - bleedPt - hTrimPt;

      // Keep-clear / live zones (fridge, glass display, TVs, shelves, ...)
      drawZones(lZone, lLabel, p, trimLeftXpt, trimBottomYpt, mirrored);

      // Door cut + hardware (only if flagged); Side B gets the mirrored hand
      if (p.door === "left" || p.door === "right") {
        var doorSide = mirrored ? ((p.door === "left") ? "right" : "left") : p.door;
        drawDoor(lDoor, lLabel, doorSide, p, trimLeftXpt, trimBottomYpt);
      }

      // Marked door openings along one long graphic (door_marks)
      drawDoorMarks(lDoor, lLabel, p, trimLeftXpt, trimBottomYpt, mirrored);

      // Label (just inside the top-left, below the bleed) — scaled to fit the panel
      addLabel(lLabel, abLeft + bleedPt + sPt(2), abTop - bleedPt - sPt(2), p, displayName,
               wTrimPt - sPt(4), abHpt - sPt(2));

      xCursor += abWpt + gapPt;
      if (abHpt > rowMaxH) rowMaxH = abHpt;
      built++;
    }
  }

  try { doc.activeLayer = lArt; } catch (e) {}

  alert("Done.\rJob: " + JOB_NAME +
        "\rSpec: " + (SPEC.__source || "built-in") +
        "\rArtboards created: " + built +
        (oversized.length ? "\r\rSKIPPED (too large for one artboard — see each item):\r  - " + oversized.join("\r  - ") : "") +
        "\rScale: " + (SCALE * 100) + "%  |  Bleed: " + BLEED_PER_SIDE + '" per side (' + (BLEED_PER_SIDE * 2) + '" total)' +
        "\r\rColors:  cyan = bleed,  black = trim,  magenta = safe area," +
        "\r  orange = keep-clear (fixture/TV/shelf),  green = live art area,  red = door." +
        "\r\rDrop artwork on the 'ARTWORK' layer, inside the magenta safe area, out to the cyan bleed.");
}
