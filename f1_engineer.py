#!/usr/bin/env python3
r"""Pure-logic virtual race-engineer insight engine.

Raw UDP telemetry is converted into actionable setup, ERS, fuel, pit-window,
undercut, micro-sector and corner guidance. Messages use priority 1 for critical
actions, priority 2 for strategy, and priority 3 for coaching.
"""
from collections import deque
from statistics import median

import numpy as np

from f1_track_data import load_track
from f1_community_reference import ENGINE_POWER_PCT, TYRE_TEMPERATURES_C

# Shared application palette.
RED = "#ff4257"
GREEN = "#2ee56b"
YELLOW = "#ffd447"
CYAN = "#27c4f5"
PURPLE = "#b47cff"
DIM = "#8a93a6"

# Adjustable strategy heuristics. Track-specific game data takes precedence.
PIT_LOSS_S = 21.0        # Average pit loss: entry, stationary time, and exit.
DIRTY_AIR_S = 2.0        # Below this gap the car is in dirty air.
UNDERCUT_GAIN_S = 1.5    # Conservative fresh-tyre gain on an out-lap.
ERS_MAX_J = 4_000_000.0
ERS_MODE_NAMES = {0: "None", 1: "Medium", 2: "Hotlap", 3: "Overtake/Boost"}


class Msg:
    __slots__ = ("prio", "title", "detail", "color", "key")

    def __init__(self, prio, title, detail="", color=YELLOW, key=None):
        self.prio = prio
        self.title = title
        self.detail = detail
        self.color = color
        self.key = key or title

    def __repr__(self):
        return f"<Msg p{self.prio} {self.title!r}>"


# ============================================================================
# 1. SETUP: brake bias and traction
# ============================================================================
class SetupAdvisor:
    """Detect front/rear thermal imbalance, wear imbalance, and wheelspin."""

    def __init__(self):
        self.temp_hist = deque(maxlen=240)   # (rear_avg, front_avg)
        self.wear_ref = None                 # (rear wear, front wear) at first sample
        self.spin_events = deque(maxlen=400)  # wheelspin timestamps
        self._last_speed = None
        self._last_t = None

    def feed(self, tel, dmg, t_now):
        """tel = CarTelemetry tuple, dmg = CarDamage tuple."""
        if not tel:
            return
        # Surface temperatures: 14=RL, 15=RR, 16=FL, 17=FR.
        rear = (tel[14] + tel[15]) / 2.0
        front = (tel[16] + tel[17]) / 2.0
        self.temp_hist.append((rear, front))
        if dmg:
            wr = (dmg[0] + dmg[1]) / 2.0
            wf = (dmg[2] + dmg[3]) / 2.0
            if self.wear_ref is None:
                self.wear_ref = (wr, wf)
        # Wheelspin proxy without the MotionEx packet.
        # High throttle + low gear + weak longitudinal acceleration.
        if self._last_speed is not None and self._last_t is not None:
            dt = t_now - self._last_t
            if 0.01 < dt < 0.5:
                accel = (tel[0] - self._last_speed) / 3.6 / dt      # m/s^2
                if tel[1] > 0.88 and 1 <= tel[5] <= 3 and 35 < tel[0] < 160 \
                        and accel < 1.2 and tel[3] < 0.05:
                    self.spin_events.append(t_now)
        self._last_speed, self._last_t = tel[0], t_now

    def balance(self):
        """Return rear-minus-front temperature delta and wear delta."""
        if len(self.temp_hist) < 60:
            return None, None
        rear = sum(r for r, _ in self.temp_hist) / len(self.temp_hist)
        front = sum(f for _, f in self.temp_hist) / len(self.temp_hist)
        return rear - front, None

    def messages(self, dmg, brake_bias, t_now):
        out = []
        dt, _ = self.balance()
        wear_gap = None
        if dmg:
            wr = (dmg[0] + dmg[1]) / 2.0
            wf = (dmg[2] + dmg[3]) / 2.0
            wear_gap = wr - wf
        # Hotter, more worn rear tyres suggest moving bias forward.
        if dt is not None and dt > 6 and (wear_gap is None or wear_gap > 2):
            bb = f" (currently {brake_bias}%)" if brake_bias else ""
            out.append(Msg(2, "MOVE BRAKE BIAS 1-2% FORWARD",
                           f"Rear is {dt:.0f}\u00b0C hotter"
                           + (f", wear +{wear_gap:.0f}%" if wear_gap else "") + bb,
                           YELLOW, key="bias_front"))
        elif dt is not None and dt < -8:
            bb = f" (currently {brake_bias}%)" if brake_bias else ""
            out.append(Msg(3, "BRAKE BIAS: MOVE 1% REARWARD",
                           f"Front is {abs(dt):.0f}\u00b0C hotter{bb}",
                           CYAN, key="bias_rear"))
        # Frequent wheelspin on corner exits.
        recent = [x for x in self.spin_events if t_now - x < 60]
        if len(recent) >= 6:
            out.append(Msg(2, "OPEN THE ON-THROTTLE DIFFERENTIAL",
                           f"{len(recent)} wheelspin events in the last minute "
                           f"\u2014 protect the rear tyres", YELLOW, key="diff"))
        return out


