#!/usr/bin/env python3
"""F1 25 / F1 26 split-screen UDP telemetry engine.

One long-running process captures both split-screen players, logs each frame to
per-player and per-session CSV files, and automatically generates a report when
``m_sessionUID`` changes. UDP formats 2025 and 2026 are detected automatically.

Run: ``python f1_26_split_telemetry.py --port 20777 --out reports``
Use ``--no-ui`` for logging and reports without the terminal dashboard.
"""

import argparse
import csv
import math
import os
import socket
import struct
import subprocess
import sys
import threading
import time
from datetime import datetime

from f1_race_control import RaceControlTracker

# Windows consoles may use cp1252; force UTF-8 for consistent output.
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

try:
    from rich.live import Live
    from rich.table import Table
    from rich.panel import Panel
    from rich.columns import Columns
    from rich.console import Group, Console
    from rich.text import Text
    from rich.align import Align
    RICH = True
except ImportError:
    RICH = False


# ============================================================================
# 1. FORMATE STRUCT  (little-endian, packed - conform spec EA F1 25/26)
# ============================================================================
HEADER_FMT = "<HBBBBBQfIIBB"
HEADER_SIZE = struct.calcsize(HEADER_FMT)                 # 29
CAR_TELEMETRY_FMT = "<HfffBbHBBH4H4B4BH4f4B"
CAR_TELEMETRY_SIZE = struct.calcsize(CAR_TELEMETRY_FMT)  # 60 (2025)
CAR_TELEMETRY_2026_FMT = "<HfffBbHBBH4H4B4BB4f4B"
CAR_TELEMETRY_2026_SIZE = struct.calcsize(CAR_TELEMETRY_2026_FMT)  # 59
LAP_DATA_FMT = "<IIHBHBHBHBfffBBBBBBBBBBBBBBBHHBfB"
LAP_DATA_SIZE = struct.calcsize(LAP_DATA_FMT)            # 57
CAR_STATUS_FMT = "<BBBBBfffHHBBHBBBbfffBfffB"
CAR_STATUS_SIZE = struct.calcsize(CAR_STATUS_FMT)        # 55 (2025)
CAR_STATUS_2026_FMT = "<BBBBBfffHHBBHBBBbfffBffffB"
CAR_STATUS_2026_SIZE = struct.calcsize(CAR_STATUS_2026_FMT)  # 59
CAR_DAMAGE_FMT = "<4f12B18B"
CAR_DAMAGE_SIZE = struct.calcsize(CAR_DAMAGE_FMT)        # 46
CAR_SETUP_FMT = "<BBBBffffBBBBBBBBBffffBf"
CAR_SETUP_SIZE = struct.calcsize(CAR_SETUP_FMT)          # 50
PARTICIPANT_FMT = "<7B32sBBHBB12B"
PARTICIPANT_SIZE = struct.calcsize(PARTICIPANT_FMT)      # 57 (2025)
PARTICIPANT_2026_FMT = "<BHHHBBB32sBBHBB12B"
PARTICIPANT_2026_SIZE = struct.calcsize(PARTICIPANT_2026_FMT)  # 60
SESSION_HEAD_FMT = "<BbbBHBb"
TIME_TRIAL_SET_FMT = "<BBIIIIBBBBBB"
TIME_TRIAL_SET_SIZE = struct.calcsize(TIME_TRIAL_SET_FMT)  # 24 bytes
TIME_TRIAL_2026_SET_FMT = "<BHIIIIBBBBBB"
TIME_TRIAL_2026_SET_SIZE = struct.calcsize(TIME_TRIAL_2026_SET_FMT)  # 25

assert (HEADER_SIZE, CAR_TELEMETRY_SIZE, LAP_DATA_SIZE, CAR_STATUS_SIZE,
        CAR_DAMAGE_SIZE, PARTICIPANT_SIZE) == (29, 60, 57, 55, 46, 57)
assert (CAR_TELEMETRY_2026_SIZE, CAR_STATUS_2026_SIZE,
        PARTICIPANT_2026_SIZE, TIME_TRIAL_2026_SET_SIZE) == (59, 59, 60, 25)
assert CAR_SETUP_SIZE == 50

PKT_SESSION, PKT_LAP, PKT_EVENT, PKT_PARTICIPANTS, PKT_SETUP = 1, 2, 3, 4, 5
PKT_TELEMETRY, PKT_STATUS, PKT_DAMAGE = 6, 7, 10
PKT_TIME_TRIAL = 14
SUPPORTED_PACKET_FORMATS = (2025, 2026)

VISUAL_TYRE = {16: "Soft", 17: "Medium", 18: "Hard", 7: "Inter", 8: "Wet",
               19: "SuSoft", 20: "Soft", 21: "Med", 22: "Hard", 15: "Wet"}
