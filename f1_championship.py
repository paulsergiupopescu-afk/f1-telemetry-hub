#!/usr/bin/env python3
r"""Generate a championship HTML report from every session in a folder.

Player CSV files are paired automatically. Circuits come from the CSV track
field, or are inferred from lap length and pace for older files. Qualifying and
race sessions are paired by circuit and race winners are determined by final
position, with best lap as the fallback.

Run: ``python f1_championship.py reports --out f1_championship.html``
"""
import csv
import glob
import os
import re
import sys

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

from f1_race_report import analytics, load_rich, race_section, build_css, esc, fmt_ms, PAUL, STEFAN

# Circuit lengths for old CSV files without a track column.
TRACK_LEN = {
 "Melbourne · Australia": 5278, "Paul Ricard · France": 5842, "Shanghai · China": 5451,
 "Bahrain": 5412, "Barcelona · Spain": 4657, "Monaco": 3337, "Montreal · Canada": 4361,
 "Silverstone · England": 5891, "Hockenheim · Germany": 4574, "Hungaroring · Hungary": 4381,
 "Spa · Belgium": 7004, "Monza · Italy": 5793, "Singapore": 4940, "Suzuka · Japan": 5807,
 "Abu Dhabi": 5281, "COTA · USA": 5513, "Interlagos · Brazil": 4309,
 "Red Bull Ring · Austria": 4318, "Sochi · Russia": 5848, "Mexico City · Mexico": 4304,
 "Baku · Azerbaijan": 6003, "Zandvoort · Netherlands": 4259, "Imola · Italy": 4909,
 "Portimão · Portugal": 4653, "Jeddah · Saudi Arabia": 6174, "Miami · USA": 5412,
 "Las Vegas · USA": 6201, "Losail · Qatar": 5419,
}
# Similar-length circuits are disambiguated using pace.
AMBIG = [
    ({"Montreal · Canada", "Hungaroring · Hungary", "Interlagos · Brazil",
      "Mexico City · Mexico", "Red Bull Ring · Austria", "Zandvoort · Netherlands"}, None),
]
PACE_HINT = {   # Typical lap time used to separate similar circuit lengths.
    "Montreal · Canada": 75, "Hungaroring · Hungary": 81, "Red Bull Ring · Austria": 68,
    "Zandvoort · Netherlands": 73, "Interlagos · Brazil": 72, "Mexico City · Mexico": 79,
    "Bahrain": 93, "Miami · USA": 90,
}


def _csv_track(path):
    """Circuit din coloana track (CSV v4+), altfel None."""
    try:
        with open(path, newline="", encoding="utf-8") as fh:
            r = csv.DictReader(fh)
            if "track" not in (r.fieldnames or []):
                return None
            for row in r:
                if row.get("track"):
                    return row["track"]
    except OSError:
        return None
    return None


def _guess_track(lap_len, best_ms):
    """Infer old CSV tracks from a combined lap-length and pace score."""
    near = [(n, L) for n, L in TRACK_LEN.items() if abs(L - lap_len) < 80]
    if not near:
        return f"Track {lap_len:.0f}m"
    if len(near) == 1 or not best_ms:
        return min(near, key=lambda kv: abs(kv[1] - lap_len))[0]
    pace = best_ms / 1000.0
    def score(item):
        n, L = item
        s_len = (abs(L - lap_len) / 15.0) ** 2
        s_pace = ((abs(PACE_HINT.get(n, pace) - pace)) / 4.0) ** 2
        return s_len + s_pace
    return min(near, key=score)[0]


def discover(folder):
    """Return sorted session dictionaries discovered in an output folder."""
    pairs = {}
    for p in glob.glob(os.path.join(folder, "f1_p1_s*.csv")):
        m = re.search(r"_s(\d+)_(\d+_\d+|\d+)", os.path.basename(p))
        if not m:
            continue
        idx = int(m.group(1))
        q = p.replace("f1_p1_", "f1_p2_")
        if os.path.exists(q):
            pairs[idx] = (p, q)

    sessions = []
    for idx in sorted(pairs):
        p1, p2 = pairs[idx]
        try:
            a1, a2 = analytics(p1), analytics(p2)
        except SystemExit:
            continue
        if not (a1["best"] or a2["best"]):
            continue
        b1 = a1["best"]["t"] if a1["best"] else 0
        b2 = a2["best"]["t"] if a2["best"] else 0
        nl = max(a1["nlaps"], a2["nlaps"])
        typ = "Race" if nl >= 5 else "Qualifying"
        track = _csv_track(p1) or _csv_track(p2)
        if not track:
            lap_len = max((x["dist"] for x in load_rich(p1)), default=0)
            track = _guess_track(lap_len, min(x for x in (b1, b2) if x) if (b1 or b2) else 0)
        if typ == "Race":
            win_p1 = (a1["pos"] or 99) < (a2["pos"] or 99)
            win_p2 = (a2["pos"] or 99) < (a1["pos"] or 99)
            winner = 1 if win_p1 else (2 if win_p2 else (1 if b1 and (not b2 or b1 < b2) else 2))
        else:
            winner = 1 if b1 and (not b2 or b1 < b2) else 2
        sessions.append(dict(idx=idx, p1=p1, p2=p2, a1=a1, a2=a2, track=track,
                             typ=typ, laps=nl, b1=b1, b2=b2, winner=winner))
    return sessions


