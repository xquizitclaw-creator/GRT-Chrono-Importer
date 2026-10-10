"""
chrono_import.py - Parse Garmin Xero / Athlon Rangecraft chronograph files
(CSV / XLS / XLSX) and build a GRT .grtload file.

The .grtload format is URL-encoded XML. The measurement-tab structure mirrors
the reference web tool exactly:

  <Measurement index="N" showinreport="true" title="Imported%20Measurement">
    <charge name="..." showinreport="true" expanded="true" expandedstats="true"
            note="AVG-E=...%20SD=...%20ES=...%20MIN=...%20MAX=...%20UNIT=m/s"
            value="0.00xxxxxxxxxx" source="Chronograph%20Import">
      <shot name="" velocity="800.1" pressure="0" note="PF=...%20TIME=..." />
      ...
    </charge>
  </Measurement>

Velocities are always written to GRT in m/s (fps inputs are converted).
"""

import csv
import io
import math
import os
import re
import statistics
from urllib.parse import quote

FT_TO_M = 0.3048
GRAINS_PER_GRAM = 15.4323584


# --- File reading ---------------------------------------------------------

def read_rows(path):
    """Return a list of rows (each a list of cell strings) from CSV/XLS/XLSX."""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".xlsx":
        return _read_xlsx(path)
    if ext == ".xls":
        # Some devices write zip-based workbooks with an .xls extension;
        # only hand genuine BIFF files to xlrd.
        if _is_real_xls(path):
            return _read_xls(path)
        return _read_xlsx(path)
    return _read_delimited(path)


def _is_real_xls(path):
    """True for genuine legacy (BIFF/OLE2) .xls; False for zip-based .xlsx."""
    try:
        with open(path, "rb") as f:
            head = f.read(8)
    except OSError:
        return False
    # OLE2 compound-document signature
    return head.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1")


def _read_delimited(path):
    with open(path, "r", encoding="utf-8-sig", errors="replace", newline="") as f:
        sample = f.read(4096)
        f.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        except csv.Error:
            class _D(csv.Dialect):
                delimiter = ","
                quotechar = '"'
                doublequote = True
                skipinitialspace = True
                lineterminator = "\n"
                quoting = csv.QUOTE_MINIMAL
            dialect = _D()
        return [list(r) for r in csv.reader(f, dialect)]


def _read_xlsx(path):
    try:
        from openpyxl import load_workbook
    except ImportError as e:
        raise RuntimeError(
            "Reading .xlsx requires the 'openpyxl' package in this build."
        ) from e
    wb = load_workbook(path, read_only=True, data_only=True)
    ws = wb.active
    rows = []
    for r in ws.iter_rows(values_only=True):
        rows.append(["" if c is None else str(c) for c in r])
    return rows


def _read_xls(path):
    """Read legacy (BIFF) .xls via xlrd, which openpyxl cannot open."""
    try:
        import xlrd
    except ImportError as e:
        raise RuntimeError(
            "Reading legacy .xls requires the 'xlrd' package in this build."
        ) from e
    book = xlrd.open_workbook(path)
    sheet = book.sheet_by_index(0)
    rows = []
    for ri in range(sheet.nrows):
        rows.append(["" if v is None else str(v) for v in sheet.row_values(ri)])
    return rows


def read_all_sheets(path):
    """Return [(sheet_name, rows), ...] for every worksheet in an .xls/.xlsx.

    Used by Sessions mode, where each worksheet is one shooting session.
    For CSV (single table) returns a single ("", rows) entry.
    """
    ext = os.path.splitext(path)[1].lower()
    if ext == ".xlsx":
        from openpyxl import load_workbook
        wb = load_workbook(path, read_only=True, data_only=True)
        out = []
        for ws in wb.worksheets:
            rows = [["" if c is None else str(c) for c in r]
                    for r in ws.iter_rows(values_only=True)]
            out.append((ws.title, rows))
        return out
    if ext == ".xls":
        if _is_real_xls(path):
            import xlrd
            book = xlrd.open_workbook(path)
            out = []
            for sheet in book.sheets():
                rows = [["" if v is None else str(v) for v in sheet.row_values(ri)]
                        for ri in range(sheet.nrows)]
                out.append((sheet.name, rows))
            return out
        from openpyxl import load_workbook
        wb = load_workbook(path, read_only=True, data_only=True)
        out = []
        for ws in wb.worksheets:
            rows = [["" if c is None else str(c) for c in r]
                    for r in ws.iter_rows(values_only=True)]
            out.append((ws.title, rows))
        return out
    return [("", _read_delimited(path))]


