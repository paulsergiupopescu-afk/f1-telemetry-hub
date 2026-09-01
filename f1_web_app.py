"""Premium WebView application shell and versioned live snapshot bridge."""

from __future__ import annotations

import glob
import os
import queue
import statistics
import sys
import threading
import time

from f1_26_split_telemetry import ERS_MODE, Shared, VISUAL_TYRE, fmt_ms
from f1_ai_engineer import AIEngineerError, OpenAIRaceEngineer
from f1_behavior_tracker import BehaviorTracker
from f1_database import TelemetryDatabase
from f1_driver_learning import DriverLearning
from f1_community_reference import get_reference
from f1_setup_packages import SOURCE as SETUP_PACKAGE_SOURCE, package_data
from f1_engineer import RaceEngineer
from f1_live_strategy import LiveStrategyEngine
from f1_setup_library import get_setup, tracks
from f1_solo import DeltaEngine, PaceTracker, SoloReceiver, drive_phase, drs_state
from f1_strategy import Scenario, StrategyEngine, format_race_time
from f1_track_data import projected_track
from f1_ui import apply_webview_icon, resource_path


WEATHER = {0: "Clear", 1: "Light cloud", 2: "Overcast", 3: "Light rain",
           4: "Heavy rain", 5: "Storm"}


def runtime_data_root():
    """Choose a stable data folder for source and packaged repository runs."""
    if not getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(__file__))
    executable_dir = os.path.dirname(os.path.abspath(sys.executable))
    project_dir = os.path.dirname(executable_dir)
    if (os.path.basename(executable_dir).casefold() == "dist" and
            os.path.isfile(os.path.join(project_dir, "F1TelemetryHub.spec"))):
        return project_dir
    return executable_dir


def webview_storage_root():
    """Use a writable, persistent WebView2 profile for faster reliable starts."""
    parent = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    if not parent:
        parent = os.path.join(os.path.expanduser("~"), ".f1-telemetry-hub")
    path = os.path.join(parent, "F1TelemetryHub", "WebView2")
    os.makedirs(path, exist_ok=True)
    return path
LENGTHS = {2: "3 laps", 3: "5 laps", 4: "25%", 5: "35%", 6: "50%", 7: "100%"}


def _damage(dmg):
    if not dmg:
        return {}
    return {
        "tyre_damage": max(dmg[4:8]), "front_wing_left": dmg[16],
        "front_wing_right": dmg[17], "rear_wing": dmg[18], "floor": dmg[19],
        "diffuser": dmg[20], "sidepod": dmg[21],
    }


def describe_prerace_result(result, scenario, profile, rank):
    """Turn a terse optimizer result into an actionable, explainable plan."""
    starts = [scenario.current_lap, *result.stops]
    ends = [lap - 1 for lap in result.stops] + [scenario.total_laps]
    compounds = [scenario.current_compound, *result.compounds]
    stints = [{"compound": compound, "start": start, "end": end,
               "laps": max(0, end - start + 1)}
              for compound, start, end in zip(compounds, starts, ends)]
    why = []
    if result.stops:
        first_stop = result.stops[0]
        trace_index = max(0, min(len(result.wear_trace) - 1,
                                 first_stop - scenario.current_lap - 1))
        stop_wear = result.wear_trace[trace_index] if result.wear_trace else 0
        final_stint = stints[-1]
        why.append(
            f"Pit on Lap {first_stop}: the opening {scenario.current_compound} stint is "
            f"projected near {stop_wear:.0f}% wear before its lap-time loss accelerates.")
        why.append(
            f"Fit {result.compounds[0]} for {stints[1]['laps']} laps"
            + (f"; projected finish wear is {result.finish_wear:.0f}%."
               if len(stints) == 2 else "; the remaining stint sequence controls degradation."))
    else:
        why.append(
            f"Stay out: paying the {scenario.pit_loss:.0f}s pit loss is slower than managing "
            f"the current {scenario.current_compound} to the finish.")
        why.append(f"Projected finish wear is {result.finish_wear:.0f}%.")
    if rank == 1:
        why.append("This is the fastest valid plan in the current simulation after pit loss, traffic and tyre degradation.")
    else:
        why.append(f"This alternative costs {result.delta:.2f}s versus the primary plan but may offer a different risk profile.")
    if profile.get("wear_per_lap") or profile.get("fuel_per_lap"):
        why.append(
            f"Personal calibration: {profile.get('wear_per_lap') or scenario.wear_per_lap:.2f}% wear/lap, "
            f"{profile.get('fuel_per_lap') or scenario.fuel_per_lap:.2f} kg fuel/lap.")
    else:
        why.append("No representative personal long run exists yet, so conservative default wear and fuel rates are used.")
    instruction = "STAY OUT TO THE FINISH"
    if result.stops:
        calls = [f"PIT LAP {lap} → FIT {compound.upper()}" for lap, compound in
                 zip(result.stops, result.compounds)]
        instruction = "START " + scenario.current_compound.upper() + " · " + " · THEN ".join(calls)
        if len(calls) == 1:
            instruction += " TO FINISH"
    return {"instruction": instruction, "stints": stints, "why": why,
            "uncertainty": round(result.confidence_seconds, 2)}


