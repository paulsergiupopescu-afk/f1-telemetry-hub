#!/usr/bin/env python3
r"""F1 Hub — graphical split-screen telemetry for F1 25/26.

The dashboard shows a continuously updated live gap, best-lap delta, two
complete driver cards, pace trends, and an imported racing-line mini-map.
Session changes are detected automatically and reports are generated in-process
so source and packaged executable behavior remain identical.

Run: ``python f1_hub.py [--port 20777] [--out reports]``
Build: ``.\build_exe.ps1``
"""

import argparse
import os
import sys
import threading
import time
import queue

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

import tkinter as tk
from tkinter import font as tkfont, messagebox

# Network and parsing logic comes from the shared engine.
from f1_26_split_telemetry import (Receiver, Shared, fmt_ms, VISUAL_TYRE,
                                   ERS_MODE)
from f1_track_data import LiveTrackMap
from f1_ui import enable_high_dpi, configure_tk_scaling, apply_app_icon

# Reports are generated in-process so packaged executables work identically.
import f1_report
import f1_compare
import f1_championship


# ============================================================================
# Receiver with in-process report generation.
# ============================================================================
class HubReceiver(Receiver):
    def __init__(self, shared, port, out_dir, notify_q, database=None):
        super().__init__(shared, port, out_dir, database, "split")
        self.notify_q = notify_q

    def _finalize_session(self):
        # inchidem fisierele exact ca parintele...
        for f in self._files.values():
            try:
                f.close()
            except Exception:
                pass
        self._files, self._writers = {}, {}
        if self.cur_uid is None or not self._session_has_lap:
            return
        p1 = self._paths.get("p1")
        p2 = self._paths.get("p2")
        if not (p1 and p2 and os.path.exists(p1) and os.path.exists(p2)):
            return
        i, s = self._session_index, self._session_stamp
        xlsx = os.path.join(self.out_dir, f"f1_report_s{i}_{s}.xlsx")
        png = os.path.join(self.out_dir, f"f1_compare_s{i}_{s}.png")

        def work():
            ok = []
            try:
                f1_report.build(p1, p2, xlsx)
                ok.append(os.path.basename(xlsx))
            except SystemExit as e:      # Example: no usable laps in the session.
                pass
            except Exception as e:
                self.notify_q.put(f"Excel report failed: {e}")
            try:
                f1_compare.analyse(p1, p2, out=png)
                ok.append(os.path.basename(png))
            except SystemExit:
                pass
            except Exception as e:
                self.notify_q.put(f"Chart failed: {e}")
            # Rebuild the championship from every session recorded so far.
            try:
                champ = os.path.join(self.out_dir, "f1_championship.html")
                f1_championship.build_championship(self.out_dir, champ)
                ok.append("f1_championship.html")
            except SystemExit:
                pass
            except Exception as e:
                self.notify_q.put(f"Championship report failed: {e}")
            if ok:
                self.notify_q.put(f"Session {i}: generated " + " + ".join(ok))
        threading.Thread(target=work, daemon=True).start()


# ============================================================================
# Delta live continuu
# ============================================================================
def live_gap(p1, p2):
    """Return the continuous track gap in seconds; positive means P1 leads."""
    if not (p1.lap and p2.lap and p1.tel and p2.tel):
        return None
    gap_m = p1.lap[11] - p2.lap[11]          # m_totalDistance
    v_behind = (p2.tel[0] if gap_m >= 0 else p1.tel[0]) / 3.6
    if v_behind < 0.5:
        v_ref = max(p1.tel[0], p2.tel[0]) / 3.6
        if v_ref < 0.5:
            return None
        v_behind = v_ref
    return gap_m / v_behind


def best_delta(p1, p2):
    if p1.best_lap_ms and p2.best_lap_ms:
        return (p1.best_lap_ms - p2.best_lap_ms) / 1000.0
    return None