# ============================================================================
# 2. ERS
# ============================================================================
class _BaselineErsAdvisor:
    def __init__(self):
        self.wasted = deque(maxlen=600)

    def messages(self, st, tel, gap_ahead_s, t_now, packet_format=None):
        out = []
        if not st or not tel:
            return out
        store = st[19]
        mode = st[20]
        pct = store / ERS_MAX_J * 100
        boost_name = "BOOST" if packet_format == 2026 else "OVERTAKE"
        range_name = "the active-aero zone"
        # High-speed deployment without a target wastes energy against drag.
        if mode == 3 and tel[0] > 280 and (gap_ahead_s is None or gap_ahead_s > 1.5):
            self.wasted.append(t_now)
        recent = [x for x in self.wasted if t_now - x < 25]
        if len(recent) >= 12:
            out.append(Msg(2, f"INEFFICIENT {boost_name} USE",
                           "Above 280 km/h with no target in range \u2014 save the "
                           "battery for exits from slow corners",
                           YELLOW, key="ers_waste"))
        if pct < 12 and mode >= 2:
            out.append(Msg(1, "BATTERY ALMOST EMPTY",
                           f"{pct:.0f}% \u2014 switch to Medium to recharge "
                           f"before {range_name}", RED, key="ers_low"))
        elif pct > 92 and mode <= 1:
            out.append(Msg(3, "BATTERY FULL \u2014 USE IT",
                           "Harvesting is wasted while full; deploy on exits "
                           "from slow corners",
                           CYAN, key="ers_full"))
        return out


# Context-aware 2026 ERS coach.  This intentionally replaces the compact
# baseline above while preserving its public interface for legacy callers.
class ErsAdvisor(_BaselineErsAdvisor):
    def __init__(self):
        super().__init__()
        self.call = {"action": "HOLD", "title": "ERS BASELINE",
                     "detail": "Collecting deployment and recovery data", "urgency": 3}

    def snapshot(self):
        return dict(self.call)

    def messages(self, st, tel, gap_ahead_s, t_now, packet_format=None,
                 lap=None, session=None, gaps_behind=None):
        baseline = super().messages(st, tel, gap_ahead_s, t_now, packet_format)
        if not st or not tel:
            return baseline
        session, gaps_behind = session or {}, gaps_behind or []
        pct, mode = st[19] / ERS_MAX_J * 100, st[20]
        speed, throttle, brake = tel[0], tel[1], tel[3]
        boost_name = "BOOST" if packet_format == 2026 else "OVERTAKE"
        lap_distance = lap[10] if lap else 0
        track = load_track(session.get("track"), session.get("track_id"))
        priority_zone = bool(track and min(track, key=lambda p: abs(p[0] - lap_distance))[3])
        behind_gap = gaps_behind[0][1] if gaps_behind else None
        total_laps, current_lap = session.get("laps") or 0, lap[14] if lap else 0
        laps_left = max(0, total_laps - current_lap) if total_laps else None
        session_name = str(session.get("type") or "").casefold()
        is_quali = "q" in session_name or "qual" in session_name
        action, title, detail, urgency = (
            "HOLD", "ERS: MEDIUM",
            "Build charge for a useful acceleration zone", 3)

        if pct < 12:
            action, title, detail, urgency = (
                "RECHARGE", "ERS: RECOVERY LAP",
                "Use None/Medium now; pre-lift into the next heavy braking zone", 1)
        elif mode == 3 and speed > 285 and (gap_ahead_s is None or gap_ahead_s > 1.5):
            action, title, detail, urgency = (
                "SAVE", f"ERS: STOP WASTING {boost_name}",
                "Switch down before top speed; spend the burst during acceleration", 2)
        elif pct > 92:
            action, title, detail = (
                "DEPLOY", f"ERS: USE {boost_name}",
                "Use it at the next clean exit, then switch down before braking")
        elif is_quali and pct > 18 and speed < 230 and throttle > .82 and brake < .05:
            action, title, detail, urgency = (
                "DEPLOY", f"ERS: {boost_name} ON EXIT",
                "Qualifying lap: deploy early and target low charge at the finish line", 2)
        elif ((gap_ahead_s is not None and 0 <= gap_ahead_s <= 1.1) or
              (behind_gap is not None and 0 <= behind_gap <= 1.1)) and pct >= 28:
            if speed < 285:
                action, title, detail = ("DEPLOY", f"ERS: {boost_name} NOW",
                                         "Attack/defend window: deploy under acceleration")
            else:
                action, title, detail = ("SAVE", "ERS: HOLD FOR NEXT EXIT",
                                         "Near top speed: preserve the burst for the next acceleration zone")
            urgency = 2
        elif laps_left is not None and laps_left <= 2 and pct >= 35 and (priority_zone or speed < 270):
            action, title, detail, urgency = (
                "DEPLOY", "ERS: RELEASE FINAL-LAP RESERVE",
                "Spend in priority acceleration zones; avoid finishing with unused energy", 2)
        elif mode >= 2 and (brake > .08 or throttle < .55):
            action, title, detail, urgency = (
                "SAVE", "ERS: SWITCH DOWN BEFORE BRAKING",
                "Power can taper after the input; change mode before the braking board", 2)
        elif pct < 35 and (gap_ahead_s is None or gap_ahead_s > 1.6):
            action, title, detail = (
                "RECHARGE", "ERS: BUILD AN ATTACK RESERVE",
                "Use None/Medium in low-value zones and pre-lift at the next heavy stop")
        elif priority_zone and pct >= 55 and speed < 280:
            action, title, detail = (
                "DEPLOY", f"ERS: {boost_name} IN PRIORITY ZONE",
                "This mapped straight rewards deployment while the car is accelerating")

        self.call = {"action": action, "title": title, "detail": detail,
                     "urgency": urgency, "battery_pct": round(pct),
                     "mode": ERS_MODE_NAMES.get(mode, str(mode)),
                     "deployed_lap_mj": round(st[23] / 1_000_000, 2),
                     "priority_zone": priority_zone}
        if action in ("DEPLOY", "RECHARGE", "SAVE"):
            baseline.append(Msg(urgency, title, detail,
                                GREEN if action == "DEPLOY" else CYAN,
                                key="ers_live_call"))
        return baseline