# --- Column detection & shot extraction -----------------------------------

_NUM_RE = re.compile(r"-?\d+(?:[.,]\d+)?")


def _to_float(cell):
    """Parse a numeric cell, tolerant of thousands/decimal separator styles.

    Handles, in order:
      "2,882.7"  US thousands comma + period decimal      -> 2882.7
      "2.882,7"  EU period thousands + comma decimal       -> 2882.7
      "2885,8"   EU comma decimal (no thousands)           -> 2885.8
      "2,885"    US thousands comma, no decimal            -> 2885
      "2885.8" / "2885"  plain                             -> as-is

    Rule: if both separators are present, the RIGHTMOST is the decimal and the
    other is the thousands separator. If only commas are present, a comma
    followed by exactly 3 digits at the very end is treated as a thousands
    separator; otherwise it is the decimal point.
    """
    if cell is None:
        return None
    s = str(cell).replace("﻿", "").strip().strip('"').strip()
    if not s:
        return None
    m = re.search(r"-?\d[\d.,]*", s)
    if not m:
        return None
    tok = m.group(0)

    has_comma = "," in tok
    has_dot = "." in tok
    if has_comma and has_dot:
        # Rightmost separator is the decimal point.
        if tok.rfind(",") > tok.rfind("."):
            tok = tok.replace(".", "").replace(",", ".")
        else:
            tok = tok.replace(",", "")
    elif has_comma:
        # ",ddd" at the end is a thousands group; ",d" / ",dd" is a decimal.
        if re.search(r",\d{3}$", tok) and not re.search(r",\d{1,2}$", tok):
            tok = tok.replace(",", "")
        else:
            tok = tok.replace(",", ".")

    try:
        return float(tok)
    except ValueError:
        return None


def detect_columns(rows):
    """Heuristically find header row + shot#/velocity/pf/time/notes columns.

    Returns dict: {start_row, shot_col, vel_col, pf_col, time_col, note_col}.
    Mirrors the auto-detect behaviour of the reference importer; the GUI lets
    the user override via the column-mapping step when detection is unsure.
    """
    def _norm(cell):
        return str(cell).replace("﻿", "").strip().strip('"').lower()

    def _looks_like_velocity_header(c):
        return any(k in c for k in ("velocity", "speed", "fps", "m/s", "v0"))

    def _score_header_row(row):
        """How strongly this row looks like a SHOT TABLE header (not metadata).

        Requires a velocity-type column AND at least one other recognized
        column header in the SAME row. Metadata labels like "Velocity:" or
        "Average velocity" sit alone in a row and score 0.
        """
        cells = [_norm(c) for c in row]
        nonempty = [c for c in cells if c]
        if len(nonempty) < 2:
            return 0
        has_vel = any(_looks_like_velocity_header(c) for c in cells)
        if not has_vel:
            return 0
        others = 0
        for c in cells:
            if _looks_like_velocity_header(c):
                continue
            if (c in ("#", "shot", "shot #", "shot#", "no", "no.", "nr", "nr.")
                    or c.startswith("shot")
                    or "power" in c or c == "pf" or "factor" in c
                    or "ke" in c or "energy" in c
                    or c == "time" or "dev" in c or "avg" in c):
                others += 1
        return 1 + others if others else 0

    header_idx = None
    best_score = 0
    for i, row in enumerate(rows):
        sc = _score_header_row(row)
        if sc > best_score:
            best_score = sc
            header_idx = i

    cols = {"shot": None, "vel": None, "pf": None, "time": None, "note": None}
    if header_idx is not None:
        for j, cell in enumerate(rows[header_idx]):
            c = _norm(cell)
            if cols["vel"] is None and _looks_like_velocity_header(c):
                cols["vel"] = j
            elif cols["pf"] is None and ("power" in c or c == "pf" or "factor" in c):
                cols["pf"] = j
            elif cols["time"] is None and (c == "time" or "timestamp" in c
                                           or c == "date"):
                cols["time"] = j
            elif cols["note"] is None and ("note" in c or "comment" in c):
                cols["note"] = j
            elif cols["shot"] is None and (
                    c in ("#", "shot", "shot #", "shot#", "no", "no.", "nr", "nr.")
                    or (c.startswith("shot") and "note" not in c)):
                cols["shot"] = j

    start_row = header_idx + 1 if header_idx is not None else 0

    # No velocity header found: pick the column with the most values in a
    # plausible chronograph range.
    if cols["vel"] is None and rows:
        ncol = max(len(r) for r in rows)
        best, best_score = None, -1
        for j in range(ncol):
            score = 0
            for r in rows[start_row:start_row + 50]:
                if j < len(r):
                    v = _to_float(r[j])
                    if v is not None and 30 <= v <= 6000:
                        score += 1
            if score > best_score:
                best, best_score = j, score
        cols["vel"] = best

    return {
        "start_row": start_row,
        "shot_col": cols["shot"],
        "vel_col": cols["vel"],
        "pf_col": cols["pf"],
        "time_col": cols["time"],
        "note_col": cols["note"],
    }