# ============================================================================
# UI
# ============================================================================
BG = "#150407"
CARD = "#401016"
EDGE = "#84252e"
FG = "#fff7fb"
DIM = "#d7a9bf"
CYAN = "#53d9ff"
PINK = "#ff3b52"
GREEN = "#4ce68a"
RED = "#ff4f68"
YELLOW = "#ffad18"
PURPLE = "#c48cff"


class Bar(tk.Canvas):
    def __init__(self, parent, color, width=170, height=14):
        super().__init__(parent, width=width, height=height, bg=CARD,
                         highlightthickness=0)
        self.w, self.h, self.color = width, height, color
        self.rect_bg = self.create_rectangle(0, 0, width, height, fill="#090204",
                                             outline=EDGE)
        self.rect = self.create_rectangle(0, 0, 0, height, fill=color, outline="")

    def set(self, frac):
        frac = max(0.0, min(1.0, frac))
        self.coords(self.rect, 0, 0, int(self.w * frac), self.h)


# ============================================================================
# Pace assistant: lap history, trend, and engineer messages.
# ============================================================================
class PaceTracker:
    """Track a driver's completed laps and evaluate pace."""
    def __init__(self):
        self.laps = []            # [(lap_num, ms)]
        self._seen = None         # Last recorded (lap_num, last_lap).

    def reset(self):
        self.laps.clear()
        self._seen = None

    def feed(self, lap_tuple):
        """Consume LapData on every tick and detect newly completed laps."""
        if not lap_tuple:
            return False
        last_ms, lap_num = lap_tuple[0], lap_tuple[14]
        if last_ms <= 0:
            return False
        key = (lap_num, last_ms)
        if key == self._seen:
            return False
        # A completed lap advances the lap number beyond the stored value.
        if self.laps and lap_num <= self.laps[-1][0]:
            self._seen = key
            return False
        self._seen = key
        self.laps.append((lap_num - 1 if lap_num > 1 else lap_num, last_ms))
        return True

    def best(self):
        return min((ms for _, ms in self.laps), default=0)

    def trend(self):
        """Return ``(direction, seconds_per_lap, streak)`` for recent pace."""
        t = [ms for _, ms in self.laps]
        if len(t) < 2:
            return 0, 0.0, 0
        diffs = [(t[i] - t[i - 1]) / 1000.0 for i in range(1, len(t))]
        streak = 1
        for d_prev, d in zip(reversed(diffs[:-1]), reversed(diffs[1:])):
            if (d > 0) == (diffs[-1] > 0):
                streak += 1
            else:
                break
        recent = diffs[-3:]
        rate = sum(recent) / len(recent)
        if abs(rate) < 0.12:
            return 0, rate, streak
        return (1 if rate > 0 else -1), rate, streak

    def message(self):
        """Return the current pace-engineer message and color."""
        n = len(self.laps)
        if n == 0:
            return "Collecting data...", DIM
        last = self.laps[-1][1]
        if n >= 2 and last == self.best():
            return "\u2605 PERSONAL BEST!", GREEN
        d, rate, streak = self.trend()
        if d > 0 and streak >= 2:
            return f"Pace \u25bc for {streak} laps (+{rate:.2f}s/lap)", RED
        if d > 0:
            return f"Slower lap (+{rate:.2f}s)", YELLOW
        if d < 0:
            return f"Pace \u25b2 ({abs(rate):.2f}s faster)", GREEN
        return f"Consistent (\u00b1{abs(rate):.2f}s)", DIM

    def avg_last(self, k=3):
        t = [ms for _, ms in self.laps[-k:]]
        return sum(t) / len(t) if t else 0