# ============================================================================
# 3. FUEL: lift and coast
# ============================================================================
class FuelAdvisor:
    def __init__(self):
        self.lap_fuel = {}     # lap_num -> fuel at the start of the lap.
        self.per_lap = None
        self.learned_per_lap = None

    def feed(self, st, lap):
        if not st or not lap:
            return
        ln = lap[14]
        if ln not in self.lap_fuel:
            self.lap_fuel[ln] = st[5]
            if len(self.lap_fuel) >= 2:
                keys = sorted(self.lap_fuel)[-3:]
                if len(keys) >= 2:
                    drops = [self.lap_fuel[keys[i - 1]] - self.lap_fuel[keys[i]]
                             for i in range(1, len(keys))]
                    drops = [d for d in drops if d > 0]
                    if drops:
                        self.per_lap = sum(drops) / len(drops)

    def messages(self, st, lap, total_laps):
        out = []
        if not st or not lap:
            return out
        delta_laps = st[7]           # fuelRemainingLaps (negative = deficit)
        if delta_laps is None:
            return out
        laps_left = None
        if total_laps:
            laps_left = max(1, total_laps - lap[14] + 1)
        if delta_laps < -0.05:
            deficit = abs(delta_laps)
            rate = self.per_lap or self.learned_per_lap
            if rate and laps_left:
                kg_needed = deficit * rate
                per_lap_save = kg_needed / laps_left
                pct = per_lap_save / rate * 100
                detail = (f"Save {per_lap_save:.02f} kg/lap ({pct:.0f}% of "
                          f"consumption) for {laps_left} laps")
                if pct > 12:
                    action = "AGGRESSIVE LIFT & COAST: lift about 100m earlier"
                elif pct > 5:
                    action = "LIFT & COAST: lift about 50m earlier"
                else:
                    action = "LIFT SLIGHTLY on the main straight"
                out.append(Msg(1, action, detail, RED, key="fuel"))
            else:
                out.append(Msg(1, "FUEL DEFICIT",
                               f"Deficit of {deficit:.2f} laps \u2014 start lift & coast",
                               RED, key="fuel"))
        elif delta_laps > 0.9:
            out.append(Msg(3, "EXTRA FUEL AVAILABLE",
                           f"+{delta_laps:.1f} laps \u2014 you can push "
                           f"(richer mix)", GREEN, key="fuel_rich"))
        return out


