#!/usr/bin/env python3
r"""Generate a visual F1 weekend report in a pit-wall/broadcast style.

Two drivers are compared across one or more races with SVG charts generated
directly in Python, without an external charting dependency.
"""
import csv
import html
import statistics
import sys

import numpy as np

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

from f1_compare import extract_laps, pick_fastest, clean_curve, lap_sectors, fmt_ms
from f1_track_data import track_svg

esc = html.escape

# ---- paleta (motorsport dark) ---------------------------------------------
PAUL = "#35D2F0"      # cyan/gheata
STEFAN = "#FF9E3D"    # amber
INK = "#0B0E14"
PANEL = "#131A27"
LINE = "#26324A"
FOG = "#8A94A9"
CHALK = "#EDF1F8"
WIN = "#3EE594"


def _f(x, d=0.0):
    try:
        return float(x)
    except (ValueError, TypeError):
        return d


def load_rich(path):
    out = []
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if not r.get("lap_num") or not r.get("lap_distance") or not r.get("cur_lap_ms"):
                continue
            out.append({
                "lap": int(_f(r["lap_num"])), "dist": _f(r["lap_distance"]),
                "t": _f(r["cur_lap_ms"]), "last_lap": _f(r.get("last_lap_ms")),
                "speed": _f(r.get("speed_kmh")), "s1": _f(r.get("s1_ms")),
                "s2": _f(r.get("s2_ms")), "invalid": int(_f(r.get("lap_invalid"))),
                "tyre": (r.get("tyre_visual") or "").strip(),
                "pos": int(_f(r.get("position"))) if r.get("position") else None,
            })
    return out


def analytics(path):
    s = load_rich(path)
    laps = extract_laps(s)
    order = [L for L in sorted(laps) if laps[L]["t"] and laps[L].get("coverage", 0) > 0.5]
    perlap = []
    for L in order:
        d = laps[L]
        s1, s2, s3 = lap_sectors(d, d["t"])
        tyres = [x["tyre"] for x in d["samples"] if x["tyre"]]
        perlap.append({"lap": L, "t": d["t"], "valid": d["valid"], "s1": s1,
                       "s2": s2, "s3": s3,
                       "tyre": max(set(tyres), key=tyres.count) if tyres else ""})
    flying = [p for p in perlap if p["valid"] and p["t"]]
    pool = flying or perlap
    best = min(pool, key=lambda p: p["t"]) if pool else None
    times = [p["t"] for p in flying]
    avg = sum(times) / len(times) if times else 0
    sigma = statistics.pstdev(times) / 1000 if len(times) > 1 else 0
    top = max((x["speed"] for x in s), default=0)
    b1 = min((p["s1"] for p in flying if p["s1"]), default=0)
    b2 = min((p["s2"] for p in flying if p["s2"]), default=0)
    b3 = min((p["s3"] for p in flying if p["s3"]), default=0)
    pos = next((x["pos"] for x in reversed(s) if x["pos"]), None)
    fi = pick_fastest(laps)
    if fi is None:
        cand = [L for L in laps if laps[L]["t"]]
        fi = min(cand, key=lambda L: laps[L]["t"]) if cand else None
    if fi is not None:
        dist, ctime = clean_curve(laps[fi]["samples"], "t")
        _, spd = clean_curve(laps[fi]["samples"], "speed")
    else:
        dist = ctime = spd = np.array([])
    return {"perlap": perlap, "flying": flying, "best": best, "avg": avg,
            "sigma": sigma, "top": top, "b1": b1, "b2": b2, "b3": b3,
            "theo": b1 + b2 + b3, "pos": pos, "dist": dist, "ctime": ctime,
            "spd": spd, "nlaps": len(order)}


# ===========================================================================
# SVG helpers
# ===========================================================================
def _poly(xs, ys, color, w=2.2, dash=""):
    pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys))
    d = f' stroke-dasharray="{dash}"' if dash else ""
    return f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="{w}" stroke-linejoin="round"{d}/>'


