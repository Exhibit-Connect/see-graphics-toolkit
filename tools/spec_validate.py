#!/usr/bin/env python3
"""Shared booth-JSON validation for the document generators.

A hand-edited booth spec with a missing/string panel dimension, a zone missing
a coordinate, or `scale: 0` used to surface as a raw KeyError/TypeError/
ZeroDivisionError halfway through writing a client file (leaving truncated
HTML on disk) — or, where a value was interpolated unescaped, as raw markup
injected into a client-facing PDF. Every generator now fails FAST with one
line per problem naming the panel/field, before anything is written.

Bad panels are never silently skipped — a dropped panel is a quietly-lost
guide the client would design without.
"""


class SpecError(ValueError):
    """Booth spec failed validation. str() is one line per problem;
    `.problems` is the list."""

    def __init__(self, problems):
        self.problems = list(problems)
        super().__init__("\n".join(self.problems))


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _coerce_setting(container, key, problems, label):
    """Coerce a numeric-string setting in place ('1.5' -> 1.5); record a
    problem when the value is not a number at all. Returns the numeric value
    or None."""
    v = container.get(key)
    if v is None:
        return None
    if not _is_num(v):
        try:
            container[key] = v = float(v)
        except (TypeError, ValueError):
            problems.append(f"{label}: must be a number, got {v!r}")
            return None
    return v


def validate_spec(spec, zone_xy=True):
    """Return the list of problems (empty = valid). Checks:

    - every panel has numeric w/h > 0 (a string \"78\" is an error, not data);
    - zones: with zone_xy=True (the geometry renderers — previews and client
      templates DRAW every zone) each zone needs numeric x/y/w/h; with
      zone_xy=False (spec packet, which only prints live-area sizes) only
      kind=='live' zones need numeric w/h > 0 — keep-clear zones may stay
      label-only, as intake drafts seed them;
    - settings bleed/scale/safe_margin/resolution_ppi coerce to numbers
      (in place) or are reported; scale <= 0 is rejected.
    """
    if not isinstance(spec, dict):
        return [f"booth spec must be a JSON object, got a top-level {type(spec).__name__}"]
    problems = []
    st = spec.get("settings") or {}
    if not isinstance(st, dict):
        problems.append("settings: must be an object")
        st = {}
    for key in ("bleed_per_side_in", "safe_margin_in"):
        _coerce_setting(st, key, problems, f"settings.{key}")
    sc = _coerce_setting(st, "scale", problems, "settings.scale")
    if sc is not None and sc <= 0:
        problems.append(f"settings.scale: must be > 0, got {sc!r}")
    ppi = st.get("resolution_ppi")
    if ppi is not None:
        if isinstance(ppi, dict):
            for k in ("min", "max"):
                _coerce_setting(ppi, k, problems, f"settings.resolution_ppi.{k}")
        else:
            problems.append("settings.resolution_ppi: must be an object with min/max")

    panels = spec.get("panels")
    if panels is not None and not isinstance(panels, list):
        problems.append("panels: must be a list")
        panels = []
    for p in panels or []:
        if not isinstance(p, dict):
            problems.append(f"panel {p!r}: must be an object")
            continue
        name = p.get("name", "?")
        for k in ("w", "h"):
            v = p.get(k)
            if v is None:
                problems.append(f"panel '{name}': missing '{k}'")
            elif not _is_num(v):
                problems.append(f"panel '{name}': '{k}' must be a number, got {v!r}")
            elif v <= 0:
                problems.append(f"panel '{name}': '{k}' must be > 0, got {v!r}")
        zones = p.get("zones") or []
        if not isinstance(zones, list):
            problems.append(f"panel '{name}': 'zones' must be a list")
            zones = []
        for zi, z in enumerate(zones, 1):
            if not isinstance(z, dict):
                problems.append(f"panel '{name}' zone {zi}: must be an object")
                continue
            zlabel = f"zone {zi}" + (f" ('{z['label']}')" if z.get("label") else "")
            live = z.get("kind") == "live"
            keys = ("x", "y", "w", "h") if zone_xy else (("w", "h") if live else ())
            for k in keys:
                v = z.get(k)
                if v is None:
                    problems.append(f"panel '{name}' {zlabel}: missing '{k}'")
                elif not _is_num(v):
                    problems.append(f"panel '{name}' {zlabel}: '{k}' must be a number, got {v!r}")
                elif k in ("w", "h") and live and v <= 0:
                    problems.append(f"panel '{name}' {zlabel}: '{k}' must be > 0, got {v!r}")
    return problems


def validate_or_raise(spec, zone_xy=True):
    """Raise SpecError (one line per problem) when the spec is invalid."""
    problems = validate_spec(spec, zone_xy=zone_xy)
    if problems:
        raise SpecError(problems)
    return spec


def report_and_exit(err, out=None):
    """CLI helper: print a SpecError one line per problem and exit 2."""
    import sys
    stream = out or sys.stderr
    print("booth spec INVALID — fix these and re-run:", file=stream)
    for pr in err.problems:
        print(f"  - {pr}", file=stream)
    sys.exit(2)
