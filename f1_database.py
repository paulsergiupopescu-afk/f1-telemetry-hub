#!/usr/bin/env python3
"""Persistent SQLite telemetry store and long-term driving-style learning."""

from __future__ import annotations

import csv
import itertools
import json
import math
import os
import re
import sqlite3
import statistics
import threading
import time
from contextlib import contextmanager
from datetime import datetime


SESSION_LENGTHS = {
    0: "None", 1: "Unknown", 2: "3 laps", 3: "5 laps",
    4: "25%", 5: "35%", 6: "50%", 7: "100%",
}
WEATHER = {0: "Clear", 1: "Light cloud", 2: "Overcast",
           3: "Light rain", 4: "Heavy rain", 5: "Storm"}
SAFETY_CAR = {0: "Green", 1: "Safety Car", 2: "Virtual Safety Car",
              3: "Formation Lap"}


SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY,
    uid TEXT NOT NULL UNIQUE,
    capture_mode TEXT NOT NULL DEFAULT 'solo',
    session_index INTEGER,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    packet_format INTEGER,
    game_year INTEGER,
    track_id INTEGER,
    track_name TEXT,
    session_type_id INTEGER,
    session_type TEXT,
    session_length_code INTEGER,
    session_length TEXT,
    session_label TEXT,
    total_laps INTEGER,
    ai_difficulty INTEGER,
    formula INTEGER,
    game_mode INTEGER,
    rule_set INTEGER,
    weather INTEGER,
    weather_name TEXT,
    track_temp INTEGER,
    air_temp INTEGER,
    pit_speed_limit INTEGER,
    pit_ideal_lap INTEGER,
    pit_latest_lap INTEGER,
    pit_rejoin_position INTEGER,
    safety_car_periods INTEGER DEFAULT 0,
    assists_json TEXT,
    forecast_json TEXT,
    samples_count INTEGER DEFAULT 0,
    completed_laps INTEGER DEFAULT 0,
    best_lap_ms INTEGER,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS telemetry_samples (
    id INTEGER PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    player TEXT NOT NULL,
    wall_time REAL,
    session_time REAL,
    frame INTEGER,
    speed_kmh INTEGER,
    gear INTEGER,
    rpm INTEGER,
    throttle REAL,
    brake REAL,
    steer REAL,
    clutch INTEGER,
    aero_active INTEGER,
    position INTEGER,
    lap_num INTEGER,
    sector INTEGER,
    lap_invalid INTEGER,
    cur_lap_ms INTEGER,
    last_lap_ms INTEGER,
    s1_ms INTEGER,
    s2_ms INTEGER,
    lap_distance REAL,
    tyre_compound TEXT,
    tyre_age INTEGER,
    ers_store_j REAL,
    ers_mode INTEGER,
    ers_deployed_lap_j REAL,
    fuel_kg REAL,
    fuel_remaining_laps REAL,
    tyre_temp_rl REAL,
    tyre_temp_rr REAL,
    tyre_temp_fl REAL,
    tyre_temp_fr REAL,
    tyre_wear_rl REAL,
    tyre_wear_rr REAL,
    tyre_wear_fl REAL,
    tyre_wear_fr REAL,
    engine_temp REAL,
    penalties INTEGER
);

CREATE INDEX IF NOT EXISTS idx_samples_session_player_lap
ON telemetry_samples(session_id, player, lap_num);
CREATE INDEX IF NOT EXISTS idx_samples_session_frame
ON telemetry_samples(session_id, frame);

CREATE TABLE IF NOT EXISTS laps (
    id INTEGER PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    player TEXT NOT NULL,
    lap_number INTEGER NOT NULL,
    lap_time_ms INTEGER,
    sector1_ms INTEGER,
    sector2_ms INTEGER,
    sector3_ms INTEGER,
    valid INTEGER,
    position INTEGER,
    compound TEXT,
    tyre_age INTEGER,
    wear_start REAL,
    wear_end REAL,
    fuel_start REAL,
    fuel_end REAL,
    ers_start REAL,
    ers_end REAL,
    avg_speed REAL,
    max_speed INTEGER,
    full_throttle_pct REAL,
    heavy_brake_pct REAL,
    UNIQUE(session_id, player, lap_number)
);