def extract_shots(rows, mapping, file_unit):
    """Return (velocities_ms, shot_meta) using the column mapping.

    file_unit: 'imperial' (ft/s in file) or 'metric' (m/s in file).
    GRT always receives m/s, so fps is converted here.

    Real chronograph exports (e.g. Garmin Xero) append a SUMMARY FOOTER after
    the shot list -- rows like "AVERAGE SPEED", "STD DEV", "SPREAD", often
    preceded by a "-" separator row. Those trailing values must NOT be read as
    shots. We stop at the first row that isn't a genuine shot, detected by:
      * the shot-number column no longer holding a number (e.g. "-",
        "AVERAGE SPEED"), when a shot-number column exists; or
      * the velocity cell being empty/non-numeric; or
      * the velocity being outside a sane chronograph range.
    """
    vel_ms = []
    meta = []
    vc = mapping["vel_col"]
    sc = mapping["shot_col"]
    pfc = mapping["pf_col"]
    tc = mapping["time_col"]
    nc = mapping["note_col"]

    # Sane chronograph velocity window (covers fps and m/s inputs).
    lo, hi = 100.0, 5200.0

    started = False
    for r in rows[mapping["start_row"]:]:
        v = _to_float(r[vc]) if vc is not None and vc < len(r) else None
        v_in_range = v is not None and lo <= v <= hi

        # A shot-number column that stops holding numbers marks the footer.
        if sc is not None and sc < len(r) and _to_float(r[sc]) is None:
            if started and not v_in_range:
                break
            if not started:
                continue

        if v is None:
            if started:
                break
            continue
        if not v_in_range:
            if started:
                break
            continue

        started = True
        v_ms = v * FT_TO_M if file_unit == "imperial" else v
        vel_ms.append(v_ms)
        meta.append({
            "pf": r[pfc] if pfc is not None and pfc < len(r) else None,
            "time": r[tc] if tc is not None and tc < len(r) else None,
            "note": r[nc] if nc is not None and nc < len(r) else None,
        })
    return vel_ms, meta


def compute_stats(vel_ms, file_unit):
    if not vel_ms:
        return {}
    if file_unit == "imperial":
        series = [v / FT_TO_M for v in vel_ms]
    else:
        series = list(vel_ms)
    avg = statistics.fmean(series)
    # sample SD (n-1), as GRT shows it; Garmin and some chronographs show the population SD
    sd = statistics.stdev(series) if len(series) > 1 else 0.0
    return {
        "avg": avg,
        "sd": sd,
        "es": max(series) - min(series),
        "min": min(series),
        "max": max(series),
        "n": len(series),
    }


# --- .grtload building -----------------------------------------------------