# ============================================================================
# 4. STINT: tyre life, degradation, temperatures, and compound rules
# ============================================================================
class StintAdvisor:
    """Turn live tyre data into conservative, explainable stint guidance."""

    DRY_COMPOUNDS = {16, 17, 18}
    WET_COMPOUNDS = {7, 8, 15}

    def __init__(self):
        self.laps = deque(maxlen=12)  # (lap number, lap time ms, max wear)
        self.compounds_used = set()
        self.wet_used = False
        self._lap = None
        self.max_wear = 0.0
        self.avg_wear = 0.0
        self.wear_rate = None
        self.pace_deg = None
        self.projected_laps = None
        self.compound = None
        self.actual_compound = None
        self.age = 0
        self.learned_wear_rate = None

    def feed(self, tel, lap, st, dmg):
        if st:
            self.actual_compound = st[13]
            self.compound = st[14]
            self.age = st[15]
            if self.compound in self.DRY_COMPOUNDS:
                self.compounds_used.add(self.compound)
            elif self.compound in self.WET_COMPOUNDS:
                self.wet_used = True
        if dmg:
            wear = [max(0.0, min(100.0, float(x))) for x in dmg[:4]]
            self.max_wear, self.avg_wear = max(wear), sum(wear) / 4.0
        if not lap:
            return
        lap_num = lap[14]
        if self._lap is None:
            self._lap = lap_num
        elif lap_num != self._lap:
            last_ms = lap[0]
            if 20_000 < last_ms < 600_000:
                self.laps.append((lap_num - 1, last_ms, self.max_wear))
            self._lap = lap_num
            if len(self.laps) >= 2:
                wear_steps = [self.laps[i][2] - self.laps[i - 1][2]
                              for i in range(1, len(self.laps))]
                wear_steps = [x for x in wear_steps[-5:] if 0.0 < x < 15.0]
                self.wear_rate = median(wear_steps) if wear_steps else None
                time_steps = [(self.laps[i][1] - self.laps[i - 1][1]) / 1000.0
                              for i in range(1, len(self.laps))]
                self.pace_deg = median(time_steps[-3:]) if time_steps else None
            if self.wear_rate and self.wear_rate > 0.05:
                self.projected_laps = max(0.0, (72.0 - self.max_wear) /
                                          self.wear_rate)
        if self.projected_laps is None and self.learned_wear_rate:
            self.projected_laps = max(0.0, (72.0 - self.max_wear) /
                                      self.learned_wear_rate)

    def should_consider_pit(self, lap, session):
        if not lap:
            return False
        current = lap[14]
        ideal = session.get("pit_ideal_lap") or 0
        return (self.age >= 6 and self.max_wear >= 40.0) or (
            ideal > 0 and current >= max(2, ideal - 2))

    def summary(self, session=None):
        life = (f"~{self.projected_laps:.0f}L TO 72%"
                if self.projected_laps is not None else "LEARNING LIFE")
        window = "NO WINDOW"
        if session:
            ideal = session.get("pit_ideal_lap") or 0
            latest = session.get("pit_latest_lap") or 0
            if ideal:
                window = f"PIT L{ideal}" + (f"–{latest}" if latest else "")
        return (f"TYRE {self.max_wear:.0f}% · {life}", window)

    def messages(self, tel, lap, st, dmg, session):
        out = []
        if not lap or not st:
            return out
        current = lap[14]
        total = session.get("laps") or 0
        laps_left = max(0, total - current + 1) if total else None
        ideal = session.get("pit_ideal_lap") or 0
        latest = session.get("pit_latest_lap") or 0
        rejoin = session.get("pit_rejoin_position") or 0

        if self.max_wear >= 75:
            out.append(Msg(1, "BOX — TYRE LIFE CRITICAL",
                           f"Worst tyre {self.max_wear:.0f}% worn; avoid kerbs and "
                           "high-load slides", RED, key="tyre_life"))
        elif self.max_wear >= 60:
            life = (f", about {self.projected_laps:.0f} laps to 72%"
                    if self.projected_laps is not None else "")
            out.append(Msg(2, "TYRES APPROACHING THE CLIFF",
                           f"Worst tyre {self.max_wear:.0f}%{life}", YELLOW,
                           key="tyre_life"))

        if ideal and current >= ideal and (not latest or current <= latest):
            detail = f"Game strategy window L{ideal}"
            if latest:
                detail += f"–{latest}"
            if rejoin:
                detail += f" · predicted rejoin P{rejoin}"
            out.append(Msg(2, "STRATEGY PIT WINDOW OPEN", detail, GREEN,
                           key="game_window"))
        elif latest and current > latest and self.age > 1:
            out.append(Msg(1, "PLANNED PIT WINDOW MISSED",
                           f"Window ended on lap {latest}; reassess compound and traffic",
                           RED, key="game_window"))

        if (laps_left is not None and laps_left <= 4 and not self.wet_used and
                len(self.compounds_used) < 2 and current > 1):
            out.append(Msg(1, "DRY-TYRE COMPOUND CHANGE REQUIRED",
                           f"{laps_left} laps remain; use a different dry compound",
                           RED, key="compound_rule"))
        if (laps_left is not None and laps_left <= 5 and
                session.get("packet_format") == 2026 and
                (session.get("track") or "").casefold() == "monaco" and
                lap[16] < 2):
            out.append(Msg(1, "MONACO: TWO PIT STOPS REQUIRED",
                           f"{laps_left} laps remain and only {lap[16]} stop(s) recorded",
                           RED, key="monaco_stops"))

        if self.pace_deg is not None and self.pace_deg > 0.45 and len(self.laps) >= 4:
            out.append(Msg(2, "TYRE DEGRADATION IS RISING",
                           f"Recent pace loss ~{self.pace_deg:.2f}s per lap; reduce "
                           "sliding or prepare to box", YELLOW, key="degradation"))

        return out

    def temperature_messages(self, tel):
        """Tyre-temperature coaching is useful in every session type."""
        out = []
        if tel and tel[0] > 100:
            avg_temp = sum(tel[14:18]) / 4.0
            spread = max(tel[14:18]) - min(tel[14:18])
            compound_name = {15: "C6", 16: "C5", 17: "C4", 18: "C3",
                             19: "C2", 20: "C1"}.get(self.actual_compound)
            low, high = TYRE_TEMPERATURES_C.get(compound_name, (72, 112))
            if avg_temp > high:
                out.append(Msg(2, "COOL THE TYRES",
                               f"Average surface {avg_temp:.0f}°C; avoid sliding and "
                               "use clean air", YELLOW, key="tyre_temp"))
            elif avg_temp < low and self.compound in self.DRY_COMPOUNDS:
                out.append(Msg(3, "BUILD TYRE TEMPERATURE",
                               f"Average surface {avg_temp:.0f}°C; progressive load "
                               "before pushing", CYAN, key="tyre_temp"))
            if spread > 28:
                out.append(Msg(3, "TYRE TEMPERATURE IMBALANCE",
                               f"{spread:.0f}°C spread across the car", YELLOW,
                               key="tyre_spread"))
        return out


