#!/usr/bin/env python3
r"""F1 Solo Engineer — single-player race engineer for a second monitor.

The large live delta compares the current lap with the driver's own best lap.
The dashboard also shows the gaps to the cars ahead and behind, current-lap
prediction, pace guidance, tyre state, engineer advice, and a live circuit map.
Reports are generated automatically after every session.

Run: ``python f1_solo.py [--port 20777] [--out solo_reports] [--fullscreen]``
"""

import argparse
import os
import queue
import struct
import sys
import threading
import time

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

import tkinter as tk
from tkinter import font as tkfont, messagebox

import numpy as np

from f1_26_split_telemetry import (Receiver, Shared, fmt_ms, VISUAL_TYRE,
                                   ERS_MODE, HEADER_FMT, HEADER_SIZE,
                                   LAP_DATA_FMT, LAP_DATA_SIZE,
                                   PARTICIPANT_FMT, PARTICIPANT_SIZE,
                                   PARTICIPANT_2026_FMT,
                                   PARTICIPANT_2026_SIZE,
                                   CAR_STATUS_FMT, CAR_STATUS_SIZE,
                                   CAR_STATUS_2026_FMT, CAR_STATUS_2026_SIZE,
                                   PKT_LAP, PKT_PARTICIPANTS, PKT_STATUS)
import f1_solo_report
from f1_engineer import RaceEngineer
from f1_track_data import LiveTrackMap
from f1_ui import enable_high_dpi, configure_tk_scaling, apply_app_icon

# Shared visual palette.
BG = "#150407"
CARD = "#401016"
EDGE = "#84252e"
FG = "#fff7fb"
DIM = "#d7a9bf"
ACC = "#ff3b52"
GREEN = "#4ce68a"
RED = "#ff4f68"
YELLOW = "#ffad18"
PURPLE = "#c48cff"
CHALK_MARK = "#ffffff"


# ============================================================================
# Solo receiver parses every car for positions and gaps.
# ============================================================================
class SoloReceiver(Receiver):
    def __init__(self, shared, port, out_dir, notify_q, database=None):
        super().__init__(shared, port, out_dir, database, "solo")
        self.notify_q = notify_q
        self.field = []       # (position, total_distance, index) for every car.
        self.names = {}       # car index -> driver name
        self.field_details = {}  # car index -> strategy-relevant public state
        self.field_lock = threading.Lock()

    def _handle(self, data):
        super()._handle(data)
        try:
            header = struct.unpack_from(HEADER_FMT, data, 0)
            pkt_format, pkt_id = header[0], header[5]
        except struct.error:
            return
        if pkt_id == PKT_LAP:
            self._scan_field(data, pkt_format)
        elif pkt_id == PKT_PARTICIPANTS:
            self._scan_names(data, pkt_format)
        elif pkt_id == PKT_STATUS:
            self._scan_status(data, pkt_format)

    def _scan_field(self, data, pkt_format=2025):
        rows = []
        updates = {}
        for i in range(24 if pkt_format == 2026 else 22):
            try:
                rec = struct.unpack_from(LAP_DATA_FMT, data,
                                         HEADER_SIZE + i * LAP_DATA_SIZE)
            except struct.error:
                break
            pos, total = rec[13], rec[11]
            if pos and pos < 100:
                rows.append((pos, total, i))
                updates[i] = dict(position=pos, total_distance=total,
                                  lap_num=rec[14], pit_status=rec[15],
                                  pit_stops=rec[16], last_lap_ms=rec[0])
        rows.sort()
        with self.field_lock:
            self.field = rows
            for index, values in updates.items():
                self.field_details.setdefault(index, {}).update(values)

    def _scan_names(self, data, pkt_format=2025):
        base = HEADER_SIZE + 1
        names = {}
        fmt, size = ((PARTICIPANT_2026_FMT, PARTICIPANT_2026_SIZE)
                     if pkt_format == 2026 else
                     (PARTICIPANT_FMT, PARTICIPANT_SIZE))
        for i in range(24 if pkt_format == 2026 else 22):
            try:
                rec = struct.unpack_from(fmt, data, base + i * size)
            except struct.error:
                break
            nm = rec[7].split(b"\x00")[0].decode("utf-8", "replace").strip()
            if nm:
                names[i] = nm
        with self.field_lock:
            self.names = names

    def _scan_status(self, data, pkt_format=2025):
        fmt, size = ((CAR_STATUS_2026_FMT, CAR_STATUS_2026_SIZE)
                     if pkt_format == 2026 else (CAR_STATUS_FMT, CAR_STATUS_SIZE))
        max_cars = 24 if pkt_format == 2026 else 22
        with self.field_lock:
            for i in range(max_cars):
                try:
                    rec = struct.unpack_from(fmt, data, HEADER_SIZE + i * size)
                except struct.error:
                    break
                if pkt_format == 2026:
                    rec = rec[:23] + rec[24:]
                detail = self.field_details.setdefault(i, {})
                detail.update(fuel_kg=rec[5], fuel_delta_laps=rec[7],
                              compound=VISUAL_TYRE.get(rec[14], rec[14]),
                              compound_id=rec[14], tyre_age=rec[15],
                              ers_j=rec[19], ers_mode=rec[20])

    def field_snapshot(self):
        with self.field_lock:
            rows = []
            for position, distance, index in self.field:
                item = dict(self.field_details.get(index, {}))
                item.update(index=index, position=position, total_distance=distance,
                            name=self.names.get(index, f"P{position}"))
                rows.append(item)
            return rows

    def all_gaps(self, my_idx, my_speed_kmh):
        """Return the gap ahead and sorted named gaps behind."""
        with self.field_lock:
            rows = list(self.field)
            names = dict(self.names)
        me = next((r for r in rows if r[2] == my_idx), None)
        if not me:
            return None, None, []
        my_pos, my_dist, _ = me
        v = max(my_speed_kmh, 40) / 3.6
        ahead = next((r for r in rows if r[0] == my_pos - 1), None)
        ga = (ahead[1] - my_dist) / v if ahead else None
        na = names.get(ahead[2], "CAR AHEAD") if ahead else None
        behind = [(names.get(r[2], f"P{r[0]}"), (my_dist - r[1]) / v)
                  for r in rows if r[0] > my_pos]
        behind.sort(key=lambda x: x[1])
        return ga, na, behind

    def gaps(self, my_idx, my_speed_kmh):
        """-> (pos, total, name_ahead, gap_ahead_s, name_behind, gap_behind_s)"""
        with self.field_lock:
            rows = list(self.field)
            names = dict(self.names)
        if not rows:
            return None
        me = next((r for r in rows if r[2] == my_idx), None)
        if not me:
            return None
        my_pos, my_dist, _ = me
        v = max(my_speed_kmh, 40) / 3.6
        ahead = next((r for r in rows if r[0] == my_pos - 1), None)
        behind = next((r for r in rows if r[0] == my_pos + 1), None)
        ga = (ahead[1] - my_dist) / v if ahead else None
        gb = (my_dist - behind[1]) / v if behind else None
        return (my_pos, len(rows),
                names.get(ahead[2], "—") if ahead else None, ga,
                names.get(behind[2], "—") if behind else None, gb)

    # ---- in-process reports at session end --------------------------------
    def _finalize_session(self):
        for f in self._files.values():
            try:
                f.close()
            except Exception:
                pass
        self._files, self._writers = {}, {}
        if self.cur_uid is None or not self._session_has_lap:
            return
        p1 = self._paths.get("p1")
        if not (p1 and os.path.exists(p1)):
            return
        i, s = self._session_index, self._session_stamp
        html = os.path.join(self.out_dir, f"f1_solo_s{i}_{s}.html")

        def work():
            try:
                f1_solo_report.build_solo(p1, html)
                self.notify_q.put(f"Session {i}: generated {os.path.basename(html)}")
            except SystemExit:
                pass
            except Exception as e:
                self.notify_q.put(f"Report failed: {e}")
        threading.Thread(target=work, daemon=True).start()


