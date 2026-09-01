#!/usr/bin/env python3
r"""Generate a single-player HTML session report.

The report covers best sectors, every lap, consistency, tyre stints, the speed
trace, and the imported circuit outline using the championship visual style.
"""
import html
import os
import statistics
import sys

import numpy as np

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

from f1_compare import extract_laps, pick_fastest, clean_curve, lap_sectors, fmt_ms
from f1_race_report import load_rich, build_css, PAUL as ACC, STEFAN as ACC2, \
    FOG, LINE, CHALK, PANEL
from f1_track_data import track_svg

esc = html.escape


def analyse_solo(path):
    s = load_rich(path)
    laps = extract_laps(s)
    order = [L for L in sorted(laps)
             if laps[L]["t"] and laps[L].get("coverage", 0) > 0.5]
    rows = []
    for L in order:
        d = laps[L]
        s1, s2, s3 = lap_sectors(d, d["t"])
        tyres = [x["tyre"] for x in d["samples"] if x["tyre"]]
        speeds = [x["speed"] for x in d["samples"] if x["speed"] > 0]
        rows.append({"lap": L, "t": d["t"], "valid": d["valid"], "s1": s1,
                     "s2": s2, "s3": s3,
                     "top": max(speeds) if speeds else 0,
                     "tyre": max(set(tyres), key=tyres.count) if tyres else ""})
    valid = [r for r in rows if r["valid"] and r["t"]]
    pool = valid or rows
    best = min(pool, key=lambda r: r["t"]) if pool else None
    times = [r["t"] for r in valid]
    fi = pick_fastest(laps)
    if fi is None:
        cand = [L for L in laps if laps[L]["t"]]
        fi = min(cand, key=lambda L: laps[L]["t"]) if cand else None
    dist, spd = (clean_curve(laps[fi]["samples"], "speed") if fi is not None
                 else (np.array([]), np.array([])))
    return {
        "rows": rows, "best": best,
        "avg": sum(times) / len(times) if times else 0,
        "sigma": statistics.pstdev(times) / 1000 if len(times) > 1 else 0,
        "top": max((r["top"] for r in rows), default=0),
        "b1": min((r["s1"] for r in valid if r["s1"]), default=0),
        "b2": min((r["s2"] for r in valid if r["s2"]), default=0),
        "b3": min((r["s3"] for r in valid if r["s3"]), default=0),
        "dist": dist, "spd": spd,
        "track": next((x.get("track") for x in s if x.get("track")), None),
        "driver": next((x.get("driver") for x in s if x.get("driver")), None),
        "stype": next((x.get("stype") for x in s if x.get("stype")), None),
    }


