#!/usr/bin/env python3
"""Native in-app browser for recorded F1 sessions and learned insights."""

import json
import tkinter as tk
from tkinter import ttk


BG = "#150407"
CARD = "#401016"
EDGE = "#84252e"
FG = "#fff7fb"
DIM = "#d7a9bf"
CYAN = "#53d9ff"
GREEN = "#4ce68a"
YELLOW = "#ffad18"


def lap_time(ms):
    if not ms:
        return "--:--.---"
    minutes, rest = divmod(int(ms), 60000)
    return f"{minutes}:{rest / 1000:06.3f}"


def number(value, digits=1, suffix=""):
    if value is None:
        return "--"
    return f"{value:.{digits}f}{suffix}" if isinstance(value, float) else f"{value}{suffix}"


class SessionStudio:
    def __init__(self, parent, database):
        self.db = database
        self.data_session_id = None
        self.data_page = 0
        self.data_page_size = 1000
        self.window = tk.Toplevel(parent)
        self.window.title("F1 SESSION STUDIO")
        self.window.configure(bg=BG)
        self.window.geometry("1420x820")
        self.window.minsize(1050, 650)
        try:
            self.window.state("zoomed")
        except tk.TclError:
            pass
        self._style()
        self._build()
        self.refresh()

    def _style(self):
        style = ttk.Style(self.window)
        style.theme_use("clam")
        style.configure("Treeview", background=CARD, fieldbackground=CARD,
                        foreground=FG, rowheight=30, borderwidth=0,
                        font=("Segoe UI", 10))
        style.configure("Treeview.Heading", background="#710b14", foreground=DIM,
                        relief="flat", font=("Segoe UI", 9, "bold"))
        style.map("Treeview", background=[("selected", "#98232c")])
        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure("TNotebook.Tab", background="#710b14", foreground=DIM,
                        padding=(18, 9), font=("Segoe UI", 10, "bold"))
        style.map("TNotebook.Tab", background=[("selected", CARD)],
                  foreground=[("selected", CYAN)])

    def _build(self):
        head = tk.Frame(self.window, bg=BG)
        head.pack(fill="x", padx=22, pady=(16, 10))
        tk.Label(head, text="SESSION STUDIO", bg=BG, fg=FG,
                 font=("Segoe UI", 26, "bold")).pack(side="left")
        tk.Label(head, text="Every lap, input, setup and learned trend - inside the app",
                 bg=BG, fg=DIM, font=("Segoe UI", 11)).pack(side="left", padx=18)
        tk.Button(head, text="REFRESH", command=self.refresh, bg=CYAN, fg=BG,
                  relief="flat", padx=18, pady=7,
                  font=("Segoe UI", 10, "bold")).pack(side="right")

        body = tk.PanedWindow(self.window, orient="horizontal", bg=BG,
                              sashwidth=6, bd=0)
        body.pack(fill="both", expand=True, padx=22, pady=(0, 18))
        left = tk.Frame(body, bg=CARD, highlightbackground=EDGE, highlightthickness=1)
        right = tk.Frame(body, bg=BG)
        body.add(left, width=390, minsize=300)
        body.add(right, minsize=650)

        tk.Label(left, text="RECORDED SESSIONS", bg=CARD, fg=DIM,
                 font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=12, pady=10)
        self.sessions = ttk.Treeview(left, columns=("date", "session", "track", "laps"),
                                     show="headings", selectmode="browse")
        widths = {"date": 92, "session": 155, "track": 100, "laps": 45}
        for col, title in (("date", "DATE"), ("session", "SESSION"),
                           ("track", "TRACK"), ("laps", "LAPS")):
            self.sessions.heading(col, text=title)
            self.sessions.column(col, width=widths[col], anchor="w")
        self.sessions.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self.sessions.bind("<<TreeviewSelect>>", self._selected)

        self.book = ttk.Notebook(right)
        self.book.pack(fill="both", expand=True)
        self.summary_tab = tk.Frame(self.book, bg=BG)
        self.laps_tab = tk.Frame(self.book, bg=BG)
        self.data_tab = tk.Frame(self.book, bg=BG)
        self.driver_tab = tk.Frame(self.book, bg=BG)
        self.book.add(self.summary_tab, text="OVERVIEW")
        self.book.add(self.laps_tab, text="LAPS")
        self.book.add(self.data_tab, text="RECORDED DATA")
        self.book.add(self.driver_tab, text="DRIVING + SETUP")
        self._build_summary()
        self._build_tables()
        self._build_driver()

    def _build_summary(self):
        self.title = tk.Label(self.summary_tab, text="Select a session", bg=BG, fg=FG,
                              font=("Segoe UI", 24, "bold"), anchor="w")
        self.title.pack(fill="x", padx=18, pady=(18, 4))
        self.meta = tk.Label(self.summary_tab, text="", bg=BG, fg=DIM,
                             font=("Consolas", 11), justify="left", anchor="nw")
        self.meta.pack(fill="x", padx=18)
        self.cards = tk.Frame(self.summary_tab, bg=BG)
        self.cards.pack(fill="x", padx=18, pady=15)
        self.card_values = {}
        for col, (key, label, color) in enumerate((
                ("best", "BEST LAP", CYAN), ("laps", "COMPLETED LAPS", FG),
                ("samples", "DATA POINTS", GREEN), ("ai", "AI DIFFICULTY", YELLOW))):
            card = tk.Frame(self.cards, bg=CARD, highlightbackground=EDGE,
                            highlightthickness=1)
            card.grid(row=0, column=col, sticky="nsew", padx=4)
            self.cards.columnconfigure(col, weight=1)
            tk.Label(card, text=label, bg=CARD, fg=DIM,
                     font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=12, pady=(10, 1))
            value = tk.Label(card, text="--", bg=CARD, fg=color,
                             font=("Consolas", 20, "bold"))
            value.pack(anchor="w", padx=12, pady=(0, 12))
            self.card_values[key] = value
        tk.Label(self.summary_tab, text="LAP TIME TREND", bg=BG, fg=DIM,
                 font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=22)
        self.chart = tk.Canvas(self.summary_tab, bg=CARD, highlightbackground=EDGE,
                               highlightthickness=1, height=290)
        self.chart.pack(fill="both", expand=True, padx=18, pady=(4, 18))

    def _build_tables(self):
        lap_cols = ("lap", "time", "s1", "s2", "s3", "valid", "pos", "tyre",
                    "wear", "fuel", "avg", "max")
        self.lap_table = ttk.Treeview(self.laps_tab, columns=lap_cols, show="headings")
        lap_titles = ("LAP", "TIME", "S1", "S2", "S3", "VALID", "POS", "TYRE",
                      "WEAR", "FUEL USED", "AVG KM/H", "MAX KM/H")
        for col, title in zip(lap_cols, lap_titles):
            self.lap_table.heading(col, text=title)
            self.lap_table.column(col, width=85 if col != "time" else 105, anchor="center")
        self.lap_table.pack(fill="both", expand=True, padx=10, pady=10)

        data_cols = ("time", "lap", "dist", "speed", "gear", "thr", "brk", "steer",
                     "pos", "fuel", "ers", "tyre", "wear")
        self.data_table = ttk.Treeview(self.data_tab, columns=data_cols, show="headings")
        titles = ("TIME", "LAP", "DIST", "SPEED", "GEAR", "THR", "BRK", "STEER",
                  "POS", "FUEL", "ERS %", "TYRE", "AVG WEAR")
        for col, title in zip(data_cols, titles):
            self.data_table.heading(col, text=title)
            self.data_table.column(col, width=78, anchor="center")
        self.data_table.pack(fill="both", expand=True, padx=10, pady=(10, 2))
        pager = tk.Frame(self.data_tab, bg=BG)
        pager.pack(fill="x", padx=12, pady=(0, 8))
        tk.Button(pager, text="PREVIOUS", command=lambda: self._change_page(-1),
                  bg=CARD, fg=FG, relief="flat", padx=12, pady=5).pack(side="left")
        tk.Button(pager, text="NEXT", command=lambda: self._change_page(1),
                  bg=CARD, fg=FG, relief="flat", padx=12, pady=5).pack(side="left", padx=6)
        self.data_note = tk.Label(pager, text="", bg=BG, fg=DIM,
                                  font=("Segoe UI", 9), anchor="w")
        self.data_note.pack(side="left", fill="x", expand=True, padx=8)

    def _build_driver(self):
        self.profile_text = tk.Label(self.driver_tab, text="", bg=CARD, fg=FG,
                                     justify="left", anchor="nw", padx=18, pady=14,
                                     font=("Segoe UI", 11), wraplength=800)
        self.profile_text.pack(fill="x", padx=12, pady=(12, 6))
        tk.Label(self.driver_tab, text="LEARNED SETUP SUGGESTIONS", bg=BG, fg=CYAN,
                 font=("Segoe UI", 11, "bold")).pack(anchor="w", padx=18, pady=(8, 3))
        self.recommendations = tk.Frame(self.driver_tab, bg=BG)
        self.recommendations.pack(fill="x", padx=12)
        tk.Label(self.driver_tab, text="RECORDED CAR SETUP", bg=BG, fg=DIM,
                 font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=18, pady=(14, 3))
        self.setup_text = tk.Text(self.driver_tab, bg=CARD, fg=FG, insertbackground=FG,
                                  relief="flat", height=12, font=("Consolas", 10),
                                  padx=12, pady=10)
        self.setup_text.pack(fill="both", expand=True, padx=12, pady=(0, 12))

    def refresh(self):
        selected = self.sessions.selection()
        previous = selected[0] if selected else None
        self.sessions.delete(*self.sessions.get_children())
        rows = self.db.list_sessions()
        for row in rows:
            iid = str(row["id"])
            date = (row.get("started_at") or "").replace("T", " ")[:16]
            label = row.get("session_label") or row.get("session_type") or "Unknown"
            self.sessions.insert("", "end", iid=iid, values=(date, label,
                                 row.get("track_name") or "--",
                                 row.get("completed_laps") or 0))
        target = previous if previous and self.sessions.exists(previous) else (
            str(rows[0]["id"]) if rows else None)
        if target:
            self.sessions.selection_set(target)
            self.sessions.focus(target)
            self._load(int(target))

    def _selected(self, _event=None):
        selection = self.sessions.selection()
        if selection:
            self._load(int(selection[0]))

    def _load(self, session_id):
        info = self.db.session_details(session_id)
        laps = self.db.session_laps(session_id)
        self.data_session_id = session_id
        self.data_page = 0
        samples, sample_count = self.db.session_samples_page(
            session_id, limit=self.data_page_size)
        style = self.db.session_style(session_id)
        setup = self.db.session_setup(session_id)
        self.title.config(text=f"{info.get('track_name') or 'Unknown track'}  -  "
                               f"{info.get('session_label') or 'Unknown session'}")
        assists = json.loads(info.get("assists_json") or "{}")
        enabled = [key.replace("_", " ").title() for key, val in assists.items() if val]
        self.meta.config(text=(
            f"START  {info.get('started_at') or '--'}     END  {info.get('ended_at') or 'LIVE'}\n"
            f"FORMAT  {info.get('packet_format') or '--'}     GAME YEAR  {info.get('game_year') or '--'}"
            f"     WEATHER  {info.get('weather_name') or '--'}     TRACK/AIR  "
            f"{info.get('track_temp') or '--'}C / {info.get('air_temp') or '--'}C\n"
            f"RULE SET  {info.get('rule_set')}     GAME MODE  {info.get('game_mode')}"
            f"     PIT LIMIT  {info.get('pit_speed_limit') or '--'} km/h     ASSISTS  "
            f"{', '.join(enabled) if enabled else 'None/unknown'}"))
        self.card_values["best"].config(text=lap_time(info.get("best_lap_ms")))
        self.card_values["laps"].config(text=str(info.get("completed_laps") or 0))
        self.card_values["samples"].config(text=f"{info.get('samples_count') or 0:,}")
        self.card_values["ai"].config(text=number(info.get("ai_difficulty"), 0))
        self._fill_laps(laps)
        self._fill_samples(samples, sample_count)
        self._draw_chart(laps)
        self._fill_driver(info, style, setup)

    def _fill_laps(self, rows):
        self.lap_table.delete(*self.lap_table.get_children())
        for row in rows:
            wear = None
            if row.get("wear_end") is not None and row.get("wear_start") is not None:
                wear = row["wear_end"] - row["wear_start"]
            fuel = None
            if row.get("fuel_start") is not None and row.get("fuel_end") is not None:
                fuel = row["fuel_start"] - row["fuel_end"]
            self.lap_table.insert("", "end", values=(row["lap_number"], lap_time(row["lap_time_ms"]),
                lap_time(row["sector1_ms"]), lap_time(row["sector2_ms"]), lap_time(row["sector3_ms"]),
                "YES" if row["valid"] else "NO", row.get("position") or "--",
                row.get("compound") or "--", number(wear, 2, "%"), number(fuel, 2, " kg"),
                number(row.get("avg_speed"), 1), row.get("max_speed") or "--"))

    def _fill_samples(self, rows, total):
        self.data_table.delete(*self.data_table.get_children())
        for row in rows:
            wears = [row.get(k) for k in ("tyre_wear_rl", "tyre_wear_rr",
                                           "tyre_wear_fl", "tyre_wear_fr")]
            wears = [x for x in wears if x is not None]
            wear = sum(wears) / len(wears) if wears else None
            ers = (row.get("ers_store_j") or 0) / 4_000_000 * 100
            self.data_table.insert("", "end", values=(number(row.get("session_time"), 1),
                row.get("lap_num") or 0, number(row.get("lap_distance"), 0),
                row.get("speed_kmh") or 0, row.get("gear"),
                number((row.get("throttle") or 0) * 100, 0, "%"),
                number((row.get("brake") or 0) * 100, 0, "%"),
                number(row.get("steer"), 2), row.get("position") or "--",
                number(row.get("fuel_kg"), 2), number(ers, 0),
                row.get("tyre_compound") or "--", number(wear, 1, "%")))
        first = self.data_page * self.data_page_size + (1 if rows else 0)
        last = self.data_page * self.data_page_size + len(rows)
        pages = max(1, (total + self.data_page_size - 1) // self.data_page_size)
        note = (f"Rows {first:,}-{last:,} of {total:,}  |  "
                f"Page {self.data_page + 1}/{pages}  |  every captured sample is available")
        self.data_note.config(text=note)

    def _change_page(self, direction):
        if self.data_session_id is None:
            return
        target = max(0, self.data_page + direction)
        rows, total = self.db.session_samples_page(
            self.data_session_id, limit=self.data_page_size,
            offset=target * self.data_page_size)
        if not rows and target > 0:
            return
        self.data_page = target
        self._fill_samples(rows, total)

    def _fill_driver(self, info, style, setup):
        profile = self.db.get_profile(info.get("track_name"))
        text = (f"SESSION STYLE  {style.get('style_label') or 'Complete a representative stint to learn'}\n\n"
                f"TRACK HISTORY  {profile.get('sessions', 0)} sessions / {profile.get('laps', 0) or 0} valid laps\n"
                f"Full throttle {number(profile.get('full_throttle_pct'), 1, '%')}   |   "
                f"Heavy braking {number(profile.get('heavy_brake_pct'), 1, '%')}   |   "
                f"Tyre wear/lap {number(profile.get('wear_per_lap'), 2, '%')}   |   "
                f"Fuel/lap {number(profile.get('fuel_per_lap'), 2, ' kg')}   |   "
                f"Consistency {number(profile.get('pace_consistency_ms'), 0, ' ms')}")
        self.profile_text.config(text=text)
        for widget in self.recommendations.winfo_children():
            widget.destroy()
        for rec in self.db.setup_recommendations(info.get("track_name")):
            box = tk.Frame(self.recommendations, bg=CARD, highlightbackground=EDGE,
                           highlightthickness=1)
            box.pack(fill="x", pady=3)
            tk.Label(box, text=rec["title"], bg=CARD, fg=YELLOW,
                     font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=12, pady=(8, 1))
            tk.Label(box, text=rec["detail"], bg=CARD, fg=FG,
                     font=("Segoe UI", 10), wraplength=900,
                     justify="left").pack(anchor="w", padx=12, pady=(0, 8))
        self.setup_text.config(state="normal")
        self.setup_text.delete("1.0", "end")
        self.setup_text.insert("1.0", json.dumps(setup, indent=2) if setup else
                               "No car setup packet was recorded for this session.")
        self.setup_text.config(state="disabled")

    def _draw_chart(self, rows):
        canvas = self.chart
        canvas.delete("all")
        valid = [(row["lap_number"], row["lap_time_ms"]) for row in rows
                 if row.get("valid") and row.get("lap_time_ms")]
        if not valid:
            canvas.create_text(20, 25, text="Complete valid laps to build the pace chart",
                               anchor="w", fill=DIM, font=("Segoe UI", 11))
            return
        canvas.update_idletasks()
        width, height = max(canvas.winfo_width(), 400), max(canvas.winfo_height(), 180)
        times = [x[1] for x in valid]
        low, high = min(times), max(times)
        spread = max(1000, high - low)
        points = []
        for index, (lap, value) in enumerate(valid):
            x = 45 + index * (width - 80) / max(1, len(valid) - 1)
            y = height - 35 - (value - low) / spread * (height - 70)
            points.extend((x, y))
            canvas.create_text(x, height - 15, text=str(lap), fill=DIM,
                               font=("Consolas", 9))
        if len(points) >= 4:
            canvas.create_line(*points, fill=CYAN, width=3, smooth=True)
        for x, y in zip(points[::2], points[1::2]):
            canvas.create_oval(x - 4, y - 4, x + 4, y + 4, fill=GREEN, outline="")
        canvas.create_text(12, 16, text=lap_time(high), anchor="w", fill=DIM)
        canvas.create_text(12, height - 36, text=lap_time(low), anchor="w", fill=CYAN)