ERS_MODE = {0: "None", 1: "Medium", 2: "Hotlap", 3: "Overtake"}
TRACKS = {0: "Melbourne", 1: "Paul Ricard", 2: "Shanghai", 3: "Bahrain",
    4: "Catalunya", 5: "Monaco", 6: "Montreal", 7: "Silverstone",
    8: "Hockenheim", 9: "Hungaroring", 10: "Spa", 11: "Monza", 12: "Singapore",
    13: "Suzuka", 14: "Abu Dhabi", 15: "COTA", 16: "Interlagos",
    17: "Red Bull Ring", 18: "Sochi", 19: "Mexico", 20: "Baku",
    21: "Bahrain (s)", 22: "Silverstone (s)", 23: "COTA (s)", 24: "Suzuka (s)",
    25: "Hanoi", 26: "Zandvoort", 27: "Imola", 28: "Portimao", 29: "Jeddah",
    30: "Miami", 31: "Las Vegas", 32: "Losail"}
SESSION_TYPE = {0: "Unknown", 1: "P1", 2: "P2", 3: "P3", 4: "Short P", 5: "Q1",
    6: "Q2", 7: "Q3", 8: "Short Q", 9: "OSQ", 10: "SQ1", 11: "SQ2", 12: "SQ3",
    13: "Short SQ", 14: "OSSQ", 15: "Race", 16: "Race 2", 17: "Race 3",
    18: "Time Trial"}


def fmt_ms(ms):
    if not ms:
        return "--:--.---"
    m, rem = divmod(int(ms), 60000)
    return f"{m}:{rem/1000:06.3f}"


# ============================================================================
# 2. LARGE DELTA FONT (dependency-free, five-row glyphs)
# ============================================================================
GLYPHS = {
    "0": ["###", "# #", "# #", "# #", "###"], "1": ["  #", "  #", "  #", "  #", "  #"],
    "2": ["###", "  #", "###", "#  ", "###"], "3": ["###", "  #", "###", "  #", "###"],
    "4": ["# #", "# #", "###", "  #", "  #"], "5": ["###", "#  ", "###", "  #", "###"],
    "6": ["###", "#  ", "###", "# #", "###"], "7": ["###", "  #", "  #", "  #", "  #"],
    "8": ["###", "# #", "###", "# #", "###"], "9": ["###", "# #", "###", "  #", "###"],
    ".": ["   ", "   ", "   ", "   ", " ##"], "-": ["   ", "   ", "###", "   ", "   "],
    "+": ["   ", " # ", "###", " # ", "   "], "s": ["###", "#  ", "###", "  #", "###"],
    " ": ["   ", "   ", "   ", "   ", "   "],
}


def render_big(text):
    rows = ["", "", "", "", ""]
    for ch in text:
        g = GLYPHS.get(ch, GLYPHS[" "])
        for i in range(5):
            rows[i] += "".join("██" if c == "#" else "  " for c in g[i]) + "  "
    return rows


# ============================================================================
# 3. SHARED STATE
# ============================================================================
class CarState:
    __slots__ = ("name", "tel", "lap", "status", "dmg", "setup",
                 "last_update", "best_lap_ms")

    def __init__(self):
        self.name = ""
        self.tel = self.lap = self.status = self.dmg = self.setup = None
        self.last_update = 0.0
        self.best_lap_ms = 0


class Shared:
    def __init__(self):
        self.lock = threading.Lock()
        self.p1 = CarState()
        self.p2 = CarState()
        self.p1_idx = None
        self.p2_idx = None
        self.session = {"track": None, "type": None, "laps": None,
                        "trackTemp": None, "airTemp": None, "weather": None,
                        "weather_forecast": [], "safety_car": 0,
                        "pit_speed_limit": None, "pit_ideal_lap": 0,
                        "pit_latest_lap": 0, "pit_rejoin_position": 0}
        self.race_control = RaceControlTracker().snapshot()
        self.packets = 0
        self.last_packet_time = 0.0
        self.fmt_warned = False
        self.session_index = 0
        self.last_report = ""
        self.errors = 0
        self.warning = ""
        self.packet_format = None
        self.time_trial = {}
        self.session_database_id = None


