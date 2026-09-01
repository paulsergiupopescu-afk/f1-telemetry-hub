"""Stateful, player-specific live pit strategy recommendations."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import math

from f1_setup_library import get_setup
from f1_strategy import COMPOUNDS, Scenario, StrategyEngine, format_race_time
from f1_community_reference import get_reference


@dataclass
class StrategyRecommendation:
    action: str = "REASSESS"
    lap: int | None = None
    target_lap: int | None = None
    window_start: int | None = None
    window_end: int | None = None
    compound: str | None = None
    predicted_rejoin: int | None = None
    advantage_seconds: float = 0.0
    confidence: str = "LOW"
    uncertainty_seconds: float = 0.0
    headline: str = "COLLECTING RACE DATA"
    detail: str = "A stable recommendation will appear when live race context is available."
    evidence: list[str] = field(default_factory=list)
    change_reason: str = "Initial recommendation"
    critical: bool = False
    options: list[dict] = field(default_factory=list)

    def to_dict(self):
        return asdict(self)


class LiveStrategyEngine:
    """Re-rank the remaining race while applying confidence-aware hysteresis."""

    def __init__(self, database=None):
        self.engine = StrategyEngine()
        self.database = database
        self.current = StrategyRecommendation()
        self._current_plan = None
        self._signature = None
        self._last_phase = None

    def reset(self):
        self.current = StrategyRecommendation()
        self._current_plan = None
        self._signature = None
        self._last_phase = None

    @staticmethod
    def _compound(value):
        value = str(value or "Medium")
        return {"Inter": "Intermediate", "Med": "Medium", "SuSoft": "Soft"}.get(
            value, value if value in COMPOUNDS else "Medium")

    @staticmethod
    def _phase(context):
        return (context.get("race_control") or {}).get("phase") or "GREEN"

    def _scenario(self, context):
        session, player = context.get("session") or {}, context.get("player") or {}
        profile = context.get("profile") or {}
        track_setup = get_setup(session.get("track")) or {}
        total = int(session.get("laps") or 58)
        current = max(1, int(player.get("lap_num") or 1))
        compound = self._compound(player.get("compound"))
        wears = [float(x) for x in (player.get("tyre_wear") or []) if x is not None]
        wear = max(wears) if wears else 5.0
        fuel_rate = float(profile.get("fuel_per_lap") or 1.8)
        measured_wear = profile.get("wear_per_lap")
        profile_laps = profile.get("laps")
        # A partial/out-lap can produce tiny deltas that make a Soft appear able
        # to run an entire 100% race. Do not trust a personal degradation rate
        # until five representative laps exist, and reject implausibly low data.
        wear_rate = (float(measured_wear) if measured_wear is not None and
                     (profile_laps is None or int(profile_laps) >= 5) and
                     float(measured_wear) >= .50 else 1.6)
        wear_rate = max(.50, min(6.0, wear_rate))
        best_ms = player.get("best_lap_ms") or 0
        base = float(best_ms) / 1000.0 if best_ms else float(
            track_setup.get("baseline_lap_seconds") or 90.0)
        phase = self._phase(context)
        safety_mode = {"SC": "Safety Car", "VSC": "VSC"}.get(phase, "Green")
        forecast = session.get("weather_forecast") or []
        imminent_rain = max((item.get("rain", 0) for item in forecast
                             if 0 <= item.get("minutes", 99) <= 15), default=0)
        # EA weather is a category, not a linear rain percentage.  In particular,
        # light cloud/overcast must never be interpreted as a wet crossover.
        weather_rain = {3: .45, 4: .80, 5: 1.0}.get(
            int(session.get("weather") or 0), 0.0)
        rain = max(weather_rain, imminent_rain / 100.0)
        field = context.get("field") or []
        close_cars = sum(1 for car in field if 0 < abs(car.get("gap_to_player", 99)) < 3)
        traffic = min(1.0, 0.12 + close_cars * 0.13)
        is_monaco = str(session.get("track") or "").casefold() == "monaco"
        completed_stops = int(player.get("pit_stops") or 0)
        return Scenario(
            total_laps=total,
            current_lap=current,
            base_lap_seconds=max(30.0, base - COMPOUNDS[compound]["pace"]),
            current_compound=compound,
            current_wear=wear,
            fuel_kg=float(player.get("fuel_kg") or max(5, (total-current+1)*fuel_rate)),
            fuel_per_lap=fuel_rate,
            wear_per_lap=wear_rate,
            pit_loss=float(track_setup.get("pit_loss_seconds") or 21.0),
            traffic=traffic,
            rain=rain,
            safety_mode=safety_mode,
            safety_laps=3 if phase == "SC" else (2 if phase == "VSC" else 0),
            consistency_seconds=float(profile.get("pace_consistency_ms") or 500)/1000.0,
            min_stops=max(0, (2 if is_monaco else 0) - completed_stops),
            min_dry_compounds=2,
        ).normalized()

    def _contextualize_results(self, context, scenario, results):
        """Apply live traffic and undercut/overcut effects before final ranking."""
        player = context.get("player") or {}
        position = int(player.get("position") or 0)
        field = context.get("field") or []
        ahead = next((car for car in field if car.get("position") == position - 1), None)
        track_temp = float((context.get("session") or {}).get("trackTemp") or 30)
        degradation_gain = max(0.0, .012 * scenario.current_wear +
                               .00135 * scenario.current_wear ** 2)
        for result in results:
            if not result.stops:
                continue
            first_stop = result.stops[0]
            urgency = max(0, 3 - (first_stop - scenario.current_lap))
            # Rejoining within two seconds of a car costs time in dirty air.
            behind = [car for car in field if car.get("gap_to_player", -1) > 0]
            post_stop_gaps = [abs(car.get("gap_to_player", 99) - scenario.pit_loss)
                              for car in behind]
            nearest = min(post_stop_gaps, default=99)
            if nearest < 2:
                result.total_seconds += (2 - nearest) * 1.2
            # A nearby rival on older tyres increases the value of an early undercut.
            if (ahead and abs(float(ahead.get("gap_to_player") or 99)) <= 2.5 and
                    int(ahead.get("tyre_age") or 0) >= int(player.get("tyre_age") or 0)):
                result.total_seconds -= min(2.0, degradation_gain + .35) * urgency / 3
            # Cool conditions add fresh-tyre warm-up cost and can favour an overcut.
            if track_temp < 25 and first_stop <= scenario.current_lap + 1:
                result.total_seconds += min(1.5, (25 - track_temp) * .08)
        results.sort(key=lambda item: item.total_seconds)
        if results:
            best = results[0].total_seconds
            for result in results:
                result.delta = result.total_seconds - best
        return results

    @staticmethod
    def _predicted_rejoin(context, pit_loss):
        player = context.get("player") or {}
        position = int(player.get("position") or 0)
        behind = sorted((car for car in context.get("field") or []
                         if car.get("gap_to_player", -1) > 0),
                        key=lambda car: car.get("gap_to_player", 999))
        lost = sum(1 for car in behind if car.get("gap_to_player", 999) < pit_loss)
        return position + lost if position else None

    @staticmethod
    def _confidence(uncertainty, evidence_count):
        if uncertainty <= 3.5 and evidence_count >= 3:
            return "HIGH"
        if uncertainty <= 7.5 and evidence_count >= 2:
            return "MEDIUM"
        return "LOW"

    def _build(self, context, results, scenario):
        player, session = context.get("player") or {}, context.get("session") or {}
        phase = self._phase(context)
        lap = scenario.current_lap
        wear = scenario.current_wear
        damage = context.get("damage") or {}
        wing = max(float(damage.get("front_wing_left") or 0),
                   float(damage.get("front_wing_right") or 0))
        race_control = context.get("race_control") or {}
        if race_control.get("finished"):
            return StrategyRecommendation(
                action="REASSESS", lap=lap, headline="CHEQUERED FLAG — SESSION COMPLETE",
                detail="Tactical calls are closed. The completed race is ready for review.",
                evidence=["Race-finish event received"],
                change_reason="Race finished", critical=True)
        if phase == "RED_FLAG":
            return StrategyRecommendation(
                action="REASSESS", lap=lap, headline="RED FLAG — STRATEGY FROZEN",
                detail="Waiting for restart compound, grid order, fuel and fresh telemetry.",
                evidence=["Tactical calls suppressed during the stoppage"],
                change_reason="Red flag", critical=True)
        if phase in ("FORMATION", "RESTARTING"):
            headline = ("FORMATION LAP — STRATEGY CALIBRATING" if phase == "FORMATION"
                        else "RESTART — READING FRESH CAR STATE")
            return StrategyRecommendation(
                action="REASSESS", lap=lap, headline=headline,
                detail="Waiting for stable motion, fitted compound, wear, fuel, damage and grid order.",
                evidence=["Pre-red-flag gaps and pit windows remain invalid"],
                change_reason="Restart calibration", critical=True)
        if not str(session.get("type") or "").casefold().startswith("race"):
            return StrategyRecommendation(
                action="REASSESS", lap=lap, headline="RACE STRATEGY STANDBY",
                detail="Live pit optimization activates in a race session.")
        completed_green_laps = max(0, lap - 1)
        actual_wet = int(session.get("weather") or 0) >= 3
        early_emergency = (wear >= 75 or wing >= 35 or actual_wet or
                           phase in ("SC", "VSC"))
        if completed_green_laps < 5 and scenario.total_laps > 8 and not early_emergency:
            needed = 5 - completed_green_laps
            return StrategyRecommendation(
                action="STAY OUT", lap=lap,
                headline="STAY OUT — DO NOT PIT",
                detail=(f"NORMAL PACE · HOLD POSITION · {completed_green_laps}/5 opening "
                        f"laps complete · review in {needed} "
                        f"lap{'s' if needed != 1 else ''}."),
                evidence=[
                    "ERS: recharge out of combat; deploy only to attack or defend",
                    "TYRES: normal pace; avoid wheelspin and sliding",
                    "OVERRIDE: damage, rain, Safety Car or VSC triggers an immediate review",
                ],
                change_reason="Opening-lap strategy guard", critical=False)
        if not results:
            return StrategyRecommendation(
                action="REASSESS", lap=lap, headline="NO VALID STRATEGY",
                detail="Tyre life or compound constraints require fresh telemetry.", critical=True)

        ranked = list(results)
        best = ranked[0]
        target = best.stops[0] if best.stops else None
        compound = best.compounds[0] if best.compounds else None
        critical = wear >= 75 or wing >= 35 or actual_wet
        if critical:
            target = lap + 1
            if wing >= 35 and scenario.rain < .28:
                remaining = scenario.total_laps - lap
                compound = ("Medium" if remaining > 20 else "Soft")
                if compound == scenario.current_compound:
                    compound = "Hard" if compound != "Hard" else "Medium"
            elif not compound:
                choices = ("Intermediate", "Wet") if scenario.rain >= .28 else (
                    "Soft", "Medium", "Hard")
                compound = next((item for item in choices if item != scenario.current_compound),
                                choices[0])

        next_best = ranked[1].total_seconds if len(ranked) > 1 else best.total_seconds
        advantage = max(0.0, next_best - best.total_seconds)
        rejoin = self._predicted_rejoin(context, scenario.pit_loss)
        evidence = [
            f"Worst tyre {wear:.0f}% · projected {scenario.wear_per_lap:.2f}%/lap",
            f"Track pit loss {scenario.pit_loss:.0f}s · predicted rejoin " +
            (f"P{rejoin}" if rejoin else "unknown"),
        ]
        if phase in ("SC", "VSC"):
            evidence.append(f"{phase} reduces effective pit loss")
        if scenario.rain >= .28:
            evidence.append(f"Wet-weather crossover risk {scenario.rain*100:.0f}%")
        if wing >= 15:
            evidence.append(f"Front-wing damage {wing:.0f}%")
        ideal, latest = session.get("pit_ideal_lap"), session.get("pit_latest_lap")
        reference = get_reference(session.get("track"))
        if reference and reference.get("strategy_50"):
            evidence.append(f"Community 50% prior: {reference['strategy_50']}")
        if ideal:
            evidence.append(f"Game window L{ideal}" + (f"–{latest}" if latest else ""))

        if target is None:
            action, headline = "STAY OUT", "STAY OUT — CURRENT STINT IS FASTER"
            detail = "No stop beats the valid alternatives from the current race state."
        elif target <= lap + 1:
            action, headline = "PIT NOW", f"BOX THIS LAP — FIT {compound.upper()}"
            detail = f"Expected rejoin P{rejoin}. " if rejoin else ""
            detail += "Commit unless race control or weather changes."
        else:
            action, headline = "PIT WINDOW", f"TARGET LAP {target} — FIT {compound.upper()}"
            detail = f"Window L{max(lap+1, target-1)}–{min(scenario.total_laps, target+1)}"
            detail += f" · predicted rejoin P{rejoin}" if rejoin else ""
        uncertainty = float(best.confidence_seconds)
        options = [{
            "rank": index + 1, "label": result.label,
            "total_time": format_race_time(result.total_seconds),
            "delta": round(result.delta, 2), "finish_wear": round(result.finish_wear, 1),
            "stops": list(result.stops), "compounds": list(result.compounds),
            "wear_trace": [round(value, 2) for value in result.wear_trace],
        } for index, result in enumerate(ranked[:6])]
        return StrategyRecommendation(
            action=action, lap=lap, target_lap=target,
            window_start=max(lap+1, target-1) if target else None,
            window_end=min(scenario.total_laps, target+1) if target else None,
            compound=compound, predicted_rejoin=rejoin,
            advantage_seconds=round(advantage, 2),
            confidence=self._confidence(uncertainty, len(evidence)),
            uncertainty_seconds=round(uncertainty, 2), headline=headline,
            detail=detail, evidence=evidence, critical=critical,
            change_reason="Critical condition" if critical else "Live context changed",
            options=options)

    @staticmethod
    def _key(rec):
        return rec.action, rec.target_lap, rec.compound

    def update(self, context, force=False):
        player, session = context.get("player") or {}, context.get("session") or {}
        phase = self._phase(context)
        race_control_changed = phase != self._last_phase
        self._last_phase = phase
        wear = max(player.get("tyre_wear") or [0])
        damage = context.get("damage") or {}
        signature = (
            session.get("track"), session.get("type"), player.get("lap_num"),
            player.get("compound"), int(float(wear) // 2),
            round(float(player.get("fuel_delta_laps") or 0), 1), player.get("position"),
            phase, bool((context.get("race_control") or {}).get("finished")),
            session.get("weather"), session.get("pit_ideal_lap"),
            int(max(float(damage.get("front_wing_left") or 0),
                    float(damage.get("front_wing_right") or 0)) // 5),
            tuple((car.get("position"), int(float(car.get("gap_to_player") or 0)))
                  for car in (context.get("field") or [])[:8]),
        )
        if not force and signature == self._signature:
            return self.current.to_dict()
        self._signature = signature
        scenario = self._scenario(context)
        results = self.engine.generate(scenario, max_results=40)
        results = self._contextualize_results(context, scenario, results)[:16]
        candidate = self._build(context, results, scenario)
        changed = self._key(candidate) != self._key(self.current)
        if (changed and not candidate.critical and self.current.lap is not None and
                self.current.action != "REASSESS" and not race_control_changed):
            threshold = max(.75, .25 * candidate.uncertainty_seconds)
            old_still_valid = (self.current.target_lap is None or
                               self.current.target_lap > scenario.current_lap)
            # Compare the fresh best plan against what the *currently displayed*
            # recommendation actually costs under today's scenario, not against
            # the runner-up in the new ranking -- otherwise a close 1st/2nd split
            # in every fresh re-rank permanently pins the old, possibly far
            # worse, call in place and the tool never updates.
            real_advantage = candidate.advantage_seconds
            if old_still_valid and self._current_plan is not None and results:
                old_result = self.engine.simulate(scenario, *self._current_plan)
                real_advantage = old_result.total_seconds - results[0].total_seconds
            if old_still_valid and real_advantage < threshold:
                return self.current.to_dict()
        if results:
            self._current_plan = (results[0].stops, results[0].compounds)
        if changed:
            self.current = candidate
            if self.database:
                self.database.record_strategy_decision(candidate.to_dict())
        else:
            candidate.change_reason = self.current.change_reason
            self.current = candidate
        return self.current.to_dict()