def svg_laptime(a1, a2, n1, n2):
    W, H = 760, 300
    ml, mr, mt, mb = 62, 18, 18, 34
    p1 = [p for p in a1["perlap"]]
    p2 = [p for p in a2["perlap"]]
    laps = sorted({p["lap"] for p in p1} | {p["lap"] for p in p2})
    if not laps:
        return ""
    allt = [p["t"] / 1000 for p in p1 + p2 if p["valid"]]
    lo, hi = min(allt), max(allt)
    pad = (hi - lo) * 0.15 + 0.3
    lo, hi = lo - pad, hi + pad
    x0, x1 = min(laps), max(laps)

    def X(l):
        return ml + (l - x0) / max(1, (x1 - x0)) * (W - ml - mr)

    def Y(t):
        return mt + (hi - t) / (hi - lo) * (H - mt - mb)
    g = [f'<svg viewBox="0 0 {W} {H}" width="100%" xmlns="http://www.w3.org/2000/svg" font-family="JetBrains Mono, Consolas, monospace">']
    # Grid lines and time-axis labels.
    for k in range(5):
        t = lo + (hi - lo) * k / 4
        y = Y(t)
        g.append(f'<line x1="{ml}" y1="{y:.0f}" x2="{W-mr}" y2="{y:.0f}" stroke="{LINE}" stroke-width="1"/>')
        g.append(f'<text x="{ml-8}" y="{y+4:.0f}" fill="{FOG}" font-size="12" text-anchor="end">{fmt_ms(int(t*1000))}</text>')
    for l in laps[::max(1, len(laps)//12)]:
        g.append(f'<text x="{X(l):.0f}" y="{H-10}" fill="{FOG}" font-size="11" text-anchor="middle">{l}</text>')
    g.append(f'<text x="{(ml+W-mr)/2:.0f}" y="{H+0}" fill="{FOG}" font-size="0"></text>')
    for a, col, valid_only in ((p1, PAUL, False), (p2, STEFAN, False)):
        xs, ys = [], []
        for p in a:
            xs.append(X(p["lap"]))
            ys.append(Y(p["t"] / 1000))
        g.append(_poly(xs, ys, col, 2.4))
        for p in a:
            r = 3 if p["valid"] else 2.2
            fill = col if p["valid"] else INK
            g.append(f'<circle cx="{X(p["lap"]):.1f}" cy="{Y(p["t"]/1000):.1f}" r="{r}" fill="{fill}" stroke="{col}" stroke-width="1.4"/>')
    g.append("</svg>")
    return "".join(g)


def _common(a1, a2):
    d1, t1 = a1["dist"], a1["ctime"]
    d2, t2 = a2["dist"], a2["ctime"]
    dmax = min(d1.max(), d2.max())
    grid = np.linspace(0, dmax, 480)
    T1 = np.interp(grid, d1, t1)
    T2 = np.interp(grid, d2, t2)
    S1 = np.interp(grid, d1, a1["spd"])
    S2 = np.interp(grid, d2, a2["spd"])
    return grid, T1, T2, S1, S2


def svg_delta(a1, a2, n1, n2):
    grid, T1, T2, S1, S2 = _common(a1, a2)
    delta = (T1 - T2) / 1000.0
    W, H = 760, 220
    ml, mr, mt, mb = 54, 18, 16, 26
    dmax = grid.max()
    amp = max(0.25, float(np.max(np.abs(delta))) * 1.15)

    def X(d):
        return ml + d / dmax * (W - ml - mr)

    def Y(v):
        return mt + (amp - v) / (2 * amp) * (H - mt - mb)
    y0 = Y(0)
    xs = [X(d) for d in grid]
    ys = [Y(v) for v in delta]
    g = [f'<svg viewBox="0 0 {W} {H}" width="100%" xmlns="http://www.w3.org/2000/svg" font-family="JetBrains Mono, Consolas, monospace">']
    g.append(f'<defs><linearGradient id="gp" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="{STEFAN}" stop-opacity="0.35"/><stop offset="100%" stop-color="{STEFAN}" stop-opacity="0"/></linearGradient>'
             f'<linearGradient id="gn" x1="0" y1="1" x2="0" y2="0"><stop offset="0%" stop-color="{PAUL}" stop-opacity="0.35"/><stop offset="100%" stop-color="{PAUL}" stop-opacity="0"/></linearGradient></defs>')
    # Positive/negative areas.
    top_area = f'{ml},{y0:.1f} ' + " ".join(f"{x:.1f},{min(y,y0):.1f}" for x, y in zip(xs, ys)) + f' {W-mr},{y0:.1f}'
    g.append(f'<polygon points="{top_area}" fill="url(#gp)"/>')
    bot_area = f'{ml},{y0:.1f} ' + " ".join(f"{x:.1f},{max(y,y0):.1f}" for x, y in zip(xs, ys)) + f' {W-mr},{y0:.1f}'
    g.append(f'<polygon points="{bot_area}" fill="url(#gn)"/>')
    g.append(f'<line x1="{ml}" y1="{y0:.1f}" x2="{W-mr}" y2="{y0:.1f}" stroke="{FOG}" stroke-width="1" stroke-dasharray="3 3"/>')
    g.append(_poly(xs, ys, CHALK, 2))
    # etichete
    g.append(f'<text x="{ml}" y="{mt+2}" fill="{STEFAN}" font-size="11">▲ {esc(n2)} faster</text>')
    g.append(f'<text x="{ml}" y="{H-8}" fill="{PAUL}" font-size="11">▼ {esc(n1)} faster</text>')
    for frac in (0, .25, .5, .75, 1):
        g.append(f'<text x="{X(dmax*frac):.0f}" y="{H-8}" fill="{FOG}" font-size="10" text-anchor="middle">{dmax*frac:.0f}m</text>')
    g.append("</svg>")
    return "".join(g)


def svg_speed(a1, a2, n1, n2):
    grid, T1, T2, S1, S2 = _common(a1, a2)
    W, H = 760, 220
    ml, mr, mt, mb = 54, 18, 16, 26
    dmax = grid.max()
    lo = min(float(S1.min()), float(S2.min())) - 8
    hi = max(float(S1.max()), float(S2.max())) + 8

    def X(d):
        return ml + d / dmax * (W - ml - mr)

    def Y(v):
        return mt + (hi - v) / (hi - lo) * (H - mt - mb)
    g = [f'<svg viewBox="0 0 {W} {H}" width="100%" xmlns="http://www.w3.org/2000/svg" font-family="JetBrains Mono, Consolas, monospace">']
    for k in range(4):
        v = lo + (hi - lo) * k / 3
        y = Y(v)
        g.append(f'<line x1="{ml}" y1="{y:.0f}" x2="{W-mr}" y2="{y:.0f}" stroke="{LINE}" stroke-width="1"/>')
        g.append(f'<text x="{ml-8}" y="{y+4:.0f}" fill="{FOG}" font-size="11" text-anchor="end">{v:.0f}</text>')
    g.append(_poly([X(d) for d in grid], [Y(v) for v in S1], PAUL, 2.2))
    g.append(_poly([X(d) for d in grid], [Y(v) for v in S2], STEFAN, 2.2))
    for frac in (0, .25, .5, .75, 1):
        g.append(f'<text x="{X(dmax*frac):.0f}" y="{H-8}" fill="{FOG}" font-size="10" text-anchor="middle">{dmax*frac:.0f}m</text>')
    g.append("</svg>")
    return "".join(g)


def sector_rows(a1, a2, n1, n2):
    rows = []
    for i, key in enumerate(("b1", "b2", "b3"), 1):
        t1, t2 = a1[key], a2[key]
        d = (t1 - t2) / 1000.0
        faster = n1 if d < 0 else (n2 if d > 0 else "—")
        col = PAUL if d < 0 else (STEFAN if d > 0 else FOG)
        w1 = 50 if not (t1 or t2) else int(100 * t1 / max(t1, t2))
        w2 = 50 if not (t1 or t2) else int(100 * t2 / max(t1, t2))
        rows.append(f'''
        <div class="secrow">
          <div class="secname">S{i}</div>
          <div class="secbar"><div class="sb sb-l" style="width:{w1}%;background:{PAUL}"></div></div>
          <div class="sectime mono">{fmt_ms(t1)}</div>
          <div class="secdelta mono" style="color:{col}">{'+' if d>=0 else ''}{d:.3f}s</div>
          <div class="sectime mono r">{fmt_ms(t2)}</div>
          <div class="secbar"><div class="sb sb-r" style="width:{w2}%;background:{STEFAN}"></div></div>
        </div>''')
    return "".join(rows)


def perlap_table(a1, a2, n1, n2):
    laps = sorted({p["lap"] for p in a1["perlap"]} | {p["lap"] for p in a2["perlap"]})
    m1 = {p["lap"]: p for p in a1["perlap"]}
    m2 = {p["lap"]: p for p in a2["perlap"]}
    best1 = a1["best"]["lap"] if a1["best"] else None
    best2 = a2["best"]["lap"] if a2["best"] else None
    rows = []
    for L in laps:
        p, q = m1.get(L), m2.get(L)
        t1 = fmt_ms(p["t"]) if p else "—"
        t2 = fmt_ms(q["t"]) if q else "—"
        d = ""
        dc = FOG
        if p and q and p["t"] and q["t"]:
            dd = (p["t"] - q["t"]) / 1000
            d = f"{'+' if dd>=0 else ''}{dd:.3f}"
            dc = PAUL if dd < 0 else STEFAN
        c1 = "cellbest" if L == best1 else ""
        c2 = "cellbest" if L == best2 else ""
        inv1 = " inv" if p and not p["valid"] else ""
        inv2 = " inv" if q and not q["valid"] else ""
        ty = (p or q or {}).get("tyre", "")
        rows.append(f'<tr><td class="lp">{L}</td>'
                    f'<td class="mono {c1}{inv1}">{t1}</td>'
                    f'<td class="mono d" style="color:{dc}">{d}</td>'
                    f'<td class="mono r {c2}{inv2}">{t2}</td>'
                    f'<td class="ty">{esc(ty)}</td></tr>')
    return "".join(rows)


def stat_block(a, name, color, tag):
    best = fmt_ms(a["best"]["t"]) if a["best"] else "—"
    return f'''
    <div class="driver">
      <div class="dhead" style="--c:{color}">
        <span class="ddot" style="background:{color}"></span>
        <span class="dname">{esc(name)}</span>
        {tag}
      </div>
      <div class="dbest mono" style="color:{color}">{best}</div>
      <div class="dbestlbl">best lap</div>
      <div class="dstats">
        <div><span class="mono">{fmt_ms(int(a['avg']))}</span><label>race average</label></div>
        <div><span class="mono">{a['sigma']:.3f}s</span><label>consistency σ</label></div>
        <div><span class="mono">{a['top']:.0f}</span><label>top speed km/h</label></div>
        <div><span class="mono">{fmt_ms(a['theo'])}</span><label>theoretical lap</label></div>
      </div>
    </div>'''


def race_section(idx, title, date, a1, a2, n1, n2, winner, laps_txt="", pole=None):
    # Result and race story.
    pos1 = a1["pos"] or 0
    pos2 = a2["pos"] or 0
    win_c = PAUL if winner == n1 else STEFAN
    fast_holder = n1 if (a1["best"] and a2["best"] and a1["best"]["t"] < a2["best"]["t"]) else n2
    dbest = None
    if a1["best"] and a2["best"]:
        dbest = (a1["best"]["t"] - a2["best"]["t"]) / 1000
    if fast_holder != winner:
        story = (f"{esc(winner)} won the race, although the fastest lap "
                 f"belonged to {esc(fast_holder)} — pace versus result.")
    else:
        story = f"{esc(winner)} controlled both the victory and the fastest lap."

    # Qualifying pole strip.
    pole_html = ""
    if pole and pole[0] and pole[1] and pole[0]["best"] and pole[1]["best"]:
        q1, q2 = pole[0]["best"]["t"], pole[1]["best"]["t"]
        poler = n1 if q1 < q2 else n2
        pc = PAUL if q1 < q2 else STEFAN
        dq = abs(q1 - q2) / 1000
        pole_html = f'''
      <div class="pole">
        <span class="plabel">Qualifying · pole</span>
        <span class="mono" style="color:{PAUL}">{fmt_ms(q1)}</span>
        <span class="pvs">vs</span>
        <span class="mono" style="color:{STEFAN}">{fmt_ms(q2)}</span>
        <span class="pole-win" style="--c:{pc}">POLE {esc(poler)} · +{dq:.3f}s</span>
      </div>'''

    tag1 = f'<span class="wtag" style="--c:{PAUL}">P{pos1} · WIN</span>' if winner == n1 else f'<span class="ptag">P{pos1}</span>'
    tag2 = f'<span class="wtag" style="--c:{STEFAN}">P{pos2} · WIN</span>' if winner == n2 else f'<span class="ptag">P{pos2}</span>'

    delta_txt = ""
    if dbest is not None:
        c = PAUL if dbest < 0 else STEFAN
        who = n1 if dbest < 0 else n2
        delta_txt = f'<div class="vsdelta"><span class="mono" style="color:{c}">{abs(dbest):.3f}s</span><label>Δ best lap · {esc(who)}</label></div>'

    return f'''
  <section class="race" id="r{idx}">
    <div class="reyebrow"><span class="rnum">R{idx:02d}</span> RACE REPORT · {esc(date)}{laps_txt}</div>
    <div class="rtitle-row">
      <h2 class="rtitle">{esc(title)}</h2>
      <div class="rwin" style="--c:{win_c}">Winner: <b>{esc(winner)}</b></div>
    </div>
    <p class="rstory">{story}</p>
    {pole_html}

    <div class="versus">
      {stat_block(a1, n1, PAUL, tag1)}
      {delta_txt}
      {stat_block(a2, n2, STEFAN, tag2)}
    </div>

    <div class="grid2">
      <div class="card">
        <div class="ctitle">Sectors — each driver's best</div>
        <div class="seclegend"><span style="color:{PAUL}">{esc(n1)}</span><span style="color:{STEFAN}">{esc(n2)}</span></div>
        {sector_rows(a1, a2, n1, n2)}
      </div>
      <div class="card">
        <div class="ctitle">Lap-time progression</div>
        {svg_laptime(a1, a2, n1, n2)}
        <div class="clegend"><span class="dot" style="background:{PAUL}"></span>{esc(n1)}<span class="dot" style="background:{STEFAN};margin-left:16px"></span>{esc(n2)}<span class="hollow">○ invalid lap</span></div>
      </div>
    </div>

    <div class="card">
      <div class="ctitle">Reference-lap analysis — where the lap is won</div>
      <div class="tracelbl">Δ time over distance</div>
      {svg_delta(a1, a2, n1, n2)}
      <div class="tracelbl">Speed over distance</div>
      {svg_speed(a1, a2, n1, n2)}
      <div class="clegend"><span class="dot" style="background:{PAUL}"></span>{esc(n1)}<span class="dot" style="background:{STEFAN};margin-left:16px"></span>{esc(n2)}</div>
    </div>

    <div class="card">
      <div class="ctitle">Circuit map — imported racing line</div>
      {track_svg(title, width=900, height=330, stroke=FOG, accent=win_c)}
    </div>

    <details class="card lapcard">
      <summary>All laps — technical data ({a1['nlaps']} / {a2['nlaps']} laps)</summary>
      <table class="laptable">
        <thead><tr><th>Lap</th><th>{esc(n1)}</th><th>Δ</th><th class="r">{esc(n2)}</th><th>Tyres</th></tr></thead>
        <tbody>{perlap_table(a1, a2, n1, n2)}</tbody>
      </table>
    </details>
  </section>'''


def build_css():
    return f"""
    :root{{--paul:{PAUL};--stefan:{STEFAN};--ink:{INK};--panel:{PANEL};--line:{LINE};--fog:{FOG};--chalk:{CHALK};--win:{WIN}}}
    *{{box-sizing:border-box}}
    body{{margin:0;background:
        radial-gradient(1200px 500px at 80% -10%, #16203300, #0000),
        linear-gradient(180deg,#0c1220,{INK});color:{CHALK};
        font-family:'Saira','Segoe UI',system-ui,sans-serif;line-height:1.5;-webkit-font-smoothing:antialiased}}
    .mono{{font-family:'JetBrains Mono',Consolas,monospace;font-variant-numeric:tabular-nums}}
    .wrap{{max-width:980px;margin:0 auto;padding:40px 22px 80px}}
    /* ---- hero serie ---- */
    .hero{{position:relative;border:1px solid {LINE};border-radius:16px;overflow:hidden;
        background:{PANEL};padding:34px 30px}}
    .hero:before{{content:"";position:absolute;inset:0;background:
        linear-gradient(115deg,{PAUL}14 0%,#0000 42%,#0000 58%,{STEFAN}14 100%)}}
    .kicker{{position:relative;font-family:'Saira Condensed','Arial Narrow',sans-serif;
        letter-spacing:.32em;text-transform:uppercase;color:{FOG};font-size:13px;font-weight:600}}
    .htitle{{position:relative;font-family:'Saira Condensed','Arial Narrow',sans-serif;font-weight:700;
        text-transform:uppercase;font-size:clamp(38px,8vw,74px);line-height:.94;margin:8px 0 4px;letter-spacing:.01em}}
    .htitle .p{{color:{PAUL}}} .htitle .s{{color:{STEFAN}}} .htitle .v{{color:{FOG};margin:0 .18em}}
    .hsub{{position:relative;color:{FOG};max-width:60ch}}
    .series{{position:relative;display:flex;gap:14px;align-items:stretch;margin-top:24px;flex-wrap:wrap}}
    .scard{{flex:1;min-width:150px;border:1px solid {LINE};border-radius:12px;padding:16px 18px;background:#0e1522}}
    .scard .n{{font-family:'Saira Condensed',sans-serif;text-transform:uppercase;letter-spacing:.08em;font-weight:700;font-size:20px}}
    .scard .w{{font-family:'JetBrains Mono',monospace;font-size:40px;font-weight:700;line-height:1}}
    .scard label{{color:{FOG};font-size:12px;text-transform:uppercase;letter-spacing:.14em}}
    .score{{flex:0 0 auto;display:flex;flex-direction:column;justify-content:center;align-items:center;
        border:1px solid {LINE};border-radius:12px;padding:10px 22px;background:#0e1522}}
    .score .v{{font-family:'JetBrains Mono',monospace;font-size:34px;font-weight:700}}
    .score label{{color:{FOG};font-size:11px;letter-spacing:.18em;text-transform:uppercase}}
    /* ---- race ---- */
    .race{{margin-top:52px}}
    .reyebrow{{font-family:'Saira Condensed',sans-serif;letter-spacing:.28em;text-transform:uppercase;
        color:{FOG};font-size:12px;font-weight:600;display:flex;align-items:center;gap:10px}}
    .rnum{{color:{INK};background:{CHALK};font-weight:700;padding:2px 8px;border-radius:5px;letter-spacing:.05em}}
    .rtitle-row{{display:flex;justify-content:space-between;align-items:flex-end;gap:16px;flex-wrap:wrap;margin-top:6px}}
    .rtitle{{font-family:'Saira Condensed','Arial Narrow',sans-serif;text-transform:uppercase;font-weight:700;
        font-size:clamp(30px,5vw,46px);margin:0;letter-spacing:.01em}}
    .rwin{{border:1px solid var(--c);color:var(--c);border-radius:999px;padding:5px 14px;font-size:14px;white-space:nowrap}}
    .rwin b{{font-weight:700}}
    .rstory{{color:{FOG};margin:8px 0 22px;max-width:70ch}}
    /* versus */
    .versus{{display:grid;grid-template-columns:1fr auto 1fr;gap:18px;align-items:center;
        border:1px solid {LINE};border-radius:14px;background:{PANEL};padding:22px;position:relative;overflow:hidden}}
    .versus:before{{content:"";position:absolute;top:0;bottom:0;left:calc(50% - 1px);width:2px;
        background:linear-gradient(180deg,#0000,{LINE},#0000)}}
    .driver .dhead{{display:flex;align-items:center;gap:10px}}
    .ddot{{width:11px;height:11px;border-radius:50%;box-shadow:0 0 12px var(--c)}}
    .dname{{font-family:'Saira Condensed',sans-serif;text-transform:uppercase;font-weight:700;font-size:22px;letter-spacing:.04em}}
    .wtag{{margin-left:auto;font-family:'Saira Condensed',sans-serif;font-size:12px;letter-spacing:.1em;
        color:var(--c);border:1px solid var(--c);border-radius:5px;padding:2px 8px}}
    .ptag{{margin-left:auto;font-family:'Saira Condensed',sans-serif;font-size:12px;letter-spacing:.1em;
        color:{FOG};border:1px solid {LINE};border-radius:5px;padding:2px 8px}}
    .dbest{{font-size:44px;font-weight:700;line-height:1.1;margin-top:12px}}
    .dbestlbl{{color:{FOG};font-size:12px;text-transform:uppercase;letter-spacing:.16em;margin-top:-2px}}
    .dstats{{display:grid;grid-template-columns:1fr 1fr;gap:10px 16px;margin-top:16px}}
    .dstats span{{font-size:17px;font-weight:600}} .dstats label{{display:block;color:{FOG};font-size:11px;text-transform:uppercase;letter-spacing:.12em}}
    .vsdelta{{text-align:center;padding:0 6px}}
    .vsdelta span{{font-size:26px;font-weight:700;display:block}}
    .vsdelta label{{color:{FOG};font-size:11px;text-transform:uppercase;letter-spacing:.1em}}
    /* cards */
    .grid2{{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-top:16px}}
    .card{{border:1px solid {LINE};border-radius:14px;background:{PANEL};padding:18px}}
    .ctitle{{font-family:'Saira Condensed',sans-serif;text-transform:uppercase;letter-spacing:.1em;
        font-weight:700;font-size:15px;color:{CHALK};margin-bottom:12px}}
    .tracelbl{{color:{FOG};font-size:11px;text-transform:uppercase;letter-spacing:.16em;margin:10px 0 2px}}
    .clegend{{color:{FOG};font-size:12px;margin-top:10px;display:flex;align-items:center;gap:6px}}
    .dot{{width:10px;height:10px;border-radius:50%;display:inline-block}}
    .hollow{{margin-left:auto;color:{FOG}}}
    /* sectors */
    .seclegend{{display:flex;justify-content:space-between;font-size:12px;text-transform:uppercase;letter-spacing:.1em;margin-bottom:10px}}
    .secrow{{display:grid;grid-template-columns:26px 1fr 66px 64px 66px 1fr;align-items:center;gap:8px;margin:9px 0}}
    .secname{{font-family:'Saira Condensed',sans-serif;font-weight:700;color:{FOG}}}
    .secbar{{height:7px;background:#0c1420;border-radius:4px;overflow:hidden}}
    .sb{{height:100%}} .sb-l{{float:right}} 
    .sectime{{font-size:13px}} .sectime.r{{text-align:right}}
    .secdelta{{text-align:center;font-size:13px;font-weight:600}}
    /* tabel */
    .lapcard summary{{font-family:'Saira Condensed',sans-serif;text-transform:uppercase;letter-spacing:.08em;
        font-weight:700;cursor:pointer;color:{CHALK}}}
    .laptable{{width:100%;border-collapse:collapse;margin-top:14px;font-size:13px}}
    .laptable th{{text-align:left;color:{FOG};font-weight:600;text-transform:uppercase;font-size:11px;letter-spacing:.1em;
        border-bottom:1px solid {LINE};padding:6px 8px}}
    .laptable td{{padding:5px 8px;border-bottom:1px solid #1a2231}}
    .laptable td.r,.laptable th.r{{text-align:right}} .laptable td.d{{text-align:center;font-weight:600}}
    .laptable .lp{{color:{FOG}}} .laptable .ty{{color:{FOG}}}
    .cellbest{{background:#1b2740;border-radius:4px;font-weight:700}}
    .inv{{opacity:.4}}
    .foot{{margin-top:56px;color:{FOG};font-size:12px;text-align:center;border-top:1px solid {LINE};padding-top:20px}}
    /* pole strip */
    .pole{{display:flex;align-items:center;gap:12px;flex-wrap:wrap;border:1px dashed {LINE};
        border-radius:10px;padding:10px 14px;margin-bottom:14px;background:#0e1522}}
    .plabel{{font-family:'Saira Condensed',sans-serif;text-transform:uppercase;letter-spacing:.14em;
        font-size:11px;color:{FOG}}}
    .pole .mono{{font-size:16px}} .pvs{{color:{FOG};font-size:12px}}
    .pole-win{{margin-left:auto;color:var(--c);border:1px solid var(--c);border-radius:5px;
        padding:2px 9px;font-family:'Saira Condensed',sans-serif;font-size:12px;letter-spacing:.08em}}
    /* standings chips */
    .standings{{position:relative;display:flex;gap:8px;flex-wrap:wrap;margin-top:20px}}
    .rchip{{border:1px solid {LINE};border-radius:9px;padding:9px 12px;background:#0e1522;min-width:118px}}
    .rchip .rt{{font-family:'Saira Condensed',sans-serif;text-transform:uppercase;font-size:12px;
        letter-spacing:.06em;color:{CHALK};white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
    .rchip .rr{{display:flex;align-items:center;gap:6px;margin-top:5px}}
    .rchip .rw{{font-family:'JetBrains Mono',monospace;font-size:12px;color:var(--c);font-weight:700}}
    .rdotc{{width:8px;height:8px;border-radius:50%;background:var(--c)}}
    /* appendix */
    .allsess{{margin-top:52px}}
    .atable{{width:100%;border-collapse:collapse;margin-top:14px;font-size:13px}}
    .atable th{{text-align:left;color:{FOG};font-weight:600;text-transform:uppercase;font-size:11px;
        letter-spacing:.1em;border-bottom:1px solid {LINE};padding:8px}}
    .atable td{{padding:7px 8px;border-bottom:1px solid #1a2231}}
    .atable td.r{{text-align:right}} .atable .win{{font-weight:700}}
    .atable tr.rc td{{background:#101827}}
    .abadge{{font-family:'Saira Condensed',sans-serif;font-size:11px;letter-spacing:.06em;
        padding:1px 7px;border-radius:4px;border:1px solid {LINE};color:{FOG}}}
    .abadge.race{{color:{CHALK};border-color:{FOG}}}
    @media(max-width:760px){{.grid2{{grid-template-columns:1fr}}.versus{{grid-template-columns:1fr}}.versus:before{{display:none}}
        .secrow{{grid-template-columns:22px 1fr 60px 58px 60px 1fr}}}}
"""


def build(rounds, appendix, out, d1, d2):
    """rounds: list of dict(title, date, laps, p1, p2, winner, q1, q2).
       appendix: list of dict(idx, track, typ, laps, b1, b2, winner)."""
    sections, chips = [], []
    wins = {d1: 0, d2: 0}
    for i, rd in enumerate(rounds, 1):
        a1, a2 = analytics(rd["p1"]), analytics(rd["p2"])
        pole = None
        if rd.get("q1") and rd.get("q2"):
            pole = (analytics(rd["q1"]), analytics(rd["q2"]))
        wins[rd["winner"]] += 1
        laps_txt = f' · {rd["laps"]} laps' if rd.get("laps") else ""
        sections.append(race_section(i, rd["title"], rd["date"], a1, a2, d1, d2,
                                     rd["winner"], laps_txt, pole))
        wc = PAUL if rd["winner"] == d1 else STEFAN
        short = rd["title"].split(" · ")[0]
        chips.append(f'<a href="#r{i}" class="rchip" style="--c:{wc};text-decoration:none">'
                     f'<div class="rt">R{i:02d} · {esc(short)}</div>'
                     f'<div class="rr"><span class="rdotc"></span><span class="rw">{esc(rd["winner"])}</span></div></a>')

    # appendix table
    arows = []
    for a in appendix:
        wc = PAUL if a["winner"] == d1 else STEFAN
        cls = "rc" if a["typ"] == "Race" else ""
        badge = "abadge race" if a["typ"] == "Race" else "abadge"
        arows.append(f'<tr class="{cls}"><td class="mono">s{a["idx"]}</td>'
                     f'<td>{esc(a["track"])}</td>'
                     f'<td><span class="{badge}">{a["typ"]}</span></td>'
                     f'<td class="r mono">{a["laps"]}</td>'
                     f'<td class="r mono" style="color:{PAUL}">{fmt_ms(a["b1"]) if a["b1"] else "—"}</td>'
                     f'<td class="r mono" style="color:{STEFAN}">{fmt_ms(a["b2"]) if a["b2"] else "—"}</td>'
                     f'<td class="win" style="color:{wc}">{esc(a["winner"])}</td></tr>')

    lead = d1 if wins[d1] >= wins[d2] else d2
    lead_c = PAUL if lead == d1 else STEFAN

    css = build_css()
    html_doc = f'''<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(d1)} vs {esc(d2)} — Evening Championship</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Saira+Condensed:wght@500;600;700&family=Saira:wght@400;500;600&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">
<style>{css}</style></head><body><div class="wrap">
  <header class="hero">
    <div class="kicker">F1 26 · Split screen · Telemetry · {len(rounds)} rounds</div>
    <div class="htitle"><span class="p">{esc(d1)}</span><span class="v">vs</span><span class="s">{esc(d2)}</span></div>
    <div class="hsub">Evening championship across {len(rounds)} circuits. Each qualifying and race round is compared lap by lap from real telemetry. Leader: <b style="color:{lead_c}">{esc(lead)}</b>.</div>
    <div class="series">
      <div class="scard"><label>Race wins</label><div class="w" style="color:{PAUL}">{wins[d1]}</div><div class="n" style="color:{PAUL}">{esc(d1)}</div></div>
      <div class="score"><label>Standings</label><div class="v">{wins[d1]} — {wins[d2]}</div></div>
      <div class="scard" style="text-align:right"><label>Race wins</label><div class="w" style="color:{STEFAN}">{wins[d2]}</div><div class="n" style="color:{STEFAN}">{esc(d2)}</div></div>
    </div>
    <div class="standings">{''.join(chips)}</div>
  </header>
  {''.join(sections)}
  <section class="allsess">
    <div class="reyebrow"><span class="rnum">LOG</span> ALL RECORDED SESSIONS</div>
    <h2 class="rtitle">Complete log</h2>
    <table class="atable">
      <thead><tr><th>Session</th><th>Track</th><th>Type</th><th class="r">Laps</th>
      <th class="r">{esc(d1)}</th><th class="r">{esc(d2)}</th><th>Faster</th></tr></thead>
      <tbody>{''.join(arows)}</tbody>
    </table>
  </section>
  <div class="foot">Generated from F1 26 UDP telemetry · {len(appendix)} sessions with data · times, sectors, and traces come from recorded raw data.</div>
</div></body></html>'''
    with open(out, "w", encoding="utf-8") as f:
        f.write(html_doc)
    print(f"Report written: {out}  ({len(html_doc)//1024} KB, {len(rounds)} rounds, {len(appendix)} sessions)")


if __name__ == "__main__":
    import glob as _glob

    def find(sess, who):
        g = _glob.glob(f"reports/f1_{who}_s{sess}_*.csv")
        return g[0] if g else None

    # Manually identified rounds in chronological order (length and pace).
    ROUNDS = [
        {"title": "Spa · Belgium", "date": "Race", "laps": 13, "winner": "Stefan",
         "p1": find(13, "p1"), "p2": find(13, "p2"), "q1": find(1, "p1"), "q2": find(1, "p2")},
        {"title": "Montreal · Canada", "date": "Race", "laps": 24, "winner": "Paul",
         "p1": find(27, "p1"), "p2": find(27, "p2"), "q1": find(21, "p1"), "q2": find(21, "p2")},
        {"title": "Barcelona · Spain", "date": "Race", "laps": 22, "winner": "Paul",
         "p1": find(45, "p1"), "p2": find(45, "p2"), "q1": find(37, "p1"), "q2": find(37, "p2")},
        {"title": "Red Bull Ring · Austria", "date": "Race", "laps": 24, "winner": "Paul",
         "p1": find(70, "p1"), "p2": find(70, "p2"), "q1": find(59, "p1"), "q2": find(59, "p2")},
        {"title": "Hungaroring · Hungary", "date": "Race", "laps": 24, "winner": "Stefan",
         "p1": find(87, "p1"), "p2": find(87, "p2"), "q1": find(78, "p1"), "q2": find(78, "p2")},
        {"title": "Zandvoort · Netherlands", "date": "Race", "laps": 24, "winner": "Paul",
         "p1": find(109, "p1"), "p2": find(109, "p2"), "q1": find(100, "p1"), "q2": find(100, "p2")},
    ]

    # Table of every session with track names corrected by round.
    TRACK = {1: "Spa · Belgium", 13: "Spa · Belgium", 21: "Montreal · Canada",
             27: "Montreal · Canada", 37: "Barcelona · Spain", 45: "Barcelona · Spain",
             59: "Red Bull Ring · Austria", 70: "Red Bull Ring · Austria",
             78: "Hungaroring · Hungary", 87: "Hungaroring · Hungary",
             100: "Zandvoort · Netherlands", 106: "Zandvoort · Netherlands", 109: "Zandvoort · Netherlands"}
    appendix = []
    for idx in sorted(TRACK):
        p1, p2 = find(idx, "p1"), find(idx, "p2")
        if not (p1 and p2):
            continue
        a1, a2 = analytics(p1), analytics(p2)
        b1 = a1["best"]["t"] if a1["best"] else 0
        b2 = a2["best"]["t"] if a2["best"] else 0
        nl = max(a1["nlaps"], a2["nlaps"])
        typ = "Race" if nl >= 5 else "Qualifying"
        if typ == "Race":
            win = "Paul" if (a1["pos"] or 9) < (a2["pos"] or 9) else (
                  "Stefan" if (a2["pos"] or 9) < (a1["pos"] or 9) else
                  ("Paul" if b1 < b2 else "Stefan"))
        else:
            win = "Paul" if b1 and (not b2 or b1 < b2) else "Stefan"
        appendix.append({"idx": idx, "track": TRACK[idx], "typ": typ, "laps": nl,
                         "b1": b1, "b2": b2, "winner": win})

    build(ROUNDS, appendix, "f1_evening_championship.html", "Paul", "Stefan")