# ============================================================================
# 5. CONDITIONS, race control, and car health
# ============================================================================
class ConditionsAdvisor:
    WEATHER = {0: "clear", 1: "light cloud", 2: "overcast",
               3: "light rain", 4: "heavy rain", 5: "storm"}

    def messages(self, session, st, stint, lap):
        out = []
        safety = session.get("safety_car") or 0
        if safety in (1, 2) and stint.should_consider_pit(lap, session):
            kind = "SAFETY CAR" if safety == 1 else "VIRTUAL SAFETY CAR"
            out.append(Msg(1, f"{kind}: CHEAP PIT OPPORTUNITY",
                           "Pit loss is reduced; box if the required tyre is ready",
                           GREEN, key="safety_pit"))
        forecasts = session.get("weather_forecast") or []
        session_type_id = session.get("session_type_id")
        upcoming = next((x for x in forecasts
                         if 0 < x.get("minutes", 0) <= 15 and
                         x.get("rain", 0) >= 40 and
                         (session_type_id is None or
                          x.get("session_type") == session_type_id)), None)
        if upcoming:
            out.append(Msg(2, f"RAIN RISK {upcoming['rain']}% IN "
                               f"{upcoming['minutes']} MIN",
                           "Keep the stint flexible and avoid an unnecessary dry stop",
                           CYAN, key="rain"))
        weather = session.get("weather")
        if weather is not None and weather >= 3 and st and st[14] in StintAdvisor.DRY_COMPOUNDS:
            out.append(Msg(1, "RAIN ON SLICKS — ASSESS GRIP",
                           "Reduce steering and throttle peaks; box when crossover "
                           "pace favours intermediates", RED, key="wet_slick"))
        return out


class CarHealthAdvisor:
    def messages(self, tel, dmg):
        out = []
        if tel:
            brake_max = max(tel[10:14])
            if brake_max > 1150:
                out.append(Msg(1, "BRAKES OVERHEATING",
                               f"Peak {brake_max:.0f}°C; lift earlier and cool in clean air",
                               RED, key="brakes"))
            if tel[22] >= 135:
                out.append(Msg(2, "ENGINE TEMPERATURE HIGH",
                               f"{tel[22]}°C; use clean air and short-shift",
                               YELLOW, key="engine_temp"))
        if dmg and len(dmg) >= 22:
            front_left, front_right, rear_wing = dmg[16], dmg[17], dmg[18]
            front_wing = max(front_left, front_right)
            floor = max(dmg[19], dmg[20], dmg[21])
            tyre_damage = max(dmg[4:8])
            # Aero damage changes the car immediately and must not be hidden by
            # a lower-value tyre-damage reading from the same impact.
            if front_wing >= 15:
                side = ("left" if front_left > front_right else "right" if
                        front_right > front_left else "both sides")
                critical = front_wing >= 35
                out.append(Msg(1 if critical else 2,
                               "FRONT WING DAMAGE — BOX" if critical else
                               "FRONT WING DAMAGE",
                               f"{side.title()} {front_wing}% · reduced front grip"
                               + (" · replace at the next stop" if critical else
                                  " · brake earlier and avoid kerbs"),
                               RED if critical else YELLOW, key="front_wing_damage"))
            if rear_wing >= 15:
                out.append(Msg(1 if rear_wing >= 35 else 2,
                               "REAR WING DAMAGE",
                               f"Rear wing {rear_wing}% · traction and stability reduced",
                               RED if rear_wing >= 35 else YELLOW,
                               key="rear_wing_damage"))
            if tyre_damage >= 20:
                out.append(Msg(1 if tyre_damage >= 50 else 2,
                               "TYRE DAMAGE — BOX" if tyre_damage >= 50 else
                               "TYRE DAMAGE",
                               f"Worst tyre {tyre_damage}%",
                               RED if tyre_damage >= 50 else YELLOW,
                               key="tyre_damage"))
            if floor >= 20:
                out.append(Msg(2, "FLOOR DAMAGE: MANAGE PACE",
                               f"Floor/diffuser damage {floor}%", YELLOW,
                               key="floor_damage"))
        return out


class BattleAdvisor:
    def messages(self, st, gap_ahead, name_ahead, gaps_behind, packet_format):
        out = []
        battery = st[19] / ERS_MAX_J * 100 if st else 0
        system = "OVERTAKE" if packet_format == 2026 else "STRAIGHT MODE"
        if gap_ahead is not None and 0 <= gap_ahead <= 1.05 and name_ahead:
            detail = f"{name_ahead} +{gap_ahead:.2f}s"
            detail += (" · deploy Boost on the best exit" if battery >= 30 else
                       " · recharge before committing")
            out.append(Msg(2, f"ATTACK — {system} RANGE", detail, GREEN,
                           key="attack"))
        if gaps_behind:
            name, gap = gaps_behind[0]
            if 0 <= gap <= 1.05:
                out.append(Msg(2, f"DEFEND FROM {name}",
                               f"{gap:.2f}s behind · protect battery and exits",
                               YELLOW, key="defend"))
        return out