def _enc(s):
    """URL-encode the way GRT stores attribute text (spaces -> %20, etc.)."""
    return quote(str(s), safe="")


def _fmt(x):
    """Format a stat the way the reference tool does (trim trailing zeros)."""
    s = f"{x:.2f}"
    return s


def build_charge_xml(name, vel_ms, meta, stats, file_unit, value_kg):
    note_pieces = []
    if "avg" in stats:
        note_pieces.append("AVG-E=" + _enc(_fmt(stats["avg"])))
        note_pieces.append("SD=" + _enc(_fmt(stats["sd"])))
        note_pieces.append("ES=" + _enc(_fmt(stats["es"])))
        note_pieces.append("MIN=" + _enc(_fmt(stats["min"])))
        note_pieces.append("MAX=" + _enc(_fmt(stats["max"])))
    note_pieces.append("UNIT=" + ("ft/s" if file_unit == "imperial" else "m/s"))
    note_attr = "%20".join(note_pieces)

    charge_name = _enc(name)
    lines = [
        f'        <charge name="{charge_name}" showinreport="true" expanded="true" expandedstats="true" note="'
        f'{note_attr}" value="'
        f'{value_kg:.12f}" source="Chronograph%20Import">'
    ]
    for i, v in enumerate(vel_ms):
        if not math.isfinite(v):
            continue
        m = meta[i] if i < len(meta) else {}
        shot_notes = []
        pf = m.get("pf")
        if pf not in (None, "") and str(pf).strip():
            shot_notes.append("PF=" + re.sub(r"\s+", "%20", str(pf).strip()))
        time_str = m.get("time")
        if time_str:
            shot_notes.append("TIME=" + _enc(str(time_str)))
        note_text = m.get("note")
        if note_text not in (None, "") and str(note_text).strip():
            shot_notes.append("NOTE=" + _enc(str(note_text).strip()))
        shot_note_attr = f' note="{"%20".join(shot_notes)}"' if shot_notes else ""
        lines.append(
            f'          <shot name="" velocity="{v:.1f}" pressure="0"'
            f'{shot_note_attr} />'
        )
    lines.append("        </charge>")
    return "\n".join(lines) + "\n"


def build_grtload(charges_xml, propellant_mass_g=0.0, base_content=None,
                  measurement_title="Imported Measurement", extra_tabs=""):
    """Wrap charge XML into a full .grtload document.

    If base_content (text of an existing .grtload) is provided, the new
    Measurement tab is injected into its <appendix> so the user's original
    tabs and ladder remain intact. Otherwise a minimal fresh file is created.

    extra_tabs: optional XML for additional appendix tabs (e.g. an Analysis
    <note> and a Chrono-vs-Sim <picture>) injected after the Measurement.
    """
    title_enc = _enc(measurement_title)
    measurement = (
        f'      <Measurement index="1" showinreport="true" title="{title_enc}">\n'
        f"{charges_xml}"
        "      </Measurement>\n"
    )
    if extra_tabs:
        measurement = measurement + extra_tabs

    if base_content:
        open_idx = base_content.find("<appendix>")
        close_idx = base_content.find("</appendix>")
        if open_idx != -1 and close_idx != -1:
            before = base_content[:open_idx]
            inner = base_content[open_idx + len("<appendix>"):close_idx]
            after = base_content[close_idx + len("</appendix>"):]
            new_inner = inner + "\n" + measurement
            return before + "<appendix>" + new_inner + "</appendix>" + after

    mc_kg = propellant_mass_g / 1000.0
    xml = []
    xml.append('<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>')
    xml.append('<GordonsReloadingTool version="2021.2030-NIGHTLY">')
    xml.append("  <InnerBallistikInput>")
    xml.append("    <title>GRT Chrono Importer</title>")
    xml.append('    <caliber>\n      <input name="CaliberName" value="Generic" />\n    </caliber>')
    xml.append('    <gun><input name="GunName" value="Generic" /></gun>')
    xml.append('    <projectile><input name="ProjectileName" value="Generic" /></projectile>')
    xml.append(
        '    <propellant><input name="pname" value="Generic" /><input name="mc" value="'
        f'{mc_kg}" unit="g" type="decimal" descr="propellant mass" /></propellant>'
    )
    xml.append("    <appendix>")
    xml.append(measurement)
    xml.append("    </appendix>")
    xml.append("  </InnerBallistikInput>")
    xml.append("</GordonsReloadingTool>")
    return "\n".join(xml)


