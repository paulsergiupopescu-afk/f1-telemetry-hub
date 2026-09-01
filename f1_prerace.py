#!/usr/bin/env python3
"""High-resolution pre-race setup and strategy command centre."""

import tkinter as tk
from tkinter import ttk

from f1_setup_library import tracks, get_setup, ALIASES
from f1_strategy import Scenario, StrategyEngine, format_race_time
from f1_theme import (BG, BG_DEEP, SIDEBAR, SIDEBAR_DARK, PANEL, PANEL_2,
                      PANEL_SOFT, CARD, CARD_ALT, EDGE, TEXT, MUTED, PINK, HOT,
                      GOLD, GREEN, CYAN, RED, apply_ttk, rounded_rectangle,
                      button, card, section_label)


class PreRaceStudio:
    def __init__(self, parent, database):
        self.db = database
        self.engine = StrategyEngine()
        self.setup = None
        self.results = []
        self.window = tk.Toplevel(parent)
        self.window.title("F1 PRE-RACE COMMAND CENTRE")
        self.window.configure(bg=BG)
        self.window.geometry("1600x900")
        self.window.minsize(1250, 720)
        try:
            self.window.state("zoomed")
        except tk.TclError:
            pass
        apply_ttk(self.window)
        self._build()
        self.track_list.selection_set(0)
        self._track_selected()

    def _build(self):
        top = tk.Frame(self.window, bg=PANEL_2, height=62)
        top.pack(fill="x")
        top.pack_propagate(False)
        tk.Label(top, text="F1 26  /  PRE-RACE", bg=PANEL_2, fg=TEXT,
                 font=("Segoe UI", 18, "bold")).pack(side="left", padx=24)
        tk.Label(top, text="SETUP  •  STRATEGY  •  PROJECTED RACE TIME",
                 bg=PANEL_2, fg=MUTED, font=("Segoe UI", 10, "bold")).pack(side="left")
        tk.Label(top, text="MATT212 BASELINE + YOUR TELEMETRY",
                 bg=PANEL_2, fg=GOLD, font=("Segoe UI", 9, "bold")).pack(
                     side="right", padx=24)

        body = tk.Frame(self.window, bg=BG)
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, minsize=235)
        body.columnconfigure(1, weight=1)
        body.columnconfigure(2, minsize=330)
        body.rowconfigure(0, weight=1)
        self._build_sidebar(body)
        self._build_center(body)
        self._build_intelligence(body)

    def _build_sidebar(self, parent):
        side = tk.Frame(parent, bg=SIDEBAR_DARK)
        side.grid(row=0, column=0, sticky="nsew")
        tk.Label(side, text="RACE WEEKEND", bg=SIDEBAR_DARK, fg=TEXT,
                 font=("Segoe UI", 16, "bold")).pack(anchor="w", padx=18, pady=(22, 2))
        tk.Label(side, text="Choose your circuit", bg=SIDEBAR_DARK, fg=MUTED,
                 font=("Segoe UI", 9)).pack(anchor="w", padx=18, pady=(0, 12))
        self.track_list = tk.Listbox(side, bg=SIDEBAR_DARK, fg=TEXT,
                                     selectbackground=PANEL_SOFT,
                                     selectforeground=TEXT, relief="flat", bd=0,
                                     highlightthickness=0,
                                     font=("Segoe UI", 10), activestyle="none",
                                     exportselection=False)
        for name in tracks():
            self.track_list.insert("end", f"  {name}")
        self.track_list.pack(fill="both", expand=True, padx=9)
        self.track_list.bind("<<ListboxSelect>>", self._track_selected)
        foot = tk.Frame(side, bg=BG_DEEP)
        foot.pack(fill="x")
        tk.Label(foot, text="PRE-RACE MODE", bg=BG_DEEP, fg=GOLD,
                 font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=18, pady=(12, 2))
        tk.Label(foot, text="Plan before joining the grid",
                 bg=BG_DEEP, fg=MUTED, font=("Segoe UI", 8)).pack(
                     anchor="w", padx=18, pady=(0, 12))

    def _build_center(self, parent):
        center = tk.Frame(parent, bg=BG)
        center.grid(row=0, column=1, sticky="nsew", padx=16, pady=14)
        self.hero = tk.Canvas(center, bg=BG, highlightthickness=0, height=150)
        self.hero.pack(fill="x")
        self.hero.bind("<Configure>", lambda _e: self._draw_hero())

        setup_head = tk.Frame(center, bg=BG)
        setup_head.pack(fill="x", pady=(12, 5))
        tk.Label(setup_head, text="BASE SETUP", bg=BG, fg=TEXT,
                 font=("Segoe UI", 15, "bold")).pack(side="left")
        self.learned_badge = tk.Label(setup_head, text="PDF BASELINE", bg=PANEL_2,
                                      fg=GOLD, padx=10, pady=4,
                                      font=("Segoe UI", 8, "bold"))
        self.learned_badge.pack(side="left", padx=10)
        button(setup_head, "COPY SETUP", self.copy_setup, GOLD, dark=True).pack(side="right")

        grid = tk.Frame(center, bg=BG)
        grid.pack(fill="x")
        for col in range(3):
            grid.columnconfigure(col, weight=1, uniform="setup")
        self.setup_cards = {}
        cards = (("aero", "AERODYNAMICS"), ("transmission", "TRANSMISSION"),
                 ("geometry", "SUSPENSION GEOMETRY"),
                 ("suspension", "SUSPENSION"), ("brakes", "BRAKES"),
                 ("tyres", "TYRE PRESSURES"))
        for index, (key, title) in enumerate(cards):
            panel = card(grid, bg=CARD_ALT)
            panel.grid(row=index // 3, column=index % 3, sticky="nsew", padx=4, pady=4)
            tk.Label(panel, text=title, bg=CARD_ALT, fg=MUTED,
                     font=("Segoe UI", 8, "bold")).pack(anchor="w", padx=12, pady=(9, 2))
            value = tk.Label(panel, text="--", bg=CARD_ALT, fg=TEXT,
                             justify="left", anchor="w", font=("Consolas", 11, "bold"))
            value.pack(fill="x", padx=12, pady=(0, 10))
            self.setup_cards[key] = value

        strategy_head = tk.Frame(center, bg=BG)
        strategy_head.pack(fill="x", pady=(12, 5))
        tk.Label(strategy_head, text="STRATEGY PROJECTION", bg=BG, fg=TEXT,
                 font=("Segoe UI", 15, "bold")).pack(side="left")
        self.controls = {}
        control_spec = (("distance", "DISTANCE", ("25%", "35%", "50%", "100%"), "50%"),
                        ("compound", "START TYRE", ("Soft", "Medium", "Hard"), "Medium"),
                        ("rain", "RAIN %", None, "0"),
                        ("traffic", "TRAFFIC %", None, "25"),
                        ("pit_loss", "PIT LOSS", None, "21"))
        controls = tk.Frame(center, bg=PANEL, highlightbackground=EDGE,
                            highlightthickness=1)
        controls.pack(fill="x", pady=(0, 6))
        for key, label, choices, default in control_spec:
            unit = tk.Frame(controls, bg=PANEL)
            unit.pack(side="left", padx=10, pady=8)
            tk.Label(unit, text=label, bg=PANEL, fg=MUTED,
                     font=("Segoe UI", 8, "bold")).pack(anchor="w")
            var = tk.StringVar(value=default)
            if choices:
                widget = ttk.Combobox(unit, textvariable=var, values=choices,
                                      state="readonly", width=10, style="F1.TCombobox")
            else:
                widget = tk.Entry(unit, textvariable=var, bg=CARD_ALT, fg=TEXT,
                                  insertbackground=TEXT, relief="flat", width=8,
                                  justify="center", font=("Consolas", 10))
            widget.pack(ipady=4)
            self.controls[key] = var
        self.safety = tk.StringVar(value="Green")
        unit = tk.Frame(controls, bg=PANEL)
        unit.pack(side="left", padx=10, pady=8)
        tk.Label(unit, text="TRACK STATE", bg=PANEL, fg=MUTED,
                 font=("Segoe UI", 8, "bold")).pack(anchor="w")
        ttk.Combobox(unit, textvariable=self.safety,
                     values=("Green", "Safety Car", "VSC"), state="readonly",
                     width=12, style="F1.TCombobox").pack(ipady=4)
        button(controls, "CALCULATE", self.calculate, PINK).pack(side="right", padx=12)

        columns = ("rank", "plan", "stops", "time", "delta", "wear")
        self.result_table = ttk.Treeview(center, columns=columns, show="headings",
                                         height=6, style="F1.Treeview")
        for col, title, width in zip(columns,
                ("#", "PLAN", "STOPS", "PROJECTED TIME", "DELTA", "FINISH WEAR"),
                (40, 270, 60, 130, 90, 110)):
            self.result_table.heading(col, text=title)
            self.result_table.column(col, width=width,
                                     anchor="w" if col == "plan" else "center")
        self.result_table.pack(fill="both", expand=True)
        self.result_table.bind("<<TreeviewSelect>>", self._result_selected)

    def _build_intelligence(self, parent):
        right = tk.Frame(parent, bg=PANEL_2)
        right.grid(row=0, column=2, sticky="nsew")
        tk.Label(right, text="RACE INTELLIGENCE", bg=PANEL_2, fg=TEXT,
                 font=("Segoe UI", 15, "bold")).pack(anchor="w", padx=18, pady=(22, 2))
        tk.Label(right, text="Your fastest projected route", bg=PANEL_2, fg=MUTED,
                 font=("Segoe UI", 9)).pack(anchor="w", padx=18)
        self.call_card = card(right, bg=PANEL_SOFT, edge=GOLD)
        self.call_card.pack(fill="x", padx=14, pady=14)
        tk.Label(self.call_card, text="PRIMARY CALL", bg=PANEL_SOFT, fg=GOLD,
                 font=("Segoe UI", 8, "bold")).pack(anchor="w", padx=14, pady=(12, 2))
        self.primary_call = tk.Label(self.call_card, text="CALCULATING...", bg=PANEL_SOFT,
                                     fg=TEXT, wraplength=270, justify="left",
                                     font=("Segoe UI", 16, "bold"))
        self.primary_call.pack(anchor="w", padx=14)
        self.primary_time = tk.Label(self.call_card, text="--:--.--", bg=PANEL_SOFT,
                                     fg=GREEN, font=("Consolas", 20, "bold"))
        self.primary_time.pack(anchor="w", padx=14, pady=(6, 12))

        self.pdf_strategy = self._info_block(right, "PDF 50% BENCHMARK")
        self.calibration = self._info_block(right, "PERSONAL CALIBRATION")
        self.selected_detail = self._info_block(right, "SELECTED PLAN")
        tk.Label(right, text="SETUP ADAPTATION", bg=PANEL_2, fg=MUTED,
                 font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=18, pady=(14, 4))
        self.setup_advice = tk.Label(right, text="Complete recorded laps to personalise this baseline.",
                                     bg=PANEL_2, fg=TEXT, justify="left",
                                     wraplength=290, font=("Segoe UI", 10))
        self.setup_advice.pack(anchor="w", padx=18)

    def _info_block(self, parent, title):
        box = card(parent, bg=CARD)
        box.pack(fill="x", padx=14, pady=5)
        tk.Label(box, text=title, bg=CARD, fg=MUTED,
                 font=("Segoe UI", 8, "bold")).pack(anchor="w", padx=12, pady=(9, 2))
        value = tk.Label(box, text="--", bg=CARD, fg=TEXT, justify="left",
                         wraplength=275, font=("Segoe UI", 10, "bold"))
        value.pack(anchor="w", padx=12, pady=(0, 9))
        return value

    def _track_selected(self, _event=None):
        selected = self.track_list.curselection()
        if not selected:
            return
        name = self.track_list.get(selected[0]).strip()
        self.setup = get_setup(name)
        if not self.setup:
            return
        self.controls["pit_loss"].set(str(self.setup["pit_loss_seconds"]))
        self._update_setup()
        self._draw_hero()
        self.calculate()

    def _profile(self):
        if not self.setup:
            return {}
        candidates = [self.setup["track"]]
        candidates += [alias for alias, target in ALIASES.items()
                       if target == self.setup["track"]]
        for name in candidates:
            profile = self.db.get_profile(name)
            if profile:
                return profile
        return {}

    def _update_setup(self):
        s = self.setup
        self.setup_cards["aero"].config(
            text=f"FRONT {s['front_wing']:>2}   REAR {s['rear_wing']:>2}")
        self.setup_cards["transmission"].config(
            text=f"ON {s['on_throttle_diff']}%   OFF {s['off_throttle_diff']}%")
        self.setup_cards["geometry"].config(
            text=f"CAMBER {s['front_camber']:.2f} / {s['rear_camber']:.2f}\n"
                 f"TOE       {s['front_toe']:.2f} / {s['rear_toe']:.2f}")
        self.setup_cards["suspension"].config(
            text=f"SUSP {s['front_suspension']} / {s['rear_suspension']}   "
                 f"ARB {s['front_anti_roll_bar']} / {s['rear_anti_roll_bar']}\n"
                 f"HEIGHT {s['front_ride_height']} / {s['rear_ride_height']}")
        self.setup_cards["brakes"].config(
            text=f"BIAS {s['brake_bias']}%   PRESSURE {s['brake_pressure']}%")
        self.setup_cards["tyres"].config(
            text=f"FRONT {s['front_left_pressure']:.1f} / {s['front_right_pressure']:.1f}\n"
                 f"REAR  {s['rear_left_pressure']:.1f} / {s['rear_right_pressure']:.1f} PSI")
        self.pdf_strategy.config(text=s["pdf_strategy"])
        profile = self._profile()
        if profile:
            self.learned_badge.config(text=f"PERSONALISED • {profile.get('laps', 0) or 0} LAPS",
                                      fg=GREEN)
            self.calibration.config(text=(
                f"Wear {profile.get('wear_per_lap') or 0:.2f}%/lap  •  "
                f"Fuel {profile.get('fuel_per_lap') or 0:.2f} kg/lap\n"
                f"Consistency ±{(profile.get('pace_consistency_ms') or 0)/1000:.2f}s"))
            advice = self.db.setup_recommendations(self.setup["track"])
            self.setup_advice.config(text=(advice[0]["title"] + "\n" + advice[0]["detail"]) if advice else "Baseline balanced.")
        else:
            self.learned_badge.config(text="PDF BASELINE", fg=GOLD)
            self.calibration.config(text="No personal laps yet • using conservative defaults")
            self.setup_advice.config(text="Complete a representative stint to adapt this setup to your driving style.")

    def _draw_hero(self):
        if not self.setup:
            return
        c = self.hero
        c.delete("all")
        width = max(700, c.winfo_width())
        rounded_rectangle(c, 0, 0, width, 145, 26, fill=PANEL_2, outline=GOLD, width=1)
        c.create_polygon(width*.55, 0, width, 0, width, 145, width*.72, 145,
                         fill=HOT, outline="")
        c.create_polygon(width*.70, 0, width*.80, 0, width*.62, 145, width*.52, 145,
                         fill=PINK, outline="")
        c.create_text(28, 28, text="F1 26 PRE-RACE PACKAGE", fill=GOLD,
                      anchor="w", font=("Segoe UI", 9, "bold"))
        c.create_text(28, 70, text=self.setup["track"].upper(), fill=TEXT,
                      anchor="w", font=("Segoe UI", 26, "bold"))
        c.create_text(30, 111, text=self.setup["pdf_strategy"], fill=MUTED,
                      anchor="w", font=("Segoe UI", 11, "bold"))

    def _distance_laps(self):
        factor = {"25%": .5, "35%": .7, "50%": 1.0, "100%": 2.0}.get(
            self.controls["distance"].get(), 1.0)
        return max(5, round(self.setup["race_laps_50"] * factor))

    def calculate(self):
        if not self.setup:
            return
        profile = self._profile()
        try:
            total = self._distance_laps()
            fuel_rate = profile.get("fuel_per_lap") or 1.8
            wear_rate = profile.get("wear_per_lap") or 1.6
            scenario = Scenario(total_laps=total, current_lap=1,
                base_lap_seconds=self.setup["baseline_lap_seconds"],
                current_compound=self.controls["compound"].get(), current_wear=0,
                fuel_kg=total * fuel_rate + .5, fuel_per_lap=fuel_rate,
                wear_per_lap=wear_rate,
                pit_loss=float(self.controls["pit_loss"].get()),
                traffic=float(self.controls["traffic"].get()) / 100,
                rain=float(self.controls["rain"].get()) / 100,
                safety_mode=self.safety.get(),
                safety_laps=3 if self.safety.get() == "Safety Car" else
                            (2 if self.safety.get() == "VSC" else 0),
                consistency_seconds=(profile.get("pace_consistency_ms") or 500)/1000)
        except ValueError:
            self.primary_call.config(text="CHECK INPUT VALUES", fg=RED)
            return
        self.results = self.engine.generate(scenario, max_results=20)
        self.result_table.delete(*self.result_table.get_children())
        for rank, result in enumerate(self.results[:8], 1):
            self.result_table.insert("", "end", iid=str(rank-1), values=(rank,
                result.label, len(result.stops), format_race_time(result.total_seconds),
                "BEST" if rank == 1 else f"+{result.delta:.2f}s",
                f"{result.finish_wear:.1f}%"))
        if self.results:
            best = self.results[0]
            call = (f"PIT LAP {best.stops[0]} • {best.compounds[0].upper()}"
                    if best.stops else "STAY OUT")
            self.primary_call.config(text=call, fg=TEXT)
            self.primary_time.config(text=format_race_time(best.total_seconds))
            self.result_table.selection_set("0")
            self._show_result(best)

    def _result_selected(self, _event=None):
        selection = self.result_table.selection()
        if selection and self.results:
            index = int(selection[0])
            if index < len(self.results):
                self._show_result(self.results[index])

    def _show_result(self, result):
        stops = ", ".join(f"L{lap} {compound}" for lap, compound in
                          zip(result.stops, result.compounds)) or "No stop"
        self.selected_detail.config(text=(
            f"{stops}\n{format_race_time(result.total_seconds)}  •  "
            f"+{result.delta:.2f}s  •  finish wear {result.finish_wear:.1f}%"))

    def copy_setup(self):
        if not self.setup:
            return
        excluded = {"source", "baseline_lap_seconds", "pit_loss_seconds", "race_laps_50"}
        text = "\n".join(f"{key.replace('_', ' ').title()}: {value}"
                         for key, value in self.setup.items() if key not in excluded)
        self.window.clipboard_clear()
        self.window.clipboard_append(text)
        self.learned_badge.config(text="COPIED TO CLIPBOARD", fg=GREEN)