# ============================================================================
# 6. RULES: penalties and track limits
# ============================================================================
class RulesAdvisor:
    def messages(self, lap):
        out = []
        if not lap:
            return out
        penalties = lap[19]
        warnings = lap[20]
        corner_warnings = lap[21]
        drive_through = lap[22]
        stop_go = lap[23]
        if drive_through:
            out.append(Msg(1, "SERVE DRIVE-THROUGH PENALTY",
                           f"{drive_through} unserved drive-through penalty/penalties",
                           RED, key="serve_penalty"))
        if stop_go:
            out.append(Msg(1, "SERVE STOP-GO PENALTY",
                           f"{stop_go} unserved stop-go penalty/penalties",
                           RED, key="serve_penalty"))
        if corner_warnings >= 2:
            out.append(Msg(2, "TRACK LIMITS — NO MORE RISKS",
                           f"{corner_warnings} corner-cutting warnings · "
                           f"{penalties}s penalties", YELLOW, key="track_limits"))
        elif penalties:
            out.append(Msg(3, f"PENALTIES: +{penalties}s",
                           f"Total warnings: {warnings}", YELLOW,
                           key="penalties"))
        return out


# ============================================================================
# 7. PIT: window, dirty air, and undercut
# ============================================================================
class PitAdvisor:
    def __init__(self, pit_loss=PIT_LOSS_S):
        self.pit_loss = pit_loss

    def analyse(self, my_pos, gaps_behind, gap_ahead, name_ahead):
        """Analyse sorted ``(name, positive_gap_seconds)`` entries behind."""
        out = []
        # Expected rejoin position after pitting now.
        emerge_behind = None
        for nm, g in gaps_behind:
            if g < self.pit_loss:
                emerge_behind = (nm, self.pit_loss - g)
            else:
                break
        if emerge_behind:
            nm, margin = emerge_behind
            if margin < DIRTY_AIR_S:
                out.append(Msg(2, f"DO NOT PIT NOW \u2014 emerge {margin:.1f}s behind "
                                  f"{nm}",
                               "Dirty air. Stay out for 1-2 laps to open the "
                               "window", RED, key="pit_window"))
            else:
                out.append(Msg(2, f"PIT WINDOW OPEN \u2014 emerge {margin:.1f}s "
                                  f"behind {nm}",
                               "Enough space for clean air", GREEN,
                               key="pit_window"))
        elif gaps_behind:
            out.append(Msg(3, "CLEAR PIT WINDOW \u2014 EMERGE IN CLEAN AIR",
                           f"Nobody within {self.pit_loss:.0f}s behind",
                           GREEN, key="pit_window"))
        # Undercut opportunity on the car ahead.
        if gap_ahead is not None and gap_ahead <= 2.5 and name_ahead:
            need = gap_ahead - UNDERCUT_GAIN_S
            if need <= 0:
                out.append(Msg(2, f"UNDERCUT AVAILABLE ON {name_ahead}",
                               f"Gap is {gap_ahead:.2f}s \u2014 fresh tyres "
                               f"should be enough", GREEN, key="undercut"))
            else:
                out.append(Msg(2, f"UNDERCUT: FIND \u2212{need:.2f}s ON THE IN-LAP",
                               f"{name_ahead} is {gap_ahead:.2f}s ahead \u2014 push "
                               f"in the final sector before pitting", YELLOW,
                               key="undercut"))
        return out