CREATE TABLE IF NOT EXISTS setups (
    id INTEGER PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    player TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    setup_json TEXT NOT NULL,
    UNIQUE(session_id, player)
);

CREATE TABLE IF NOT EXISTS style_metrics (
    session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    player TEXT NOT NULL,
    sample_count INTEGER,
    lap_count INTEGER,
    full_throttle_pct REAL,
    heavy_brake_pct REAL,
    avg_brake REAL,
    avg_abs_steer REAL,
    rear_front_temp_delta REAL,
    rear_front_wear_delta REAL,
    wear_per_lap REAL,
    fuel_per_lap REAL,
    pace_consistency_ms REAL,
    style_label TEXT,
    computed_at TEXT NOT NULL,
    PRIMARY KEY(session_id, player)
);

CREATE TABLE IF NOT EXISTS recommendations (
    id INTEGER PRIMARY KEY,
    session_id INTEGER REFERENCES sessions(id) ON DELETE CASCADE,
    player TEXT NOT NULL DEFAULT 'p1',
    category TEXT NOT NULL,
    priority INTEGER NOT NULL,
    title TEXT NOT NULL,
    detail TEXT,
    evidence TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS race_control_events (
    id INTEGER PRIMARY KEY,
    session_id INTEGER REFERENCES sessions(id) ON DELETE CASCADE,
    code TEXT NOT NULL,
    phase TEXT NOT NULL,
    detail TEXT,
    event_time REAL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS strategy_decisions (
    id INTEGER PRIMARY KEY,
    session_id INTEGER REFERENCES sessions(id) ON DELETE CASCADE,
    player TEXT NOT NULL DEFAULT 'p1',
    lap_number INTEGER,
    action TEXT NOT NULL,
    target_lap INTEGER,
    compound TEXT,
    advantage_seconds REAL,
    confidence TEXT,
    reason TEXT,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


SAMPLE_COLUMNS = (
    "wall_time", "session_time", "frame", "speed_kmh", "gear", "rpm",
    "throttle", "brake", "steer", "clutch", "drs", "position",
    "lap_num", "sector", "lap_invalid", "cur_lap_ms", "last_lap_ms",
    "s1_ms", "s2_ms", "lap_distance", "tyre_visual", "tyre_age_laps",
    "ers_store_j", "ers_mode", "ers_deployed_lap_j", "fuel_kg",
    "fuel_remaining_laps", "tyreTemp_RL", "tyreTemp_RR", "tyreTemp_FL",
    "tyreTemp_FR", "tyreWear_RL", "tyreWear_RR", "tyreWear_FL",
    "tyreWear_FR", "engineTemp", "penalties",
)


class TelemetryDatabase:
    """One writer connection plus short-lived read connections for the GUI."""

    def __init__(self, path):
        self.path = os.path.abspath(path)
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self.lock = threading.RLock()
        self.conn = sqlite3.connect(self.path, check_same_thread=False,
                                    timeout=15.0)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()
        self.session_id = None
        self._last_lap = {}
        self._pending = 0
        self._last_commit = time.monotonic()

    @contextmanager
    def _reader(self):
        conn = sqlite3.connect(self.path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def begin_session(self, uid, session_index=0, capture_mode="solo",
                      packet_format=None, game_year=None):
        uid = str(uid)
        now = datetime.now().isoformat(timespec="seconds")
        with self.lock:
            self._last_lap.clear()
            self.conn.execute(
                """INSERT INTO sessions(uid,capture_mode,session_index,started_at,
                       packet_format,game_year) VALUES(?,?,?,?,?,?)
                   ON CONFLICT(uid) DO UPDATE SET ended_at=NULL,
                       capture_mode=excluded.capture_mode,
                       packet_format=COALESCE(excluded.packet_format,sessions.packet_format),
                       game_year=COALESCE(excluded.game_year,sessions.game_year)""",
                (uid, capture_mode, session_index, now, packet_format, game_year))
            row = self.conn.execute("SELECT id FROM sessions WHERE uid=?", (uid,)).fetchone()
            self.session_id = row[0]
            self.conn.commit()
            return self.session_id

    def import_legacy_csv_folder(self, folder):
        """Recover historical solo CSV captures into an empty/new database.

        Imports are idempotent: each source filename and size maps to one stable
        session UID. Original timestamps are retained for monthly numbering.
        """
        folder = os.path.abspath(folder)
        if not os.path.isdir(folder):
            return {"files": 0, "sessions": 0, "samples": 0}
        files = sorted(
            os.path.join(folder, name) for name in os.listdir(folder)
            if re.match(r"f1_p1_s\d+_.*\.csv$", name, re.IGNORECASE)
        )
        imported_sessions = imported_samples = 0
        for path in files:
            uid = f"legacy-csv:{os.path.basename(path)}:{os.path.getsize(path)}"
            with self.lock:
                exists = self.conn.execute(
                    "SELECT 1 FROM sessions WHERE uid=?", (uid,)).fetchone()
            if exists:
                continue
            try:
                handle = open(path, "r", encoding="utf-8-sig", errors="replace", newline="")
            except OSError:
                continue
            with handle:
                reader = csv.DictReader(handle)
                buffered = list(itertools.islice(reader, 500))
                if not buffered:
                    continue
                match = re.search(r"_s(\d+)_", os.path.basename(path), re.IGNORECASE)
                session_index = int(match.group(1)) if match else 0
                track = next((row.get("track") for row in buffered if row.get("track")), None)
                session_type = next((row.get("session_type") for row in buffered
                                     if row.get("session_type")), None) or "Time Trial"
                track_id = next((self._num(row.get("track_id")) for row in buffered
                                 if self._num(row.get("track_id")) is not None), None)
                wall_times = []
                self.begin_session(uid, session_index, "legacy_csv")
                self.update_session({
                    "track": track or "Unknown circuit",
                    "track_id": int(track_id) if track_id is not None else None,
                    "type": session_type,
                })
                last_row = None
                for row in itertools.chain(buffered, reader):
                    wall_time = self._num(row.get("wall_time"))
                    if wall_time and 946684800 <= wall_time <= 4102444800:
                        wall_times.append(wall_time)
                    self.record_sample("p1", row)
                    last_row = row
                    imported_samples += 1
                self.end_session()
                started = (datetime.fromtimestamp(min(wall_times)).isoformat(timespec="seconds")
                           if wall_times else datetime.fromtimestamp(
                               os.path.getmtime(path)).isoformat(timespec="seconds"))
                ended = (datetime.fromtimestamp(max(wall_times)).isoformat(timespec="seconds")
                         if wall_times else started)
                with self.lock:
                    self.conn.execute(
                        """UPDATE sessions SET started_at=?,ended_at=?,notes=?
                           WHERE id=?""",
                        (started, ended,
                         f"Recovered from {os.path.basename(path)}", self.session_id))
                    self.conn.commit()
                imported_sessions += 1
        self.session_id = None
        self._last_lap.clear()
        return {"files": len(files), "sessions": imported_sessions,
                "samples": imported_samples}

    def update_session(self, session, packet_format=None, game_year=None):
        if not self.session_id:
            return
        stype = session.get("type") or "Unknown"
        length_code = session.get("session_length")
        length = SESSION_LENGTHS.get(length_code, f"Code {length_code}")
        label = stype
        if stype.casefold().startswith("race") and length not in ("None", "Unknown"):
            label = f"{stype} · {length}"
        ai = session.get("ai_difficulty")
        if ai is not None:
            label += f" · AI {ai}"
        assists = {key: session.get(key) for key in (
            "steering_assist", "braking_assist", "gearbox_assist",
            "pit_assist", "pit_release_assist", "ers_assist", "drs_assist",
            "dynamic_racing_line")}
        values = (
            packet_format, game_year, session.get("track_id"), session.get("track"),
            session.get("session_type_id"), stype, length_code, length, label,
            session.get("laps"), ai, session.get("formula"),
            session.get("game_mode"), session.get("rule_set"),
            session.get("weather"), WEATHER.get(session.get("weather"), "Unknown"),
            session.get("trackTemp"), session.get("airTemp"),
            session.get("pit_speed_limit"), session.get("pit_ideal_lap"),
            session.get("pit_latest_lap"), session.get("pit_rejoin_position"),
            json.dumps(assists, separators=(",", ":")),
            json.dumps(session.get("weather_forecast") or [], separators=(",", ":")),
            self.session_id,
        )
        with self.lock:
            self.conn.execute(
                """UPDATE sessions SET packet_format=COALESCE(?,packet_format),
                   game_year=COALESCE(?,game_year),track_id=?,track_name=?,
                   session_type_id=?,session_type=?,session_length_code=?,
                   session_length=?,session_label=?,total_laps=?,ai_difficulty=?,
                   formula=?,game_mode=?,rule_set=?,weather=?,weather_name=?,
                   track_temp=?,air_temp=?,pit_speed_limit=?,pit_ideal_lap=?,
                   pit_latest_lap=?,pit_rejoin_position=?,assists_json=?,
                   forecast_json=? WHERE id=?""", values)
            self.conn.commit()
            self._last_commit = time.monotonic()

    @staticmethod
    def _num(value, default=None):
        if value in (None, ""):
            return default
        try:
            number = float(value)
            return number if math.isfinite(number) else default
        except (TypeError, ValueError):
            return default

    def record_sample(self, player, row):
        if not self.session_id:
            return
        values = [self._num(row.get(column)) for column in SAMPLE_COLUMNS]
        placeholders = ",".join("?" for _ in range(39))
        sql = f"""INSERT INTO telemetry_samples(
            session_id,player,wall_time,session_time,frame,speed_kmh,gear,rpm,
            throttle,brake,steer,clutch,aero_active,position,lap_num,sector,
            lap_invalid,cur_lap_ms,last_lap_ms,s1_ms,s2_ms,lap_distance,
            tyre_compound,tyre_age,ers_store_j,ers_mode,ers_deployed_lap_j,
            fuel_kg,fuel_remaining_laps,tyre_temp_rl,tyre_temp_rr,tyre_temp_fl,
            tyre_temp_fr,tyre_wear_rl,tyre_wear_rr,tyre_wear_fl,tyre_wear_fr,
            engine_temp,penalties) VALUES({placeholders})"""
        # tyre_visual is text and should not be converted to a number.
        values[20] = str(row.get("tyre_visual") or "")
        lap_num = int(self._num(row.get("lap_num"), 0) or 0)
        with self.lock:
            previous = self._last_lap.get(player)
            if previous and lap_num and lap_num != previous:
                self._finalize_lap(player, previous, row)
            if lap_num:
                self._last_lap[player] = lap_num
            self.conn.execute(sql, [self.session_id, player] + values)
            self._pending += 1
            self._maybe_commit()

    def record_setup(self, player, setup):
        if not self.session_id or not setup:
            return
        with self.lock:
            self.conn.execute(
                """INSERT INTO setups(session_id,player,captured_at,setup_json)
                   VALUES(?,?,?,?) ON CONFLICT(session_id,player) DO UPDATE SET
                   captured_at=excluded.captured_at,setup_json=excluded.setup_json""",
                (self.session_id, player, datetime.now().isoformat(timespec="seconds"),
                 json.dumps(setup, separators=(",", ":"))))
            self.conn.commit()
            self._last_commit = time.monotonic()

    def record_race_control_event(self, event):
        if not self.session_id or not event:
            return
        with self.lock:
            self.conn.execute(
                """INSERT INTO race_control_events(
                   session_id,code,phase,detail,event_time,created_at)
                   VALUES(?,?,?,?,?,?)""",
                (self.session_id, event.get("code", ""), event.get("phase", "GREEN"),
                 event.get("detail", ""), self._num(event.get("timestamp")),
                 datetime.now().isoformat(timespec="seconds")))
            self.conn.commit()

    def record_strategy_decision(self, recommendation, player="p1"):
        if not self.session_id or not recommendation:
            return
        payload = dict(recommendation)
        with self.lock:
            self.conn.execute(
                """INSERT INTO strategy_decisions(
                   session_id,player,lap_number,action,target_lap,compound,
                   advantage_seconds,confidence,reason,payload_json,created_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (self.session_id, player, payload.get("lap"), payload.get("action", ""),
                 payload.get("target_lap"), payload.get("compound"),
                 self._num(payload.get("advantage_seconds")), payload.get("confidence"),
                 payload.get("change_reason") or payload.get("detail"),
                 json.dumps(payload, separators=(",", ":"), default=str),
                 datetime.now().isoformat(timespec="seconds")))
            self.conn.commit()

    def session_race_control_events(self, session_id):
        with self._reader() as conn:
            rows = conn.execute(
                "SELECT * FROM race_control_events WHERE session_id=? ORDER BY id",
                (session_id,)).fetchall()
        return [dict(row) for row in rows]

    def session_strategy_decisions(self, session_id, player="p1"):
        with self._reader() as conn:
            rows = conn.execute(
                """SELECT * FROM strategy_decisions
                   WHERE session_id=? AND player=? ORDER BY id""",
                (session_id, player)).fetchall()
        return [dict(row) for row in rows]

    def _finalize_lap(self, player, lap_number, transition_row=None):
        aggregate = self.conn.execute(
            """SELECT MIN(fuel_kg),MAX(fuel_kg),MIN(ers_store_j),MAX(ers_store_j),
               MIN((tyre_wear_rl+tyre_wear_rr+tyre_wear_fl+tyre_wear_fr)/4.0),
               MAX((tyre_wear_rl+tyre_wear_rr+tyre_wear_fl+tyre_wear_fr)/4.0),
               AVG(speed_kmh),MAX(speed_kmh),
               AVG(CASE WHEN throttle>=0.9 THEN 100.0 ELSE 0.0 END),
               AVG(CASE WHEN brake>=0.7 THEN 100.0 ELSE 0.0 END),
               MAX(s1_ms),MAX(s2_ms),MAX(position),MAX(tyre_age),
               MAX(tyre_compound),MAX(lap_invalid)
               FROM telemetry_samples WHERE session_id=? AND player=? AND lap_num=?""",
            (self.session_id, player, lap_number)).fetchone()
        if not aggregate or aggregate[6] is None:
            return
        lap_time = int(self._num((transition_row or {}).get("last_lap_ms"), 0) or 0)
        s1, s2 = int(aggregate[10] or 0), int(aggregate[11] or 0)
        s3 = max(0, lap_time - s1 - s2) if lap_time else 0
        self.conn.execute(
            """INSERT INTO laps(session_id,player,lap_number,lap_time_ms,
               sector1_ms,sector2_ms,sector3_ms,valid,position,compound,tyre_age,
               wear_start,wear_end,fuel_start,fuel_end,ers_start,ers_end,
               avg_speed,max_speed,full_throttle_pct,heavy_brake_pct)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(session_id,player,lap_number) DO UPDATE SET
               lap_time_ms=excluded.lap_time_ms,sector1_ms=excluded.sector1_ms,
               sector2_ms=excluded.sector2_ms,sector3_ms=excluded.sector3_ms,
               valid=excluded.valid,position=excluded.position,
               compound=excluded.compound,tyre_age=excluded.tyre_age,
               wear_start=excluded.wear_start,wear_end=excluded.wear_end,
               fuel_start=excluded.fuel_start,fuel_end=excluded.fuel_end,
               ers_start=excluded.ers_start,ers_end=excluded.ers_end,
               avg_speed=excluded.avg_speed,max_speed=excluded.max_speed,
               full_throttle_pct=excluded.full_throttle_pct,
               heavy_brake_pct=excluded.heavy_brake_pct""",
            (self.session_id, player, lap_number, lap_time, s1, s2, s3,
             0 if aggregate[15] else 1, aggregate[12], aggregate[14], aggregate[13],
             aggregate[4], aggregate[5], aggregate[1], aggregate[0], aggregate[3],
             aggregate[2], aggregate[6], aggregate[7], aggregate[8], aggregate[9]))

    def _maybe_commit(self, force=False):
        if force or self._pending >= 240 or time.monotonic() - self._last_commit > 1.5:
            self.conn.commit()
            self._pending = 0
            self._last_commit = time.monotonic()

    def end_session(self):
        if not self.session_id:
            return
        with self.lock:
            self._maybe_commit(True)
            for player in tuple(self._last_lap):
                self.compute_style(self.session_id, player)
            stats = self.conn.execute(
                """SELECT COUNT(*),COUNT(DISTINCT CASE WHEN lap_num>0 THEN lap_num END),
                   MIN(CASE WHEN last_lap_ms>0 THEN last_lap_ms END)
                   FROM telemetry_samples WHERE session_id=?""",
                (self.session_id,)).fetchone()
            self.conn.execute(
                """UPDATE sessions SET ended_at=?,samples_count=?,completed_laps=?,
                   best_lap_ms=? WHERE id=?""",
                (datetime.now().isoformat(timespec="seconds"), stats[0],
                 max(0, (stats[1] or 0) - 1), stats[2], self.session_id))
            self.conn.commit()

    def compute_style(self, session_id, player="p1"):
        row = self.conn.execute(
            """SELECT COUNT(*),
               AVG(CASE WHEN throttle>=0.9 THEN 100.0 ELSE 0.0 END),
               AVG(CASE WHEN brake>=0.7 THEN 100.0 ELSE 0.0 END),
               AVG(CASE WHEN brake>0.05 THEN brake END),AVG(ABS(steer)),
               AVG((tyre_temp_rl+tyre_temp_rr-tyre_temp_fl-tyre_temp_fr)/2.0),
               AVG((tyre_wear_rl+tyre_wear_rr-tyre_wear_fl-tyre_wear_fr)/2.0)
               FROM telemetry_samples WHERE session_id=? AND player=?""",
            (session_id, player)).fetchone()
        laps = self.conn.execute(
            """SELECT lap_time_ms,wear_start,wear_end,fuel_start,fuel_end
               FROM laps WHERE session_id=? AND player=? AND valid=1 AND lap_time_ms>0
               ORDER BY lap_number""", (session_id, player)).fetchall()
        times = [x[0] for x in laps]
        wear_rates = [x[2] - x[1] for x in laps if x[1] is not None and
                      x[2] is not None and 0 <= x[2] - x[1] < 15]
        fuel_rates = [x[3] - x[4] for x in laps if x[3] is not None and
                      x[4] is not None and 0 < x[3] - x[4] < 10]
        consistency = statistics.pstdev(times) if len(times) >= 2 else None
        full_throttle, heavy_brake = row[1] or 0, row[2] or 0
        rear_wear = row[6] or 0
        labels = []
        labels.append("aggressive throttle" if full_throttle > 48 else
                      "progressive throttle")
        labels.append("late/hard braking" if heavy_brake > 12 else
                      "progressive braking")
        if rear_wear > 2:
            labels.append("rear-limited tyres")
        elif rear_wear < -2:
            labels.append("front-limited tyres")
        else:
            labels.append("balanced tyre use")
        values = (session_id, player, row[0] or 0, len(laps), full_throttle,
                  heavy_brake, row[3], row[4], row[5], rear_wear,
                  statistics.median(wear_rates) if wear_rates else None,
                  statistics.median(fuel_rates) if fuel_rates else None,
                  consistency, " · ".join(labels),
                  datetime.now().isoformat(timespec="seconds"))
        self.conn.execute(
            """INSERT OR REPLACE INTO style_metrics(session_id,player,sample_count,
               lap_count,full_throttle_pct,heavy_brake_pct,avg_brake,
               avg_abs_steer,rear_front_temp_delta,rear_front_wear_delta,
               wear_per_lap,fuel_per_lap,pace_consistency_ms,style_label,computed_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", values)
        return dict(zip(("session_id", "player", "sample_count", "lap_count",
                         "full_throttle_pct", "heavy_brake_pct", "avg_brake",
                         "avg_abs_steer", "rear_front_temp_delta",
                         "rear_front_wear_delta", "wear_per_lap", "fuel_per_lap",
                         "pace_consistency_ms", "style_label", "computed_at"), values))

    def get_profile(self, track_name=None, player="p1"):
        where, params = "m.player=?", [player]
        if track_name:
            where += " AND s.track_name=?"
            params.append(track_name)
        with self._reader() as conn:
            row = conn.execute(
                f"""SELECT COUNT(*),SUM(m.lap_count),AVG(m.full_throttle_pct),
                    AVG(m.heavy_brake_pct),AVG(m.avg_brake),AVG(m.avg_abs_steer),
                    AVG(m.rear_front_temp_delta),AVG(m.rear_front_wear_delta),
                    AVG(m.wear_per_lap),AVG(m.fuel_per_lap),
                    AVG(m.pace_consistency_ms)
                    FROM style_metrics m JOIN sessions s ON s.id=m.session_id
                    WHERE {where}""", params).fetchone()
        keys = ("sessions", "laps", "full_throttle_pct", "heavy_brake_pct",
                "avg_brake", "avg_abs_steer", "rear_front_temp_delta",
                "rear_front_wear_delta", "wear_per_lap", "fuel_per_lap",
                "pace_consistency_ms")
        return dict(zip(keys, row)) if row and row[0] else {}

    def setup_recommendations(self, track_name=None, player="p1"):
        profile = self.get_profile(track_name, player)
        if not profile:
            return [{"priority": 3, "title": "MORE DATA REQUIRED",
                     "detail": "Complete at least one representative stint."}]
        recommendations = []
        wear_bias = profile.get("rear_front_wear_delta") or 0
        temp_bias = profile.get("rear_front_temp_delta") or 0
        if wear_bias > 2 or temp_bias > 6:
            recommendations += [
                {"priority": 1, "title": "PROTECT REAR TYRES",
                 "detail": "Reduce on-throttle differential 3–5% and soften rear anti-roll bar one click."},
                {"priority": 2, "title": "MOVE BRAKE BIAS FORWARD",
                 "detail": "Try +1% front brake bias and compare rear wear over a full stint."},
            ]
        elif wear_bias < -2 or temp_bias < -7:
            recommendations += [
                {"priority": 1, "title": "REDUCE FRONT TYRE LOAD",
                 "detail": "Soften front anti-roll bar one click and move brake bias rearward 1%."},
                {"priority": 2, "title": "CHECK FRONT PRESSURES",
                 "detail": "Reduce front pressures by 0.2–0.4 psi if temperatures remain high."},
            ]
        if (profile.get("heavy_brake_pct") or 0) > 12:
            recommendations.append(
                {"priority": 2, "title": "STABILISE HEAVY BRAKING",
                 "detail": "Reduce brake pressure 1–2% if locking occurs; keep the current value otherwise."})
        if (profile.get("full_throttle_pct") or 0) > 50 and wear_bias > 0:
            recommendations.append(
                {"priority": 2, "title": "CALM CORNER EXITS",
                 "detail": "Use a more open on-throttle differential and one-click softer rear suspension."})
        if (profile.get("pace_consistency_ms") or 0) > 900:
            recommendations.append(
                {"priority": 3, "title": "FAVOUR A STABLE PLATFORM",
                 "detail": "Add one rear-wing click and avoid extreme roll-bar settings for repeatable laps."})
        if not recommendations:
            recommendations.append(
                {"priority": 3, "title": "BASELINE IS WELL BALANCED",
                 "detail": "Keep the mechanical balance; tune wings for circuit efficiency."})
        return recommendations

    def list_sessions(self, limit=200):
        with self._reader() as conn:
            rows = conn.execute(
                """SELECT id,started_at,ended_at,session_label,track_name,
                   session_type,session_length,ai_difficulty,total_laps,
                   completed_laps,best_lap_ms,samples_count,packet_format,
                   (SELECT COUNT(*) FROM sessions prior
                    WHERE substr(prior.started_at,1,7)=substr(sessions.started_at,1,7)
                      AND prior.id<=sessions.id
                      AND (prior.track_name IS NOT NULL OR prior.id=sessions.id)) month_index
                   FROM sessions ORDER BY id DESC LIMIT ?""", (limit,)).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            try:
                month = datetime.fromisoformat(item["started_at"]).strftime("%B").upper()
            except (TypeError, ValueError):
                month = "SESSION"
            item["display_name"] = f"{month} · SESSION {int(item.get('month_index') or 0):02d}"
            result.append(item)
        return result

    def session_details(self, session_id):
        with self._reader() as conn:
            row = conn.execute(
                """SELECT sessions.*,
                   (SELECT COUNT(*) FROM sessions prior
                    WHERE substr(prior.started_at,1,7)=substr(sessions.started_at,1,7)
                      AND prior.id<=sessions.id
                      AND (prior.track_name IS NOT NULL OR prior.id=sessions.id)) month_index
                   FROM sessions WHERE id=?""", (session_id,)).fetchone()
        item = dict(row) if row else {}
        if item:
            try:
                month = datetime.fromisoformat(item["started_at"]).strftime("%B").upper()
            except (TypeError, ValueError):
                month = "SESSION"
            item["display_name"] = f"{month} · SESSION {int(item.get('month_index') or 0):02d}"
        return item

    def session_laps(self, session_id, player="p1"):
        with self._reader() as conn:
            rows = conn.execute(
                "SELECT * FROM laps WHERE session_id=? AND player=? ORDER BY lap_number",
                (session_id, player)).fetchall()
        return [dict(row) for row in rows]

    def session_samples(self, session_id, player="p1", limit=1500):
        with self._reader() as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM telemetry_samples WHERE session_id=? AND player=?",
                (session_id, player)).fetchone()[0]
            step = max(1, count // max(1, limit))
            rows = conn.execute(
                """SELECT id,session_time,frame,lap_num,lap_distance,speed_kmh,
                   gear,throttle,brake,steer,position,fuel_kg,ers_store_j,
                   tyre_compound,tyre_age,tyre_wear_rl,tyre_wear_rr,
                   tyre_wear_fl,tyre_wear_fr FROM telemetry_samples
                   WHERE session_id=? AND player=? AND id % ?=0
                   ORDER BY id LIMIT ?""", (session_id, player, step, limit)).fetchall()
        return [dict(row) for row in rows]

    def session_samples_page(self, session_id, player="p1", limit=1000, offset=0):
        with self._reader() as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM telemetry_samples WHERE session_id=? AND player=?",
                (session_id, player)).fetchone()[0]
            rows = conn.execute(
                """SELECT id,session_time,frame,lap_num,lap_distance,speed_kmh,
                   gear,throttle,brake,steer,position,fuel_kg,ers_store_j,
                   tyre_compound,tyre_age,tyre_wear_rl,tyre_wear_rr,
                   tyre_wear_fl,tyre_wear_fr FROM telemetry_samples
                   WHERE session_id=? AND player=? ORDER BY id LIMIT ? OFFSET ?""",
                (session_id, player, limit, max(0, offset))).fetchall()
        return [dict(row) for row in rows], count

    def session_style(self, session_id, player="p1"):
        with self._reader() as conn:
            row = conn.execute(
                "SELECT * FROM style_metrics WHERE session_id=? AND player=?",
                (session_id, player)).fetchone()
        return dict(row) if row else {}

    def session_setup(self, session_id, player="p1"):
        with self._reader() as conn:
            row = conn.execute(
                "SELECT captured_at,setup_json FROM setups WHERE session_id=? AND player=?",
                (session_id, player)).fetchone()
        if not row:
            return {}
        try:
            setup = json.loads(row["setup_json"])
        except (TypeError, ValueError):
            setup = {}
        setup["captured_at"] = row["captured_at"]
        return setup

    def strategy_context(self, session_id, player="p1"):
        """Return one compact, read-only snapshot for the Strategy Lab."""
        info = self.session_details(session_id)
        if not info:
            return {}
        with self._reader() as conn:
            latest = conn.execute(
                """SELECT lap_num,position,fuel_kg,fuel_remaining_laps,
                   tyre_compound,tyre_age,tyre_wear_rl,tyre_wear_rr,
                   tyre_wear_fl,tyre_wear_fr,ers_store_j
                   FROM telemetry_samples WHERE session_id=? AND player=?
                   ORDER BY id DESC LIMIT 1""", (session_id, player)).fetchone()
            pace = conn.execute(
                """SELECT MIN(CASE WHEN valid=1 AND lap_time_ms>0 THEN lap_time_ms END),
                   AVG(CASE WHEN valid=1 AND lap_time_ms>0 THEN lap_time_ms END)
                   FROM laps WHERE session_id=? AND player=?""",
                (session_id, player)).fetchone()
        context = dict(info)
        context["latest"] = dict(latest) if latest else {}
        context["measured_best_lap_ms"] = pace[0] if pace else None
        context["measured_avg_lap_ms"] = pace[1] if pace else None
        context["profile"] = self.get_profile(info.get("track_name"), player)
        return context

    def current_session_id(self):
        return self.session_id

    def close(self):
        with self.lock:
            self._maybe_commit(True)
            self.conn.close()