def pair_rounds(sessions):
    """Pair each race with the most recent preceding qualifying at that track."""
    rounds = []
    last_quali = {}
    for s in sessions:
        if s["typ"] == "Qualifying":
            last_quali[s["track"]] = s
        else:
            rounds.append(dict(title=s["track"], laps=s["laps"], race=s,
                               quali=last_quali.pop(s["track"], None)))
    return rounds


def build_championship(folder, out, n1="Paul", n2="Stefan"):
    sessions = discover(folder)
    if not sessions:
        raise SystemExit(f"No sessions with data in {folder}")
    rounds = pair_rounds(sessions)
    names = {1: n1, 2: n2}
    wins = {n1: 0, n2: 0}
    sections, chips = [], []
    for i, rd in enumerate(rounds, 1):
        rc = rd["race"]
        winner = names[rc["winner"]]
        wins[winner] += 1
        pole = None
        if rd["quali"]:
            pole = (rd["quali"]["a1"], rd["quali"]["a2"])
        laps_txt = f" · {rd['laps']} laps"
        sections.append(race_section(i, rd["title"], "Race", rc["a1"], rc["a2"],
                                     n1, n2, winner, laps_txt, pole))
        wc = PAUL if winner == n1 else STEFAN
        short = rd["title"].split(" · ")[0]
        chips.append(f'<a href="#r{i}" class="rchip" style="--c:{wc};text-decoration:none">'
                     f'<div class="rt">R{i:02d} · {esc(short)}</div>'
                     f'<div class="rr"><span class="rdotc"></span><span class="rw">{esc(winner)}</span></div></a>')

    arows = []
    for s in sessions:
        winner = names[s["winner"]]
        wc = PAUL if winner == n1 else STEFAN
        cls = "rc" if s["typ"] == "Race" else ""
        badge = "abadge race" if s["typ"] == "Race" else "abadge"
        arows.append(f'<tr class="{cls}"><td class="mono">s{s["idx"]}</td>'
                     f'<td>{esc(s["track"])}</td>'
                     f'<td><span class="{badge}">{s["typ"]}</span></td>'
                     f'<td class="r mono">{s["laps"]}</td>'
                     f'<td class="r mono" style="color:{PAUL}">{fmt_ms(s["b1"]) if s["b1"] else "—"}</td>'
                     f'<td class="r mono" style="color:{STEFAN}">{fmt_ms(s["b2"]) if s["b2"] else "—"}</td>'
                     f'<td class="win" style="color:{wc}">{esc(winner)}</td></tr>')

    lead = n1 if wins[n1] >= wins[n2] else n2
    lead_c = PAUL if lead == n1 else STEFAN
    css = build_css()
    html_doc = f'''<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(n1)} vs {esc(n2)} — Championship</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Saira+Condensed:wght@500;600;700&family=Saira:wght@400;500;600&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">
<style>{css}</style></head><body><div class="wrap">
  <header class="hero">
    <div class="kicker">F1 26 · Split screen · Telemetry · {len(rounds)} rounds · championship in progress</div>
    <div class="htitle"><span class="p">{esc(n1)}</span><span class="v">vs</span><span class="s">{esc(n2)}</span></div>
    <div class="hsub">Report generated automatically from all recorded sessions. Leader: <b style="color:{lead_c}">{esc(lead)}</b>.</div>
    <div class="series">
      <div class="scard"><label>Race wins</label><div class="w" style="color:{PAUL}">{wins[n1]}</div><div class="n" style="color:{PAUL}">{esc(n1)}</div></div>
      <div class="score"><label>Standings</label><div class="v">{wins[n1]} — {wins[n2]}</div></div>
      <div class="scard" style="text-align:right"><label>Race wins</label><div class="w" style="color:{STEFAN}">{wins[n2]}</div><div class="n" style="color:{STEFAN}">{esc(n2)}</div></div>
    </div>
    <div class="standings">{''.join(chips)}</div>
  </header>
  {''.join(sections)}
  <section class="allsess">
    <div class="reyebrow"><span class="rnum">LOG</span> ALL RECORDED SESSIONS</div>
    <h2 class="rtitle">Complete log</h2>
    <table class="atable">
      <thead><tr><th>Session</th><th>Track</th><th>Type</th><th class="r">Laps</th>
      <th class="r">{esc(n1)}</th><th class="r">{esc(n2)}</th><th>Faster</th></tr></thead>
      <tbody>{''.join(arows)}</tbody>
    </table>
  </section>
  <div class="foot">Generated automatically from F1 26 UDP telemetry · {len(sessions)} sessions with data.</div>
</div></body></html>'''
    with open(out, "w", encoding="utf-8") as f:
        f.write(html_doc)
    return dict(rounds=len(rounds), sessions=len(sessions), wins=wins, out=out)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", nargs="?", default="reports")
    ap.add_argument("--out", default=None)
    ap.add_argument("--p1", default="Paul")
    ap.add_argument("--p2", default="Stefan")
    a = ap.parse_args()
    out = a.out or os.path.join(a.folder, "f1_championship.html")
    r = build_championship(a.folder, out, a.p1, a.p2)
    print(f"Championship: {r['rounds']} rounds, {r['sessions']} sessions -> {r['out']}")
    print(f"Standings: {a.p1} {r['wins'][a.p1]} - {r['wins'][a.p2]} {a.p2}")
