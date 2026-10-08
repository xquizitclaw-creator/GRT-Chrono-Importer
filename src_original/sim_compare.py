"""
sim_compare.py - "Chrono vs Sim" support for the GRT Chrono Importer.

Consumes a GRT "Export simulation results" JSON (the user exports it from GRT),
pairs each simulated ladder rung with the matching chrono string by charge
weight, and produces:

  * an Analysis text tab  (<note> element)         -- always
  * a "Chrono vs Sim" chart PNG embedded as a       -- when matplotlib present
    <picture> tab

The sim JSON shape (relevant parts):

  {
    "propellant": { "mc": "53.31 grain", "laddercnt": "9",
                    "laddermc": "0.30 grain", ... },
    "ladder": [
      { "charge": "53.31 grain",
        "results": { "MuzzleVelocity": "2891.6 ft/s",
                     "PeakPressure": "57396 psi",
                     "BarrelTime": "1.5978 ms",
                     "OptimalBarrelTime": "1.5033 ms",
                     "OptimalBarrelTimeNode": "#4 1/2" } },
      ...
    ]
  }

Velocities in the JSON are ft/s. Charge weights are grains. We match on
charge weight rounded to 0.01 gr.
"""

import re
from urllib.parse import quote


def _num(s):
    """Pull the leading number out of a value like '2891.6 ft/s' or '53.31 grain'."""
    if s is None:
        return None
    m = re.search(r"-?\d+(?:\.\d+)?", str(s).replace(",", "."))
    return float(m.group(0)) if m else None


def parse_sim_json(data):
    """Return a list of sim rungs sorted high->low charge:
        [{"charge_gr": float, "v0_fps": float, "peak_psi": float,
          "barrel_ms": float, "obt_ms": float, "obt_node": str}, ...]
    Accepts either a parsed dict or a JSON string.
    """
    import json
    if isinstance(data, (str, bytes)):
        data = json.loads(data)
    rungs = []
    for entry in data.get("ladder", []):
        res = entry.get("results", {}) or {}
        charge_gr = _num(entry.get("charge"))
        if charge_gr is None:
            continue
        rungs.append({
            "charge_gr": charge_gr,
            "v0_fps": _num(res.get("MuzzleVelocity")),
            "peak_psi": _num(res.get("PeakPressure")),
            "barrel_ms": _num(res.get("BarrelTime")),
            "obt_ms": _num(res.get("OptimalBarrelTime")),
            "obt_node": str(res.get("OptimalBarrelTimeNode", "")).strip(),
        })
    rungs.sort(key=lambda r: r["charge_gr"], reverse=True)
    return rungs


def match_chrono_to_sim(chrono_charges, sim_rungs, tol=0.05):
    """Pair chrono charges (from import summary) with sim rungs by weight.

    chrono_charges: list of dicts with at least {"weight_gr", "avg", "sd",
                    "es", "shots", "name"} (avg/sd/es in the file's unit = fps
                    for imperial).
    Returns list of merged dicts sorted ascending by charge:
        {"charge_gr", "chrono_avg", "chrono_sd", "chrono_es", "shots",
         "name", "sim_v0", "delta" (chrono-sim), "peak_psi", "obt_ms",
         "barrel_ms", "obt_node"}
    Unmatched chrono entries still appear (sim fields None).
    """
    by_weight = {}
    for s in sim_rungs:
        by_weight[round(s["charge_gr"], 2)] = s

    merged = []
    for c in chrono_charges:
        w = c.get("weight_gr")
        sim = None
        if w is not None:
            sim = by_weight.get(round(w, 2))
            if sim is None:
                best = None
                for s in sim_rungs:
                    d = abs(s["charge_gr"] - w)
                    if d <= tol and (best is None or d < abs(best["charge_gr"] - w)):
                        best = s
                sim = best
        row = {
            "charge_gr": w,
            "name": c.get("name", ""),
            "chrono_avg": c.get("avg"),
            "chrono_sd": c.get("sd"),
            "chrono_es": c.get("es"),
            "shots": c.get("shots"),
            "sim_v0": sim["v0_fps"] if sim else None,
            "peak_psi": sim["peak_psi"] if sim else None,
            "obt_ms": sim["obt_ms"] if sim else None,
            "barrel_ms": sim["barrel_ms"] if sim else None,
            "obt_node": sim["obt_node"] if sim else "",
        }
        if row["chrono_avg"] is not None and row["sim_v0"] is not None:
            row["delta"] = row["chrono_avg"] - row["sim_v0"]
        else:
            row["delta"] = None
        merged.append(row)

    merged.sort(key=lambda r: (r["charge_gr"] is None, r["charge_gr"]))
    return merged