class Sparkline(tk.Canvas):
    """Recent-lap sparkline with the best point highlighted."""
    def __init__(self, parent, color, width=240, height=44):
        super().__init__(parent, width=width, height=height, bg=BG,
                         highlightthickness=0)
        self.w, self.h, self.color = width, height, color

    def draw(self, laps):
        self.delete("all")
        t = [ms for _, ms in laps][-12:]
        if len(t) < 2:
            self.create_text(self.w / 2, self.h / 2, text="\u2014",
                             fill=DIM, font=("Segoe UI", 10))
            return
        lo, hi = min(t), max(t)
        span = max(hi - lo, 250)
        n = len(t)
        pts = []
        for i, ms in enumerate(t):
            x = 6 + i * (self.w - 12) / (n - 1)
            y = 6 + (ms - lo) / span * (self.h - 12)
            pts.append((x, y))
        for a, b in zip(pts, pts[1:]):
            self.create_line(*a, *b, fill=self.color, width=2)
        bi = t.index(min(t))
        for i, (x, y) in enumerate(pts):
            if i == bi:
                self.create_oval(x - 4, y - 4, x + 4, y + 4, fill=GREEN,
                                 outline="")
            else:
                self.create_oval(x - 2.4, y - 2.4, x + 2.4, y + 2.4,
                                 fill=self.color, outline="")


def temp_color(t):
    """Map tyre temperature from cold blue through green to hot red."""
    if t < 75:   return "#3d7bff"
    if t < 85:   return "#31c9e8"
    if t < 105:  return "#2ee56b"
    if t < 115:  return "#ffc93d"
    return "#ff4257"


class TyreWidget(tk.Canvas):
    """Top-down four-tyre diagram showing temperature, wear, compound and age."""
    W, H = 190, 150
    def __init__(self, parent):
        super().__init__(parent, width=self.W, height=self.H, bg=CARD,
                         highlightthickness=0)
        tw, th = 44, 56
        pos = {"FL": (18, 8), "FR": (self.W-18-tw, 8),
               "RL": (18, self.H-8-th), "RR": (self.W-18-tw, self.H-8-th)}
        # Car body.
        self.create_rectangle(self.W/2-16, 20, self.W/2+16, self.H-20,
                              outline=EDGE, width=2)
        self.items = {}
        f_w = tkfont.Font(family="Consolas", size=11, weight="bold")
        f_t = tkfont.Font(family="Consolas", size=9)
        f_l = tkfont.Font(family="Segoe UI", size=8)
        for k, (x, y) in pos.items():
            r = self.create_rectangle(x, y, x+tw, y+th, fill="#26090d",
                                      outline=EDGE, width=1)
            wear = self.create_text(x+tw/2, y+th/2-7, text="--", fill=FG, font=f_w)
            temp = self.create_text(x+tw/2, y+th/2+11, text="--\u00b0", fill=DIM, font=f_t)
            lab_y = y-2 if y < 30 else y+th+7
            self.create_text(x+tw/2, lab_y, text=k, fill=DIM, font=f_l,
                             anchor="s" if y < 30 else "n")
            self.items[k] = (r, wear, temp)
        f_c = tkfont.Font(family="Segoe UI", size=10, weight="bold")
        self.compound = self.create_text(self.W/2, self.H/2-8, text="—",
                                         fill=YELLOW, font=f_c)
        self.age = self.create_text(self.W/2, self.H/2+8, text="", fill=DIM,
                                    font=tkfont.Font(family="Segoe UI", size=9))

    def set(self, temps, wears, compound, age):
        # Order defined by the UDP specification: RL, RR, FL, FR.
        order = ("RL", "RR", "FL", "FR")
        for i, k in enumerate(order):
            r, wtxt, ttxt = self.items[k]
            t = temps[i] if temps else 0
            w = wears[i] if wears else None
            self.itemconfig(r, fill=temp_color(t) if temps else "#26090d")
            self.itemconfig(wtxt, text=f"{w:.0f}%" if w is not None else "--")
            self.itemconfig(ttxt, text=f"{t:.0f}\u00b0" if temps else "--\u00b0")
        self.itemconfig(self.compound, text=compound or "—")
        self.itemconfig(self.age, text=f"{age} laps" if age is not None else "")