# ============================================================================
# 4. RECEIVER (network, parsing, logging, per-session reports)
# ============================================================================
CSV_FIELDS = [
    "wall_time", "session_time", "frame",
    "speed_kmh", "gear", "rpm", "throttle", "brake", "steer", "clutch", "drs",
    "position", "lap_num", "sector", "lap_invalid",
    "cur_lap_ms", "last_lap_ms", "s1_ms", "s2_ms", "lap_distance",
    "tyre_visual", "tyre_age_laps",
    "ers_store_j", "ers_mode", "ers_deployed_lap_j",
    "fuel_kg", "fuel_remaining_laps",
    "tyreTemp_RL", "tyreTemp_RR", "tyreTemp_FL", "tyreTemp_FR",
    "tyreWear_RL", "tyreWear_RR", "tyreWear_FL", "tyreWear_FR",
    "engineTemp", "penalties",
    "driver", "track", "track_id", "session_type", "weather",
    "safety_car", "pit_ideal_lap", "pit_latest_lap", "pit_rejoin_position",
]


class Receiver(threading.Thread):
    def __init__(self, shared, port, out_dir, database=None, capture_mode="split"):
        super().__init__(daemon=True)
        self.shared = shared
        self.port = port
        self.out_dir = out_dir
        self.database = database
        self.capture_mode = capture_mode
        self.running = True
        self.ready = threading.Event()
        self.startup_error = None
        self.here = os.path.dirname(os.path.abspath(__file__))
        # Session state owned by this thread.
        self.cur_uid = None
        self._session_index = 0
        self._session_stamp = ""
        self._session_has_lap = False
        self._paths = {}
        self._files = {}
        self._writers = {}
        self.race_control = RaceControlTracker()

    # -- session management -------------------------------------------------
    def _open_session(self, uid, packet_format=None, game_year=None):
        self._session_index += 1
        self._session_stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.cur_uid = uid
        self._session_has_lap = False
        i, s = self._session_index, self._session_stamp
        self._paths = {"p1": os.path.join(self.out_dir, f"f1_p1_s{i}_{s}.csv"),
                       "p2": os.path.join(self.out_dir, f"f1_p2_s{i}_{s}.csv")}
        self._files, self._writers = {}, {}
        self.race_control.reset()
        with self.shared.lock:
            self.shared.p1.best_lap_ms = 0
            self.shared.p2.best_lap_ms = 0
            self.shared.session_index = i
            self.shared.session["race_control_phase"] = self.race_control.phase
            self.shared.race_control = self.race_control.snapshot()
        if self.database:
            session_id = self.database.begin_session(uid, i, self.capture_mode,
                                                     packet_format, game_year)
            with self.shared.lock:
                self.shared.session_database_id = session_id

    def _close_session(self):
        """Finalize legacy reports and the embedded database together."""
        self._finalize_session()
        if self.database:
            self.database.end_session()

    def _finalize_session(self):
        for f in self._files.values():
            try:
                f.close()
            except Exception:
                pass
        self._files, self._writers = {}, {}
        if self.cur_uid is None or not self._session_has_lap:
            return
        p1, p2 = self._paths.get("p1"), self._paths.get("p2")
        if not (p1 and p2 and os.path.exists(p1) and os.path.exists(p2)):
            return
        i, s = self._session_index, self._session_stamp
        xlsx = os.path.join(self.out_dir, f"f1_report_s{i}_{s}.xlsx")
        png = os.path.join(self.out_dir, f"f1_compare_s{i}_{s}.png")
        report = os.path.join(self.here, "f1_report.py")
        compare = os.path.join(self.here, "f1_compare.py")
        msg = f"Session {i}: generating report -> {os.path.basename(xlsx)}"
        with self.shared.lock:
            self.shared.last_report = msg
        flags = getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0)
        try:
            if os.path.exists(report):
                subprocess.Popen([sys.executable, report, p1, p2, "--out", xlsx],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 creationflags=flags)
            if os.path.exists(compare):
                subprocess.Popen([sys.executable, compare, p1, p2, "--out", png],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 creationflags=flags)
        except Exception as e:
            with self.shared.lock:
                self.shared.last_report = f"Report failed: {e}"

    def _writer(self, key):
        if key not in self._writers:
            f = open(self._paths[key], "w", newline="", encoding="utf-8")
            w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
            w.writeheader()
            self._files[key], self._writers[key] = f, w
        return self._writers[key]

    @staticmethod
    def _unpack_at(fmt, size, data, base, idx):
        off = base + idx * size
        if idx < 0 or off + size > len(data):
            return None
        return struct.unpack_from(fmt, data, off)

    # -- network loop --------------------------------------------------------
    def run(self):
        sock = None
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            # SO_REUSEADDR permits two UDP listeners to bind the same port on
            # Windows, which makes double-launched app instances unreliable.
            if os.name != "nt":
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("0.0.0.0", self.port))
            sock.settimeout(1.0)
            self.ready.set()
            while self.running:
                try:
                    data, _ = sock.recvfrom(4096)
                except socket.timeout:
                    continue
                except OSError:
                    break
                if len(data) >= HEADER_SIZE:
                    try:
                        self._handle(data)
                    except Exception:
                        with self.shared.lock:
                            self.shared.errors += 1
        except OSError as exc:
            self.startup_error = exc
            with self.shared.lock:
                self.shared.warning = f"UDP port {self.port} is unavailable: {exc}"
        finally:
            self.ready.set()
            self._close_session()   # Close and report the final session.
            if sock is not None:
                sock.close()

    def _handle(self, data):
        (pkt_format, game_year, _mj, _mn, _pv, pkt_id, uid, sess_time,
         frame, _of, p1_idx, p2_idx) = struct.unpack_from(HEADER_FMT, data, 0)

        # Session rollover uses thread-owned state and requires no lock.
        if self.cur_uid is None:
            self._open_session(uid, pkt_format, game_year)
        elif uid != self.cur_uid:
            self._close_session()
            self._open_session(uid, pkt_format, game_year)

        s = self.shared
        with s.lock:
            s.packets += 1
            s.last_packet_time = time.time()
            s.p1_idx = p1_idx
            s.p2_idx = None if p2_idx == 255 else p2_idx
            s.packet_format = pkt_format
            if pkt_format not in SUPPORTED_PACKET_FORMATS and not s.fmt_warned:
                s.fmt_warned = True
                s.warning = (f"Unsupported UDP format {pkt_format}; select 2025 or "
                             "2026 Season Pack in the game settings")

        def _valid(ix):
            max_cars = 24 if pkt_format == 2026 else 22
            return ix if (ix is not None and 0 <= ix < max_cars) else None
        targets = [("p1", _valid(p1_idx)),
                   ("p2", _valid(None if p2_idx == 255 else p2_idx))]
        if pkt_id == PKT_SESSION:
            self._parse_session(data, pkt_format, game_year)
        elif pkt_id == PKT_EVENT:
            self._parse_event(data)
        elif pkt_id == PKT_PARTICIPANTS:
            self._parse_participants(data, targets, pkt_format)
        elif pkt_id == PKT_SETUP:
            self._parse_setup(data, targets)
        elif pkt_id == PKT_TELEMETRY:
            self._parse_telemetry(data, targets, sess_time, frame, pkt_format)
        elif pkt_id == PKT_LAP:
            self._parse_generic(data, targets, PKT_LAP)
        elif pkt_id == PKT_STATUS:
            self._parse_generic(data, targets, PKT_STATUS, pkt_format)
        elif pkt_id == PKT_DAMAGE:
            self._parse_generic(data, targets, PKT_DAMAGE)
        elif pkt_id == PKT_TIME_TRIAL:
            self._parse_time_trial(data, pkt_format)

    def _parse_session(self, data, packet_format=None, game_year=None):
        weather, tT, aT, laps, _tl, sType, trackId = \
            struct.unpack_from(SESSION_HEAD_FMT, data, HEADER_SIZE)
        formula = time_left = duration = pit_speed = paused = 0
        safety_car = pit_ideal = pit_latest = pit_rejoin = 0
        forecasts = []
        ai = game_mode = rule_set = session_length = None
        assists = {}
        try:
            formula, time_left, duration, pit_speed, paused = struct.unpack_from(
                "<BHHBB", data, HEADER_SIZE + 8)
            safety_car = data[HEADER_SIZE + 124]
            forecast_count = min(data[HEADER_SIZE + 126], 64)
            forecast_base = HEADER_SIZE + 127
            for index in range(forecast_count):
                off = forecast_base + index * 8
                values = struct.unpack_from("<BBBbbbbB", data, off)
                forecasts.append({
                    "session_type": values[0], "minutes": values[1],
                    "weather": values[2], "track_temp": values[3],
                    "air_temp": values[5], "rain": values[7],
                })
            pit_ideal = data[HEADER_SIZE + 653]
            pit_latest = data[HEADER_SIZE + 654]
            pit_rejoin = data[HEADER_SIZE + 655]
            ai = data[HEADER_SIZE + 640]
            assist_names = ("steering_assist", "braking_assist", "gearbox_assist",
                            "pit_assist", "pit_release_assist", "ers_assist",
                            "drs_assist", "dynamic_racing_line")
            assists = dict(zip(assist_names,
                               data[HEADER_SIZE + 656:HEADER_SIZE + 664]))
            game_mode = data[HEADER_SIZE + 665]
            rule_set = data[HEADER_SIZE + 666]
            session_length = data[HEADER_SIZE + 671]
        except (IndexError, struct.error):
            pass
        with self.shared.lock:
            self.shared.session.update(track=TRACKS.get(trackId, f"Track {trackId}"),
                type=SESSION_TYPE.get(sType, str(sType)), laps=laps,
                trackTemp=tT, airTemp=aT, track_id=trackId, weather=weather,
                session_type_id=sType,
                weather_forecast=forecasts, safety_car=safety_car,
                pit_speed_limit=pit_speed, game_paused=bool(paused),
                session_time_left=time_left, session_duration=duration,
                formula=formula, pit_ideal_lap=pit_ideal,
                pit_latest_lap=pit_latest,
                pit_rejoin_position=pit_rejoin, ai_difficulty=ai,
                game_mode=game_mode, rule_set=rule_set,
                session_length=session_length, **assists)
            phase = self.race_control.consume_session(safety_car)
            self.shared.session["race_control_phase"] = phase
            self.shared.race_control = self.race_control.snapshot()
            snapshot = dict(self.shared.session)
        if self.database:
            self.database.update_session(snapshot, packet_format, game_year)

    def _parse_event(self, data):
        """Parse the four-character event code used by both supported formats."""
        if len(data) < HEADER_SIZE + 4:
            return
        code = data[HEADER_SIZE:HEADER_SIZE + 4].decode("ascii", "replace")
        if code == "SCAR" and len(data) >= HEADER_SIZE + 6:
            event = self.race_control.consume_safety_event(
                data[HEADER_SIZE + 4], data[HEADER_SIZE + 5])
        else:
            event = self.race_control.consume_event(code)
        with self.shared.lock:
            self.shared.session["race_control_phase"] = self.race_control.phase
            self.shared.race_control = self.race_control.snapshot()
        if self.database:
            self.database.record_race_control_event(event.to_dict())

    def _parse_setup(self, data, targets):
        names = ("front_wing", "rear_wing", "on_throttle_diff", "off_throttle_diff",
                 "front_camber", "rear_camber", "front_toe", "rear_toe",
                 "front_suspension", "rear_suspension", "front_anti_roll_bar",
                 "rear_anti_roll_bar", "front_suspension_height",
                 "rear_suspension_height", "brake_pressure", "brake_bias",
                 "engine_braking", "rear_left_pressure", "rear_right_pressure",
                 "front_left_pressure", "front_right_pressure", "ballast",
                 "fuel_load")
        for key, idx in targets:
            if idx is None:
                continue
            record = self._unpack_at(CAR_SETUP_FMT, CAR_SETUP_SIZE, data,
                                     HEADER_SIZE, idx)
            if record is None:
                continue
            setup = dict(zip(names, record))
            with self.shared.lock:
                getattr(self.shared, key).setup = setup
            if self.database:
                self.database.record_setup(key, setup)

    def _parse_participants(self, data, targets, pkt_format=2025):
        base = HEADER_SIZE + 1
        fmt, size = ((PARTICIPANT_2026_FMT, PARTICIPANT_2026_SIZE)
                     if pkt_format == 2026 else
                     (PARTICIPANT_FMT, PARTICIPANT_SIZE))
        for key, idx in targets:
            if idx is None:
                continue
            rec = self._unpack_at(fmt, size, data, base, idx)
            if rec is None:
                continue
            name = rec[7].split(b"\x00")[0].decode("utf-8", "replace")
            with self.shared.lock:
                getattr(self.shared, key).name = name

    def _parse_time_trial(self, data, pkt_format=2025):
        """Parse session-best, personal-best, and rival Time Trial records."""
        names = ("session_best", "personal_best", "rival")
        records = {}
        fmt, size = ((TIME_TRIAL_2026_SET_FMT, TIME_TRIAL_2026_SET_SIZE)
                     if pkt_format == 2026 else
                     (TIME_TRIAL_SET_FMT, TIME_TRIAL_SET_SIZE))
        for index, name in enumerate(names):
            offset = HEADER_SIZE + index * size
            if offset + size > len(data):
                return
            row = struct.unpack_from(fmt, data, offset)
            records[name] = {
                "car_idx": row[0], "team_id": row[1], "lap_ms": row[2],
                "s1_ms": row[3], "s2_ms": row[4], "s3_ms": row[5],
                "traction_control": row[6], "gearbox_assist": row[7],
                "abs": row[8], "equal_performance": row[9],
                "custom_setup": row[10], "valid": bool(row[11]),
            }
        with self.shared.lock:
            self.shared.time_trial = records

    def _parse_telemetry(self, data, targets, sess_time, frame, pkt_format=2025):
        fmt, size = ((CAR_TELEMETRY_2026_FMT, CAR_TELEMETRY_2026_SIZE)
                     if pkt_format == 2026 else
                     (CAR_TELEMETRY_FMT, CAR_TELEMETRY_SIZE))
        for key, idx in targets:
            if idx is None:
                continue
            t = self._unpack_at(fmt, size, data, HEADER_SIZE, idx)
            if t is None:
                continue
            if not (0 <= t[0] <= 450 and 0.0 <= t[1] <= 1.01 and
                    -1.01 <= t[2] <= 1.01 and 0.0 <= t[3] <= 1.01 and
                    -1 <= t[5] <= 8 and t[7] in (0, 1)):
                with self.shared.lock:
                    self.shared.errors += 1
                    self.shared.warning = "Rejected an invalid telemetry frame"
                continue
            cs = getattr(self.shared, key)
            with self.shared.lock:
                cs.tel = t
                cs.last_update = time.time()
                if key == "p1" and self.race_control.observe_motion(t[0]):
                    self.shared.session["race_control_phase"] = self.race_control.phase
                    self.shared.race_control = self.race_control.snapshot()
                if self.shared.warning.startswith("Rejected an invalid telemetry"):
                    self.shared.warning = ""
            self._log_row(key, cs, sess_time, frame)

    def _parse_generic(self, data, targets, pkt_id, pkt_format=2025):
        status_layout = ((CAR_STATUS_2026_FMT, CAR_STATUS_2026_SIZE, "status")
                         if pkt_format == 2026 else
                         (CAR_STATUS_FMT, CAR_STATUS_SIZE, "status"))
        fmt, size, attr = {
            PKT_LAP: (LAP_DATA_FMT, LAP_DATA_SIZE, "lap"),
            PKT_STATUS: status_layout,
            PKT_DAMAGE: (CAR_DAMAGE_FMT, CAR_DAMAGE_SIZE, "dmg"),
        }[pkt_id]
        for key, idx in targets:
            if idx is None:
                continue
            rec = self._unpack_at(fmt, size, data, HEADER_SIZE, idx)
            if rec is None:
                continue
            # The 2026 status record adds m_ersHarvestLimitPerLap before
            # m_ersDeployedThisLap. Remove that extra field internally so all
            # UI/report code can use one stable 2025-compatible index layout.
            if pkt_id == PKT_STATUS and pkt_format == 2026:
                rec = rec[:23] + rec[24:]
            if pkt_id == PKT_STATUS and not (
                    rec[4] in (0, 1) and rec[11] in (0, 1) and
                    math.isfinite(rec[5]) and -0.1 <= rec[5] <= 150.0 and
                    math.isfinite(rec[19]) and -1.0 <= rec[19] <= 4_100_000.0):
                with self.shared.lock:
                    self.shared.errors += 1
                    self.shared.warning = "Rejected an invalid car-status frame"
                continue
            cs = getattr(self.shared, key)
            with self.shared.lock:
                setattr(cs, attr, rec)
                if (pkt_id == PKT_STATUS and
                        self.shared.warning.startswith("Rejected an invalid car-status")):
                    self.shared.warning = ""
                if pkt_id == PKT_LAP and rec[0] > 0:
                    if cs.best_lap_ms == 0 or rec[0] < cs.best_lap_ms:
                        cs.best_lap_ms = rec[0]
                    self._session_has_lap = True

    def _log_row(self, key, cs, sess_time, frame):
        t, lap, st, dmg = cs.tel, cs.lap, cs.status, cs.dmg
        row = {f: "" for f in CSV_FIELDS}
        row["wall_time"] = f"{time.time():.3f}"
        row["session_time"] = f"{sess_time:.3f}"
        row["frame"] = frame
        row.update(speed_kmh=t[0], gear=t[5], rpm=t[6], throttle=round(t[1], 4),
                   brake=round(t[3], 4), steer=round(t[2], 4), clutch=t[4], drs=t[7],
                   tyreTemp_RL=t[14], tyreTemp_RR=t[15], tyreTemp_FL=t[16],
                   tyreTemp_FR=t[17], engineTemp=t[22])
        if lap:
            row.update(position=lap[13], lap_num=lap[14], sector=lap[17],
                       lap_invalid=lap[18], cur_lap_ms=lap[1], last_lap_ms=lap[0],
                       s1_ms=lap[2] + lap[3] * 60000, s2_ms=lap[4] + lap[5] * 60000,
                       lap_distance=round(lap[10], 2), penalties=lap[19])
        if st:
            row.update(tyre_visual=VISUAL_TYRE.get(st[14], st[14]), tyre_age_laps=st[15],
                       ers_store_j=round(st[19]), ers_mode=ERS_MODE.get(st[20], st[20]),
                       ers_deployed_lap_j=round(st[23]),
                       fuel_kg=round(st[5], 3),
                       fuel_remaining_laps=round(st[7], 2))
        if dmg:
            row.update(tyreWear_RL=round(dmg[0], 2), tyreWear_RR=round(dmg[1], 2),
                       tyreWear_FL=round(dmg[2], 2), tyreWear_FR=round(dmg[3], 2))
        sess = self.shared.session
        row.update(driver=cs.name, track=sess.get("track") or "",
                   track_id=sess.get("track_id", ""),
                   session_type=sess.get("type") or "",
                   weather=sess.get("weather", ""),
                   safety_car=sess.get("safety_car", ""),
                   pit_ideal_lap=sess.get("pit_ideal_lap", ""),
                   pit_latest_lap=sess.get("pit_latest_lap", ""),
                   pit_rejoin_position=sess.get("pit_rejoin_position", ""))
        self._writer(key).writerow(row)
        if self.database:
            self.database.record_sample(key, row)


