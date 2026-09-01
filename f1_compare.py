#!/usr/bin/env python3
"""Compare two F1 telemetry laps after a session.

The tool extracts official lap times, selects each player's fastest complete
lap, aligns both laps by distance, calculates the time delta, prints a sector
summary, and generates speed, pedal and delta charts.
"""

import argparse
import csv
import sys

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

try:
    import numpy as np
except ImportError:
    sys.exit("numpy is missing. Run: pip install numpy matplotlib")


# ----------------------------------------------------------------------------
def _f(x, default=0.0):
    try:
        return float(x)
    except (ValueError, TypeError):
        return default


def load_samples(path):
    """Load a CSV file into a cleaned list of numeric sample dictionaries."""
    out = []
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            ln = r.get("lap_num", "")
            dist = r.get("lap_distance", "")
            cur = r.get("cur_lap_ms", "")
            if ln in ("", None) or dist in ("", None) or cur in ("", None):
                continue
            out.append({
                "lap": int(_f(ln)),
                "dist": _f(dist),
                "t": _f(cur),                 # Milliseconds into the lap.
                "last_lap": _f(r.get("last_lap_ms")),
                "speed": _f(r.get("speed_kmh")),
                "thr": _f(r.get("throttle")),
                "brk": _f(r.get("brake")),
                "s1": _f(r.get("s1_ms")),
                "s2": _f(r.get("s2_ms")),
                "invalid": int(_f(r.get("lap_invalid"))),
            })
    if not out:
        sys.exit(f"No valid samples in {path}. Is this a telemetry CSV?")
    return out


def extract_laps(samples):
    """Group samples by lap and attach official time and validity metadata."""
    laps = {}
    order = []
    for s in samples:
        L = s["lap"]
        if L not in laps:
            laps[L] = {"t": None, "valid": True, "samples": []}
            order.append(L)
        laps[L]["samples"].append(s)
        if s["invalid"]:
            laps[L]["valid"] = False

    # Official time arrives on the next-lap transition.
    for i in range(1, len(order)):
        prev, cur = order[i - 1], order[i]
        first_next = laps[cur]["samples"][0]
        if first_next["last_lap"] > 0:
            laps[prev]["t"] = first_next["last_lap"]

    # Coverage filters partial out-laps.
    max_dist_overall = max(s["dist"] for s in samples)
    for L, d in laps.items():
        ds = [x["dist"] for x in d["samples"]]
        d["coverage"] = (max(ds) - min(ds)) / max_dist_overall if max_dist_overall else 0
        d["min_dist"] = min(ds)
        d["max_dist"] = max(ds)
    return laps


def clean_curve(samples, key):
    """Return sorted distance/value arrays with strictly increasing distance."""
    pts = sorted(((s["dist"], s[key]) for s in samples if s["dist"] >= 0),
                 key=lambda p: p[0])
    if not pts:
        return np.array([]), np.array([])
    d = np.array([p[0] for p in pts], dtype=float)
    v = np.array([p[1] for p in pts], dtype=float)
    keep = np.concatenate(([True], np.diff(d) > 1e-6))  # Remove duplicate x values.
    return d[keep], v[keep]


def pick_fastest(laps):
    cand = [(L, d["t"]) for L, d in laps.items()
            if d["t"] and d["valid"] and d["coverage"] > 0.7]
    if not cand:  # Relax the filter when no clean laps exist.
        cand = [(L, d["t"]) for L, d in laps.items() if d["t"]]
    if not cand:
        return None
    return min(cand, key=lambda x: x[1])[0]


def lap_sectors(lapdict, total_ms):
    """Return sector 1, 2 and 3 times in milliseconds from lap samples."""
    s1 = max((x["s1"] for x in lapdict["samples"]), default=0)
    s2 = max((x["s2"] for x in lapdict["samples"]), default=0)
    s3 = total_ms - s1 - s2 if (total_ms and s1 and s2) else 0
    return s1, s2, s3


def fmt_ms(ms):
    if not ms or ms <= 0:
        return "--:--.---"
    m, rem = divmod(int(ms), 60000)
    return f"{m}:{rem/1000:06.3f}"