class PlayerCard(tk.Frame):
    def __init__(self, parent, accent):
        super().__init__(parent, bg=CARD, highlightbackground=EDGE,
                         highlightthickness=1)
        self.accent = accent
        f_name = tkfont.Font(family="Segoe UI", size=17, weight="bold")
        f_pos = tkfont.Font(family="Segoe UI", size=26, weight="bold")
        f_speed = tkfont.Font(family="Segoe UI", size=42, weight="bold")
        f_gear = tkfont.Font(family="Segoe UI", size=30, weight="bold")
        f_lab = tkfont.Font(family="Segoe UI", size=9)
        f_cur = tkfont.Font(family="Consolas", size=24, weight="bold")
        f_val = tkfont.Font(family="Consolas", size=13)
        f_small = tkfont.Font(family="Consolas", size=11)

        head = tk.Frame(self, bg=CARD)
        head.pack(fill="x", padx=14, pady=(10, 2))
        self.name = tk.Label(head, text="—", font=f_name, fg=accent, bg=CARD)
        self.name.pack(side="left")
        self.pos = tk.Label(head, text="P-", font=f_pos, fg=FG, bg=CARD)
        self.pos.pack(side="right")

        # Speed, gear, and active-aero row.
        spd = tk.Frame(self, bg=CARD)
        spd.pack(fill="x", padx=14)
        self.speed = tk.Label(spd, text="---", font=f_speed, fg=FG, bg=CARD)
        self.speed.pack(side="left")
        tk.Label(spd, text="km/h", font=f_lab, fg=DIM, bg=CARD).pack(side="left",
                 anchor="s", pady=(0, 12), padx=(4, 12))
        self.gear = tk.Label(spd, text="N", font=f_gear, fg=YELLOW, bg=CARD)
        self.gear.pack(side="left", padx=6)
        self.drs = tk.Label(spd, text="CORNER MODE", font=f_name,
                            fg=PURPLE, bg=CARD)
        self.drs.pack(side="right", padx=4)

        # bare
        bars = tk.Frame(self, bg=CARD)
        bars.pack(fill="x", padx=14, pady=(2, 4))
        for lbl, attr, col, full in (("RPM", "rpm_bar", accent, 13500),
                                     ("THR", "thr_bar", GREEN, 1),
                                     ("BRK", "brk_bar", RED, 1)):
            row = tk.Frame(bars, bg=CARD)
            row.pack(fill="x", pady=1)
            tk.Label(row, text=lbl, font=f_lab, fg=DIM, bg=CARD, width=4,
                     anchor="w").pack(side="left")
            b = Bar(row, col, width=210, height=15)
            b.pack(side="left")
            setattr(self, attr, b)
        self.rpm_val = tk.Label(bars, text="", font=f_small, fg=DIM, bg=CARD)

        # Body: timing on the left, tyres on the right.
        body = tk.Frame(self, bg=CARD)
        body.pack(fill="both", expand=True, padx=14, pady=(4, 6))
        left = tk.Frame(body, bg=CARD)
        left.pack(side="left", fill="both", expand=True)
        tk.Label(left, text="CURRENT LAP", font=f_lab, fg=DIM, bg=CARD,
                 anchor="w").pack(fill="x")
        self.cur = tk.Label(left, text="--:--.---", font=f_cur, fg=FG, bg=CARD,
                            anchor="w")
        self.cur.pack(fill="x")
        self.lapinfo = tk.Label(left, text="", font=f_small, fg=DIM, bg=CARD,
                                anchor="w")
        self.lapinfo.pack(fill="x")
        self.last = tk.Label(left, text="LAST  --:--.---", font=f_val, fg=FG,
                             bg=CARD, anchor="w")
        self.last.pack(fill="x", pady=(6, 0))
        self.bestl = tk.Label(left, text="BEST  --:--.---", font=f_val,
                              fg=accent, bg=CARD, anchor="w")
        self.bestl.pack(fill="x")
        self.sect = tk.Label(left, text="S1 --:--.---  S2 --:--.---",
                             font=f_small, fg=DIM, bg=CARD, anchor="w")
        self.sect.pack(fill="x", pady=(4, 0))
        self.ers = tk.Label(left, text="ERS --%", font=f_val, fg=FG, bg=CARD,
                            anchor="w")
        self.ers.pack(fill="x", pady=(8, 0))
        self.fuel = tk.Label(left, text="FUEL --", font=f_val, fg=FG, bg=CARD,
                             anchor="w")
        self.fuel.pack(fill="x")

        right = tk.Frame(body, bg=CARD)
        right.pack(side="right", anchor="n")
        tk.Label(right, text="TYRES", font=f_lab, fg=DIM, bg=CARD).pack()
        self.tyres = TyreWidget(right)
        self.tyres.pack()

    def update_from(self, cs, fallback_name, packet_format=None):
        t, lap, st, dmg = cs.tel, cs.lap, cs.status, cs.dmg
        self.name.config(text=cs.name or fallback_name)
        if t is None:
            self.speed.config(text="---")
            self.lapinfo.config(text="waiting for data...")
            return
        self.speed.config(text=f"{t[0]:d}")
        g = "R" if t[5] == -1 else ("N" if t[5] == 0 else str(t[5]))
        self.gear.config(text=g)
        if t[7]:
            aero_text, aero_color = "STRAIGHT MODE", GREEN
        elif st and st[11]:
            aero_text, aero_color = "STRAIGHT READY", CYAN
        else:
            aero_text, aero_color = "CORNER MODE", PURPLE
        self.drs.config(text=aero_text, fg=aero_color)
        self.rpm_bar.set(t[6] / 13500.0)
        self.thr_bar.set(t[1])
        self.brk_bar.set(t[3])
        if lap:
            self.pos.config(text=f"P{lap[13]}")
            self.cur.config(text=fmt_ms(lap[1]),
                            fg=RED if lap[18] else FG)
            sec = {0: "S1", 1: "S2", 2: "S3"}.get(lap[17], "?")
            inv = "  INVALID" if lap[18] else ""
            self.lapinfo.config(text=f"Lap {lap[14]}  \u00b7  {sec}{inv}")
            self.last.config(text=f"LAST  {fmt_ms(lap[0])}")
            best = fmt_ms(cs.best_lap_ms) if cs.best_lap_ms else "--:--.---"
            self.bestl.config(text=f"BEST  {best}")
            s1 = lap[2] + lap[3] * 60000
            s2 = lap[4] + lap[5] * 60000
            self.sect.config(text=f"S1 {fmt_ms(s1)}  S2 {fmt_ms(s2)}")
        if st:
            ers_pct = max(0.0, min(100.0, st[19] / 4_000_000 * 100))
            self.ers.config(text=f"ERS {ers_pct:3.0f}%  [{ERS_MODE.get(st[20], '?')}]")
            self.fuel.config(text=f"FUEL {st[5]:.2f} kg  ({st[7]:+.2f} laps)")
        temps = (t[14], t[15], t[16], t[17])
        wears = (dmg[0], dmg[1], dmg[2], dmg[3]) if dmg else None
        comp = VISUAL_TYRE.get(st[14], st[14]) if st else None
        age = st[15] if st else None
        self.tyres.set(temps, wears, comp, age)