# ============================================================================
# 5. DASHBOARD LIVE
# ============================================================================
def bar(value, width=12):
    value = max(0.0, min(1.0, value))
    n = int(round(value * width))
    return "█" * n + "·" * (width - n)


def live_gap(p1, p2):
    """Return live track gap as ``(seconds, metres)``; positive means P1 leads."""
    if p1.lap and p2.lap and p1.tel and p2.tel:
        gap_m = p1.lap[11] - p2.lap[11]           # Total-distance difference.
        behind = (p2.tel[0] if gap_m > 0 else p1.tel[0]) / 3.6
        if behind > 1.0:
            return gap_m / behind, gap_m
    return None, None


def best_lap_delta(p1, p2):
    if p1.best_lap_ms and p2.best_lap_ms:
        return (p1.best_lap_ms - p2.best_lap_ms) / 1000.0
    return None


def big_delta_panel(p1, p2, n1, n2):
    gap, gap_m = live_gap(p1, p2)
    if gap is None:
        big = "\n".join(render_big("--.--s"))
        inner = Group(Align.center(Text("waiting for both players on track", style="dim")),
                      Align.center(Text(big, style="bold grey58")))
        return Panel(inner, border_style="grey58", title="[bold]LIVE GAP[/]")

    ahead = n1 if gap > 0 else n2
    color = "bright_cyan" if gap > 0 else "bright_magenta"
    big = "\n".join(render_big(f"{abs(gap):.2f}s"))
    head = Text.assemble((ahead, f"bold {color}"), (" is ahead by", "dim"))
    parts = [Align.center(head), Align.center(Text(big, style=f"bold {color}"))]

    bl = best_lap_delta(p1, p2)
    if bl is not None:
        who = n1 if bl < 0 else n2
        blc = "bright_green" if bl < 0 else "bright_red"
        parts.append(Align.center(Text.assemble(
            (f"best lap   {n1} {fmt_ms(p1.best_lap_ms)}   {n2} {fmt_ms(p2.best_lap_ms)}   ", "white"),
            (f"Δ {abs(bl):.3f}s  {who}", f"bold {blc}"))))
    else:
        parts.append(Align.center(Text("best lap: no complete laps yet", style="dim")))
    return Panel(Group(*parts), border_style=color, title="[bold]LIVE GAP[/]")