def build_live_coach(player, session, race_control, strategy, ers, damage,
                     gap_ahead, name_ahead, gaps_behind, pace, micro=None):
    """Build explicit calls and an evidence-based explanation of lap-time loss."""
    phase = (race_control or {}).get("phase") or "GREEN"
    position = int((player or {}).get("position") or 0)
    battery = int((ers or {}).get("battery_pct") or (player or {}).get("ers_pct") or 0)
    behind_name, behind_gap = gaps_behind[0] if gaps_behind else (None, None)
    action = (strategy or {}).get("action")

    values = [int(row.get("time_ms") or 0) for row in pace or []
              if 30_000 <= int(row.get("time_ms") or 0) <= 300_000]
    clean = []
    if values:
        centre = statistics.median(values)
        clean = [value for value in values if .93 * centre <= value <= 1.07 * centre]
    average = round(sum(clean) / len(clean)) if clean else 0
    last = clean[-1] if clean else 0
    prior_average = (round(sum(clean[:-1]) / len(clean[:-1]))
                     if len(clean) >= 2 else 0)
    delta_average = last - average if average and last else 0
    delta_prior = last - prior_average if prior_average and last else 0
    slope = ((clean[-1] - clean[0]) / max(1, len(clean) - 1)) if len(clean) >= 2 else 0
    trend = "IMPROVING" if slope < -150 else ("FADING" if slope > 150 else "STABLE")

    if phase == "RED_FLAG":
        drive_title, drive_detail = "STOP — RED FLAG", "No tactical driving or pit call until restart calibration completes."
    elif action == "PIT NOW":
        drive_title, drive_detail = "BOX THIS LAP", (strategy or {}).get("detail") or "Commit to pit entry."
    elif position == 1 and behind_gap is not None and behind_gap <= 1.05:
        drive_title = "DEFEND THE LEAD"
        drive_detail = f"{behind_name} is {behind_gap:.2f}s behind · prioritise exits and force them to spend ERS."
    elif gap_ahead is not None and gap_ahead <= 1.05:
        if battery >= 35:
            drive_title = "ATTACK NOW"
            drive_detail = f"{name_ahead} is {gap_ahead:.2f}s ahead · deploy on the best acceleration exit."
        else:
            drive_title = "WAIT — BUILD BATTERY"
            drive_detail = f"{name_ahead} is in range, but ERS is only {battery}% · stay in the tow."
    elif behind_gap is not None and behind_gap <= 1.05:
        drive_title = "DEFEND"
        drive_detail = f"{behind_name} is {behind_gap:.2f}s behind · protect the next exit."
    elif position == 1:
        drive_title, drive_detail = "CONTROL THE LEAD", "Normal pace · preserve ERS and avoid unnecessary tyre sliding."
    else:
        drive_title, drive_detail = "HOLD POSITION", "Normal pace while the next attack/defence window develops."

    ers_title = f"{(ers or {}).get('action') or 'HOLD'} · {battery}%"
    ers_detail = (ers or {}).get("detail") or "Build charge for the next useful acceleration zone."
    wears = list((player or {}).get("tyre_wear") or [0, 0, 0, 0])
    temps = list((player or {}).get("tyre_temps") or [0, 0, 0, 0])
    corners = ("RL", "RR", "FL", "FR")
    worst_index = max(range(min(4, len(wears))), key=lambda i: wears[i]) if wears else 0
    hot_index = max(range(min(4, len(temps))), key=lambda i: temps[i]) if temps else 0
    if temps and temps[hot_index] >= 115:
        tyre_title = f"COOL {corners[hot_index]} · {temps[hot_index]:.0f}°C"
        tyre_detail = "Stop sliding/locking that corner; use a cleaner brake release and exit."
    elif wears and max(wears) >= 70:
        tyre_title = f"TYRE SAVE · {corners[worst_index]} {wears[worst_index]:.0f}%"
        tyre_detail = "Reduce slip and avoid kerbs until the pit decision is confirmed."
    elif wears and max(wears) - min(wears) >= 1.0:
        tyre_title = f"PROTECT {corners[worst_index]} · {wears[worst_index]:.1f}%"
        tyre_detail = "This is the limiting tyre; avoid repeated lock-up or wheelspin."
    else:
        tyre_title = f"NORMAL PACE · {max(wears or [0]):.1f}%"
        tyre_detail = "Tyre state is balanced; no saving is required right now."

    # Diagnose only from telemetry we can actually observe. Causes are ordered by
    # how strongly they can explain time loss and each cause has a concrete fix.
    wing = max(float((damage or {}).get("front_wing_left") or 0),
               float((damage or {}).get("front_wing_right") or 0))
    wear_spread = max(wears or [0]) - min(wears or [0])
    hot_temp = float(temps[hot_index]) if temps else 0
    losing_micro = [int(row.get("index") or 0) + 1 for row in micro or []
                    if float(row.get("delta") or 0) > .035]
    causes, fixes, evidence = [], [], []
    if wing >= 15:
        causes.append(f"{wing:.0f}% front-wing damage is reducing front grip and braking stability.")
        fixes.append("Brake slightly earlier, release smoothly, and avoid forcing mid-corner rotation.")
        if wing >= 35:
            fixes.append("Prepare to box: this damage is large enough to dominate lap time.")
    if hot_temp >= 110:
        causes.append(f"The {corners[hot_index]} tyre is overheating at {hot_temp:.0f}°C, usually from sliding, wheelspin, or locking.")
        fixes.append(f"Cool {corners[hot_index]}: use one progressive input, short-shift on exit, and avoid scrubbing steering.")
    if battery <= 15 and phase == "GREEN":
        causes.append(f"ERS is only {battery}%, so acceleration and straight-line defence are compromised.")
        fixes.append("Harvest for one lap; deploy only to defend or complete a certain pass.")
    if wear_spread >= 2.0:
        causes.append(f"Tyre wear is imbalanced by {wear_spread:.1f}%; {corners[worst_index]} is the limiting corner.")
        fixes.append(f"Protect {corners[worst_index]} with a cleaner brake release and less exit wheelspin.")
    if gap_ahead is not None and gap_ahead <= 1.05:
        causes.append(f"Traffic behind {name_ahead or 'the car ahead'} is costing front grip in dirty air.")
        if battery >= 35:
            fixes.append("Prioritise the exit before the longest straight, then use ERS to finish the pass.")
        else:
            fixes.append("Stay in the tow, rebuild ERS, and avoid overheating the fronts in dirty air.")
    if trend == "FADING" and len(clean) >= 3:
        causes.append(f"Clean-lap pace is fading by about {abs(slope) / 1000:.2f}s per lap.")
        fixes.append("Reduce sliding for one lap and compare the next lap before changing the strategy.")
    if losing_micro:
        shown = ", ".join(str(index) for index in losing_micro[:4])
        evidence.append(f"Current reference loss appears in micro-sectors {shown}.")

    if len(clean) >= 2:
        sign = "+" if delta_prior >= 0 else ""
        evidence.insert(0, f"Last lap {sign}{delta_prior / 1000:.3f}s versus the previous clean-lap average.")
    if wing:
        evidence.append(f"Front-wing damage: {wing:.0f}%.")
    evidence.append(f"ERS {battery}% · tyre spread {wear_spread:.1f}% · hottest tyre {hot_temp:.0f}°C.")

    if phase == "RED_FLAG":
        diagnosis_title = "ANALYSIS PAUSED — RED FLAG"
        diagnosis_summary = "Old gaps and current-lap comparisons are invalid during the stoppage."
        fixes = ["Wait for fresh moving telemetry after the restart; the app will rebuild the diagnosis."]
        diagnosis_state = "neutral"
    elif len(clean) < 2:
        diagnosis_title = f"LEARNING YOUR PACE · {len(clean)}/2 LAPS"
        diagnosis_summary = "A reliable loss comparison needs two clean completed laps. Live car-state warnings remain active."
        fixes = fixes[:2] or ["Drive a clean representative lap; avoid unnecessary ERS use and tyre sliding."]
        diagnosis_state = "learning"
    elif delta_prior > 250:
        diagnosis_title = f"LOSING {delta_prior / 1000:.3f}s VS RECENT PACE"
        diagnosis_summary = causes[0] if causes else "The lap was slower, but telemetry does not show a single dominant mechanical cause."
        fixes = fixes[:2] or ["Repeat your normal references; prioritise clean braking and exits before pushing harder."]
        diagnosis_state = "losing"
    elif delta_prior < -250:
        diagnosis_title = f"GAINING {abs(delta_prior) / 1000:.3f}s VS RECENT PACE"
        diagnosis_summary = "The last lap improved. Keep the same braking references and exit technique."
        fixes = ["Repeat the inputs that worked; do not spend extra ERS unless the tactical call changes."]
        diagnosis_state = "gaining"
    else:
        diagnosis_title = "PACE ON TARGET"
        diagnosis_summary = "The last lap is within 0.25s of your recent clean-lap level."
        fixes = fixes[:1] or ["Keep the same references and build consistency; no corrective change is needed."]
        diagnosis_state = "stable"

    strategy_title = (strategy or {}).get("headline") or "STRATEGY CALIBRATING"
    strategy_detail = (strategy or {}).get("detail") or "Collecting reliable race context."
    return {
        "drive": {"title": drive_title, "detail": drive_detail},
        "ers": {"title": ers_title, "detail": ers_detail},
        "tyres": {"title": tyre_title, "detail": tyre_detail},
        "strategy": {"title": strategy_title, "detail": strategy_detail},
        "pace": {"average_ms": average, "last_ms": last,
                 "last_vs_average_ms": delta_average, "trend": trend,
                 "clean_laps": len(clean), "prior_average_ms": prior_average},
        "diagnosis": {"state": diagnosis_state, "title": diagnosis_title,
                      "summary": diagnosis_summary, "actions": fixes[:2],
                      "evidence": evidence[:3],
                      "confidence": "HIGH" if len(clean) >= 5 else
                                    ("MEDIUM" if len(clean) >= 2 else "LEARNING")},
    }