def read_base_ladder_defaults(base_content):
    """Extract ladder defaults from an existing .grtload.

    GRT models a ladder with three fields:
      mc         - base/top charge mass (the highest rung)
      laddercnt  - number of steps (2..10; <2 means ladder disabled)
      laddermc   - mass increment between steps (the step size)
    plus a <laddersteps> list right after laddermc holding the actual
    decrement for each step going down from mc. GRT lets the user edit these
    individually, so they are the authoritative rung spacing.

    Returns a dict with grain-converted values for pre-filling the UI:
      {"top_gr": float, "step_gr": float, "count": int,
       "weights_gr": [top, top - step1, ...] (descending) or None}
    Missing/zero fields come back as None so the UI can fall back to blanks.
    """
    import re
    out = {"top_gr": None, "step_gr": None, "count": None, "weights_gr": None}
    if not base_content:
        return out

    def _field(name):
        m = re.search(
            r'<input\s+name="%s"\s+value="([^"]*)"[^>]*?(?:unit="([^"]*)")?[^>]*/?>' % name,
            base_content,
        )
        if not m:
            return None, None
        try:
            return float(m.group(1)), (m.group(2) or "")
        except ValueError:
            return None, None

    mc, mc_unit = _field("mc")
    lcnt, _ = _field("laddercnt")
    lmc, lmc_unit = _field("laddermc")

    def _to_grams(val, unit):
        if val is None:
            return None
        if unit == "kg":
            return val * 1000.0
        return val

    mc_g = _to_grams(mc, mc_unit)
    lmc_g = _to_grams(lmc, lmc_unit)
    if mc_g and mc_g > 0:
        out["top_gr"] = mc_g * GRAINS_PER_GRAM
    if lmc_g and lmc_g > 0:
        out["step_gr"] = lmc_g * GRAINS_PER_GRAM
    if lcnt and lcnt >= 2:
        out["count"] = int(round(lcnt))

    # Per-step decrements. Only trusted when there is one per gap (count-1).
    if out["top_gr"] and out["count"]:
        m = _LADDERSTEPS_RE.search(base_content)
        if m:
            steps_g = []
            for vm in re.finditer(r'<var\s+name="mcstep"\s+value="([^"]*)"[^>]*?(?:unit="([^"]*)")?[^>]*/?>',
                                  m.group(2)):
                try:
                    steps_g.append(_to_grams(float(vm.group(1)), vm.group(2) or ""))
                except ValueError:
                    steps_g = None
                    break
            if steps_g and len(steps_g) == out["count"] - 1 and all(g > 0 for g in steps_g):
                w = [out["top_gr"]]
                for g in steps_g:
                    w.append(w[-1] - g * GRAINS_PER_GRAM)
                if w[-1] > 0:
                    out["weights_gr"] = w
    return out


# The propellant's <laddersteps> block (the one following laddermc).
_LADDERSTEPS_RE = re.compile(
    r'(<input\s+name="laddermc"[^>]*/>\s*<laddersteps>)(.*?)(\s*</laddersteps>)', re.S)


