#!/usr/bin/env python3
"""Premium in-app live strategy, setup and AI race-engineer workspace."""

from __future__ import annotations

import json
import os
import queue
import threading
import tkinter as tk
from tkinter import ttk
from collections import deque

from f1_ai_engineer import DEFAULT_MODEL, OpenAIRaceEngineer, AIEngineerError
from f1_setup_library import get_setup
from f1_strategy import Scenario, StrategyEngine, scenario_from_context, format_race_time
from f1_theme import (BG, BG_DEEP, SIDEBAR_DARK, PANEL, PANEL_2, PANEL_SOFT,
                      CARD, CARD_ALT, EDGE, TEXT, MUTED, PINK, HOT, GOLD,
                      GREEN, CYAN, RED, apply_ttk, button)
from f1_ui import apply_app_icon


FUEL_MAP = {0: "LEAN", 1: "STANDARD", 2: "RICH", 3: "MAX"}
ERS_MAP = {0: "NONE", 1: "MEDIUM", 2: "HOTLAP", 3: "BOOST"}


def _fmt(value, suffix="", digits=0, empty="--"):
    if value is None:
        return empty
    try:
        return f"{float(value):.{digits}f}{suffix}"
    except (TypeError, ValueError):
        return f"{value}{suffix}"


class StrategyLab:
    """One-window command centre backed by live shared state or recorded data."""

    def __init__(self, parent, database, shared=None):
        self.db = database
        self.shared = shared
        self.engine = StrategyEngine()
        self.results = []
        self.snapshot = {}
        self.session_map = {}
        self._last_signature = None
        self.ai_queue = queue.Queue()
        self.ai_busy = False
        self.live_history = deque(maxlen=180)

        self.window = tk.Toplevel(parent)
        self.window.title("F1 RACE ENGINEER · LIVE STRATEGY")
        self.window.configure(bg=BG)
        self.window.geometry("1600x900")
        self.window.minsize(1250, 720)
        apply_app_icon(self.window)
        try:
            self.window.state("zoomed")
        except tk.TclError:
            pass
        apply_ttk(self.window)
        self._style()
        self._build()
        self.refresh_source()
        self._tick()

    def _style(self):
        style = ttk.Style(self.window)
        style.configure("Engineer.Treeview", background=CARD_ALT,
                        fieldbackground=CARD_ALT, foreground=TEXT,
                        rowheight=31, borderwidth=0, font=("Segoe UI", 10))
        style.configure("Engineer.Treeview.Heading", background=PANEL_2,
                        foreground=MUTED, relief="flat",
                        font=("Segoe UI", 8, "bold"))
        style.map("Engineer.Treeview", background=[("selected", PANEL_SOFT)],
                  foreground=[("selected", TEXT)])
        style.configure("Engineer.TCombobox", fieldbackground=CARD,
                        background=CARD, foreground=TEXT, arrowcolor=GOLD)
        style.map("Engineer.TCombobox", fieldbackground=[("readonly", CARD),
                                                          ("disabled", CARD)],
                  foreground=[("readonly", TEXT), ("disabled", MUTED)])

    def _build(self):
        self._build_header()
        body = tk.Frame(self.window, bg=BG)
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, minsize=250)
        body.columnconfigure(1, weight=1)
        body.columnconfigure(2, minsize=270)
        body.rowconfigure(0, weight=1)
        self._build_live_column(body)
        self._build_strategy_column(body)
        self._build_ai_column(body)

    def _build_header(self):
        head = tk.Frame(self.window, bg=PANEL_2, height=74)
        head.pack(fill="x")
        head.pack_propagate(False)
        brand = tk.Frame(head, bg=PANEL_2)
        brand.pack(side="left", padx=22, pady=4)
        tk.Label(brand, text="RACE ENGINEER", bg=PANEL_2, fg=TEXT,
                 font=("Segoe UI", 19, "bold")).pack(anchor="w")
        tk.Label(brand, text="LIVE SETUP · STRATEGY · AI CALLS", bg=PANEL_2,
                 fg=MUTED, font=("Segoe UI", 8, "bold")).pack(anchor="w")
        self.source_var = tk.StringVar()
        self.source_combo = ttk.Combobox(
            head, textvariable=self.source_var, state="readonly", width=48,
            style="Engineer.TCombobox")
        self.source_combo.pack(side="left", padx=24, ipady=5)
        self.source_combo.bind("<<ComboboxSelected>>", self._source_changed)
        self.live_badge = tk.Label(head, text="● RECORDED", bg=PANEL_2, fg=MUTED,
                                   font=("Segoe UI", 9, "bold"))
        self.live_badge.pack(side="right", padx=22)

    def _panel_title(self, parent, title, subtitle=None, color=TEXT):
        tk.Label(parent, text=title, bg=parent["bg"], fg=color,
                 font=("Segoe UI", 12, "bold")).pack(anchor="w", padx=16,
                                                       pady=(13, 1))
        if subtitle:
            tk.Label(parent, text=subtitle, bg=parent["bg"], fg=MUTED,
                     font=("Segoe UI", 8)).pack(anchor="w", padx=16,
                                                pady=(0, 7))

    def _build_live_column(self, parent):
        left = tk.Frame(parent, bg=SIDEBAR_DARK)
        left.grid(row=0, column=0, sticky="nsew")
        self._panel_title(left, "LIVE CAR STATE",
                          "Read directly from the game UDP packets", GOLD)
        strip = tk.Frame(left, bg=PANEL_SOFT)
        strip.pack(fill="x", padx=12, pady=(0, 8))
        self.track_value = tk.Label(strip, text="WAITING FOR SESSION", bg=PANEL_SOFT,
                                    fg=TEXT, font=("Segoe UI", 14, "bold"))
        self.track_value.pack(anchor="w", padx=12, pady=(9, 0))
        self.session_value = tk.Label(strip, text="--", bg=PANEL_SOFT, fg=MUTED,
                                      font=("Segoe UI", 9))
        self.session_value.pack(anchor="w", padx=12, pady=(0, 9))

        self._panel_title(left, "CURRENT MAPS", color=TEXT)
        maps = tk.Frame(left, bg=SIDEBAR_DARK)
        maps.pack(fill="x", padx=10)
        self.map_values = {}
        for index, (key, title) in enumerate((
                ("fuel_map", "FUEL"), ("ers_map", "ENERGY"),
                ("brake_bias", "BRAKE BIAS"), ("aero", "STRAIGHT MODE"))):
            box = tk.Frame(maps, bg=CARD_ALT, highlightbackground=EDGE,
                           highlightthickness=1)
            box.grid(row=index // 2, column=index % 2, sticky="nsew", padx=3, pady=3)
            maps.columnconfigure(index % 2, weight=1)
            tk.Label(box, text=title, bg=CARD_ALT, fg=MUTED,
                     font=("Segoe UI", 7, "bold")).pack(anchor="w", padx=9,
                                                        pady=(8, 1))
            value = tk.Label(box, text="--", bg=CARD_ALT, fg=TEXT,
                             font=("Segoe UI", 11, "bold"))
            value.pack(anchor="w", padx=9, pady=(0, 8))
            self.map_values[key] = value

        self.live_chart = tk.Canvas(left, height=105, bg=BG_DEEP,
                                    highlightbackground=EDGE,
                                    highlightthickness=1)
        self.live_chart.pack(fill="x", padx=12, pady=(9, 0))

        self._panel_title(left, "CURRENT GAME SETUP",
                          "Captured automatically when the garage sends it")
        self.setup_text = tk.Text(left, width=31, height=11, bg=BG_DEEP, fg=TEXT,
                                  insertbackground=TEXT, relief="flat", bd=0,
                                  padx=12, pady=10, wrap="word",
                                  font=("Consolas", 9))
        self.setup_text.pack(fill="both", expand=True, padx=12, pady=(0, 7))
        self.setup_text.config(state="disabled")
        actions = tk.Frame(left, bg=SIDEBAR_DARK)
        actions.pack(fill="x", padx=12, pady=(0, 12))
        button(actions, "COPY CURRENT SETUP", self.copy_setup, GOLD,
               dark=True).pack(side="left", fill="x", expand=True)
        self.setup_badge = tk.Label(actions, text="UDP READ-ONLY", bg=SIDEBAR_DARK,
                                    fg=MUTED, font=("Segoe UI", 7, "bold"))
        self.setup_badge.pack(side="right", padx=(9, 0))

    def _build_strategy_column(self, parent):
        center = tk.Frame(parent, bg=BG)
        center.grid(row=0, column=1, sticky="nsew", padx=14, pady=12)

        hero = tk.Frame(center, bg=PANEL, highlightbackground=GOLD,
                        highlightthickness=1)
        hero.pack(fill="x")
        text = tk.Frame(hero, bg=PANEL)
        text.pack(side="left", fill="both", expand=True, padx=18, pady=14)
        tk.Label(text, text="PRIMARY RACE CALL", bg=PANEL, fg=GOLD,
                 font=("Segoe UI", 8, "bold")).pack(anchor="w")
        self.primary_call = tk.Label(text, text="COLLECTING TELEMETRY", bg=PANEL,
                                     fg=TEXT, font=("Segoe UI", 22, "bold"),
                                     anchor="w")
        self.primary_call.pack(fill="x")
        self.primary_detail = tk.Label(text, text="", bg=PANEL, fg=MUTED,
                                       font=("Segoe UI", 9), anchor="w")
        self.primary_detail.pack(fill="x")
        button(hero, "RECALCULATE", self.run, PINK).pack(side="right", padx=16)

        controls = tk.Frame(center, bg=CARD)
        controls.pack(fill="x", pady=(9, 7))
        self.vars = {}
        fields = (("pit_loss", "PIT LOSS", "21.0"),
                  ("traffic", "TRAFFIC %", "25"),
                  ("rain", "RAIN %", "0"))
        for key, title, default in fields:
            cell = tk.Frame(controls, bg=CARD)
            cell.pack(side="left", padx=11, pady=8)
            tk.Label(cell, text=title, bg=CARD, fg=MUTED,
                     font=("Segoe UI", 7, "bold")).pack(anchor="w")
            var = tk.StringVar(value=default)
            tk.Entry(cell, textvariable=var, width=9, bg=BG_DEEP, fg=TEXT,
                     insertbackground=TEXT, relief="flat", justify="center",
                     font=("Consolas", 10)).pack(ipady=3)
            self.vars[key] = var
        self.strategy_window = tk.Label(controls, text="GAME WINDOW  --", bg=CARD,
                                        fg=CYAN, font=("Segoe UI", 9, "bold"))
        self.strategy_window.pack(side="right", padx=15)

        columns = ("rank", "plan", "stops", "time", "delta", "wear")
        self.table = ttk.Treeview(center, columns=columns, show="headings",
                                  height=9, style="Engineer.Treeview")
        for col, title, width in zip(columns,
                ("#", "PLAN", "STOPS", "PROJECTED", "DELTA", "FINISH WEAR"),
                (30, 160, 45, 86, 62, 82)):
            self.table.heading(col, text=title)
            self.table.column(col, width=width,
                              anchor="w" if col == "plan" else "center")
        self.table.pack(fill="x")
        self.table.bind("<<TreeviewSelect>>", self._selection_changed)

        lower = tk.Frame(center, bg=BG)
        lower.pack(fill="both", expand=True, pady=(8, 0))
        lower.columnconfigure(0, weight=3)
        lower.columnconfigure(1, weight=2)
        lower.rowconfigure(0, weight=1)
        self.chart = tk.Canvas(lower, bg=CARD_ALT, highlightbackground=EDGE,
                               highlightthickness=1, height=220)
        self.chart.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
        self.plan_text = tk.Text(lower, width=23, bg=CARD_ALT, fg=TEXT, relief="flat",
                                 padx=14, pady=12, wrap="word",
                                 font=("Segoe UI", 9))
        self.plan_text.grid(row=0, column=1, sticky="nsew", padx=(4, 0))
        self.plan_text.config(state="disabled")

    def _build_ai_column(self, parent):
        right = tk.Frame(parent, bg=PANEL_2)
        right.grid(row=0, column=2, sticky="nsew")
        self._panel_title(right, "AI RACE ENGINEER",
                          "Optional · live context · session-only key", PINK)

        key_box = tk.Frame(right, bg=PANEL)
        key_box.pack(fill="x", padx=14, pady=(0, 8))
        self.api_key = tk.StringVar(value=os.environ.get("OPENAI_API_KEY", ""))
        tk.Label(key_box, text="OPENAI API KEY", bg=PANEL, fg=MUTED,
                 font=("Segoe UI", 7, "bold")).pack(anchor="w", padx=11,
                                                     pady=(9, 2))
        tk.Entry(key_box, textvariable=self.api_key, show="•", bg=BG_DEEP,
                 fg=TEXT, insertbackground=TEXT, relief="flat",
                 font=("Consolas", 9)).pack(fill="x", padx=11, ipady=5)
        model_row = tk.Frame(key_box, bg=PANEL)
        model_row.pack(fill="x", padx=11, pady=8)
        tk.Label(model_row, text="MODEL", bg=PANEL, fg=MUTED,
                 font=("Segoe UI", 7, "bold")).pack(side="left")
        self.model = tk.StringVar(value=DEFAULT_MODEL)
        ttk.Combobox(model_row, textvariable=self.model, state="readonly",
                     values=("gpt-5.6-luna", "gpt-5.6-terra", "gpt-5.6-sol"),
                     width=18, style="Engineer.TCombobox").pack(side="right")
        tk.Label(key_box, text="The key is never saved by this app.", bg=PANEL,
                 fg=MUTED, font=("Segoe UI", 7)).pack(anchor="w", padx=11,
                                                      pady=(0, 8))

        self.question = tk.StringVar(value="What should I do over the next five laps?")
        tk.Entry(right, textvariable=self.question, bg=BG_DEEP, fg=TEXT,
                 insertbackground=TEXT, relief="flat",
                 font=("Segoe UI", 9)).pack(fill="x", padx=14, ipady=7)
        self.ask_button = button(right, "ASK WITH LIVE TELEMETRY", self.ask_ai, PINK)
        self.ask_button.pack(fill="x", padx=14, pady=8)

        answer = tk.Frame(right, bg=CARD_ALT, highlightbackground=PINK,
                          highlightthickness=1)
        answer.pack(fill="both", expand=True, padx=14, pady=(0, 8))
        tk.Label(answer, text="ENGINEER RESPONSE", bg=CARD_ALT, fg=PINK,
                 font=("Segoe UI", 8, "bold")).pack(anchor="w", padx=13,
                                                     pady=(12, 4))
        self.ai_text = tk.Text(answer, width=31, bg=CARD_ALT, fg=TEXT, relief="flat",
                               padx=13, pady=8, wrap="word",
                               font=("Segoe UI", 11), spacing1=4, spacing3=5)
        self.ai_text.pack(fill="both", expand=True)
        self.ai_text.insert("1.0", "Add an API key, then ask for a contextual race call.\n\n"
                            "Deterministic strategy remains available without AI.")
        self.ai_text.config(state="disabled")
        self.token_label = tk.Label(right, text="TOKENS  0 IN · 0 OUT", bg=PANEL_2,
                                    fg=MUTED, font=("Consolas", 8))
        self.token_label.pack(anchor="e", padx=16, pady=(0, 12))

    # -- data -------------------------------------------------------------
    def refresh_source(self):
        if self.shared is not None:
            self.source_combo["values"] = ("LIVE GAME TELEMETRY",)
            self.source_var.set("LIVE GAME TELEMETRY")
            self.source_combo.config(state="disabled")
            self.live_badge.config(text="● LIVE LINK", fg=GREEN)
            self._load_live(force=True)
            return
        rows = self.db.list_sessions(200) if self.db else []
        labels = []
        for row in rows:
            label = (f"#{row['id']}  {(row.get('started_at') or '')[:10]}  "
                     f"{row.get('track_name') or '--'}  "
                     f"{row.get('session_label') or row.get('session_type') or '--'}")
            labels.append(label)
            self.session_map[label] = row["id"]
        self.source_combo["values"] = labels or ("NO RECORDED SESSION",)
        self.source_var.set((labels or ["NO RECORDED SESSION"])[0])
        self._source_changed()

    def _source_changed(self, _event=None):
        session_id = self.session_map.get(self.source_var.get())
        if not session_id or not self.db:
            return
        context = self.db.strategy_context(session_id)
        self.snapshot = self._snapshot_from_context(context, session_id)
        self._render_snapshot()
        self.run()

    def _snapshot_from_context(self, context, session_id=None):
        latest = dict(context.get("latest") or {})
        setup = self.db.session_setup(session_id) if session_id and self.db else {}
        scenario = scenario_from_context(context)
        return {"live": False, "session": context, "latest": latest,
                "setup": setup, "scenario": scenario,
                "damage": {}, "maps": {
                    "fuel": "RECORDED", "ers": "RECORDED",
                    "brake_bias": setup.get("brake_bias"), "aero": "RECORDED"}}

    def _live_data(self):
        if self.shared is None:
            return None
        with self.shared.lock:
            p = self.shared.p1
            return (dict(self.shared.session), p.tel, p.lap, p.status, p.dmg,
                    dict(p.setup or {}), p.best_lap_ms, self.shared.packet_format,
                    self.shared.last_packet_time)

    def _load_live(self, force=False):
        data = self._live_data()
        if not data:
            return
        sess, tel, lap, st, dmg, setup, best_ms, packet_format, last_packet = data
        signature = (sess.get("track"), sess.get("type"), lap[14] if lap else None,
                     st[14] if st else None, st[15] if st else None,
                     sess.get("safety_car"), sess.get("weather"), bool(setup))
        wears = list(dmg[:4]) if dmg else []
        profile = self.db.get_profile(sess.get("track")) if self.db else {}
        fuel_rate = profile.get("fuel_per_lap") or 1.8
        wear_rate = profile.get("wear_per_lap") or 1.6
        total = sess.get("laps") or 58
        current = lap[14] if lap else 1
        compound = ({16: "Soft", 17: "Medium", 18: "Hard", 7: "Intermediate",
                     8: "Wet"}.get(st[14], "Medium") if st else "Medium")
        scenario = Scenario(
            total_laps=total, current_lap=current,
            base_lap_seconds=max(30.0, (best_ms or 90_000) / 1000.0),
            current_compound=compound,
            current_wear=sum(wears) / len(wears) if wears else 5.0,
            fuel_kg=st[5] if st else max(5, (total-current+1)*fuel_rate),
            fuel_per_lap=fuel_rate, wear_per_lap=wear_rate,
            pit_loss=float(self.vars["pit_loss"].get() or 21),
            traffic=float(self.vars["traffic"].get() or 25) / 100,
            rain=float(self.vars["rain"].get() or (sess.get("weather") or 0)*20) / 100,
            safety_mode={1: "Safety Car", 2: "VSC"}.get(
                sess.get("safety_car"), "Green"),
            safety_laps=2 if sess.get("safety_car") in (1, 2) else 0,
            consistency_seconds=(profile.get("pace_consistency_ms") or 500)/1000,
        ).normalized()
        maps = {
            "fuel": FUEL_MAP.get(st[2], str(st[2])) if st else "--",
            "ers": ERS_MAP.get(st[20], str(st[20])) if st else "--",
            "brake_bias": st[3] if st else setup.get("brake_bias"),
            "aero": "ACTIVE" if tel and tel[7] else "CORNER MODE",
        }
        damage = {}
        if dmg:
            damage = {"tyre_damage": max(dmg[4:8]),
                      "front_wing_left": dmg[16], "front_wing_right": dmg[17],
                      "rear_wing": dmg[18], "floor": dmg[19],
                      "diffuser": dmg[20], "sidepod": dmg[21]}
        self.snapshot = {
            "live": True, "session": sess, "telemetry": {
                "speed_kmh": tel[0] if tel else None,
                "throttle": tel[1] if tel else None,
                "brake": tel[3] if tel else None,
                "gear": tel[5] if tel else None,
                "lap": current, "position": lap[13] if lap else None,
                "compound": compound, "tyre_age": st[15] if st else None,
                "tyre_wear": wears, "fuel_kg": st[5] if st else None,
                "fuel_delta_laps": st[7] if st else None,
                "battery_pct": st[19]/4_000_000*100 if st else None,
            }, "setup": setup, "scenario": scenario, "damage": damage,
            "maps": maps, "packet_format": packet_format,
            "strategy": {"ideal_pit_lap": sess.get("pit_ideal_lap"),
                         "latest_pit_lap": sess.get("pit_latest_lap"),
                         "rejoin_position": sess.get("pit_rejoin_position")}}
        self.live_history.append((
            self.snapshot["telemetry"].get("battery_pct") or 0,
            sum(wears) / len(wears) if wears else 0,
            self.snapshot["telemetry"].get("speed_kmh") or 0))
        self._render_snapshot()
        self._draw_live_chart()
        if force or signature != self._last_signature:
            self._last_signature = signature
            self.run()

    def _render_snapshot(self):
        snap = self.snapshot
        session = snap.get("session") or {}
        live = snap.get("live")
        self.track_value.config(text=(session.get("track") or
                                     session.get("track_name") or "NO SESSION").upper())
        label = session.get("type") or session.get("session_label") or "--"
        length = session.get("session_length") or ""
        self.session_value.config(text=f"{label}  ·  {length}".rstrip(" ·"))
        maps = snap.get("maps") or {}
        self.map_values["fuel_map"].config(text=str(maps.get("fuel", "--")))
        self.map_values["ers_map"].config(text=str(maps.get("ers", "--")),
                                           fg=GREEN if maps.get("ers") == "BOOST" else TEXT)
        self.map_values["brake_bias"].config(
            text=_fmt(maps.get("brake_bias"), "%"))
        self.map_values["aero"].config(text=str(maps.get("aero", "--")),
                                        fg=GREEN if maps.get("aero") == "ACTIVE" else TEXT)
        self._render_setup(snap.get("setup") or {}, session.get("track") or
                           session.get("track_name"))
        strategy = snap.get("strategy") or {}
        ideal, latest = strategy.get("ideal_pit_lap"), strategy.get("latest_pit_lap")
        window = f"GAME WINDOW  L{ideal}–{latest}" if ideal and latest else "GAME WINDOW  LEARNING"
        self.strategy_window.config(text=window)
        self.live_badge.config(text="● LIVE LINK" if live else "● RECORDED",
                               fg=GREEN if live else MUTED)

    def _render_setup(self, setup, track):
        baseline = get_setup(track) if track else None
        lines = []
        if setup:
            groups = (
                ("AERO", ("front_wing", "rear_wing")),
                ("DIFFERENTIAL", ("on_throttle_diff", "off_throttle_diff")),
                ("SUSPENSION", ("front_suspension", "rear_suspension",
                                "front_anti_roll_bar", "rear_anti_roll_bar")),
                ("RIDE HEIGHT", ("front_suspension_height", "rear_suspension_height")),
                ("BRAKES", ("brake_pressure", "brake_bias", "engine_braking")),
                ("PRESSURES", ("front_left_pressure", "front_right_pressure",
                               "rear_left_pressure", "rear_right_pressure")),
            )
            for title, keys in groups:
                values = [setup.get(key) for key in keys]
                lines.append(f"{title:<13} " + " / ".join(
                    "--" if value is None else f"{value:g}" if isinstance(value, float)
                    else str(value) for value in values))
        else:
            lines.append("No setup packet received yet.\nOpen the garage setup screen in game.")
        if baseline:
            lines.extend(("", "PDF BASELINE", f"WINGS         {baseline['front_wing']} / {baseline['rear_wing']}",
                          f"STRATEGY      {baseline['pdf_strategy']}"))
        self.setup_text.config(state="normal")
        self.setup_text.delete("1.0", "end")
        self.setup_text.insert("1.0", "\n".join(lines))
        self.setup_text.config(state="disabled")
        self.setup_badge.config(text="LIVE UDP + PDF" if setup and baseline else
                                "UDP READ-ONLY")

    def _draw_live_chart(self):
        c = self.live_chart
        c.delete("all")
        c.update_idletasks()
        width, height = max(250, c.winfo_width()), max(90, c.winfo_height())
        c.create_text(10, 8, anchor="nw", text="LIVE ENERGY / TYRE WEAR",
                      fill=MUTED, font=("Segoe UI", 7, "bold"))
        if len(self.live_history) < 2:
            c.create_text(width/2, height/2, text="COLLECTING LIVE SAMPLES",
                          fill=MUTED, font=("Segoe UI", 8))
            return
        left, right, top, bottom = 10, width-10, 28, height-12
        c.create_line(left, bottom, right, bottom, fill=EDGE)
        count = len(self.live_history)-1
        for series, color in ((0, GREEN), (1, PINK)):
            points = []
            for i, sample in enumerate(self.live_history):
                points.extend((left+(right-left)*i/count,
                               bottom-(bottom-top)*max(0, min(100, sample[series]))/100))
            c.create_line(*points, fill=color, width=2, smooth=True)
        c.create_text(right, top, anchor="ne", text="ENERGY", fill=GREEN,
                      font=("Segoe UI", 7, "bold"))
        c.create_text(right, top+14, anchor="ne", text="WEAR", fill=PINK,
                      font=("Segoe UI", 7, "bold"))

    # -- strategy ---------------------------------------------------------
    def run(self):
        scenario = self.snapshot.get("scenario")
        if not scenario:
            return
        try:
            scenario.pit_loss = float(self.vars["pit_loss"].get())
            scenario.traffic = float(self.vars["traffic"].get()) / 100
            scenario.rain = float(self.vars["rain"].get()) / 100
            self.results = self.engine.generate(scenario, max_results=12)
        except (TypeError, ValueError):
            return
        self.table.delete(*self.table.get_children())
        for rank, result in enumerate(self.results, 1):
            self.table.insert("", "end", iid=str(rank-1), values=(
                rank, result.label, len(result.stops), format_race_time(result.total_seconds),
                "BEST" if rank == 1 else f"+{result.delta:.2f}s",
                f"{result.finish_wear:.1f}%"))
        if self.results:
            self.table.selection_set("0")
            self._show_result(self.results[0])

    def _selection_changed(self, _event=None):
        selected = self.table.selection()
        if selected:
            self._show_result(self.results[int(selected[0])])

    def _show_result(self, result):
        self.primary_call.config(text=result.label)
        self.primary_detail.config(
            text=f"{format_race_time(result.total_seconds)} projected · "
                 f"finish wear {result.finish_wear:.1f}% · "
                 f"uncertainty ±{result.confidence_seconds:.1f}s")
        lines = ["SELECTED PLAN", "", result.label, ""]
        if result.stops:
            lines += [f"Lap {lap}: fit {compound}" for lap, compound in
                      zip(result.stops, result.compounds)]
        else:
            lines.append("Stay out to the finish")
        damage = self.snapshot.get("damage") or {}
        if max(damage.get("front_wing_left", 0),
               damage.get("front_wing_right", 0)) >= 15:
            lines += ["", "DAMAGE OVERRIDE", "Replace front wing at the next stop"]
        self.plan_text.config(state="normal")
        self.plan_text.delete("1.0", "end")
        self.plan_text.insert("1.0", "\n".join(lines))
        self.plan_text.config(state="disabled")
        self._draw_chart(result)

    def _draw_chart(self, result):
        c = self.chart
        c.delete("all")
        c.update_idletasks()
        w, h = max(300, c.winfo_width()), max(180, c.winfo_height())
        c.create_text(16, 15, anchor="nw", text="PROJECTED STINT WEAR",
                      fill=MUTED, font=("Segoe UI", 8, "bold"))
        if not result.wear_trace:
            return
        left, right, top, bottom = 18, w-18, 43, h-23
        c.create_line(left, bottom, right, bottom, fill=EDGE)
        points = []
        count = max(1, len(result.wear_trace)-1)
        for i, wear in enumerate(result.wear_trace):
            x = left + (right-left)*i/count
            y = bottom - (bottom-top)*min(100, wear)/100
            points += [x, y]
        if len(points) >= 4:
            c.create_line(*points, fill=PINK, width=3, smooth=True)
        for stop in result.stops:
            scenario = self.snapshot.get("scenario")
            i = stop - scenario.current_lap
            if 0 <= i < len(result.wear_trace):
                x = left + (right-left)*i/count
                c.create_line(x, top, x, bottom, fill=GOLD, dash=(4, 4))
                c.create_text(x+4, top+2, anchor="nw", text=f"PIT L{stop}",
                              fill=GOLD, font=("Segoe UI", 7, "bold"))

    def copy_setup(self):
        setup = self.snapshot.get("setup") or {}
        if not setup:
            return
        text = "\n".join(f"{key}: {value}" for key, value in setup.items()
                         if key != "captured_at")
        self.window.clipboard_clear()
        self.window.clipboard_append(text)
        self.setup_badge.config(text="COPIED", fg=GREEN)

    # -- AI ---------------------------------------------------------------
    def _ai_snapshot(self):
        snap = dict(self.snapshot)
        scenario = snap.pop("scenario", None)
        if scenario:
            snap["scenario"] = vars(scenario)
        if self.results:
            best = self.results[0]
            snap["calculated_best_plan"] = {
                "label": best.label, "stops": best.stops,
                "compounds": best.compounds,
                "projected_seconds": round(best.total_seconds, 2),
                "finish_wear": round(best.finish_wear, 1)}
        return snap

    def ask_ai(self):
        if self.ai_busy:
            return
        client = OpenAIRaceEngineer(self.api_key.get(), self.model.get())
        if not client.configured:
            self._set_ai_text("Add an OpenAI API key above. It is used only for this session and is never saved.")
            return
        self.ai_busy = True
        self.ask_button.config(text="ENGINEER THINKING…", state="disabled")
        snapshot, question = self._ai_snapshot(), self.question.get().strip()

        def work():
            try:
                self.ai_queue.put(("ok", client.advise(snapshot, question)))
            except AIEngineerError as exc:
                self.ai_queue.put(("error", str(exc)))
        threading.Thread(target=work, daemon=True).start()

    def _set_ai_text(self, text):
        self.ai_text.config(state="normal")
        self.ai_text.delete("1.0", "end")
        self.ai_text.insert("1.0", text)
        self.ai_text.config(state="disabled")

    def _poll_ai(self):
        try:
            status, payload = self.ai_queue.get_nowait()
        except queue.Empty:
            return
        self.ai_busy = False
        self.ask_button.config(text="ASK WITH LIVE TELEMETRY", state="normal")
        if status == "ok":
            self._set_ai_text(payload["text"])
            self.token_label.config(
                text=f"{payload['model']}  ·  TOKENS {payload['input_tokens']} IN · "
                     f"{payload['output_tokens']} OUT · {payload['total_tokens']} TOTAL")
        else:
            self._set_ai_text("OPENAI ERROR\n\n" + payload)

    def _tick(self):
        if not self.window.winfo_exists():
            return
        if self.shared is not None:
            self._load_live()
        self._poll_ai()
        self.window.after(500, self._tick)