def car_panel(cs, idx, color):
    t, lap, st, dmg = cs.tel, cs.lap, cs.status, cs.dmg
    tbl = Table.grid(padding=(0, 1))
    tbl.add_column(justify="right", style="dim")
    tbl.add_column(justify="left")
    if t is None:
        tbl.add_row("status", "waiting for data...")
        return Panel(tbl, title=f"[{color}]{cs.name or '—'}[/] (idx {idx})", border_style=color)
    gear = "R" if t[5] == -1 else ("N" if t[5] == 0 else str(t[5]))
    tbl.add_row("SPEED", f"[bold]{t[0]:>3}[/] km/h    GEAR [bold]{gear}[/]")
    tbl.add_row("RPM", f"{t[6]:>5}")
    tbl.add_row("THR", f"[green]{bar(t[1])}[/] {t[1]*100:3.0f}%")
    tbl.add_row("BRK", f"[red]{bar(t[3])}[/] {t[3]*100:3.0f}%")
    tbl.add_row("ACTIVE AERO", "[bold green]STRAIGHT MODE[/]" if t[7]
                else "corner mode")
    if lap:
        sec = {0: "S1", 1: "S2", 2: "S3"}.get(lap[17], "?")
        inv = " [red]INVALID[/]" if lap[18] else ""
        tbl.add_row("POS", f"P{lap[13]}   Lap {lap[14]}   {sec}{inv}")
        tbl.add_row("CUR", fmt_ms(lap[1]))
        tbl.add_row("LAST", fmt_ms(lap[0]))
    if st:
        tbl.add_row("ERS", f"{st[19]/4_000_000*100:4.0f}%  [{ERS_MODE.get(st[20],'?')}]")
        tbl.add_row("FUEL", f"{st[5]:5.2f} kg   {st[7]:+.2f} laps")
        tbl.add_row("TYRE", f"{VISUAL_TYRE.get(st[14], st[14])}  ({st[15]} laps)")
    tbl.add_row("T.temp", f"RL{t[14]} RR{t[15]} FL{t[16]} FR{t[17]} °C")
    if dmg:
        tbl.add_row("T.wear", f"RL{dmg[0]:.0f} RR{dmg[1]:.0f} FL{dmg[2]:.0f} FR{dmg[3]:.0f} %")
    return Panel(tbl, title=f"[{color}]{cs.name or '—'}[/] (idx {idx})", border_style=color)