def _set_base_ladder_fields(base_content, weights_gr):
    """Rewrite mc / laddercnt / laddermc / laddersteps in the base file so
    GRT's ladder view matches the imported rungs (weights_gr ascending).
    Values written in grams (GRT's storage)."""
    import re
    desc = sorted(weights_gr, reverse=True)
    count = len(desc)
    steps_g = [(desc[k] - desc[k + 1]) / GRAINS_PER_GRAM for k in range(count - 1)]
    top_g = desc[0] / GRAINS_PER_GRAM
    step_g = steps_g[0] if steps_g else 0.0

    def _replace(name, new_val, content):
        pat = re.compile(r'(<input\s+name="%s"\s+value=")([^"]*)(")' % name)
        if pat.search(content):
            return pat.sub(lambda m: m.group(1) + repr(new_val) + m.group(3), content, count=1)
        return content

    c = base_content
    c = _replace("mc", top_g, c)
    c = _replace("laddermc", step_g, c)
    pat = re.compile(r'(<input\s+name="laddercnt"\s+value=")([^"]*)(")')
    if pat.search(c):
        c = pat.sub(lambda m: m.group(1) + repr(int(count)) + m.group(3), c, count=1)
    m = _LADDERSTEPS_RE.search(c)
    if m:
        indent = re.search(r'\n([ \t]*)<input\s+name="laddermc"', c)
        indent = indent.group(1) if indent else "      "
        body = "".join('\n%s<var name="mcstep" value="%r" unit="g" type="decimal" descr="" />'
                       % (indent, g) for g in steps_g)
        c = c[:m.start(2)] + body + c[m.end(2):]
    return c


def import_ladder(file_paths, top_gr=None, step_gr=None, file_unit="imperial", base_content=None,
                  name_mode="weight", sim_json=None, device="", make_chart=True,
                  weights_gr=None):
    """Ladder import: one file per rung.

    file_paths : ordered low charge -> high charge (file[0] = lowest rung).
    weights_gr : rung weights in grains, same order as file_paths. Use this
                 for ladders with uneven steps (GRT <laddersteps>).
    top_gr     : highest rung weight in grains (the base charge mc).
    step_gr    : even step size in grains. top_gr/step_gr are used only when
                 weights_gr is not given.
    name_mode  : "weight" -> charge named e.g. "51.81 gr"; "index" -> "Charge 3".
    sim_json   : optional parsed dict / JSON text from GRT "Export simulation
                 results". When provided, an Analysis note tab and (if
                 matplotlib is available and make_chart) a Chrono-vs-Sim
                 picture tab are added.
    device     : device label for the Analysis note.
    make_chart : render the PNG chart tab (requires matplotlib).

    The number of rungs equals len(file_paths). Without weights_gr, rung i
    (0-based) weight is:
        top_gr - (N-1-i) * step_gr
    so the last file is the top charge. Writes one charge node per rung with
    that file's velocities and the rung weight as the node `value` (kg), and
    updates the base file's mc/laddercnt/laddermc/laddersteps to match.
    """
    n = len(file_paths)
    if weights_gr is None:
        weights_gr = [top_gr - (n - 1 - i) * step_gr for i in range(n)]
    elif len(weights_gr) != n:
        raise ValueError("Got %d charge weights for %d files." % (len(weights_gr), n))
    charges = []
    summary = {"files": 0, "total_shots": 0, "charges": [], "mode": "ladder"}
    for i, path in enumerate(file_paths):
        rows = read_rows(path)
        mapping = detect_columns(rows)
        vel_ms, meta = extract_shots(rows, mapping, file_unit)
        if not vel_ms:
            continue
        stats = compute_stats(vel_ms, file_unit)
        weight_gr = weights_gr[i]
        value_kg = weight_gr / GRAINS_PER_GRAM / 1000.0
        if name_mode == "index":
            name = "Charge %d" % (i + 1)
        else:
            name = "%.2f gr" % weight_gr
        charges.append(build_charge_xml(name, vel_ms, meta, stats, file_unit, value_kg=value_kg))
        summary["files"] += 1
        summary["total_shots"] += len(vel_ms)
        summary["charges"].append({"name": name, "weight_gr": round(weight_gr, 3),
                                   "shots": len(vel_ms), **stats})

    if base_content:
        base_content = _set_base_ladder_fields(base_content, weights_gr)

    extra_tabs = ""
    if sim_json is not None:
        try:
            import sim_compare
            sim_rungs = sim_compare.parse_sim_json(sim_json)
            merged = sim_compare.match_chrono_to_sim(summary["charges"], sim_rungs)
            unit_label = "ft/s" if file_unit == "imperial" else "m/s"
            extra_tabs += sim_compare.build_analysis_note(merged, summary, device or "",
                                                          unit_label=unit_label, index=3)
            if make_chart:
                pic = sim_compare.build_chart_picture(merged, unit_label=unit_label)
                if pic:
                    extra_tabs += pic
                    summary["chart"] = True
                else:
                    summary["chart"] = False
                    summary["chart_unavailable"] = True
            summary["sim_matched"] = sum(1 for r in merged if r["delta"] is not None)
        except Exception as e:
            summary["sim_error"] = str(e)

    grt = build_grtload("".join(charges), 0.0, base_content,
                        measurement_title="Imported Ladder", extra_tabs=extra_tabs)
    return grt, summary