# ============================================================================
# Delta to the driver's own best lap.
# ============================================================================
class DeltaEngine:
    """Retain a valid best-lap trace and calculate a stable live delta.

    Lap packets and telemetry packets arrive independently.  The previous
    implementation could promote an invalid/incomplete lap and displayed every
    small interpolation jump.  We retain the validity of the whole lap,
    normalise the trace to the official lap time, and lightly filter the display
    value without changing its sign or long-term value.
    """
    def __init__(self):
        self.ref_d = None
        self.ref_t = None
        self.ref_ms = 0
        self.cur = []
        self._lap = None
        self._invalid = False
        self._filtered = None
        self._last_dist = None

    def reset(self):
        self.__init__()

    def update(self, lap):
        """Consume a LapData tuple and return delta seconds when available."""
        if not lap:
            return None
        lap_num, dist, cur_ms, last_ms = lap[14], lap[10], lap[1], lap[0]
        if self._lap is None:
            self._lap = lap_num
        same_lap = lap_num == self._lap
        if same_lap:
            self._invalid = self._invalid or bool(lap[18])
        # Promote a newly completed personal best to the reference lap.
        if lap_num != self._lap:
            if (not self._invalid and 30_000 <= last_ms <= 300_000 and
                    len(self.cur) > 30 and self.cur[-1][0] > 1000 and
                    (self.ref_ms == 0 or last_ms < self.ref_ms)):
                d = np.array([p[0] for p in self.cur], dtype=float)
                t = np.array([p[1] for p in self.cur], dtype=float)
                keep = np.concatenate(([True], np.diff(d) > 0.5))
                if keep.sum() > 10:
                    self.ref_d, self.ref_t = d[keep], t[keep]
                    if self.ref_d[0] > 1.0:
                        self.ref_d = np.insert(self.ref_d, 0, 0.0)
                        self.ref_t = np.insert(self.ref_t, 0, 0.0)
                    # The last sampled timestamp is normally just before the
                    # timing line. Scale it to the official completed lap time.
                    if self.ref_t[-1] > 0:
                        self.ref_t *= float(last_ms) / self.ref_t[-1]
                    self.ref_ms = last_ms
            self.cur = []
            self._lap = lap_num
            self._invalid = bool(lap[18])
            self._filtered = None
            self._last_dist = None
        if dist >= 0 and cur_ms > 0:
            if not self.cur or dist > self.cur[-1][0]:
                self.cur.append((dist, cur_ms))
        if self.ref_d is None or dist <= 0 or dist > self.ref_d[-1]:
            return self._filtered
        # The game occasionally reports a lap distance that briefly drops
        # back (kerb strikes, wheel-spin recalculation). Feeding that into
        # the interpolation look-up makes the delta jump backwards for a
        # frame; hold the last stable value instead of reacting to it.
        if self._last_dist is not None and dist < self._last_dist - 0.5:
            return self._filtered
        self._last_dist = dist
        ref_at = float(np.interp(dist, self.ref_d, self.ref_t))
        raw = (cur_ms - ref_at) / 1000.0
        if not np.isfinite(raw) or abs(raw) > 20.0:
            return self._filtered
        if self._filtered is None:
            self._filtered = raw
        else:
            # Cap how far a single sample can move the displayed value so an
            # isolated noisy packet cannot produce a visible spike; the EMA
            # still tracks genuine, sustained changes within a lap or two.
            step = max(-0.15, min(0.15, raw - self._filtered))
            self._filtered = self._filtered * 0.68 + (self._filtered + step) * 0.32
        return self._filtered