def render(shared):
    with shared.lock:
        sess = dict(shared.session)
        p1, p2 = shared.p1, shared.p2
        i1, i2 = shared.p1_idx, shared.p2_idx
        pkts, last = shared.packets, shared.last_packet_time
        sidx, report = shared.session_index, shared.last_report
        warning, errs = shared.warning, shared.errors
    n1, n2 = p1.name or "P1", p2.name or "P2"

    top = Table.grid(expand=True)
    top.add_column(justify="left")
    top.add_column(justify="right")
    live = "●" if (time.time() - last) < 2 else "○ no packets"
    left = f"[bold]Session #{sidx}[/]   {sess.get('track') or '—'}  {sess.get('type') or ''}"
    if sess.get("laps"):
        left += f"  {sess['laps']} laps"
    tt = sess.get("trackTemp")
    right = (f"track {tt}°C air {sess.get('airTemp')}°C   " if tt is not None else "") + \
            f"pkts {pkts}" + (f"  err {errs}" if errs else "") + f"  {live}"
    top.add_row(left, right)

    blocks = [Panel(top, border_style="grey37")]
    if i2 is not None:
        blocks.append(big_delta_panel(p1, p2))       # Large central delta.
    panels = [car_panel(p1, i1, "cyan")]
    if i2 is not None:
        panels.append(car_panel(p2, i2, "magenta"))
    else:
        e = Table.grid()
        e.add_row("No second player detected.")
        e.add_row("Start split screen / select UDP Format 2025 or 2026.")
        panels.append(Panel(e, title="[magenta]Player 2[/]", border_style="magenta"))
    blocks.append(Columns(panels, equal=True, expand=True))
    if report:
        blocks.append(Text("  " + report, style="green"))
    return Group(*blocks)