class App:
    def __init__(self, root, shared, receiver, notify_q, out_dir,
                 mode_switch=None, database=None):
        self.root = root
        self.shared = shared
        self.receiver = receiver
        self.notify_q = notify_q
        self.out_dir = out_dir
        self.mode_switch = mode_switch
        self.database = database
        root.title("F1 HUB - Split Screen Telemetry")
        root.configure(bg=BG)
        root.geometry("1280x860")
        root.minsize(1080, 740)
        self._build_menu()

        f_top = tkfont.Font(family="Segoe UI", size=11)
        f_huge = tkfont.Font(family="Segoe UI", size=64, weight="bold")
        f_sub = tkfont.Font(family="Segoe UI", size=11)
        f_best = tkfont.Font(family="Consolas", size=16, weight="bold")

        self.top = tk.Label(root, text="Waiting for telemetry... check UDP "
                            "Format = 2025, port 20777", font=f_top, fg=DIM, bg=BG,
                            anchor="w")
        self.top.pack(fill="x", padx=14, pady=(10, 0))

        center = tk.Frame(root, bg=BG)
        center.pack(fill="x", pady=(4, 0))
        self.delta = tk.Label(center, text="--.---", font=f_huge, fg=DIM, bg=BG)
        self.delta.pack()
        self.delta_sub = tk.Label(center, text="LIVE GAP  (+ = P1 ahead)",
                                  font=f_sub, fg=DIM, bg=BG)
        self.delta_sub.pack()
        self.best = tk.Label(center, text="Δ best lap: --", font=f_best,
                             fg=DIM, bg=BG)
        self.best.pack(pady=(2, 6))

        # ---- PACE ASSISTANT --------------------------------------------
        f_pmsg = tkfont.Font(family="Segoe UI", size=13, weight="bold")
        f_plab = tkfont.Font(family="Segoe UI", size=9)
        f_pcmp = tkfont.Font(family="Consolas", size=13, weight="bold")
        self.trk1, self.trk2 = PaceTracker(), PaceTracker()
        self._pace_session = -1
        pace = tk.Frame(root, bg=BG)
        pace.pack(fill="x", padx=14, pady=(0, 4))
        pace.columnconfigure(0, weight=1, uniform="p")
        pace.columnconfigure(1, weight=0)
        pace.columnconfigure(2, weight=1, uniform="p")

        left = tk.Frame(pace, bg=BG)
        left.grid(row=0, column=0, sticky="e", padx=(0, 18))
        self.spark1 = Sparkline(left, CYAN)
        self.spark1.pack(anchor="e")
        self.pmsg1 = tk.Label(left, text="Collecting data...", font=f_pmsg, fg=DIM,
                              bg=BG, anchor="e")
        self.pmsg1.pack(fill="x")
        tk.Label(left, text="PACE \u00b7 recent laps", font=f_plab, fg=DIM,
                 bg=BG, anchor="e").pack(fill="x")

        mid = tk.Frame(pace, bg=BG)
        mid.grid(row=0, column=1)
        self.map_canvas = tk.Canvas(mid, width=200, height=92, bg=BG,
                                    highlightthickness=0)
        self.map_canvas.pack()
        self.track_map = LiveTrackMap(self.map_canvas, 200, 92, line="#d7a9bf")
        self.pcmp = tk.Label(mid, text="", font=f_pcmp, fg=DIM, bg=BG)
        self.pcmp.pack()
        tk.Label(mid, text="PACE \u00b7 last 3 laps", font=f_plab, fg=DIM,
                 bg=BG).pack()

        right = tk.Frame(pace, bg=BG)
        right.grid(row=0, column=2, sticky="w", padx=(18, 0))
        self.spark2 = Sparkline(right, PINK)
        self.spark2.pack(anchor="w")
        self.pmsg2 = tk.Label(right, text="Collecting data...", font=f_pmsg, fg=DIM,
                              bg=BG, anchor="w")
        self.pmsg2.pack(fill="x")
        tk.Label(right, text="PACE \u00b7 recent laps", font=f_plab, fg=DIM,
                 bg=BG, anchor="w").pack(fill="x")

        cards = tk.Frame(root, bg=BG)
        cards.pack(fill="both", expand=True, padx=14, pady=6)
        cards.columnconfigure(0, weight=1, uniform="c")
        cards.columnconfigure(1, weight=1, uniform="c")
        self.card1 = PlayerCard(cards, CYAN)
        self.card1.grid(row=0, column=0, sticky="nsew", padx=(0, 7))
        self.card2 = PlayerCard(cards, PINK)
        self.card2.grid(row=0, column=1, sticky="nsew", padx=(7, 0))

        self.status = tk.Label(root, text=f"Reports are generated automatically "
                               f"after each session -> {out_dir}",
                               font=f_sub, fg=DIM, bg=BG, anchor="w")
        self.status.pack(fill="x", padx=14, pady=(0, 8))

        root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.tick()

    def _build_menu(self):
        menu = tk.Menu(self.root)
        mode = tk.Menu(menu, tearoff=False)
        mode.add_command(label="Solo Engineer", command=lambda: self._switch("solo"))
        mode.add_command(label="Split Screen", state="disabled")
        mode.add_separator()
        mode.add_command(label="Main Menu", command=lambda: self._switch("menu"))
        mode.add_command(label="Exit", command=self.on_close)
        menu.add_cascade(label="Mode", menu=mode)
        view = tk.Menu(menu, tearoff=False)
        view.add_command(label="Fullscreen    F11", command=self.toggle_fs)
        menu.add_cascade(label="View", menu=view)
        reports = tk.Menu(menu, tearoff=False)
        reports.add_command(label="Pre-Race Command Centre", command=self.open_prerace)
        reports.add_separator()
        reports.add_command(label="Session Studio", command=self.open_studio)
        reports.add_command(label="Live Race Engineer", command=self.open_strategy_lab)
        reports.add_separator()
        reports.add_command(label="Open Report Folder", command=self.open_reports)
        menu.add_cascade(label="Reports", menu=reports)
        help_menu = tk.Menu(menu, tearoff=False)
        help_menu.add_command(label="UDP Setup", command=lambda: messagebox.showinfo(
            "UDP Telemetry Setup",
            "UDP Telemetry: On\nUDP Broadcast: Off\nUDP IP: 127.0.0.1\n"
            "UDP Port: 20777\nUDP Send Rate: 60 Hz\nUDP Format: 2025\n"
            "Your Telemetry: Public"))
        menu.add_cascade(label="Help", menu=help_menu)
        self.root.config(menu=menu)
        self.root.bind("<F11>", self.toggle_fs)
        self.root.bind("<Escape>", lambda _e: self.root.attributes("-fullscreen", False))

    def _switch(self, mode):
        if self.mode_switch:
            self.mode_switch(mode)

    def toggle_fs(self, _event=None):
        self.root.attributes("-fullscreen",
                             not self.root.attributes("-fullscreen"))

    def open_studio(self):
        if self.database:
            from f1_session_studio import SessionStudio
            SessionStudio(self.root, self.database)
        else:
            messagebox.showinfo("Session Studio", "The session database is not available.")

    def open_prerace(self):
        if self.database:
            from f1_prerace import PreRaceStudio
            PreRaceStudio(self.root, self.database)
        else:
            messagebox.showinfo("Pre-Race", "The session database is not available.")

    def open_strategy_lab(self):
        if self.database:
            from f1_strategy_lab import StrategyLab
            StrategyLab(self.root, self.database, shared=self.shared)
        else:
            messagebox.showinfo("Strategy Lab", "The session database is not available.")

    def open_reports(self):
        os.makedirs(self.out_dir, exist_ok=True)
        try:
            os.startfile(self.out_dir)
        except (AttributeError, OSError):
            messagebox.showinfo("Reports", self.out_dir)

    def tick(self):
        s = self.shared
        with s.lock:
            p1, p2 = s.p1, s.p2
            i2 = s.p2_idx
            sess = dict(s.session)
            pkts, last = s.packets, s.last_packet_time
            packet_format = s.packet_format
            sidx = s.session_index

        alive = (time.time() - last) < 2
        trk = sess.get("track") or "—"
        typ = sess.get("type") or ""
        tt = sess.get("trackTemp")
        temp = f"   track {tt}C air {sess.get('airTemp')}C" if tt is not None else ""
        state = "LIVE" if alive else "no packets"
        length = {2: "3 laps", 3: "5 laps", 4: "25%", 5: "35%",
                  6: "50%", 7: "100%"}.get(sess.get("session_length"), "")
        ai = (f"AI {sess['ai_difficulty']}"
              if sess.get("ai_difficulty") is not None else "")
        self.top.config(text=f"Session #{sidx}   {trk}  {typ} {length} {ai}{temp}   "
                             f"pkts {pkts}   {state}",
                        fg=FG if alive else DIM)

        # GAP LIVE continuu
        gap = live_gap(p1, p2) if i2 is not None else None
        if gap is None:
            self.delta.config(text="--.---", fg=DIM)
        else:
            col = GREEN if gap > 0 else (RED if gap < 0 else YELLOW)
            self.delta.config(text=f"{gap:+.3f}s", fg=col)
        bd = best_delta(p1, p2) if i2 is not None else None
        if bd is None:
            self.best.config(text="Δ best lap: --", fg=DIM)
        else:
            self.best.config(text=f"Δ best lap: {bd:+.3f}s",
                             fg=GREEN if bd < 0 else (RED if bd > 0 else YELLOW))

        self.card1.update_from(p1, "Player 1", packet_format)
        if i2 is not None:
            self.card2.update_from(p2, "Player 2", packet_format)
        else:
            self.card2.name.config(text="Player 2 — waiting for split screen")

        self.track_map.set_track(trk, sess.get("track_id"))
        if p1.lap:
            self.track_map.update_car("p1", p1.lap[10], CYAN, "P1")
        if i2 is not None and p2.lap:
            self.track_map.update_car("p2", p2.lap[10], PINK, "P2")

        # ---- pace assistant ----
        if sidx != self._pace_session:      # A new session clears history.
            self._pace_session = sidx
            self.trk1.reset()
            self.trk2.reset()
            # Seed current state so old data is not counted as a new lap.
            if p1.lap:
                self.trk1._seen = (p1.lap[14], p1.lap[0])
            if p2.lap:
                self.trk2._seen = (p2.lap[14], p2.lap[0])
            self.spark1.draw([])
            self.spark2.draw([])
        ch1 = self.trk1.feed(p1.lap)
        ch2 = self.trk2.feed(p2.lap) if i2 is not None else False
        if ch1:
            self.spark1.draw(self.trk1.laps)
        if ch2:
            self.spark2.draw(self.trk2.laps)
        m1, c1 = self.trk1.message()
        m2, c2 = self.trk2.message()
        self.pmsg1.config(text=m1, fg=c1)
        self.pmsg2.config(text=m2, fg=c2)
        a1 = self.trk1.avg_last(3)
        a2 = self.trk2.avg_last(3)
        if a1 and a2 and len(self.trk1.laps) >= 2 and len(self.trk2.laps) >= 2:
            dr = (a1 - a2) / 1000.0
            who = "P1" if dr < 0 else "P2"
            wc = GREEN if dr < 0 else RED
            self.pcmp.config(text=f"{who} faster by {abs(dr):.2f}s/lap", fg=wc)
        else:
            self.pcmp.config(text="--", fg=DIM)

        try:
            while True:
                msg = self.notify_q.get_nowait()
                self.status.config(text=msg, fg=GREEN)
        except queue.Empty:
            pass

        self.root.after(50, self.tick)   # Non-blocking 20 fps refresh.

    def on_close(self):
        self.receiver.running = False
        self.root.after(400, self.root.destroy)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=20777)
    ap.add_argument("--out", default="reports")
    args = ap.parse_args()

    # Resolve output beside the executable or script, not an arbitrary CWD.
    base = os.path.dirname(os.path.abspath(sys.argv[0]))
    out_dir = args.out if os.path.isabs(args.out) else os.path.join(base, args.out)
    os.makedirs(out_dir, exist_ok=True)

    shared = Shared()
    notify_q = queue.Queue()
    receiver = HubReceiver(shared, args.port, out_dir, notify_q)
    receiver.start()

    enable_high_dpi()
    root = tk.Tk()
    configure_tk_scaling(root)
    apply_app_icon(root)
    App(root, shared, receiver, notify_q, out_dir)
    root.mainloop()
    receiver.running = False
    time.sleep(0.5)


if __name__ == "__main__":
    main()