class PaceTracker:
    def __init__(self):
        self.laps = []
        self._seen = None

    def reset(self):
        self.laps.clear()
        self._seen = None

    def feed(self, lap):
        if not lap:
            return False
        last_ms, lap_num = lap[0], lap[14]
        if last_ms <= 0:
            return False
        key = (lap_num, last_ms)
        if key == self._seen:
            return False
        if self.laps and lap_num <= self.laps[-1][0]:
            self._seen = key
            return False
        self._seen = key
        self.laps.append((lap_num - 1 if lap_num > 1 else lap_num, last_ms))
        return True

    def best(self):
        return min((ms for _, ms in self.laps), default=0)

    def message(self):
        n = len(self.laps)
        if n == 0:
            return "Collecting data...", DIM
        if n >= 2 and self.laps[-1][1] == self.best():
            return "\u2605 PERSONAL BEST!", GREEN
        t = [ms for _, ms in self.laps]
        if n < 2:
            return "First lap recorded", DIM
        diffs = [(t[i] - t[i - 1]) / 1000 for i in range(1, len(t))]
        rate = sum(diffs[-3:]) / len(diffs[-3:])
        streak = 1
        for d in reversed(diffs[:-1]):
            if (d > 0) == (diffs[-1] > 0):
                streak += 1
            else:
                break
        if rate > 0.12 and streak >= 2:
            return f"Pace \u25bc for {streak} laps (+{rate:.2f}s/lap)", RED
        if rate > 0.12:
            return f"Slower lap (+{rate:.2f}s)", YELLOW
        if rate < -0.12:
            return f"Pace \u25b2 ({abs(rate):.2f}s faster)", GREEN
        return f"Consistent (\u00b1{abs(rate):.2f}s)", DIM


# ============================================================================
# Widgets
# ============================================================================
def temp_color(t):
    if t < 75:
        return "#3d7bff"
    if t < 85:
        return "#31c9e8"
    if t < 105:
        return GREEN
    if t < 115:
        return YELLOW
    return RED


def drive_phase(tel, status=None):
    """Describe what the car is doing without conflating it with DRS."""
    if not tel:
        return "NO DATA", DIM
    speed, throttle, steer, brake, gear = tel[0], tel[1], tel[2], tel[3], tel[5]
    if status and status[4]:
        return "PIT LIMITER", YELLOW
    if gear == -1:
        return "REVERSE", YELLOW
    if speed < 3:
        return "STOPPED", DIM
    if brake > 0.15:
        return "BRAKING", RED
    if abs(steer) > 0.22:
        return "CORNERING", PURPLE
    if abs(steer) < 0.08 and speed > 60:
        return "STRAIGHT", GREEN
    if throttle > 0.65:
        return "ACCELERATING", ACC
    return "COASTING", DIM


def drs_state(tel, status=None, packet_format=2025):
    """Return active-aero terminology without displaying the legacy DRS name."""
    if not tel:
        return "ACTIVE AERO --", DIM
    if tel[7]:
        return "STRAIGHT MODE ACTIVE", GREEN
    if status:
        if status[11]:
            return "STRAIGHT MODE READY", ACC
        if status[12] > 0:
            return f"STRAIGHT MODE IN {status[12]} m", DIM
    return "CORNER MODE", PURPLE


class TyreWidget(tk.Canvas):
    W, H = 210, 140

    def __init__(self, parent):
        super().__init__(parent, width=self.W, height=self.H, bg=CARD,
                         highlightthickness=0)
        tw, th = 48, 50
        pos = {"FL": (18, 9), "FR": (self.W - 18 - tw, 9),
               "RL": (18, self.H - 9 - th), "RR": (self.W - 18 - tw, self.H - 9 - th)}
        self.create_rectangle(self.W / 2 - 17, 22, self.W / 2 + 17, self.H - 22,
                              outline=EDGE, width=2)
        self.items = {}
        f_w = tkfont.Font(family="Consolas", size=11, weight="bold")
        f_t = tkfont.Font(family="Consolas", size=8)
        f_l = tkfont.Font(family="Segoe UI", size=8)
        for k, (x, y) in pos.items():
            r = self.create_rectangle(x, y, x + tw, y + th, fill="#26090d",
                                      outline=EDGE)
            w = self.create_text(x + tw / 2, y + th / 2 - 7, text="--", fill=FG, font=f_w)
            t = self.create_text(x + tw / 2, y + th / 2 + 10, text="--\u00b0",
                                 fill=DIM, font=f_t)
            self.create_text(x + tw / 2, y - 3 if y < 40 else y + th + 9, text=k,
                             fill=DIM, font=f_l, anchor="s" if y < 40 else "n")
            self.items[k] = (r, w, t)
        self.compound = self.create_text(self.W / 2, self.H / 2 - 10, text="\u2014",
                                         fill=YELLOW,
                                         font=tkfont.Font(family="Segoe UI", size=10,
                                                          weight="bold"))
        self.age = self.create_text(self.W / 2, self.H / 2 + 12, text="", fill=DIM,
                                    font=tkfont.Font(family="Segoe UI", size=8))

    def set(self, temps, wears, compound, age):
        for i, k in enumerate(("RL", "RR", "FL", "FR")):
            r, wt, tt = self.items[k]
            t = temps[i] if temps else 0
            w = wears[i] if wears else None
            self.itemconfig(r, fill=temp_color(t) if temps else "#26090d")
            self.itemconfig(wt, text=f"{w:.0f}%" if w is not None else "--")
            self.itemconfig(tt, text=f"{t:.0f}\u00b0" if temps else "--\u00b0")
        self.itemconfig(self.compound, text=compound or "\u2014")
        self.itemconfig(self.age, text=f"{age} laps" if age is not None else "")