def svg_laps(rows):
    W, H = 900, 300
    ml, mr, mt, mb = 70, 18, 18, 34
    pts = [r for r in rows if r["t"]]
    if len(pts) < 2:
        return ""
    t = [r["t"] / 1000 for r in pts]
    lo, hi = min(t), max(t)
    pad = (hi - lo) * 0.15 + 0.3
    lo, hi = lo - pad, hi + pad
    x0, x1 = pts[0]["lap"], pts[-1]["lap"]

    def X(l):
        return ml + (l - x0) / max(1, x1 - x0) * (W - ml - mr)

    def Y(v):
        return mt + (hi - v) / (hi - lo) * (H - mt - mb)
    g = [f'<svg viewBox="0 0 {W} {H}" width="100%" xmlns="http://www.w3.org/2000/svg" '
         f'font-family="JetBrains Mono, Consolas, monospace">']
    for k in range(5):
        v = lo + (hi - lo) * k / 4
        y = Y(v)
        g.append(f'<line x1="{ml}" y1="{y:.0f}" x2="{W-mr}" y2="{y:.0f}" '
                 f'stroke="{LINE}"/>')
        g.append(f'<text x="{ml-8}" y="{y+4:.0f}" fill="{FOG}" font-size="12" '
                 f'text-anchor="end">{fmt_ms(int(v*1000))}</text>')
    poly = " ".join(f'{X(r["lap"]):.1f},{Y(r["t"]/1000):.1f}' for r in pts)
    g.append(f'<polyline points="{poly}" fill="none" stroke="{ACC}" stroke-width="2.4"/>')
    bt = min(r["t"] for r in pts)
    for r in pts:
        x, y = X(r["lap"]), Y(r["t"] / 1000)
        if r["t"] == bt:
            g.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="6" fill="#2ee56b"/>')
        else:
            g.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.2" '
                     f'fill="{ACC if r["valid"] else "#0B0E14"}" stroke="{ACC}" '
                     f'stroke-width="1.4"/>')
    step = max(1, len(pts) // 14)
    for r in pts[::step]:
        g.append(f'<text x="{X(r["lap"]):.0f}" y="{H-10}" fill="{FOG}" '
                 f'font-size="11" text-anchor="middle">{r["lap"]}</text>')
    g.append("</svg>")
    return "".join(g)


def svg_speed(dist, spd):
    if len(dist) < 2:
        return ""
    W, H = 900, 220
    ml, mr, mt, mb = 58, 18, 16, 28
    grid = np.linspace(0, float(dist.max()), 460)
    S = np.interp(grid, dist, spd)
    lo, hi = float(S.min()) - 8, float(S.max()) + 8

    def X(d):
        return ml + d / grid.max() * (W - ml - mr)

    def Y(v):
        return mt + (hi - v) / (hi - lo) * (H - mt - mb)
    g = [f'<svg viewBox="0 0 {W} {H}" width="100%" xmlns="http://www.w3.org/2000/svg" '
         f'font-family="JetBrains Mono, Consolas, monospace">']
    for k in range(4):
        v = lo + (hi - lo) * k / 3
        y = Y(v)
        g.append(f'<line x1="{ml}" y1="{y:.0f}" x2="{W-mr}" y2="{y:.0f}" stroke="{LINE}"/>')
        g.append(f'<text x="{ml-8}" y="{y+4:.0f}" fill="{FOG}" font-size="11" '
                 f'text-anchor="end">{v:.0f}</text>')
    poly = " ".join(f"{X(d):.1f},{Y(v):.1f}" for d, v in zip(grid, S))
    g.append(f'<polyline points="{poly}" fill="none" stroke="{ACC}" stroke-width="2.2"/>')
    for f in (0, .25, .5, .75, 1):
        g.append(f'<text x="{X(grid.max()*f):.0f}" y="{H-8}" fill="{FOG}" '
                 f'font-size="10" text-anchor="middle">{grid.max()*f:.0f}m</text>')
    g.append("</svg>")
    return "".join(g)


def stints(rows):
    out = []
    for r in rows:
        if out and out[-1]["tyre"] == r["tyre"]:
            out[-1]["laps"] += 1
            out[-1]["end"] = r["lap"]
            out[-1]["times"].append(r["t"])
        else:
            out.append({"tyre": r["tyre"] or "—", "laps": 1, "start": r["lap"],
                        "end": r["lap"], "times": [r["t"]]})
    return out


def build_solo(csv_path, out):
    a = analyse_solo(csv_path)
    if not a["best"]:
        raise SystemExit("Session has no complete laps.")
    best = a["best"]
    theo = a["b1"] + a["b2"] + a["b3"]
    title = a["track"] or "Session"
    driver = a["driver"] or "Driver"

    lrows = "".join(
        f'<tr><td class="lp">{r["lap"]}</td>'
        f'<td class="mono{" cellbest" if r["t"]==best["t"] else ""}'
        f'{" inv" if not r["valid"] else ""}">{fmt_ms(r["t"])}</td>'
        f'<td class="mono">{fmt_ms(r["s1"])}</td>'
        f'<td class="mono">{fmt_ms(r["s2"])}</td>'
        f'<td class="mono">{fmt_ms(r["s3"])}</td>'
        f'<td class="mono r">{r["top"]:.0f}</td>'
        f'<td class="ty">{esc(r["tyre"])}</td></tr>' for r in a["rows"])

    srows = "".join(
        f'<tr><td>{esc(s["tyre"])}</td><td class="mono">{s["start"]}–{s["end"]}</td>'
        f'<td class="mono r">{s["laps"]}</td>'
        f'<td class="mono r">{fmt_ms(int(sum(s["times"])/len(s["times"])))}</td></tr>'
        for s in stints(a["rows"]))

    doc = f'''<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(driver)} — {esc(title)}</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Saira+Condensed:wght@500;600;700&family=Saira:wght@400;500;600&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">
<style>{build_css()}
.solo-stats{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:14px;margin-top:18px}}
.sstat{{border:1px solid {LINE};border-radius:12px;background:{PANEL};padding:16px}}
.sstat .v{{font-family:'JetBrains Mono',monospace;font-size:26px;font-weight:700;color:{CHALK}}}
.sstat label{{display:block;color:{FOG};font-size:11px;text-transform:uppercase;letter-spacing:.14em;margin-top:4px}}
</style></head><body><div class="wrap">
<header class="hero">
  <div class="kicker">F1 26 · Single player · Session report</div>
  <div class="htitle"><span class="p">{esc(title)}</span></div>
  <div class="hsub">Driver: <b>{esc(driver)}</b> · {len(a["rows"])} recorded laps.</div>
  <div class="solo-stats">
    <div class="sstat"><div class="v" style="color:{ACC}">{fmt_ms(best["t"])}</div><label>best lap (L{best["lap"]})</label></div>
    <div class="sstat"><div class="v">{fmt_ms(int(a["avg"]))}</div><label>valid-lap average</label></div>
    <div class="sstat"><div class="v">{a["sigma"]:.3f}s</div><label>consistency σ</label></div>
    <div class="sstat"><div class="v">{a["top"]:.0f}</div><label>top speed km/h</label></div>
    <div class="sstat"><div class="v" style="color:#b47cff">{fmt_ms(theo)}</div><label>theoretical lap (best sectors)</label></div>
  </div>
</header>

<section class="race">
  <div class="reyebrow"><span class="rnum">S1</span> SECTORS · PERSONAL BESTS</div>
  <div class="grid2">
    <div class="card">
      <div class="ctitle">Best sectors</div>
      <table class="laptable"><tbody>
        <tr><td>S1</td><td class="mono r">{fmt_ms(a["b1"])}</td></tr>
        <tr><td>S2</td><td class="mono r">{fmt_ms(a["b2"])}</td></tr>
        <tr><td>S3</td><td class="mono r">{fmt_ms(a["b3"])}</td></tr>
        <tr><td><b>Theoretical lap</b></td><td class="mono r"><b>{fmt_ms(theo)}</b></td></tr>
        <tr><td>Gap to actual best</td><td class="mono r">{(best["t"]-theo)/1000:+.3f}s</td></tr>
      </tbody></table>
    </div>
    <div class="card">
      <div class="ctitle">Tyre stints</div>
      <table class="laptable">
        <thead><tr><th>Compound</th><th>Lap range</th><th class="r">Laps</th><th class="r">Average</th></tr></thead>
        <tbody>{srows}</tbody></table>
    </div>
  </div>

  <div class="card">
    <div class="ctitle">Lap-time progression</div>
    {svg_laps(a["rows"])}
    <div class="clegend"><span class="dot" style="background:#2ee56b"></span>best lap
      <span class="hollow">○ invalid lap</span></div>
  </div>

  <div class="card">
    <div class="ctitle">Speed over distance — reference lap</div>
    {svg_speed(a["dist"], a["spd"])}
  </div>

  <div class="card">
    <div class="ctitle">Circuit map — imported racing line</div>
    {track_svg(title, width=900, height=330, stroke=FOG, accent=ACC)}
  </div>

  <details class="card lapcard" open>
    <summary>All laps — technical data</summary>
    <table class="laptable">
      <thead><tr><th>Lap</th><th>Time</th><th>S1</th><th>S2</th><th>S3</th>
      <th class="r">Top km/h</th><th>Tyres</th></tr></thead>
      <tbody>{lrows}</tbody></table>
  </details>
</section>
<div class="foot">Generated automatically from F1 26 UDP telemetry.</div>
</div></body></html>'''
    with open(out, "w", encoding="utf-8") as f:
        f.write(doc)
    return out


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("--out", default=None)
    x = ap.parse_args()
    o = x.out or os.path.splitext(x.csv)[0] + ".html"
    print("Solo report:", build_solo(x.csv, o))