def build_analysis_note(merged, summary, device, unit_label="ft/s", index=3, title="Analysis"):
    """Return a <note> XML element string summarizing the chrono-vs-sim session."""
    lines = []
    lines.append("Chrono → GRT session")
    lines.append("Mode: Ladder (Chrono vs Sim)")
    lines.append("Device: %s" % device)
    lines.append("Displayed as: %s" % unit_label)
    lines.append("Files: %d, total shots: %d"
                 % (summary.get("files", 0), summary.get("total_shots", 0)))
    lines.append("")

    # Best node = lowest chrono SD.
    best = None
    for r in merged:
        if r["chrono_sd"] is not None and (best is None or r["chrono_sd"] < best["chrono_sd"]):
            best = r
    if best:
        lines.append("Best node (auto, lowest SD): %s gr • SD %.2f %s • ES %.1f %s • AVG %.1f %s"
                     % ("%.2f" % best["charge_gr"] if best["charge_gr"] else "?",
                        best["chrono_sd"], unit_label,
                        best["chrono_es"] or 0.0, unit_label,
                        best["chrono_avg"] or 0.0, unit_label))
        lines.append("")

    lines.append("Chrono vs Sim (per charge):")
    for r in merged:
        cg = "%.2f gr" % r["charge_gr"] if r["charge_gr"] is not None else "?"
        if r["chrono_avg"] is not None and r["sim_v0"] is not None:
            lines.append(
                "• %s: chrono %.1f %s vs sim %.1f %s  (delta %+.1f %s)  SD %.2f  n=%d"
                % (cg, r["chrono_avg"], unit_label, r["sim_v0"], unit_label,
                   r["delta"], unit_label, r["chrono_sd"] or 0.0, r["shots"] or 0))
        elif r["chrono_avg"] is not None:
            lines.append("• %s: chrono %.1f %s (no matching sim rung)  SD %.2f  n=%d"
                         % (cg, r["chrono_avg"], unit_label, r["chrono_sd"] or 0.0,
                            r["shots"] or 0))

    deltas = [r["delta"] for r in merged if r["delta"] is not None]
    if deltas:
        lines.append("")
        lines.append("Mean chrono-minus-sim offset: %+.1f %s across %d matched charges."
                     % (sum(deltas) / len(deltas), unit_label, len(deltas)))

    text = "\n".join(lines)
    enc = quote(text, safe="")
    return (
        '      <note index="%d" hasfocus="false" showinreport="true" reporttemplate="false" title="%s" text="%s" />\n'
        % (index, quote(title, safe=""), enc)
    )


