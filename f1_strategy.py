#!/usr/bin/env python3
"""Dependency-light race strategy simulation calibrated from recorded telemetry.

The state/action idea is inspired by rembertdesigns/pit-stop-simulator, but this
is an original deterministic implementation designed for live EA F1 telemetry.
"""

from dataclasses import dataclass, field
from itertools import product
import math


COMPOUNDS = {
    "Soft": {"pace": 0.00, "wear": 1.35, "wet": False},
    "Medium": {"pace": 0.45, "wear": 1.00, "wet": False},
    "Hard": {"pace": 1.05, "wear": 0.74, "wet": False},
    "Intermediate": {"pace": 2.4, "wear": 1.05, "wet": True},
    "Wet": {"pace": 4.2, "wear": 0.82, "wet": True},
}

COMPOUND_ALIASES = {
    "S": "Soft", "Soft": "Soft", "SuSoft": "Soft",
    "M": "Medium", "Med": "Medium", "Medium": "Medium",
    "H": "Hard", "Hard": "Hard",
    "Inter": "Intermediate", "Intermediate": "Intermediate",
    "Wet": "Wet",
}


@dataclass
class Scenario:
    total_laps: int = 58
    current_lap: int = 1
    base_lap_seconds: float = 90.0
    current_compound: str = "Medium"
    current_wear: float = 5.0
    fuel_kg: float = 100.0
    fuel_per_lap: float = 1.8
    wear_per_lap: float = 1.6
    pit_loss: float = 21.0
    traffic: float = 0.25
    rain: float = 0.0
    safety_mode: str = "Green"
    safety_laps: int = 0
    consistency_seconds: float = 0.5
    min_stops: int = 0
    min_dry_compounds: int = 2

    def normalized(self):
        self.total_laps = max(1, min(100, int(self.total_laps)))
        self.current_lap = max(1, min(self.total_laps, int(self.current_lap)))
        self.base_lap_seconds = max(30.0, min(300.0, float(self.base_lap_seconds)))
        self.current_compound = COMPOUND_ALIASES.get(
            str(self.current_compound), "Medium")
        self.current_wear = max(0.0, min(100.0, float(self.current_wear)))
        self.fuel_kg = max(0.0, min(150.0, float(self.fuel_kg)))
        self.fuel_per_lap = max(0.5, min(5.0, float(self.fuel_per_lap)))
        self.wear_per_lap = max(0.1, min(8.0, float(self.wear_per_lap)))
        self.pit_loss = max(5.0, min(60.0, float(self.pit_loss)))
        self.traffic = max(0.0, min(1.0, float(self.traffic)))
        self.rain = max(0.0, min(1.0, float(self.rain)))
        self.safety_laps = max(0, min(10, int(self.safety_laps)))
        self.min_stops = max(0, min(3, int(self.min_stops)))
        self.min_dry_compounds = max(1, min(3, int(self.min_dry_compounds)))
        return self


@dataclass
class StrategyResult:
    label: str
    stops: tuple
    compounds: tuple
    total_seconds: float
    finish_wear: float
    max_wear: float
    valid: bool
    confidence_seconds: float
    lap_times: list = field(default_factory=list)
    wear_trace: list = field(default_factory=list)
    delta: float = 0.0


def scenario_from_context(context):
    latest = context.get("latest") or {}
    profile = context.get("profile") or {}
    wears = [latest.get(key) for key in ("tyre_wear_rl", "tyre_wear_rr",
                                          "tyre_wear_fl", "tyre_wear_fr")]
    wears = [float(value) for value in wears if value is not None]
    total = context.get("total_laps") or 58
    completed = bool(context.get("ended_at"))
    current = 1 if completed else (latest.get("lap_num") or 1)
    best_ms = (context.get("measured_best_lap_ms") or
               context.get("best_lap_ms") or 90_000)
    fuel_rate = profile.get("fuel_per_lap") or 1.8
    wear_rate = profile.get("wear_per_lap") or 1.6
    consistency = (profile.get("pace_consistency_ms") or 500) / 1000.0
    fuel = None if completed else latest.get("fuel_kg")
    if fuel is None:
        fuel = max(5.0, (total - current + 1) * fuel_rate)
    current_compound = COMPOUND_ALIASES.get(latest.get("tyre_compound"), "Medium")
    base_seconds = max(30.0, float(best_ms) / 1000.0 - COMPOUNDS[current_compound]["pace"])
    safety = {1: "Safety Car", 2: "VSC"}.get(context.get("safety_car"), "Green")
    return Scenario(
        total_laps=total, current_lap=current,
        base_lap_seconds=base_seconds,
        current_compound=current_compound,
        current_wear=0.0 if completed else (sum(wears) / len(wears) if wears else 5.0),
        fuel_kg=fuel, fuel_per_lap=fuel_rate, wear_per_lap=wear_rate,
        # EA weather is a category (0=Clear..5=Storm), not a linear rain percentage;
        # light cloud/overcast must never be interpreted as a wet crossover.
        rain={3: .45, 4: .80, 5: 1.0}.get(int(context.get("weather") or 0), 0.0),
        safety_mode=safety, safety_laps=2 if safety != "Green" else 0,
        consistency_seconds=consistency,
    ).normalized()