class SnapshotBroker(threading.Thread):
    """Own mutable presentation logic and publish immutable JSON-ready snapshots."""

    def __init__(self, shared, receiver, database, behavior=None):
        super().__init__(daemon=True)
        self.shared, self.receiver, self.database = shared, receiver, database
        self.behavior = behavior
        self.delta = DeltaEngine()
        self.pace = PaceTracker()
        self.engineer = RaceEngineer()
        self.strategy = LiveStrategyEngine(database)
        self.learning = DriverLearning(database)
        self.running = True
        self._lock = threading.Lock()
        self._snapshot = self._empty()
        self._behavior_state = None
        self._session_identity = None
        self._profile = {}
        self._learned = {"stages": {}, "feedback": {}}
        self._learning_lap = None
        self._display_name = "SESSION --"
        self._track_map_key = None
        self._track_map = []

    @staticmethod
    def _empty():
        return {
            "schema_version": 1, "generated_at": time.time(),
            "connection": {"live": False, "packets": 0, "warning": ""},
            "session": {}, "race_control": {"phase": "GREEN", "events": []},
            "player": {}, "lap": {}, "delta": {}, "tyres": [], "field": [],
            "pace": [], "micro_sectors": [], "engineer": {"mode": "HOLD"},
            "strategy": {}, "ers": {}, "coach": {}, "track_map": [], "split": {},
        }

    def snapshot(self):
        with self._lock:
            return dict(self._snapshot)

    def stop(self):
        self.running = False

    def run(self):
        while self.running:
            started = time.monotonic()
            try:
                value = self._build()
                behavior_state = (
                    bool((value.get("connection") or {}).get("live")),
                    (value.get("race_control") or {}).get("phase"),
                    (value.get("strategy") or {}).get("action"),
                    (value.get("strategy") or {}).get("target_lap"),
                    (value.get("strategy") or {}).get("compound"),
                )
                if self.behavior and behavior_state != self._behavior_state:
                    previous = self._behavior_state
                    self._behavior_state = behavior_state
                    self.behavior.log(
                        "live_state_changed", previous=previous, current=behavior_state,
                        session=(value.get("session") or {}).get("display_name"))
                with self._lock:
                    self._snapshot = value
            except Exception as exc:
                if self.behavior:
                    self.behavior.log("snapshot_error", level="error",
                                      error=type(exc).__name__, message=str(exc))
                with self._lock:
                    self._snapshot["connection"]["warning"] = f"Snapshot error: {exc}"
            delay = .1 - (time.monotonic() - started)
            if delay > 0:
                time.sleep(delay)

    def _build(self):
        with self.shared.lock:
            p1, p2 = self.shared.p1, self.shared.p2
            session = dict(self.shared.session)
            race_control = dict(self.shared.race_control)
            player_index = self.shared.p1_idx
            values = {
                "tel": p1.tel, "lap": p1.lap, "status": p1.status, "dmg": p1.dmg,
                "setup": dict(p1.setup or {}), "name": p1.name,
                "best_ms": p1.best_lap_ms, "p2_tel": p2.tel, "p2_lap": p2.lap,
                "p2_status": p2.status, "p2_name": p2.name,
                "packets": self.shared.packets, "last": self.shared.last_packet_time,
                "session_index": self.shared.session_index,
                "database_id": self.shared.session_database_id,
                "format": self.shared.packet_format, "warning": self.shared.warning,
            }
        tel, lap, status, dmg = values["tel"], values["lap"], values["status"], values["dmg"]
        live = time.time() - values["last"] < 2
        identity = (values["database_id"], values["session_index"])
        if identity != self._session_identity:
            self._session_identity = identity
            self.delta.reset(); self.pace.reset(); self.engineer.reset(); self.strategy.reset()
            profile = self.learning.strategy_profile(session.get("track"))
            self._profile = profile
            self._learned = self.learning.profile(session.get("track"))
            self._learning_lap = lap[14] if lap else None
            detail = self.database.session_details(values["database_id"]) if values["database_id"] else {}
            self._display_name = detail.get("display_name") or f"SESSION {values['session_index']:02d}"
            self.engineer.set_learned_profile(
                profile, self.database.setup_recommendations(session.get("track")))
        else:
            profile = self._profile
            current_lap = lap[14] if lap else None
            if current_lap is not None and current_lap != self._learning_lap:
                self._learning_lap = current_lap
                self._learned = self.learning.profile(session.get("track"))
                self._profile = self.learning.strategy_profile(session.get("track"))
                profile = self._profile
            if values["database_id"] and ("SESSION 00" in self._display_name or
                                           self._display_name == "SESSION --"):
                detail = self.database.session_details(values["database_id"])
                self._display_name = detail.get("display_name") or self._display_name

        raw_field = self.receiver.field_snapshot()
        my_row = next((item for item in raw_field if item.get("index") == player_index), {})
        my_distance = my_row.get("total_distance") or (lap[11] if lap else 0)
        metres_per_second = max(tel[0] if tel else 0, 40) / 3.6
        field = []
        for car in raw_field:
            item = dict(car)
            item["gap_to_player"] = round((my_distance - car.get("total_distance", 0)) /
                                           metres_per_second, 2)
            field.append(item)

        gap_ahead, name_ahead, behind = self.receiver.all_gaps(
            player_index, tel[0] if tel else 0) if player_index is not None else (None, None, [])
        delta_value = self.delta.update(lap) if live else None
        self.pace.feed(lap)
        session["packet_format"] = values["format"]
        messages = []
        tactical_hold = race_control.get("phase") in {"RED_FLAG", "FORMATION", "RESTARTING"}
        if live and not tactical_hold and not race_control.get("finished"):
            _, messages = self.engineer.update(
                tel, lap, status, dmg, time.time(), total_laps=session.get("laps"),
                gap_ahead=gap_ahead, name_ahead=name_ahead, gaps_behind=behind,
                session_type=session.get("type"), session=session,
                packet_format=values["format"])

        wear = [round(float(value), 1) for value in dmg[:4]] if dmg else [0, 0, 0, 0]
        temps = list(tel[14:18]) if tel else [0, 0, 0, 0]
        compound = VISUAL_TYRE.get(status[14], str(status[14])) if status else None
        player = {
            "name": values["name"] or "YOU", "speed_kmh": tel[0] if tel else 0,
            "throttle": tel[1] if tel else 0, "brake": tel[3] if tel else 0,
            "gear": tel[5] if tel else 0, "rpm": tel[6] if tel else 0,
            "position": lap[13] if lap else None, "lap_num": lap[14] if lap else None,
            "pit_status": lap[15] if lap else 0, "pit_stops": lap[16] if lap else 0,
            "lap_distance": lap[10] if lap else 0, "total_distance": lap[11] if lap else 0,
            "compound": compound, "tyre_age": status[15] if status else None,
            "tyre_wear": wear, "tyre_temps": temps,
            "fuel_kg": round(status[5], 2) if status else None,
            "fuel_delta_laps": round(status[7], 2) if status else None,
            "ers_pct": round(max(0, min(100, status[19] / 4_000_000 * 100))) if status else 0,
            "ers_mode": ("Boost" if values["format"] == 2026 and status and status[20] == 3
                         else ERS_MODE.get(status[20], "--") if status else "--"),
            "best_lap_ms": values["best_ms"],
        }
        strategy_context = {
            "session": session, "race_control": race_control, "player": player,
            "field": field, "profile": profile, "damage": _damage(dmg),
        }
        strategy = self.strategy.update(strategy_context)

        learned = self._learned
        session_name = str(session.get("type") or "").casefold()
        learning_phase = ("time_trial" if "time trial" in session_name else
                          "race" if session_name.startswith("race") else
                          "qualifying" if ("q" in session_name or "qual" in session_name) else
                          "practice")
        phase_feedback = learned.get("feedback", {}).get(learning_phase, [])

        message_rows = [{"priority": item.prio, "title": item.title,
                         "detail": item.detail, "key": item.key}
                        for item in messages[:5]]
        if phase_feedback:
            item = phase_feedback[0]
            message_rows.append({"priority": 3, "title": item["title"],
                                 "detail": item["detail"], "key": "driver_learning"})
        if race_control.get("finished"):
            engineer = {"mode": "HOLD", "title": "CHEQUERED FLAG — SESSION COMPLETE",
                        "detail": "Tactical calls closed. Your detailed report is being prepared.",
                        "queue": []}
        elif race_control.get("phase") == "RED_FLAG":
            engineer = {"mode": "RED_FLAG", "title": "RED FLAG — SESSION SUSPENDED",
                        "detail": "Strategy frozen until restart telemetry stabilizes.",
                        "queue": []}
        elif race_control.get("phase") in {"FORMATION", "RESTARTING"}:
            engineer = {"mode": "HOLD", "title": strategy.get("headline"),
                        "detail": strategy.get("detail"), "queue": []}
        elif strategy.get("action") == "PIT NOW":
            engineer = {"mode": "PIT", "title": strategy.get("headline"),
                        "detail": strategy.get("detail"), "queue": message_rows}
        elif strategy.get("change_reason") == "Opening-lap strategy guard":
            engineer = {
                "mode": "HOLD", "title": strategy.get("headline"),
                "detail": strategy.get("detail"),
                "queue": [
                    {"priority": 2, "title": "ERS",
                     "detail": "Recharge out of combat; deploy only to attack or defend",
                     "key": "opening_ers"},
                    {"priority": 2, "title": "TYRES",
                     "detail": "Normal pace; avoid wheelspin and sliding",
                     "key": "opening_tyres"},
                    {"priority": 2, "title": "NEXT REVIEW",
                     "detail": "Lap 6, or immediately for damage, rain, SC/VSC",
                     "key": "opening_review"},
                ],
            }
        elif message_rows:
            title = message_rows[0]["title"]
            mode = "ATTACK" if title.startswith("ATTACK") else (
                "DEFEND" if title.startswith("DEFEND") else "HOLD")
            engineer = {"mode": mode, "title": title,
                        "detail": message_rows[0]["detail"], "queue": message_rows[1:]}
        else:
            engineer = {"mode": "HOLD", "title": strategy.get("headline", "BUILD RHYTHM"),
                        "detail": strategy.get("detail", "Collecting live context"), "queue": []}

        micro = [{"index": index, "delta": value}
                 for index, value in enumerate(self.engineer.micro.seg_delta)]
        # The track map is static for a circuit. Rebuild the rounded drawing
        # list only when the session's circuit changes, not on every 10 Hz
        # snapshot; otherwise a ~280-point list is re-projected and re-shipped
        # in the JSON payload ten times a second.
        track_map_key = (session.get("track"), session.get("track_id"))
        if track_map_key != self._track_map_key:
            self._track_map_key = track_map_key
            projected = projected_track(track_map_key[0], track_map_key[1], 280, 145, 8, 280)
            self._track_map = [[round(x, 1), round(y, 1)] for _, x, y, _, _ in projected]
        p2_lap, p2_tel, p2_status = values["p2_lap"], values["p2_tel"], values["p2_status"]
        ers_snapshot = self.engineer.ers.snapshot()
        coach = build_live_coach(
            player, session, race_control, strategy, ers_snapshot, _damage(dmg),
            gap_ahead, name_ahead, behind,
            [{"lap": n, "time_ms": ms} for n, ms in self.pace.laps[-16:]], micro)
        return {
            "schema_version": 1, "generated_at": time.time(),
            "connection": {"live": live, "packets": values["packets"],
                           "warning": values["warning"], "udp_format": values["format"],
                           "session_index": values["session_index"]},
            "session": {**session, "weather_name": WEATHER.get(session.get("weather"), "--"),
                        "length_name": LENGTHS.get(session.get("session_length"), ""),
                        "display_name": self._display_name},
            "race_control": race_control, "player": player,
            "lap": {"current_ms": lap[1] if lap else 0, "last_ms": lap[0] if lap else 0,
                    "best_ms": values["best_ms"], "s1_ms": lap[2]+lap[3]*60000 if lap else 0,
                    "s2_ms": lap[4]+lap[5]*60000 if lap else 0,
                    "sector": lap[17] if lap else 0, "invalid": bool(lap[18]) if lap else False,
                    "penalties": lap[19] if lap else 0, "warnings": lap[20] if lap else 0,
                    "cuts": lap[21] if lap else 0,
                    "predicted_ms": int(values["best_ms"] + delta_value*1000)
                    if values["best_ms"] and delta_value is not None else 0},
            "delta": {"seconds": round(delta_value, 3) if delta_value is not None else None,
                      "progress": min(1, max(0, (lap[10] / self.delta.ref_d[-1])))
                      if lap and self.delta.ref_d is not None and self.delta.ref_d[-1] else 0},
            "tyres": [{"corner": corner, "wear": wear[index], "temp": temps[index],
                       "predicted": round(max(0, (profile.get("wear_per_lap") or 1.6) *
                                                (status[15] if status else 0)), 1)}
                      for index, corner in enumerate(("RL", "RR", "FL", "FR"))],
            "field": field, "pace": [{"lap": n, "time_ms": ms} for n, ms in self.pace.laps[-16:]],
            "micro_sectors": micro, "engineer": engineer, "strategy": strategy,
            "ers": ers_snapshot, "coach": coach,
            "track_map": self._track_map,
            "drive": {"phase": drive_phase(tel, status)[0],
                      "aero": drs_state(tel, status, values["format"] or 2025)[0]},
            "damage": _damage(dmg),
            "learning": {"phase": learning_phase,
                         "profile": learned.get("stages", {}).get(learning_phase, {}),
                         "feedback": phase_feedback},
            "split": {"name": values["p2_name"], "speed_kmh": p2_tel[0] if p2_tel else 0,
                      "position": p2_lap[13] if p2_lap else None,
                      "lap_num": p2_lap[14] if p2_lap else None,
                      "compound": VISUAL_TYRE.get(p2_status[14], "--") if p2_status else "--",
                      "fuel_kg": round(p2_status[5], 2) if p2_status else None},
        }