def build_chart_picture(merged, unit_label="ft/s", title="Chrono vs Sim", index=4):
    """Render the chrono-vs-sim chart to a base64 PNG inside a <gallery> tab.

    Drawn with Pillow (PIL) only -- no matplotlib -- so it freezes cleanly with
    PyInstaller and has no runtime data-file dependencies. GRT shows pictures
    inside a <gallery> element (the tab); a bare <picture> is ignored. Returns
    the gallery XML string, or None if Pillow is unavailable or there is
    nothing to plot.
    """
    try:
        from PIL import Image, ImageDraw, ImageFont
    except Exception:
        return None
    import io
    import base64

    pts = [r for r in merged if r["chrono_avg"] is not None]
    if not pts:
        return None

    chrono = [r["chrono_avg"] for r in pts]
    sim = [r["sim_v0"] for r in pts]
    has_sim = all(s is not None for s in sim)
    xlabels = [("%.2f" % r["charge_gr"]) if r["charge_gr"] is not None else "?"
               for r in pts]

    # Supersample factor: draw at 2x for crisp output.
    S = 2.0

    def s(x):
        return int(round(x * S))

    W, H = s(1000), s(600)
    bg = (15, 18, 26)
    fg = (210, 210, 210)
    grid = (55, 62, 74)
    c_chrono = (58, 160, 210)
    c_sim = (224, 96, 122)
    img = Image.new("RGB", (W, H), bg)
    d = ImageDraw.Draw(img)

    def _font(sz, bold=False):
        sz = s(sz)
        for name in (("arialbd.ttf",) if bold else ("arial.ttf",)) + (
                "DejaVuSans.ttf", "segoeui.ttf"):
            try:
                return ImageFont.truetype(name, sz)
            except Exception:
                continue
        return ImageFont.load_default()

    f_title = _font(26, bold=True)
    f_axis = _font(16)
    f_small = _font(14)
    f_sub = _font(11)
    f_sub_axis = _font(12)
    f_caption = _font(12)

    def _draw_v0(x, y, font, subfont, fill):
        """Draw 'V' then a lowered, smaller '0' subscript; return end x."""
        d.text((x, y), "V", font=font, fill=fill)
        vw = d.textlength("V", font=font)
        try:
            asc = font.getmetrics()[0]
        except Exception:
            asc = getattr(font, "size", 16)
        d.text((x + vw, y + int(asc * 0.45)), "0", font=subfont, fill=fill)
        return x + vw + d.textlength("0", font=subfont)

    ml, mr, mt, mb = s(90), s(40), s(90), s(70)
    pl, pr = ml, W - mr
    ptop, pbot = mt, H - mb

    allv = list(chrono) + ([s for s in sim if s is not None] if has_sim else [])
    vmin, vmax = min(allv), max(allv)
    if vmax == vmin:
        vmax = vmin + 1.0
    pad = (vmax - vmin) * 0.15
    ymin, ymax = vmin - pad, vmax + pad

    def yx(i, n):
        if n <= 1:
            return (pl + pr) / 2
        return pl + (pr - pl) * i / (n - 1)

    def yy(v):
        return pbot - (pbot - ptop) * (v - ymin) / (ymax - ymin)

    tx = d.textlength("Chrono vs Sim ", font=f_title)
    d.text((pl, s(24)), "Chrono vs Sim ", font=f_title, fill=fg)
    _draw_v0(pl + tx, s(24), f_title, _font(18, bold=True), fg)

    for k in range(6):
        v = ymin + (ymax - ymin) * k / 5
        yp = yy(v)
        d.line([(pl, yp), (pr, yp)], fill=grid, width=max(1, s(1)))
        lbl = "%.0f" % v
        d.text((pl - s(8) - d.textlength(lbl, font=f_small), yp - s(7)), lbl,
               font=f_small, fill=fg)

    ax_x = _draw_v0(s(10), ptop - s(30), f_axis, f_sub_axis, fg)
    d.text((ax_x, ptop - s(30)), " (%s)" % unit_label, font=f_axis, fill=fg)

    n = len(pts)

    for i in range(n):
        xp = yx(i, n)
        d.line([(xp, pbot), (xp, pbot + s(5))], fill=fg, width=max(1, s(1)))
        lbl = xlabels[i]
        d.text((xp - d.textlength(lbl, font=f_small) / 2, pbot + s(10)), lbl,
               font=f_small, fill=fg)
    cx0 = (pl + pr) / 2 - d.textlength("Charge (gr)", font=f_axis) / 2
    d.text((cx0, H - s(28)), "Charge (gr)", font=f_axis, fill=fg)

    d.line([(pl, ptop), (pl, pbot)], fill=fg, width=max(1, s(1)))
    d.line([(pl, pbot), (pr, pbot)], fill=fg, width=max(1, s(1)))

    def _draw_series(vals, color, dashed=False, marker=False):
        prev = None
        for i, v in enumerate(vals):
            if v is None:
                prev = None
                continue
            x, y = yx(i, n), yy(v)
            if prev is not None:
                if dashed:
                    _dashed_line(d, prev, (x, y), color, width=s(3),
                                 dash=s(12), gap=s(8))
                else:
                    d.line([prev, (x, y)], fill=color, width=s(3))
            if marker:
                r = s(4)
                d.ellipse([x - r, y - r, x + r, y + r], fill=color)
            prev = (x, y)

    _draw_series(chrono, c_chrono, dashed=False, marker=True)
    if has_sim:
        _draw_series(sim, c_sim, dashed=True, marker=False)

    lx, ly = pr - s(250), ptop + s(6)
    d.line([(lx, ly + s(8)), (lx + s(30), ly + s(8))], fill=c_chrono, width=s(3))
    d.ellipse([lx + s(13), ly + s(4), lx + s(21), ly + s(12)], fill=c_chrono)
    d.text((lx + s(38), ly), "Chrono avg", font=f_small, fill=fg)
    if has_sim:
        ly2 = ly + s(22)
        _dashed_line(d, (lx, ly2 + s(8)), (lx + s(30), ly2 + s(8)), c_sim,
                     width=s(3), dash=s(8), gap=s(5))
        sx = _draw_v0(lx + s(38) + d.textlength("Sim ", font=f_small), ly2,
                      f_small, _font(10), fg)
        d.text((lx + s(38), ly2), "Sim ", font=f_small, fill=fg)
        d.text((sx, ly2), " (GRT)", font=f_small, fill=fg)

    if has_sim:
        cx = d.textlength("Solid = chrono average    Dashed = simulated ladder ",
                          font=f_caption)
        d.text((pl, s(58)), "Solid = chrono average    Dashed = simulated ladder ",
               font=f_caption, fill=(150, 156, 168))
        _draw_v0(pl + cx, s(58), f_caption, _font(9), (150, 156, 168))

    buf = io.BytesIO()
    img.save(buf, format="png")
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")

    from urllib.parse import quote as _q
    title_enc = _q(title, safe="")
    return (
        '      <gallery index="%d" hasfocus="true" showinreport="true" title="%s">\n'
        '        <picture name="%s" type="png" width="%d" height="%d" data="%s" />\n'
        '      </gallery>\n'
        % (index, title_enc, title_enc, W, H, b64)
    )


def _dashed_line(d, p0, p1, color, width=2, dash=10, gap=6):
    """Draw a dashed line from p0 to p1 using PIL."""
    import math
    x0, y0 = p0
    x1, y1 = p1
    total = math.hypot(x1 - x0, y1 - y0)
    if total == 0:
        return
    dx, dy = (x1 - x0) / total, (y1 - y0) / total
    pos = 0.0
    while pos < total:
        seg = min(dash, total - pos)
        a = (x0 + dx * pos, y0 + dy * pos)
        b = (x0 + dx * (pos + seg), y0 + dy * (pos + seg))
        d.line([a, b], fill=color, width=width)
        pos += dash + gap