class StrategyEngine:
    """Enumerate realistic stop windows and rank them by remaining race time."""

    def generate(self, scenario, max_results=40):
        s = scenario.normalized()
        remaining = s.total_laps - s.current_lap + 1
        if remaining <= 0:
            return []
        wet = s.rain >= 0.28
        choices = ("Intermediate", "Wet") if wet else ("Soft", "Medium", "Hard")
        plans = [((), ())]
        last_pit = max(s.current_lap + 1, s.total_laps - 1)
        for pit_lap in range(s.current_lap + 1, last_pit + 1):
            for compound in choices:
                plans.append(((pit_lap,), (compound,)))
        if remaining >= 10 or s.min_stops >= 2:
            stride = 1 if remaining < 20 else (2 if remaining < 50 else 3)
            first_range = range(s.current_lap + 2,
                                s.current_lap + max(3, remaining // 2), stride)
            for first in first_range:
                second_start = first + max(5, remaining // 5)
                for second in range(second_start, s.total_laps - 1, stride):
                    for compounds in product(choices, repeat=2):
                        if not wet and len({s.current_compound, *compounds}) < 2:
                            continue
                        plans.append(((first, second), compounds))
        results = [self.simulate(s, stops, compounds) for stops, compounds in plans]
        valid = [result for result in results if result.valid]
        valid.sort(key=lambda result: result.total_seconds)
        if not valid:
            return []
        best = valid[0].total_seconds
        for result in valid:
            result.delta = result.total_seconds - best
        return valid[:max_results]

    def simulate(self, scenario, stops=(), compounds=()):
        s = scenario
        compound = s.current_compound
        wear = s.current_wear
        fuel = s.fuel_kg
        total_time = 0.0
        max_wear = wear
        lap_times, wear_trace = [], []
        used = {compound}
        stop_map = dict(zip(stops, compounds))
        for lap in range(s.current_lap, s.total_laps + 1):
            caution = lap < s.current_lap + s.safety_laps
            stopped = lap in stop_map
            pit_cost = 0.0
            if stopped:
                compound = stop_map[lap]
                used.add(compound)
                wear = 0.0
                if s.safety_mode == "Safety Car" and caution:
                    pit_cost = s.pit_loss * 0.52
                elif s.safety_mode == "VSC" and caution:
                    pit_cost = s.pit_loss * 0.68
                else:
                    pit_cost = s.pit_loss
            props = COMPOUNDS[compound]
            # Measured best lap is the zero-fuel/fresh-tyre anchor. The curve
            # becomes increasingly costly once wear moves beyond a normal stint.
            degradation = 0.012 * wear + 0.00135 * wear * wear
            fuel_cost = fuel * 0.030
            traffic_cost = s.traffic * (1.1 if compound == "Soft" else 1.35)
            if s.rain >= 0.08:
                if props["wet"]:
                    weather_cost = abs(s.rain - (0.45 if compound == "Intermediate" else 0.85)) * 5.0
                else:
                    weather_cost = 3.0 + 17.0 * s.rain
            else:
                weather_cost = 7.0 if props["wet"] else 0.0
            running_time = (s.base_lap_seconds + props["pace"] + degradation +
                            fuel_cost + traffic_cost + weather_cost)
            lap_time = running_time + pit_cost
            if caution:
                multiplier = 1.42 if s.safety_mode == "Safety Car" else 1.18
                lap_time = max(running_time, s.base_lap_seconds * multiplier) + pit_cost
            if wear > 78:
                lap_time += (wear - 78) * 0.25
            lap_times.append(lap_time)
            total_time += lap_time
            fuel = max(0.0, fuel - s.fuel_per_lap)
            wear += s.wear_per_lap * props["wear"] * (1.0 + 0.20 * s.traffic)
            if s.rain > 0.15 and not props["wet"]:
                wear += s.wear_per_lap * s.rain * 0.45
            wear = min(100.0, wear)
            max_wear = max(max_wear, wear)
            wear_trace.append(wear)
        is_dry = s.rain < 0.15
        valid = (max_wear < 96 and len(stops) >= s.min_stops and
                 (not is_dry or len(used) >= s.min_dry_compounds or
                  s.current_lap > s.total_laps * 0.75))
        label = "NO STOP"
        if stops:
            calls = [f"L{lap} {compound}" for lap, compound in zip(stops, compounds)]
            label = " / ".join(calls)
        confidence = s.consistency_seconds * math.sqrt(max(1, len(lap_times)))
        return StrategyResult(label, tuple(stops), tuple(compounds), total_time,
                              wear, max_wear, valid, confidence,
                              lap_times, wear_trace)


def format_race_time(seconds):
    seconds = max(0.0, float(seconds))
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{int(hours)}:{int(minutes):02d}:{secs:05.2f}"
    return f"{int(minutes)}:{secs:05.2f}"