# ============================================================================
# 5. MICRO-SECTORS, braking points, and apex speeds
# ============================================================================
class MicroSectors:
    """Compare the current and reference laps by micro-sector and corner."""

    def __init__(self, n=20):
        self.n = n
        self.ref = None          # dict(dist, time, speed, brake, zones)
        self.ref_ms = 0
        self.cur = []            # (dist, t, speed, brake)
        self._lap = None
        self.seg_delta = [None] * n
        self.corner_notes = []

    def reset(self):
        self.__init__(self.n)

    # ---- build reference -------------------------------------------------
    @staticmethod
    def _braking_zones(dist, brake, speed):
        """Return braking zones as ``(start_distance, apex_speed, apex_distance)``."""
        zones = []
        in_zone = False
        start = 0.0
        for i in range(len(dist)):
            if not in_zone and brake[i] > 0.3:
                in_zone = True
                start = dist[i]
            elif in_zone and brake[i] < 0.1:
                in_zone = False
                seg = [(d, s) for d, s in zip(dist, speed) if start <= d <= dist[i] + 150]
                if seg:
                    ad, asp = min(seg, key=lambda x: x[1])
                    zones.append((start, asp, ad))
        return zones

    def finish_lap(self, lap_time_ms):
        if len(self.cur) < 40 or lap_time_ms <= 0:
            self.cur = []
            return False
        if self.ref_ms and lap_time_ms >= self.ref_ms:
            self.cur = []
            return False
        d = np.array([p[0] for p in self.cur], float)
        t = np.array([p[1] for p in self.cur], float)
        s = np.array([p[2] for p in self.cur], float)
        b = np.array([p[3] for p in self.cur], float)
        keep = np.concatenate(([True], np.diff(d) > 0.5))
        if keep.sum() < 30:
            self.cur = []
            return False
        d, t, s, b = d[keep], t[keep], s[keep], b[keep]
        self.ref = {"dist": d, "time": t, "speed": s, "brake": b,
                    "zones": self._braking_zones(d, b, s)}
        self.ref_ms = lap_time_ms
        self.cur = []
        return True

    # ---- current lap ------------------------------------------------------
    def feed(self, lap, tel):
        """Return total delta in seconds, or ``None`` without a reference."""
        if not lap or not tel:
            return None
        ln, dist, cur_ms, last_ms = lap[14], lap[10], lap[1], lap[0]
        if self._lap is None:
            self._lap = ln
        if ln != self._lap:
            self.finish_lap(last_ms)
            self._lap = ln
            self.seg_delta = [None] * self.n
            self.corner_notes = []
        if dist >= 0 and cur_ms > 0 and (not self.cur or dist > self.cur[-1][0]):
            self.cur.append((dist, cur_ms, tel[0], tel[3]))
        if not self.ref or dist <= 0:
            return None
        rd, rt = self.ref["dist"], self.ref["time"]
        if dist > rd[-1]:
            return None
        delta = (cur_ms - float(np.interp(dist, rd, rt))) / 1000.0
        # delta per micro-sector
        seg_len = rd[-1] / self.n
        idx = min(self.n - 1, int(dist / seg_len))
        start_d = idx * seg_len
        if len(self.cur) > 2 and dist - start_d > seg_len * 0.25:
            cur_at_start = None
            for dd, tt, _, _ in reversed(self.cur):
                if dd <= start_d:
                    cur_at_start = tt
                    break
            if cur_at_start is not None:
                ref_start = float(np.interp(start_d, rd, rt))
                ref_now = float(np.interp(dist, rd, rt))
                self.seg_delta[idx] = ((cur_ms - cur_at_start) -
                                       (ref_now - ref_start)) / 1000.0
        return delta

    # ---- corner feedback -------------------------------------------------
    def corner_feedback(self):
        """Compare current braking points and apex speeds with the reference."""
        if not self.ref or len(self.cur) < 30:
            return []
        rd = self.ref["dist"]
        cd = np.array([p[0] for p in self.cur], float)
        cs = np.array([p[2] for p in self.cur], float)
        cb = np.array([p[3] for p in self.cur], float)
        cur_zones = self._braking_zones(cd, cb, cs)
        notes = []
        for i, (rz_start, r_apex, _) in enumerate(self.ref["zones"], 1):
            match = [z for z in cur_zones if abs(z[0] - rz_start) < 120]
            if not match:
                continue
            cz_start, c_apex, _ = match[0]
            d_brake = cz_start - rz_start          # Positive means braking later.
            d_apex = c_apex - r_apex               # Positive means a faster apex.
            if abs(d_brake) >= 4 or abs(d_apex) >= 3:
                if d_brake < -4:
                    txt = f"T{i}: braked {abs(d_brake):.0f}m EARLIER"
                    col = YELLOW
                elif d_brake > 4:
                    txt = f"T{i}: braked {d_brake:.0f}m LATER"
                    col = GREEN
                else:
                    txt = f"T{i}: same braking point"
                    col = DIM
                if d_apex <= -3:
                    txt += f", apex {abs(d_apex):.0f} km/h slower"
                    col = YELLOW
                elif d_apex >= 3:
                    txt += f", apex {d_apex:.0f} km/h faster"
                notes.append((i, txt, col))
        self.corner_notes = notes
        return notes


# ============================================================================
# 8. PROJECTED OVERTAKES: gap-trend extrapolation
# ============================================================================
class OvertakeAdvisor:
    """Track lap-by-lap gap trends and project when a battle resolves."""

    def __init__(self):
        self.history = {}  # name -> deque[(lap_num, gap_seconds)]

    def reset(self):
        self.__init__()

    def _record(self, name, lap_num, gap):
        if not name or gap is None or gap < 0 or gap > 30 or lap_num is None:
            return
        hist = self.history.setdefault(name, deque(maxlen=6))
        if hist and hist[-1][0] == lap_num:
            hist[-1] = (lap_num, gap)
        else:
            hist.append((lap_num, gap))

    def _project(self, name):
        hist = self.history.get(name)
        if not hist or len(hist) < 3:
            return None
        laps = [h[0] for h in hist]
        gaps = [h[1] for h in hist]
        span = laps[-1] - laps[0]
        if span <= 0:
            return None
        rate = (gaps[-1] - gaps[0]) / span
        if rate >= -0.05:
            return None
        laps_to_close = gaps[-1] / -rate
        if laps_to_close <= 0:
            return None
        return rate, laps_to_close

    def messages(self, lap_num, gap_ahead, name_ahead, gaps_behind):
        self._record(name_ahead, lap_num, gap_ahead)
        chaser = gaps_behind[0] if gaps_behind else (None, None)
        self._record(chaser[0], lap_num, chaser[1])

        out = []
        if name_ahead:
            proj = self._project(name_ahead)
            if proj:
                rate, laps_needed = proj
                if laps_needed <= 8:
                    out.append(Msg(2, f"PROJECTED OVERTAKE ON {name_ahead}",
                                   f"Closing {abs(rate):.2f}s/lap — in range in "
                                   f"~{laps_needed:.1f} laps", GREEN,
                                   key="overtake_ahead"))
        if chaser[0]:
            proj = self._project(chaser[0])
            if proj:
                rate, laps_needed = proj
                if laps_needed <= 8:
                    out.append(Msg(2, f"{chaser[0]} PROJECTED TO ATTACK",
                                   f"Losing {abs(rate):.2f}s/lap — in range in "
                                   f"~{laps_needed:.1f} laps", YELLOW,
                                   key="overtake_behind"))
        return out


