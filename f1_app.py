#!/usr/bin/env python3
"""Unified high-resolution entry point for F1 Race Command."""

import argparse
import os
import queue
import subprocess
import sys
import time
import tkinter as tk

from f1_26_split_telemetry import Shared
from f1_hub import App as SplitApp, HubReceiver
from f1_solo import SoloApp, SoloReceiver
from f1_database import TelemetryDatabase
from f1_session_studio import SessionStudio
from f1_strategy_lab import StrategyLab
from f1_prerace import PreRaceStudio
from f1_ui import (enable_high_dpi, configure_tk_scaling, apply_app_icon,
                   acquire_single_instance, release_single_instance)
from f1_theme import (BG, BG_DEEP, SIDEBAR_DARK, PANEL, PANEL_2, PANEL_SOFT,
                      CARD_ALT, TEXT, MUTED, PINK, HOT, GOLD, GREEN, apply_ttk,
                      rounded_rectangle, button as themed_button)


class UnifiedController:
    def __init__(self, root, port=20777, mode="menu", fullscreen=False):
        self.root = root
        self.port = port
        self.fullscreen = fullscreen
        self.receiver = None
        self.active_mode = None
        self.base = os.path.dirname(sys.executable if getattr(sys, "frozen", False)
                                    else os.path.abspath(__file__))
        self.database = TelemetryDatabase(os.path.join(self.base, "f1_telemetry.db"))
        if mode == "menu":
            self.show_menu()
        else:
            self.launch(mode)

    def open_studio(self):
        SessionStudio(self.root, self.database)

    def open_strategy_lab(self):
        StrategyLab(self.root, self.database)

    def open_prerace(self):
        PreRaceStudio(self.root, self.database)

    def _clear(self):
        for child in self.root.winfo_children():
            child.destroy()
        self.root.config(menu=tk.Menu(self.root))

    def show_menu(self):
        self._clear()
        self.root.title("F1 RACE COMMAND")
        self.root.configure(bg=BG)
        self.root.geometry("1480x850")
        self.root.minsize(1100, 700)
        try:
            self.root.state("zoomed")
        except tk.TclError:
            pass
        apply_ttk(self.root)

        shell = tk.Frame(self.root, bg=BG)
        shell.pack(fill="both", expand=True)
        shell.columnconfigure(0, minsize=235)
        shell.columnconfigure(1, weight=1)
        shell.columnconfigure(2, minsize=315)
        shell.rowconfigure(0, weight=1)
        self._build_sidebar(shell)
        self._build_home(shell)
        self._build_intelligence(shell)

        menu = tk.Menu(self.root)
        data = tk.Menu(menu, tearoff=False)
        data.add_command(label="Pre-Race Command Centre", command=self.open_prerace)
        data.add_command(label="Session Studio", command=self.open_studio)
        data.add_command(label="Race Engineer + AI", command=self.open_strategy_lab)
        menu.add_cascade(label="Command", menu=data)
        self.root.config(menu=menu)

    def _build_sidebar(self, shell):
        side = tk.Frame(shell, bg=SIDEBAR_DARK)
        side.grid(row=0, column=0, sticky="nsew")
        icon = getattr(self.root, "_race_command_icon", None)
        if icon:
            self.logo_small = icon.subsample(11, 11)
            tk.Label(side, image=self.logo_small, bg=SIDEBAR_DARK).pack(
                anchor="w", padx=18, pady=(16, 0))
        else:
            tk.Label(side, text="RC", bg=SIDEBAR_DARK, fg=GOLD,
                     font=("Segoe UI", 30, "bold")).pack(anchor="w", padx=22, pady=(24, 0))
        tk.Label(side, text="RACE COMMAND", bg=SIDEBAR_DARK, fg=TEXT,
                 font=("Segoe UI", 13, "bold")).pack(anchor="w", padx=22)
        tk.Label(side, text="EXPLORE", bg=SIDEBAR_DARK, fg=MUTED,
                 font=("Segoe UI", 8, "bold")).pack(anchor="w", padx=22, pady=(28, 6))
        links = (("●  Home", lambda: None, True),
                 ("◈  Pre-Race", self.open_prerace, False),
                 ("▲  Solo Engineer", lambda: self.launch("solo"), False),
                 ("◆  Split Screen", lambda: self.launch("split"), False),
                 ("▦  Session Studio", self.open_studio, False),
                 ("⌁  Race Engineer", self.open_strategy_lab, False))
        for label, command, active in links:
            nav = tk.Button(side, text=label, command=command, anchor="w",
                            bg=PANEL_SOFT if active else SIDEBAR_DARK, fg=TEXT,
                            activebackground=PANEL_SOFT, activeforeground=TEXT,
                            relief="flat", bd=0, padx=18, pady=10,
                            cursor="hand2",
                            font=("Segoe UI", 10, "bold" if active else "normal"))
            nav.pack(fill="x", padx=10, pady=2)
        status = tk.Frame(side, bg=BG_DEEP)
        status.pack(side="bottom", fill="x")
        tk.Label(status, text="●  TELEMETRY READY", bg=BG_DEEP, fg=GREEN,
                 font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=18, pady=(12, 2))
        tk.Label(status, text=f"UDP AUTO  •  PORT {self.port}", bg=BG_DEEP, fg=MUTED,
                 font=("Consolas", 8)).pack(anchor="w", padx=18, pady=(0, 12))

    def _build_home(self, shell):
        center = tk.Frame(shell, bg=BG)
        center.grid(row=0, column=1, sticky="nsew", padx=18, pady=16)
        head = tk.Frame(center, bg=BG)
        head.pack(fill="x", pady=(2, 12))
        tk.Label(head, text="Welcome to Race Command", bg=BG, fg=TEXT,
                 font=("Segoe UI", 24, "bold")).pack(side="left")
        tk.Label(head, text="F1 25 / F1 26", bg=PANEL_2, fg=GOLD,
                 padx=12, pady=5, font=("Segoe UI", 8, "bold")).pack(side="right")

        hero = tk.Canvas(center, height=190, bg=BG, highlightthickness=0)
        hero.pack(fill="x")

        def draw_hero(_event=None):
            hero.delete("all")
            width = max(650, hero.winfo_width())
            rounded_rectangle(hero, 0, 0, width, 184, 26,
                              fill=PANEL_2, outline=GOLD, width=1)
            hero.create_polygon(width*.55, 0, width, 0, width, 184,
                                width*.75, 184, fill=HOT, outline="")
            hero.create_polygon(width*.72, 0, width*.84, 0, width*.62, 184,
                                width*.50, 184, fill=PINK, outline="")
            hero.create_text(28, 34, text="BUILD YOUR RACE BEFORE THE LIGHTS GO OUT",
                             fill=GOLD, anchor="w", font=("Segoe UI", 9, "bold"))
            hero.create_text(28, 79, text="Pre-Race Command Centre", fill=TEXT,
                             anchor="w", font=("Segoe UI", 25, "bold"))
            hero.create_text(30, 116,
                             text="PDF setups  •  personal telemetry  •  projected strategies",
                             fill=MUTED, anchor="w", font=("Segoe UI", 11))
            pill = rounded_rectangle(hero, 28, 140, 205, 174, 14,
                                     fill=GOLD, outline="")
            caption = hero.create_text(116, 157, text="OPEN PRE-RACE", fill=BG_DEEP,
                                       font=("Segoe UI", 9, "bold"))
            for item in (pill, caption):
                hero.tag_bind(item, "<Button-1>", lambda _e: self.open_prerace())
                hero.tag_bind(item, "<Enter>", lambda _e: hero.config(cursor="hand2"))
        hero.bind("<Configure>", draw_hero)

        tk.Label(center, text="LIVE MODES", bg=BG, fg=TEXT,
                 font=("Segoe UI", 15, "bold")).pack(anchor="w", pady=(15, 6))
        cards = tk.Frame(center, bg=BG)
        cards.pack(fill="both", expand=True)
        cards.columnconfigure(0, weight=1, uniform="mode")
        cards.columnconfigure(1, weight=1, uniform="mode")
        cards.rowconfigure(0, weight=1)
        self._mode_card(cards, 0, "SOLO ENGINEER", PINK,
                        "Live delta, race intelligence, active aero, tyres and personalised strategy.",
                        lambda: self.launch("solo"))
        self._mode_card(cards, 1, "SPLIT SCREEN", GOLD,
                        "Two-driver gap, pace comparison, complete car state and shared reports.",
                        lambda: self.launch("split"))

    def _mode_card(self, parent, column, title, accent, description, command):
        panel = tk.Frame(parent, bg=CARD_ALT, highlightbackground=accent,
                         highlightthickness=1, cursor="hand2")
        panel.grid(row=0, column=column, sticky="nsew",
                   padx=(0, 8) if column == 0 else (8, 0))
        tk.Label(panel, text=title, font=("Segoe UI", 18, "bold"),
                 fg=accent, bg=CARD_ALT).pack(anchor="w", padx=20, pady=(22, 8))
        tk.Label(panel, text=description, font=("Segoe UI", 10), fg=TEXT,
                 bg=CARD_ALT, justify="left", wraplength=330).pack(anchor="w", padx=20)
        feature_names = (("PERSONAL DELTA", "TYRE LIFE", "RACE CALLS", "CAR HEALTH")
                         if "SOLO" in title else
                         ("LIVE GAP", "DRIVER CARDS", "PACE COMPARE", "CHAMPIONSHIP"))
        feature_grid = tk.Frame(panel, bg=CARD_ALT)
        feature_grid.pack(fill="x", padx=16, pady=(18, 2))
        for index, feature in enumerate(feature_names):
            badge = tk.Label(feature_grid, text=feature, bg=PANEL,
                             fg=accent, padx=10, pady=7,
                             font=("Segoe UI", 8, "bold"))
            badge.grid(row=index // 2, column=index % 2, sticky="ew", padx=3, pady=3)
            feature_grid.columnconfigure(index % 2, weight=1)
        themed_button(panel, "OPEN MODE", command, accent).pack(
            anchor="w", padx=20, pady=20)
        panel.bind("<Button-1>", lambda _e: command())

    def _build_intelligence(self, shell):
        right = tk.Frame(shell, bg=PANEL_2)
        right.grid(row=0, column=2, sticky="nsew")
        tk.Label(right, text="RACE INTELLIGENCE", bg=PANEL_2, fg=TEXT,
                 font=("Segoe UI", 14, "bold")).pack(anchor="w", padx=18, pady=(24, 2))
        tk.Label(right, text="Your latest recorded work", bg=PANEL_2, fg=MUTED,
                 font=("Segoe UI", 9)).pack(anchor="w", padx=18, pady=(0, 12))
        sessions = self.database.list_sessions(5)
        if sessions:
            for row in sessions:
                box = tk.Frame(right, bg=PANEL_SOFT)
                box.pack(fill="x", padx=14, pady=5)
                tk.Label(box, text=row.get("track_name") or "Unknown track",
                         bg=PANEL_SOFT, fg=TEXT,
                         font=("Segoe UI", 10, "bold")).pack(
                             anchor="w", padx=12, pady=(8, 1))
                tk.Label(box, text=f"{row.get('session_label') or '--'}  •  "
                                   f"{row.get('completed_laps') or 0} laps",
                         bg=PANEL_SOFT, fg=MUTED, font=("Segoe UI", 8)).pack(
                             anchor="w", padx=12, pady=(0, 8))
        else:
            tk.Label(right, text="No sessions yet.\nStart Solo Engineer to build your driver profile.",
                     bg=PANEL_2, fg=MUTED, justify="left", wraplength=270,
                     font=("Segoe UI", 10)).pack(anchor="w", padx=18, pady=12)
        quick = tk.Frame(right, bg=PANEL)
        quick.pack(side="bottom", fill="x", padx=14, pady=14)
        tk.Label(quick, text="QUICK ACTION", bg=PANEL, fg=GOLD,
                 font=("Segoe UI", 8, "bold")).pack(anchor="w", padx=12, pady=(10, 2))
        tk.Label(quick, text="Review every lap and setup in Session Studio.",
                 bg=PANEL, fg=TEXT, justify="left", wraplength=260,
                 font=("Segoe UI", 9)).pack(anchor="w", padx=12)
        themed_button(quick, "OPEN SESSION STUDIO", self.open_studio, PINK).pack(
            fill="x", padx=12, pady=10)

    def launch(self, mode):
        self._clear()
        self.active_mode = mode
        shared = Shared()
        notifications = queue.Queue()
        if mode == "solo":
            out_dir = os.path.join(self.base, "solo_reports")
            receiver = SoloReceiver(shared, self.port, out_dir, notifications,
                                    self.database)
            receiver.start()
            self.receiver = receiver
            SoloApp(self.root, shared, receiver, notifications, out_dir,
                    self.fullscreen, mode_switch=self.restart,
                    database=self.database)
        else:
            out_dir = os.path.join(self.base, "reports")
            receiver = HubReceiver(shared, self.port, out_dir, notifications,
                                   self.database)
            receiver.start()
            self.receiver = receiver
            SplitApp(self.root, shared, receiver, notifications, out_dir,
                     mode_switch=self.restart, database=self.database)

    def restart(self, mode):
        if self.receiver:
            self.receiver.running = False
            self.receiver.join(timeout=1.4)
        command = ([sys.executable] if getattr(sys, "frozen", False) else
                   [sys.executable, os.path.abspath(__file__)])
        if mode != "menu":
            command += ["--mode", mode]
        command += ["--port", str(self.port)]
        subprocess.Popen(command, cwd=self.base)
        self.root.after(100, self.root.destroy)


def _run_legacy(args, startup_warning=None):
    root = tk.Tk()
    configure_tk_scaling(root)
    apply_app_icon(root)
    UnifiedController(root, args.port, args.mode, args.fullscreen)
    if startup_warning:
        from tkinter import messagebox
        root.after(250, lambda: messagebox.showwarning(
            "F1 Telemetry Hub — Safe Mode",
            f"The WebView interface could not start, so the stable interface "
            f"was opened automatically.\n\n{startup_warning}"))
    root.mainloop()
    time.sleep(0.2)


def _restart_in_safe_mode(args):
    """Start Tk in a clean process after WinForms/WebView2 has shut down."""
    command = ([sys.executable] if getattr(sys, "frozen", False) else
               [sys.executable, os.path.abspath(__file__)])
    command += ["--legacy-ui", "--mode", args.mode, "--port", str(args.port)]
    if args.fullscreen:
        command.append("--fullscreen")
    release_single_instance()
    subprocess.Popen(command, cwd=os.path.dirname(
        sys.executable if getattr(sys, "frozen", False) else os.path.abspath(__file__)))


def main():
    parser = argparse.ArgumentParser(description="Unified F1 Race Command")
    parser.add_argument("--mode", choices=("menu", "solo", "split"), default="menu")
    parser.add_argument("--port", type=int, default=20777)
    parser.add_argument("--fullscreen", action="store_true")
    parser.add_argument("--legacy-ui", dest="legacy_ui", action="store_true",
                        default=True, help="Use the stable Tkinter interface (default)")
    parser.add_argument("--web-ui", dest="legacy_ui", action="store_false",
                        help="Use the experimental WebView2 dashboard")
    args = parser.parse_args()
    # This must run before WebView creates its native window. It also gives
    # Windows a stable application identity for taskbar icon selection.
    enable_high_dpi()
    if not acquire_single_instance(args.port):
        root = tk.Tk(); root.withdraw()
        apply_app_icon(root)
        from tkinter import messagebox
        messagebox.showinfo("F1 Telemetry Hub", "F1 Telemetry Hub is already running.")
        root.destroy()
        return
    if not args.legacy_ui:
        try:
            from f1_web_app import WebApplication
            WebApplication(args.port, "solo" if args.mode == "menu" else args.mode,
                           args.fullscreen).start()
            return
        except RuntimeError as exc:
            # WinForms and Tk do not reliably coexist sequentially in one
            # process. Restart the safe interface in a clean process.
            _restart_in_safe_mode(args)
            return
    _run_legacy(args)


if __name__ == "__main__":
    main()