class AppBridge:
    def __init__(self, host):
        self.host = host

    def get_bootstrap(self):
        diagnostics = self.host.behavior.summary()
        return {"app": "F1 Telemetry Hub", "version": 3, "mode": self.host.mode,
                "routes": ["home", "solo", "split", "prerace", "strategy",
                           "sessions", "profile", "reports"],
                "tracks": list(tracks()), "sessions": self.host.database.list_sessions(8),
                "diagnostics": {"enabled": diagnostics["enabled"],
                                "run_id": diagnostics["run_id"],
                                "folder": diagnostics["folder"],
                                "privacy": diagnostics["privacy"]}}

    def get_live_snapshot(self):
        return self.host.broker.snapshot()

    def set_mode(self, mode):
        if mode in ("solo", "split"):
            self.host.mode = mode
        return {"mode": self.host.mode}

    def get_sessions(self, limit=200):
        return self.host.database.list_sessions(max(1, min(500, int(limit))))

    def get_session(self, session_id):
        return self.host.learning.session_report(int(session_id))

    def get_profile(self, track=None):
        return self.host.learning.profile(track)

    def calculate_prerace(self, options):
        started = time.monotonic()
        options = options or {}
        setup = get_setup(options.get("track")) or get_setup(tracks()[0])
        factor = {"25%": .5, "35%": .7, "50%": 1.0, "100%": 2.0}.get(
            options.get("distance"), 1.0)
        total = max(5, round(setup["race_laps_50"] * factor))
        profile = self.host.learning.strategy_profile(setup["track"])
        scenario = Scenario(
            total_laps=total, base_lap_seconds=setup["baseline_lap_seconds"],
            current_compound=options.get("compound") or "Medium", current_wear=0,
            fuel_kg=total * (profile.get("fuel_per_lap") or 1.8) + .5,
            fuel_per_lap=profile.get("fuel_per_lap") or 1.8,
            wear_per_lap=profile.get("wear_per_lap") or 1.6,
            pit_loss=float(options.get("pit_loss") or setup["pit_loss_seconds"]),
            traffic=float(options.get("traffic") or 25)/100,
            rain=float(options.get("rain") or 0)/100,
            consistency_seconds=(profile.get("pace_consistency_ms") or 500)/1000)
        results = StrategyEngine().generate(scenario, 12)
        setup = dict(setup)
        setup["community_source"] = "F1 Game Setup · F1 2026"
        setup["community_url"] = "https://www.f1gamesetup.com/car-setup/f1-2026"
        setup["community_policy"] = (
            "Compare the same circuit, car, controller, weather and session type. "
            "Time Trial setups are raw-pace references, not race tyre/ERS baselines.")
        setup["personal_adaptations"] = self.host.database.setup_recommendations(setup["track"])
        setup["community_sheet"] = get_reference(setup["track"])
        setup["brendon_package"] = package_data(setup["track"])
        setup["package_available"] = bool(setup["brendon_package"])
        setup["package_source"] = SETUP_PACKAGE_SOURCE
        normalized_options = {
            "track": setup["track"], "distance": options.get("distance") or "50%",
            "compound": options.get("compound") or "Medium",
            "rain": float(options.get("rain") or 0),
            "traffic": float(options.get("traffic") or 25),
        }
        rows = []
        for index, result in enumerate(results):
            row = {
                "rank": index + 1, "label": result.label,
                "stops": list(result.stops), "compounds": list(result.compounds),
                "time": format_race_time(result.total_seconds),
                "delta": round(result.delta, 2),
                "finish_wear": round(result.finish_wear, 1),
                "wear_trace": [round(x, 2) for x in result.wear_trace],
            }
            row.update(describe_prerace_result(result, scenario, profile, index + 1))
            rows.append(row)
        response = {"setup": setup, "profile": profile, "options": normalized_options,
                    "inputs": {"total_laps": total, "pit_loss": scenario.pit_loss,
                               "wear_per_lap": scenario.wear_per_lap,
                               "fuel_per_lap": scenario.fuel_per_lap,
                               "traffic": scenario.traffic, "rain": scenario.rain},
                    "results": rows}
        self.host.behavior.log(
            "prerace_plan_calculated", track=setup["track"],
            distance=normalized_options["distance"], compound=normalized_options["compound"],
            rain=normalized_options["rain"], traffic=normalized_options["traffic"],
            primary=rows[0]["instruction"] if rows else None,
            duration_ms=round((time.monotonic() - started) * 1000, 1))
        return response

    def log_client_event(self, event, details=None):
        """Receive a small, sanitized UI behavior or error event."""
        if event == "frontend_ready":
            self.host.frontend_ready.set()
        self.host.behavior.log(f"client_{str(event or 'unknown')[:60]}",
                               **(details if isinstance(details, dict) else {}))
        return {"ok": True}

    def get_diagnostics_summary(self):
        return self.host.behavior.summary()

    def open_diagnostics_folder(self):
        os.makedirs(self.host.behavior.folder, exist_ok=True)
        os.startfile(self.host.behavior.folder)
        self.host.behavior.log("diagnostics_folder_opened")
        return {"ok": True}

    def get_reports(self):
        paths = []
        for folder in ("solo_reports", "reports"):
            paths.extend(glob.glob(os.path.join(self.host.base, folder, "*")))
        return [{"name": os.path.basename(path), "path": path,
                 "modified": os.path.getmtime(path)} for path in
                sorted(paths, key=os.path.getmtime, reverse=True)[:200]]

    def open_path(self, path):
        path = os.path.abspath(path)
        if (os.path.commonpath((path, os.path.abspath(self.host.base))) !=
                os.path.abspath(self.host.base) or not os.path.exists(path)):
            return {"ok": False}
        os.startfile(path)
        return {"ok": True}

    def open_external(self, url):
        from urllib.parse import urlparse
        parsed = urlparse(str(url))
        allowed = {"www.f1gamesetup.com", "simracingconfigs.com", "www.ea.com",
                   "forums.ea.com", "openf1.org", "docs.fastf1.dev"}
        if parsed.scheme != "https" or parsed.hostname not in allowed:
            return {"ok": False}
        os.startfile(url)
        return {"ok": True}

    def open_reports_folder(self):
        folder = os.path.join(self.host.base, "solo_reports")
        os.makedirs(folder, exist_ok=True); os.startfile(folder)
        return {"ok": True}

    def ask_engineer(self, question, api_key=""):
        try:
            client = OpenAIRaceEngineer(api_key=api_key)
            return {"ok": True, **client.advise(self.host.broker.snapshot(), question)}
        except AIEngineerError as exc:
            return {"ok": False, "error": str(exc)}

    def toggle_fullscreen(self):
        if self.host.window:
            self.host.window.toggle_fullscreen()
        return {"ok": True}

    def shutdown(self):
        if self.host.window:
            self.host.window.destroy()
        return {"ok": True}