def run_ui(shared, receiver):
    console = Console()
    console.print("[green]Listening for telemetry...[/] Reports are generated "
                  "automatically after every session. Press Ctrl+C to stop.\n")
    try:
        with Live(render(shared), console=console, refresh_per_second=12) as live:
            while True:
                time.sleep(1 / 12)
                live.update(render(shared))
    except KeyboardInterrupt:
        pass
    finally:
        receiver.running = False
        time.sleep(1.3)
        console.print(f"\n[bold]Stopped.[/] Files and reports are in: {receiver.out_dir}")


def run_headless(shared, receiver):
    print("Headless mode. Logging and automatic reports per session. Press Ctrl+C to stop.")
    try:
        while True:
            time.sleep(2)
            with shared.lock:
                p1, p2, sidx = shared.p1, shared.p2, shared.session_index
                pkts, rep = shared.packets, shared.last_report

            def ln(cs, tag):
                if cs.tel is None:
                    return f"{tag}: waiting"
                g = "R" if cs.tel[5] == -1 else ("N" if cs.tel[5] == 0 else cs.tel[5])
                return f"{tag} {cs.name or '-'}: {cs.tel[0]:>3}km/h G{g}"
            v, _, ok = big_delta_value(p1, p2)
            d = f"Δ {v:+.3f}s" if ok else "Δ --"
            print(f"[s{sidx} pkts {pkts}] {ln(p1,'P1')} | {ln(p2,'P2')} | {d}"
                  + (f"  <{rep}>" if rep else ""))
    except KeyboardInterrupt:
        pass
    finally:
        receiver.running = False
        time.sleep(1.3)
        print(f"\nStopped. Files and reports are in: {receiver.out_dir}")


def main():
    ap = argparse.ArgumentParser(description="F1 25/26 split-screen telemetry v3")
    ap.add_argument("--port", type=int, default=20777)
    ap.add_argument("--out", default=".", help="folder for CSV files and reports")
    ap.add_argument("--no-ui", action="store_true")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    shared = Shared()
    receiver = Receiver(shared, args.port, os.path.abspath(args.out))
    receiver.start()
    if args.no_ui or not RICH:
        if not RICH and not args.no_ui:
            print("(rich is not installed -> headless mode. Run 'pip install rich' for the dashboard.)")
        run_headless(shared, receiver)
    else:
        run_ui(shared, receiver)


if __name__ == "__main__":
    main()