class DeltaBar(tk.Canvas):
    """Simulator-style horizontal delta bar centered on the reference."""
    def __init__(self, parent, width=900, height=26):
        super().__init__(parent, width=width, height=height, bg=BG,
                         highlightthickness=0)
        self.w, self.h = width, height
        self.background = self.create_rectangle(0, 0, width, height,
                                                fill="#090204", outline=EDGE)
        self.bar = self.create_rectangle(width / 2, 2, width / 2, height - 2,
                                         fill=GREEN, outline="")
        self.center = self.create_line(width / 2, 0, width / 2, height,
                                       fill=DIM, width=2)
        self._delta = None
        self.bind("<Configure>", self._resize)

    def _resize(self, event):
        self.w = max(20, event.width)
        self.coords(self.background, 0, 0, self.w, self.h)
        self.coords(self.center, self.w / 2, 0, self.w / 2, self.h)
        self.set(self._delta)

    def set(self, delta, scale=1.5):
        self._delta = delta
        if delta is None:
            self.coords(self.bar, self.w / 2, 2, self.w / 2, self.h - 2)
            return
        frac = max(-1.0, min(1.0, delta / scale))
        c = self.w / 2
        x = c + frac * (self.w / 2 - 4)
        self.itemconfig(self.bar, fill=RED if delta > 0 else GREEN)
        self.coords(self.bar, min(c, x), 2, max(c, x), self.h - 2)


class Sparkline(tk.Canvas):
    def __init__(self, parent, color, width=260, height=34):
        super().__init__(parent, width=width, height=height, bg=BG,
                         highlightthickness=0)
        self.w, self.h, self.color = width, height, color

    def draw(self, laps):
        self.delete("all")
        t = [ms for _, ms in laps][-14:]
        if len(t) < 2:
            self.create_text(self.w / 2, self.h / 2, text="\u2014", fill=DIM,
                             font=("Segoe UI", 11))
            return
        lo, hi = min(t), max(t)
        span = max(hi - lo, 250)
        pts = [(8 + i * (self.w - 16) / (len(t) - 1),
                8 + (ms - lo) / span * (self.h - 16)) for i, ms in enumerate(t)]
        for a, b in zip(pts, pts[1:]):
            self.create_line(*a, *b, fill=self.color, width=2)
        bi = t.index(min(t))
        for i, (x, y) in enumerate(pts):
            r = 5 if i == bi else 3
            self.create_oval(x - r, y - r, x + r, y + r,
                             fill=GREEN if i == bi else self.color, outline="")


class MicroStrip(tk.Canvas):
    """Micro-sector strip: green gains and red losses versus the best lap."""
    def __init__(self, parent, n=20, width=1400, height=34):
        super().__init__(parent, width=width, height=height, bg=BG,
                         highlightthickness=0)
        self.n, self.w, self.h = n, width, height
        self.cells = []
        for i in range(n):
            self.cells.append(self.create_rectangle(0, 0, 0, height,
                                                    fill="#26090d", outline=""))
        self.marker = self.create_rectangle(0, height - 4, 0, height,
                                             fill=CHALK_MARK, outline="")
        self._cur_idx = None
        self.bind("<Configure>", self._resize)
        self._layout(width)

    def _layout(self, width):
        self.w = max(40, width)
        gap = 3
        cw = max(1, (self.w - gap * (self.n - 1)) / self.n)
        for i, cell in enumerate(self.cells):
            x = i * (cw + gap)
            self.coords(cell, x, 0, x + cw, self.h)
        if self._cur_idx is not None and 0 <= self._cur_idx < self.n:
            x1, _, x2, _ = self.coords(self.cells[self._cur_idx])
            self.coords(self.marker, x1, self.h - 4, x2, self.h)

    def _resize(self, event):
        self._layout(event.width)

    def set(self, deltas, cur_idx=None):
        self._cur_idx = cur_idx
        for i, d in enumerate(deltas[:self.n]):
            if d is None:
                col = "#26090d"
            elif d < -0.03:
                col = GREEN
            elif d > 0.03:
                col = RED
            else:
                col = "#84252e"
            self.itemconfig(self.cells[i], fill=col)
        if cur_idx is not None and 0 <= cur_idx < self.n:
            x1, y1, x2, y2 = self.coords(self.cells[cur_idx])
            self.coords(self.marker, x1, self.h - 4, x2, self.h)
        else:
            self.coords(self.marker, 0, self.h - 4, 0, self.h)


class Bar(tk.Canvas):
    def __init__(self, parent, color, width=260, height=16):
        super().__init__(parent, width=width, height=height, bg=CARD,
                         highlightthickness=0)
        self.w, self.h = width, height
        self.create_rectangle(0, 0, width, height, fill="#090204", outline=EDGE)
        self.rect = self.create_rectangle(0, 0, 0, height, fill=color, outline="")

    def set(self, frac):
        frac = max(0.0, min(1.0, frac))
        self.coords(self.rect, 0, 0, int(self.w * frac), self.h)