class WebApplication:
    def __init__(self, port=20777, mode="solo", fullscreen=False):
        self.base = runtime_data_root()
        self.mode, self.fullscreen, self.window = mode, fullscreen, None
        self.behavior = BehaviorTracker(self.base, app_version=3)
        self.database = TelemetryDatabase(os.path.join(self.base, "f1_telemetry.db"))
        recovery = self.database.import_legacy_csv_folder(
            os.path.join(self.base, "solo_reports"))
        if recovery.get("sessions"):
            self.behavior.log("legacy_sessions_recovered", **recovery)
        self.learning = DriverLearning(self.database)
        self.shared, self.notifications = Shared(), queue.Queue()
        self.receiver = SoloReceiver(self.shared, port, os.path.join(self.base, "solo_reports"),
                                     self.notifications, self.database)
        self.broker = SnapshotBroker(self.shared, self.receiver, self.database, self.behavior)
        self.bridge = AppBridge(self)
        self._stop_lock = threading.Lock()
        self._stopped = False
        self.frontend_ready = threading.Event()
        self._webview_finished = threading.Event()
        self._startup_error = None

    def _watch_frontend_startup(self):
        """Escape a blank WebView window instead of hanging indefinitely."""
        # pywebview starts this callback just before it publishes the native
        # WinForms handle. It normally appears within a few hundred ms.
        icon_applied = False
        for _ in range(30):
            icon_applied = apply_webview_icon(self.window)
            if icon_applied:
                break
            time.sleep(0.1)
        self.behavior.log("native_icon_applied", success=icon_applied)
        # WebView2 cold starts on this machine have legitimately taken 22–24
        # seconds. Leave enough headroom to distinguish slow from stalled.
        if self.frontend_ready.wait(timeout=45.0) or self._webview_finished.is_set():
            return
        self._startup_error = RuntimeError(
            "WebView2 created a window but the dashboard did not become ready within 45 seconds.")
        self.behavior.log("frontend_start_timeout", level="error", timeout_seconds=45)
        if self.window:
            self.window.destroy()

    def start(self):
        # This dashboard does not need GPU rendering. Disabling it avoids
        # WebView2 startup failures caused by graphics-driver resets/watchdogs.
        os.environ.setdefault("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", "--disable-gpu")
        try:
            import webview
        except ImportError as exc:
            raise RuntimeError("pywebview is required. Run: pip install pywebview") from exc
        self.receiver.start()
        if not self.receiver.ready.wait(timeout=3.0):
            self.stop()
            raise RuntimeError(f"Telemetry receiver did not start on UDP port {self.receiver.port}.")
        if self.receiver.startup_error is not None:
            error = self.receiver.startup_error
            self.behavior.log("telemetry_start_error", level="error",
                              port=self.receiver.port, message=str(error))
            self.stop()
            raise RuntimeError(
                f"UDP port {self.receiver.port} is already in use. "
                "Close the other telemetry app and try again.") from error
        self.broker.start()
        self.behavior.log("telemetry_threads_started", port=self.receiver.port,
                          mode=self.mode)
        page = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web", "index.html") + "#solo"
        self.window = webview.create_window(
            "F1 TELEMETRY HUB", page, js_api=self.bridge, width=1600, height=950,
            min_size=(1050, 680), fullscreen=self.fullscreen, background_color="#111318")
        self.behavior.log("webview_created", width=1600, height=950,
                          fullscreen=self.fullscreen)
        try:
            webview.start(func=self._watch_frontend_startup,
                          gui="edgechromium", debug=False,
                          private_mode=False,
                          storage_path=webview_storage_root(),
                          icon=resource_path(os.path.join(
                              "assets", "race_command_icon_v2.ico")))
        except Exception as exc:
            self.behavior.log("webview_error", level="error",
                              error=type(exc).__name__, message=str(exc))
            self.stop()
            raise RuntimeError(
                "The WebView2 interface could not start; the safe interface will be used. "
                f"Technical detail: {type(exc).__name__}: {exc}") from exc
        finally:
            self._webview_finished.set()
        if self._startup_error is not None:
            error = self._startup_error
            self.stop()
            raise RuntimeError(
                "The WebView2 dashboard stalled during startup. "
                "The safe interface will be opened automatically.") from error
        self.stop()

    def stop(self):
        with self._stop_lock:
            if self._stopped:
                return
            self._stopped = True
        self.behavior.log("app_stop")
        self.broker.stop()
        self.receiver.running = False
        if self.receiver.is_alive():
            self.receiver.join(timeout=1.5)
        if self.broker.is_alive():
            self.broker.join(timeout=1.5)
        try:
            self.database.close()
        except Exception:
            pass