def import_sessions(file_path, file_unit="imperial", base_content=None):
    """Sessions import: each worksheet in the file is one shooting session.

    Produces ONE 'Imported Sessions' Measurement tab with ONE charge per
    session, named from the worksheet (and its Date row when present). Useful
    for a multi-day event exported as a single multi-sheet Garmin file.

    Charge weights aren't known from a sessions file, so the node value is the
    base file's mc if available, else a placeholder (the point here is the
    velocity strings per session, not a charge ladder).
    """
    sheets = read_all_sheets(file_path)

    value_kg = 1e-12
    if base_content:
        d = read_base_ladder_defaults(base_content)
        if d.get("top_gr"):
            value_kg = d["top_gr"] / GRAINS_PER_GRAM / 1000.0

    charges = []
    summary = {"files": 0, "total_shots": 0, "charges": [], "mode": "sessions"}

    for sheet_name, rows in sheets:
        mapping = detect_columns(rows)
        vel_ms, meta = extract_shots(rows, mapping, file_unit)
        if not vel_ms:
            continue
        stats = compute_stats(vel_ms, file_unit)

        name = (sheet_name or "").strip()
        if not name:
            name = _find_session_date(rows) or "Session %d" % (len(charges) + 1)
        else:
            name = name.replace("_", " ")
        charges.append(
            build_charge_xml(name, vel_ms, meta, stats, file_unit, value_kg=value_kg)
        )
        summary["files"] += 1
        summary["total_shots"] += len(vel_ms)
        summary["charges"].append({"name": name, "shots": len(vel_ms), **stats})

    summary["sessions"] = summary["files"]
    grt = build_grtload("".join(charges), 0.0, base_content,
                        measurement_title="Imported Sessions")
    return grt, summary


def _find_session_date(rows):
    """Pull a 'Date' value from a session footer, if present (for naming)."""
    for r in rows:
        if r and str(r[0]).strip().lower() == "date":
            for c in r[1:]:
                if str(c).strip():
                    return str(c).strip()
    return None


def import_files(file_paths, file_unit="imperial", base_content=None, propellant_mass_g=0.0):
    """High-level: parse each file into a charge, return (grtload_text, summary).

    Standard mode charge weight:
      * If propellant_mass_g is given (>0), use it.
      * Else, if a base .grtload is supplied, pull its load charge (the `mc`
        field) so the imported measurement carries the real charge weight
        instead of a 0.00 gr placeholder.
      * Else fall back to the tiny placeholder.
    """
    charge_g = propellant_mass_g
    if not charge_g and base_content:
        d = read_base_ladder_defaults(base_content)
        if d.get("top_gr"):
            charge_g = d["top_gr"] / GRAINS_PER_GRAM

    value_kg = charge_g / 1000.0 if charge_g else 1e-12

    charges = []
    summary = {"files": 0, "total_shots": 0, "charges": [],
               "charge_gr": charge_g * GRAINS_PER_GRAM if charge_g else 0.0}
    for path in file_paths:
        rows = read_rows(path)
        mapping = detect_columns(rows)
        vel_ms, meta = extract_shots(rows, mapping, file_unit)
        if not vel_ms:
            continue
        stats = compute_stats(vel_ms, file_unit)
        name = os.path.splitext(os.path.basename(path))[0].replace("_", " ")
        charges.append(build_charge_xml(name, vel_ms, meta, stats, file_unit,
                                        value_kg=value_kg))
        summary["files"] += 1
        summary["total_shots"] += len(vel_ms)
        summary["charges"].append({"name": name, "shots": len(vel_ms), **stats})

    grt = build_grtload("".join(charges), charge_g, base_content)
    return grt, summary