# ----------------------------------------------------------------------------
def analyse(path_a, path_b, lap_a=None, lap_b=None, out=None, list_only=False):
    sa, sb = load_samples(path_a), load_samples(path_b)
    la, lb = extract_laps(sa), extract_laps(sb)

    if list_only:
        for tag, laps in (("P1 (" + path_a + ")", la), ("P2 (" + path_b + ")", lb)):
            print(f"\n{tag}")
            for L in sorted(laps):
                d = laps[L]
                flag = "" if d["valid"] else "  [INVALID]"
                print(f"  lap {L:>2}: {fmt_ms(d['t']):>10}  "
                      f"coverage {d['coverage']*100:3.0f}%{flag}")
        return

    if lap_a is None:
        lap_a = pick_fastest(la)
    if lap_b is None:
        lap_b = pick_fastest(lb)
    if lap_a is None or lap_b is None:
        sys.exit("No complete laps found in one of the files. "
                 "Run with --list to see what is available.")

    da, db = la[lap_a], lb[lap_b]
    ta, tb = da["t"], db["t"]

    # Time, speed, and pedal curves over distance.
    dist_a, time_a = clean_curve(da["samples"], "t")
    dist_b, time_b = clean_curve(db["samples"], "t")
    _, spd_a = clean_curve(da["samples"], "speed")
    _, spd_b = clean_curve(db["samples"], "speed")
    _, thr_a = clean_curve(da["samples"], "thr")
    _, thr_b = clean_curve(db["samples"], "thr")
    _, brk_a = clean_curve(da["samples"], "brk")
    _, brk_b = clean_curve(db["samples"], "brk")

    d_max = min(dist_a.max(), dist_b.max())
    grid = np.linspace(0, d_max, 600)
    Ta = np.interp(grid, dist_a, time_a)
    Tb = np.interp(grid, dist_b, time_b)
    delta = (Ta - Tb) / 1000.0            # Seconds; positive means P1 is slower.
    Sa = np.interp(grid, dist_a, spd_a)
    Sb = np.interp(grid, dist_b, spd_b)
    THa = np.interp(grid, dist_a, thr_a) * 100
    THb = np.interp(grid, dist_b, thr_b) * 100
    BRa = np.interp(grid, dist_a, brk_a) * 100
    BRb = np.interp(grid, dist_b, brk_b) * 100

    # ---- text summary -----------------------------------------------------
    s1a, s2a, s3a = lap_sectors(da, ta)
    s1b, s2b, s3b = lap_sectors(db, tb)
    dt = (ta - tb) / 1000.0
    print("=" * 60)
    print(f"  P1  lap {lap_a}:  {fmt_ms(ta)}    top {spd_a.max():.0f} km/h")
    print(f"  P2  lap {lap_b}:  {fmt_ms(tb)}    top {spd_b.max():.0f} km/h")
    print("-" * 60)
    win = "P1" if dt < 0 else ("P2" if dt > 0 else "equal")
    print(f"  LAP DELTA:  {dt:+.3f}s   → {win} faster")
    print("  Sectors (P1 vs P2):")
    for i, (a, b) in enumerate([(s1a, s1b), (s2a, s2b), (s3a, s3b)], 1):
        d = (a - b) / 1000.0
        mark = "P1" if d < 0 else ("P2" if d > 0 else "=")
        print(f"    S{i}:  {fmt_ms(a):>9}  vs  {fmt_ms(b):>9}   "
              f"({d:+.3f}s → {mark})")

    # Largest gains and losses across 20 segments.
    print("-" * 60)
    print("  Where the difference is made (segment Δ, + = P1 loses):")
    edges = np.linspace(0, d_max, 21)
    seg_delta = []
    for i in range(20):
        m = (grid >= edges[i]) & (grid < edges[i + 1])
        if m.sum() < 2:
            continue
        change = delta[m][-1] - delta[m][0]
        seg_delta.append((edges[i], edges[i + 1], change))
    seg_delta.sort(key=lambda x: x[2])
    def lbl(c):
        return "P1 loses" if c > 0 else ("P1 gains" if c < 0 else "equal")
    for a, b, c in seg_delta[-2:][::-1] + seg_delta[:2]:
        print(f"    {a:5.0f}–{b:5.0f} m :  {c:+.3f}s  ({lbl(c)})")
    print("=" * 60)

    # ---- charts -----------------------------------------------------------
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("(matplotlib is missing — skipping charts. pip install matplotlib)")
        return

    fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(13, 9), sharex=True,
                                        gridspec_kw={"height_ratios": [3, 2, 3]})
    C1, C2 = "#00b4d8", "#e83e8c"

    ax1.plot(grid, Sa, color=C1, lw=1.6, label=f"P1 lap {lap_a}")
    ax1.plot(grid, Sb, color=C2, lw=1.6, label=f"P2 lap {lap_b}")
    ax1.set_ylabel("Speed (km/h)")
    ax1.legend(loc="lower right")
    ax1.grid(alpha=0.25)
    ax1.set_title(f"P1 {fmt_ms(ta)}  vs  P2 {fmt_ms(tb)}   (Δ {dt:+.3f}s)")

    ax2.plot(grid, THa, color=C1, lw=1.2)
    ax2.plot(grid, THb, color=C2, lw=1.2)
    ax2.plot(grid, BRa, color=C1, lw=1.0, ls="--", alpha=0.7)
    ax2.plot(grid, BRb, color=C2, lw=1.0, ls="--", alpha=0.7)
    ax2.set_ylabel("Throttle — / Brake - -  (%)")
    ax2.set_ylim(-5, 105)
    ax2.grid(alpha=0.25)

    ax3.axhline(0, color="grey", lw=0.8)
    ax3.plot(grid, delta, color="#333", lw=1.8)
    ax3.fill_between(grid, delta, 0, where=(delta > 0), color=C2, alpha=0.35,
                      label="P1 loses")
    ax3.fill_between(grid, delta, 0, where=(delta < 0), color=C1, alpha=0.35,
                      label="P1 gains")
    ax3.set_ylabel("Δ time (s)  P1−P2")
    ax3.set_xlabel("Lap distance (m)")
    ax3.legend(loc="upper left")
    ax3.grid(alpha=0.25)

    fig.tight_layout()
    out = out or f"f1_compare_p1lap{lap_a}_vs_p2lap{lap_b}.png"
    fig.savefig(out, dpi=130)
    print(f"Chart saved: {out}")


def main():
    ap = argparse.ArgumentParser(description="F1 25/26 lap comparison")
    ap.add_argument("csv_p1")
    ap.add_argument("csv_p2")
    ap.add_argument("--lap-a", type=int, default=None, help="selected P1 lap")
    ap.add_argument("--lap-b", type=int, default=None, help="selected P2 lap")
    ap.add_argument("--out", default=None, help="output PNG file")
    ap.add_argument("--list", action="store_true", help="list laps and exit")
    a = ap.parse_args()
    analyse(a.csv_p1, a.csv_p2, a.lap_a, a.lap_b, a.out, a.list)


if __name__ == "__main__":
    main()