# ============================================================================
# App
# ============================================================================
class SoloApp:
    def __init__(self, root, shared, receiver, notify_q, out_dir, fullscreen=False,
                 mode_switch=None, database=None):
        self.root = root
        self.shared = shared
        self.rcv = receiver
        self.q = notify_q
        self.delta_engine = DeltaEngine()
        self.pace = PaceTracker()
        self._session = -1
        self.out_dir = out_dir
        self.mode_switch = mode_switch
        self.database = database
        self.compact = False

        root.title("F1 SOLO ENGINEER")
        root.configure(bg=BG)
        root.geometry("1500x780")
        root.minsize(1000, 680)
        if fullscreen:
            root.attributes("-fullscreen", True)
        else:
            try:
                root.state("zoomed")
            except tk.TclError:
                pass
        root.bind("<F11>", self.toggle_fs)
        root.bind("<Escape>", lambda e: root.attributes("-fullscreen", False))

        # The dashboard is deliberately a single compact page. Every live
        # value remains visible at once; no scrolling is required.
        self.page = tk.Frame(root, bg=BG)
        self.page.pack(fill="both", expand=True)
        self._build_menu()

        f_top = tkfont.Font(family="Segoe UI", size=10)
        self.f_huge = tkfont.Font(family="Segoe UI", size=32, weight="bold")
        f_huge = self.f_huge
        f_sub = tkfont.Font(family="Segoe UI", size=10)
        f_big = tkfont.Font(family="Consolas", size=25, weight="bold")
        f_mid = tkfont.Font(family="Consolas", size=14, weight="bold")
        f_lab = tkfont.Font(family="Segoe UI", size=9)
        f_val = tkfont.Font(family="Consolas", size=12)

        self.topbar = tk.Frame(self.page, bg="#710b14")
        self.topbar.pack(fill="x", padx=18)
        tk.Label(self.topbar, text="F1  SOLO ENGINEER", font=("Segoe UI", 10, "bold"),
                 fg=YELLOW, bg="#710b14").pack(side="left", padx=(10, 18), pady=1)
        self.top = tk.Label(self.topbar,
                            text="Waiting for telemetry · UDP 2025/2026 · port 20777",
                            font=f_top, fg=DIM, bg="#710b14", anchor="w")
        self.top.pack(side="left", fill="x", expand=True)
        self.live_badge = tk.Label(self.topbar, text="● WAITING",
                                   font=("Segoe UI", 9, "bold"), fg=DIM,
                                   bg="#710b14")
        self.live_badge.pack(side="right", padx=10)

        # ---- High-priority race engineer banner ----
        self.eng = RaceEngineer()
        self.f_banner = tkfont.Font(family="Segoe UI", size=16, weight="bold")
        f_banner = self.f_banner
        f_bandet = tkfont.Font(family="Segoe UI", size=10)
        self.banner = tk.Frame(self.page, bg="#49090f", highlightbackground=YELLOW,
                               highlightthickness=2)
        self.banner.pack(fill="x", padx=18, pady=(0, 1))
        self.btitle = tk.Label(self.banner, text="ENGINEER: waiting for data...",
                               font=f_banner, fg=DIM, bg="#49090f", anchor="w",
                               wraplength=1400, justify="left", height=1)
        self.btitle.pack(fill="x", padx=18, pady=(5, 0))
        self.bdetail = tk.Label(self.banner, text="", font=f_bandet, fg=DIM,
                                bg="#49090f", anchor="w", wraplength=1400,
                                justify="left", height=1)
        self.bdetail.pack(fill="x", padx=18, pady=(0, 1))
        self.bsecond = tk.Label(self.banner, text="", font=f_bandet, fg=DIM,
                                bg="#49090f", anchor="w", wraplength=1400,
                                justify="left", height=1)
        self.bsecond.pack(fill="x", padx=18, pady=(0, 5))

        # ---- Delta versus personal best ----
        center = tk.Frame(self.page, bg=BG)
        self.delta_section = center
        center.pack(fill="x")
        self.delta = tk.Label(center, text="--.---", font=f_huge, fg=DIM, bg=BG)
        self.delta.pack()
        self.dbar = DeltaBar(center, width=980, height=18)
        self.dbar.pack(fill="x", padx=90, pady=(0, 1))
        self.delta_sub = tk.Label(center, text="DELTA to personal best lap",
                                  font=f_sub, fg=DIM, bg=BG)
        self.delta_sub.pack()
        self.micro = MicroStrip(self.page, n=20, width=1420, height=20)
        self.micro.pack(fill="x", padx=18, pady=(3, 0))
        tk.Label(self.page, text="MICRO-SECTORS  \u00b7  green = gaining time   "
                            "red = losing time   (vs your reference lap)",
                 font=tkfont.Font(family="Segoe UI", size=8), fg=DIM,
                 bg=BG).pack(anchor="w", padx=18)

        # ---- row: timing | position/gap | tyres ----
        mid = tk.Frame(self.page, bg=BG)
        self.telemetry_section = mid
        mid.pack(fill="both", expand=True, padx=18, pady=2)
        for c, wgt in ((0, 1), (1, 1), (2, 0)):
            mid.columnconfigure(c, weight=wgt)

        # timing
        tcard = tk.Frame(mid, bg=CARD, highlightbackground=ACC, highlightthickness=1)
        tcard.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        tk.Label(tcard, text="CURRENT LAP", font=f_lab, fg=DIM, bg=CARD,
                 anchor="w").pack(fill="x", padx=16, pady=(6, 0))
        self.cur = tk.Label(tcard, text="--:--.---", font=f_big, fg=FG, bg=CARD,
                            anchor="w")
        self.cur.pack(fill="x", padx=16)
        self.lapinfo = tk.Label(tcard, text="", font=f_val, fg=DIM, bg=CARD, anchor="w")
        self.lapinfo.pack(fill="x", padx=16)
        self.last = tk.Label(tcard, text="LAST  --:--.---", font=f_mid, fg=FG,
                             bg=CARD, anchor="w")
        self.last.pack(fill="x", padx=16, pady=(4, 0))
        self.bestl = tk.Label(tcard, text="BEST  --:--.---", font=f_mid, fg=ACC,
                              bg=CARD, anchor="w")
        self.bestl.pack(fill="x", padx=16)
        self.pred = tk.Label(tcard, text="PREDICT  --:--.---", font=f_val,
                             fg=PURPLE, bg=CARD, anchor="w")
        self.pred.pack(fill="x", padx=16, pady=(2, 0))
        self.sect = tk.Label(tcard, text="S1 --  S2 --", font=f_val, fg=DIM,
                             bg=CARD, anchor="w")
        self.sect.pack(fill="x", padx=16, pady=(4, 1))
        self.rules_info = tk.Label(tcard, text="PEN 0s  ·  WARN 0",
                                   font=("Consolas", 10, "bold"), fg=DIM,
                                   bg=CARD, anchor="w")
        self.rules_info.pack(fill="x", padx=16)
        self.tt_info = tk.Label(tcard, text="", font=("Consolas", 11), fg=PURPLE,
                                bg=CARD, anchor="w", justify="left")
        self.tt_info.pack(fill="x", padx=16, pady=(0, 6))

        # Position and gaps.
        pcard = tk.Frame(mid, bg=CARD, highlightbackground=PURPLE, highlightthickness=1)
        pcard.grid(row=0, column=1, sticky="nsew", padx=8)
        self.position_title = tk.Label(pcard, text="RACE POSITION", font=f_lab,
                                       fg=DIM, bg=CARD, anchor="w")
        self.position_title.pack(fill="x", padx=16, pady=(6, 0))
        self.pos = tk.Label(pcard, text="P-", font=f_big, fg=FG, bg=CARD, anchor="w")
        self.pos.pack(fill="x", padx=16)
        self.map_canvas = tk.Canvas(pcard, width=260, height=70, bg=CARD,
                                    highlightthickness=0)
        self.map_canvas.pack(fill="x", padx=10)
        self.track_map = LiveTrackMap(self.map_canvas, 260, 70, line="#d7a9bf",
                                      background=CARD)
        tk.Label(pcard, text="\u25b2 AHEAD", font=f_lab, fg=DIM, bg=CARD,
                 anchor="w").pack(fill="x", padx=16, pady=(4, 0))
        self.ahead = tk.Label(pcard, text="\u2014", font=f_mid, fg=RED, bg=CARD,
                              anchor="w")
        self.ahead.pack(fill="x", padx=16)
        tk.Label(pcard, text="\u25bc BEHIND", font=f_lab, fg=DIM, bg=CARD,
                 anchor="w").pack(fill="x", padx=16, pady=(4, 0))
        self.behind = tk.Label(pcard, text="\u2014", font=f_mid, fg=GREEN, bg=CARD,
                               anchor="w")
        self.behind.pack(fill="x", padx=16)
        self.ers = tk.Label(pcard, text="ERS --", font=f_val, fg=FG, bg=CARD, anchor="w")
        self.ers.pack(fill="x", padx=16, pady=(5, 0))
        self.fuel = tk.Label(pcard, text="FUEL --", font=f_val, fg=FG, bg=CARD,
                             anchor="w")
        self.fuel.pack(fill="x", padx=16, pady=(0, 6))

        # Tyres and speed.
        rcard = tk.Frame(mid, bg=CARD, highlightbackground=GREEN, highlightthickness=1)
        rcard.grid(row=0, column=2, sticky="nsew", padx=(8, 0))
        sp = tk.Frame(rcard, bg=CARD)
        sp.pack(fill="x", padx=16, pady=(6, 0))
        self.speed = tk.Label(sp, text="---", font=tkfont.Font(family="Segoe UI",
                              size=36, weight="bold"), fg=FG, bg=CARD)
        self.speed.pack(side="left")
        tk.Label(sp, text="km/h", font=f_lab, fg=DIM, bg=CARD).pack(side="left",
                 anchor="s", pady=(0, 9), padx=4)
        self.gear = tk.Label(sp, text="N", font=tkfont.Font(family="Segoe UI",
                             size=26, weight="bold"), fg=YELLOW, bg=CARD)
        self.gear.pack(side="right")
        bars = tk.Frame(rcard, bg=CARD)
        bars.pack(fill="x", padx=16, pady=4)
        for lbl, attr, col in (("THR", "thr", GREEN), ("BRK", "brk", RED)):
            row = tk.Frame(bars, bg=CARD)
            row.pack(fill="x", pady=1)
            tk.Label(row, text=lbl, font=f_lab, fg=DIM, bg=CARD, width=4,
                     anchor="w").pack(side="left")
            b = Bar(row, col, width=170, height=14)
            b.pack(side="left")
            setattr(self, attr, b)
        self.phase = tk.Label(rcard, text="STOPPED", font=f_mid, fg=DIM, bg=CARD)
        self.phase.pack(pady=(2, 0))
        self.drs = tk.Label(rcard, text="CORNER MODE", font=f_val,
                            fg="#d7a9bf", bg=CARD)
        self.drs.pack(pady=(0, 2))
        tk.Label(rcard, text="TYRES", font=f_lab, fg=DIM, bg=CARD).pack()
        self.tyres = TyreWidget(rcard)
        self.tyres.pack(padx=16, pady=(0, 6))

        # ---- pace assistant ----
        pace = tk.Frame(self.page, bg=BG)
        self.pace_section = pace
        pace.pack(fill="x", padx=18, pady=(0, 2))
        self.spark = Sparkline(pace, ACC)
        self.spark.pack(side="left")
        pl = tk.Frame(pace, bg=BG)
        pl.pack(side="left", padx=16)
        self.pmsg = tk.Label(pl, text="Collecting data...",
                             font=tkfont.Font(family="Segoe UI", size=12,
                                              weight="bold"), fg=DIM, bg=BG, anchor="w")
        self.pmsg.pack(fill="x")
        self.strategy_line = tk.Label(pl, text="STRATEGY · learning tyre life and pit window",
                                      font=f_lab, fg=DIM, bg=BG, anchor="w")
        self.strategy_line.pack(fill="x")

        self.status = tk.Label(self.page, text=f"Automatic reports after each session \u2192 {out_dir}"
                               "     F11 = fullscreen",
                               font=f_lab, fg=DIM, bg=BG, anchor="w")
        self.status.pack(fill="x", padx=18, pady=(0, 2))

        root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.tick()

    def _build_menu(self):
        menu = tk.Menu(self.root)
        mode = tk.Menu(menu, tearoff=False)
        mode.add_command(label="Solo Engineer", state="disabled")
        mode.add_command(label="Split Screen", command=lambda: self._switch("split"))
        mode.add_separator()
        mode.add_command(label="Main Menu", command=lambda: self._switch("menu"))
        mode.add_command(label="Exit", command=self.on_close)
        menu.add_cascade(label="Mode", menu=mode)

        view = tk.Menu(menu, tearoff=False)
        view.add_command(label="All Data Dashboard", state="disabled")
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
        help_menu.add_command(label="UDP Setup", command=self.show_udp_help)
        help_menu.add_command(label="About", command=lambda: messagebox.showinfo(
            "F1 Telemetry Hub",
            "Unified F1 25/26 telemetry and race engineer\nUDP 2025/2026 · Port 20777"))
        menu.add_cascade(label="Help", menu=help_menu)
        self.root.config(menu=menu)

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

    @staticmethod
    def show_udp_help():
        messagebox.showinfo(
            "UDP Telemetry Setup",
            "UDP Telemetry: On\nUDP Broadcast: Off\nUDP IP: 127.0.0.1\n"
            "UDP Port: 20777\nUDP Send Rate: 60 Hz\n"
            "UDP Format: 2025 or 2026 Season Pack\n"
            "Your Telemetry: Public")

    def _switch(self, mode):
        if self.mode_switch:
            self.mode_switch(mode)

    def toggle_fs(self, _=None):
        self.root.attributes("-fullscreen",
                             not self.root.attributes("-fullscreen"))

    def tick(self):
        s = self.shared
        with s.lock:
            p = s.p1
            idx = s.p1_idx
            sess = dict(s.session)
            pkts, last_t, sidx = s.packets, s.last_packet_time, s.session_index
            packet_format, warning = s.packet_format, s.warning
            tel, lap, st, dmg = p.tel, p.lap, p.status, p.dmg
            best_ms, name = p.best_lap_ms, p.name
            time_trial_data = dict(s.time_trial)

        alive = (time.time() - last_t) < 2
        session_type = sess.get("type") or "Unknown"
        sess["packet_format"] = packet_format
        session_lower = session_type.casefold()
        is_time_trial = "time trial" in session_lower
        if is_time_trial:
            position_title = "TIME TRIAL RANK"
        elif session_lower.startswith("race"):
            position_title = "RACE POSITION"
        elif "q" in session_lower or "qual" in session_lower:
            position_title = "QUALIFYING POSITION"
        elif session_type.startswith("P") or "practice" in session_lower:
            position_title = "PRACTICE POSITION"
        else:
            position_title = "SESSION POSITION"
        self.position_title.config(text=position_title)
        if is_time_trial and time_trial_data:
            session_best = time_trial_data.get("session_best", {})
            personal_best = time_trial_data.get("personal_best", {})
            rival = time_trial_data.get("rival", {})
            self.tt_info.config(
                text="TT SESSION  " + fmt_ms(session_best.get("lap_ms", 0)) +
                     "\nPERSONAL    " + fmt_ms(personal_best.get("lap_ms", 0)) +
                     "\nRIVAL       " + fmt_ms(rival.get("lap_ms", 0)))
        else:
            self.tt_info.config(text="")
        tt = sess.get("trackTemp")
        temp = f"   track {tt}C air {sess.get('airTemp')}C" if tt is not None else ""
        weather_name = {0: "CLEAR", 1: "LIGHT CLOUD", 2: "OVERCAST",
                        3: "LIGHT RAIN", 4: "HEAVY RAIN", 5: "STORM"}.get(
                            sess.get("weather"), "")
        format_text = f"UDP {packet_format}" if packet_format else "UDP waiting"
        top_text = (f"Session #{sidx}   {sess.get('track') or '\u2014'}  "
                    f"{sess.get('type') or ''}{temp}   {format_text}   "
                    f"{weather_name}")
        length_name = {2: "3 LAPS", 3: "5 LAPS", 4: "25%", 5: "35%",
                       6: "50%", 7: "100%"}.get(sess.get("session_length"))
        if length_name:
            top_text += f"   {length_name}"
        if sess.get("ai_difficulty") is not None:
            top_text += f"   AI {sess['ai_difficulty']}"
        if warning:
            top_text += f"   |   {warning}"
        self.top.config(text=top_text, fg=RED if warning else (FG if alive else DIM))
        self.live_badge.config(text="● LIVE" if alive else "○ WAITING",
                               fg=GREEN if alive else DIM)

        if sidx != self._session:
            self._session = sidx
            self.delta_engine.reset()
            self.pace.reset()
            self.eng.reset()
            if self.database:
                track = sess.get("track")
                self.eng.set_learned_profile(
                    self.database.get_profile(track),
                    self.database.setup_recommendations(track))
            if lap:
                self.pace._seen = (lap[14], lap[0])
            self.spark.draw([])

        self.track_map.set_track(sess.get("track"), sess.get("track_id"))
        if lap:
            self.track_map.update_car("player", lap[10], ACC, "YOU")

        # ---- Race-engineer insight engine ----
        ga, na, behind = (self.rcv.all_gaps(idx, tel[0] if tel else 0)
                          if idx is not None else (None, None, []))
        if alive:
            try:
                _d, msgs = self.eng.update(tel, lap, st, dmg, time.time(),
                                           total_laps=sess.get("laps"),
                                           gap_ahead=ga, name_ahead=na,
                                           gaps_behind=behind,
                                           session_type=session_type, session=sess,
                                           packet_format=packet_format)
            except Exception:
                msgs = []
        else:
            msgs = []
        if not alive:
            self.btitle.config(text="TELEMETRY PAUSED — WAITING FOR LIVE DATA", fg=DIM)
            self.bdetail.config(text="Displayed car values are the last valid frame", fg=DIM)
            self.bsecond.config(text="")
            self.banner.config(highlightbackground=EDGE)
        elif msgs:
            m = msgs[0]
            self.btitle.config(text=m.title, fg=m.color)
            self.bdetail.config(text=m.detail, fg=DIM)
            self.banner.config(highlightbackground=m.color)
            next_actions = "   ·   ".join(m.title for m in msgs[1:4])
            self.bsecond.config(text=(f"NEXT  {next_actions}" if next_actions else ""),
                                fg=msgs[1].color if len(msgs) > 1 else DIM)
        else:
            self.btitle.config(text="ENGINEER: all systems within range", fg=GREEN)
            self.bdetail.config(text="")
            self.bsecond.config(text="")
            self.banner.config(highlightbackground=EDGE)
        # Micro-sector strip.
        cur_idx = None
        if lap and self.eng.micro.ref is not None:
            seg_len = float(self.eng.micro.ref["dist"][-1]) / self.eng.micro.n
            if seg_len > 0:
                cur_idx = min(self.eng.micro.n - 1, int(lap[10] / seg_len))
        self.micro.set(self.eng.micro.seg_delta, cur_idx)

        # Delta versus personal best.
        d = self.delta_engine.update(lap)
        if d is None:
            self.delta.config(text="--.---", fg=DIM)
            self.dbar.set(None)
            self.delta_sub.config(text="DELTA to personal best lap "
                                       "(one complete lap required)")
        else:
            self.delta.config(text=f"{d:+.3f}", fg=GREEN if d < 0 else RED)
            self.dbar.set(d)
            self.delta_sub.config(text="DELTA to personal best lap")

        if tel:
            self.speed.config(text=f"{tel[0]:d}")
            self.gear.config(text="R" if tel[5] == -1 else
                             ("N" if tel[5] == 0 else str(tel[5])))
            self.thr.set(tel[1])
            self.brk.set(tel[3])
            phase_text, phase_color = drive_phase(tel, st)
            if phase_text == "PIT LIMITER" and sess.get("pit_speed_limit"):
                phase_text += f"  {sess['pit_speed_limit']} KM/H"
            drs_text, drs_color = drs_state(tel, st, packet_format)
            self.phase.config(text=phase_text, fg=phase_color)
            self.drs.config(text=drs_text, fg=drs_color)
            self.speed.config(fg=FG if alive else DIM)
            self.tyres.set((tel[14], tel[15], tel[16], tel[17]),
                           (dmg[0], dmg[1], dmg[2], dmg[3]) if dmg else None,
                           VISUAL_TYRE.get(st[14], st[14]) if st else None,
                           st[15] if st else None)
        if lap:
            self.cur.config(text=fmt_ms(lap[1]), fg=RED if lap[18] else FG)
            sec = {0: "S1", 1: "S2", 2: "S3"}.get(lap[17], "?")
            self.lapinfo.config(text=f"Lap {lap[14]}  \u00b7  {sec}"
                                     f"{'  INVALID' if lap[18] else ''}")
            self.last.config(text=f"LAST  {fmt_ms(lap[0])}")
            self.bestl.config(text=f"BEST  {fmt_ms(best_ms) if best_ms else '--:--.---'}")
            self.sect.config(text=f"S1 {fmt_ms(lap[2] + lap[3]*60000)}   "
                                  f"S2 {fmt_ms(lap[4] + lap[5]*60000)}")
            self.rules_info.config(
                text=f"PEN {lap[19]}s  ·  WARN {lap[20]}  ·  CUTS {lap[21]}",
                fg=RED if lap[22] or lap[23] else (YELLOW if lap[19] else DIM))
            if best_ms and d is not None:
                self.pred.config(text=f"PREDICT  {fmt_ms(int(best_ms + d*1000))}")
            else:
                self.pred.config(text="PREDICT  --:--.---")
            self.pos.config(text=f"P{lap[13]}")

        # Gaps ahead and behind.
        g = self.rcv.gaps(idx, tel[0] if tel else 0) if idx is not None else None
        if g:
            pos, total, na, ga, nb, gb = g
            self.pos.config(text=f"P{pos}  /  {total}")
            if is_time_trial:
                self.ahead.config(text="\u2014 not applicable", fg=DIM)
                self.behind.config(text="\u2014 not applicable", fg=DIM)
            else:
                self.ahead.config(text=f"{na}   +{ga:.2f}s" if ga is not None
                                  else "\u2014 leader", fg=RED)
                self.behind.config(text=f"{nb}   -{gb:.2f}s" if gb is not None
                                   else "\u2014 last", fg=GREEN)
        if st:
            ers_mode = ("Boost" if packet_format == 2026 and st[20] == 3
                        else ERS_MODE.get(st[20], "?"))
            ers_pct = max(0.0, min(100.0, st[19] / 4_000_000 * 100))
            self.ers.config(text=f"ERS {ers_pct:3.0f}%  "
                                 f"[{ers_mode}]")
            self.fuel.config(text=f"FUEL {st[5]:.2f} kg  ({st[7]:+.2f} laps)")

        if self.pace.feed(lap):
            self.spark.draw(self.pace.laps)
        m, c = self.pace.message()
        self.pmsg.config(text=m, fg=c)
        tyre_summary, pit_summary = self.eng.summary(sess)
        safety_text = {1: "SC", 2: "VSC", 3: "FORMATION"}.get(
            sess.get("safety_car"), "GREEN")
        self.strategy_line.config(
            text=f"{tyre_summary}   ·   {pit_summary}   ·   TRACK {safety_text}")

        try:
            while True:
                self.status.config(text=self.q.get_nowait(), fg=GREEN)
        except queue.Empty:
            pass
        self.root.after(50, self.tick)

    def on_close(self):
        self.rcv.running = False
        self.root.after(400, self.root.destroy)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=20777)
    ap.add_argument("--out", default="solo_reports")
    ap.add_argument("--fullscreen", action="store_true")
    a = ap.parse_args()
    base = os.path.dirname(os.path.abspath(sys.argv[0]))
    out = a.out if os.path.isabs(a.out) else os.path.join(base, a.out)
    os.makedirs(out, exist_ok=True)

    shared = Shared()
    q = queue.Queue()
    rcv = SoloReceiver(shared, a.port, out, q)
    rcv.start()
    enable_high_dpi()
    root = tk.Tk()
    configure_tk_scaling(root)
    apply_app_icon(root)
    SoloApp(root, shared, rcv, q, out, a.fullscreen)
    root.mainloop()
    rcv.running = False
    time.sleep(0.5)


if __name__ == "__main__":
    main()