# ============================================================================
# ORCHESTRATOR
# ============================================================================
class RaceEngineer:
    """Combine every advisor and return messages ordered by priority."""

    def __init__(self, micro_n=20, pit_loss=PIT_LOSS_S):
        self.setup = SetupAdvisor()
        self.ers = ErsAdvisor()
        self.fuel = FuelAdvisor()
        self.stint = StintAdvisor()
        self.conditions = ConditionsAdvisor()
        self.health = CarHealthAdvisor()
        self.battle = BattleAdvisor()
        self.rules = RulesAdvisor()
        self.pit = PitAdvisor(pit_loss)
        self.overtake = OvertakeAdvisor()
        self.micro = MicroSectors(micro_n)
        self._msgs = {}
        self._last_corner_msg = None
        self.learned_profile = {}
        self.learned_setup = []

    def reset(self):
        self.__init__(self.micro.n, self.pit.pit_loss)

    def set_learned_profile(self, profile=None, setup_recommendations=None):
        """Seed live calls from history until the current stint has enough data."""
        self.learned_profile = dict(profile or {})
        self.learned_setup = list(setup_recommendations or [])
        self.fuel.learned_per_lap = self.learned_profile.get("fuel_per_lap")
        self.stint.learned_wear_rate = self.learned_profile.get("wear_per_lap")

    def update(self, tel, lap, st, dmg, t_now, total_laps=None,
               gap_ahead=None, name_ahead=None, gaps_behind=None,
               session_type=None, session=None, packet_format=None):
        """Return delta versus best and messages sorted by priority."""
        session = dict(session or {})
        if total_laps is not None and not session.get("laps"):
            session["laps"] = total_laps
        if session_type and not session.get("type"):
            session["type"] = session_type
        self.setup.feed(tel, dmg, t_now)
        self.fuel.feed(st, lap)
        self.stint.feed(tel, lap, st, dmg)
        delta = self.micro.feed(lap, tel)

        session_name = (session.get("type") or "").casefold()
        is_race = session_name.startswith("race")
        msgs = []
        # Fuel surplus/deficit and pit-window calls are only actionable in a
        # race.  They are misleading in Time Trial and qualifying sessions.
        if is_race:
            msgs += self.fuel.messages(st, lap, session.get("laps"))
            msgs += self.stint.messages(tel, lap, st, dmg, session)
            msgs += self.conditions.messages(session, st, self.stint, lap)
            msgs += self.battle.messages(st, gap_ahead, name_ahead,
                                         gaps_behind or [], packet_format)
            msgs += self.overtake.messages(lap[14] if lap else None,
                                           gap_ahead, name_ahead,
                                           gaps_behind or [])
        msgs += self.stint.temperature_messages(tel)
        msgs += self.ers.messages(st, tel, gap_ahead, t_now, packet_format,
                                  lap, session, gaps_behind or [])
        msgs += self.setup.messages(dmg, st[3] if st else None, t_now)
        msgs += self.health.messages(tel, dmg)
        msgs += self.rules.messages(lap)
        if not is_race and self.learned_setup:
            suggestion = self.learned_setup[0]
            msgs.append(Msg(3, "LEARNED SETUP: " + suggestion["title"],
                            suggestion["detail"], CYAN, key="learned_setup"))
        if (is_race and gaps_behind is not None and
                self.stint.should_consider_pit(lap, session)):
            msgs += self.pit.analyse(lap[13] if lap else None, gaps_behind,
                                     gap_ahead, name_ahead)
        # Show only the costliest corner note to avoid message spam.
        notes = self.micro.corner_feedback()
        if notes:
            worst = notes[-1]
            msgs.append(Msg(3, worst[1], "versus your reference lap",
                            worst[2], key="corner"))
        # Keep the highest-priority version of each topic.
        unique = {}
        for message in msgs:
            previous = unique.get(message.key)
            if previous is None or message.prio < previous.prio:
                unique[message.key] = message
        ordered = sorted(unique.values(), key=lambda m: m.prio)
        return delta, ordered

    def summary(self, session=None):
        """Return compact tyre and pit-window text for the dashboard."""
        return self.stint.summary(session or {})
