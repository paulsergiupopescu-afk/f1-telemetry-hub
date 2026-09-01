"""Robust, session-aware learning from the driver's recorded telemetry."""

from __future__ import annotations

import statistics


def _median(values, default=None):
    clean = [float(value) for value in values if value is not None]
    return statistics.median(clean) if clean else default


def _mean(values, default=None):
    clean = [float(value) for value in values if value is not None]
    return statistics.fmean(clean) if clean else default


def _stdev(values):
    clean = [float(value) for value in values if value is not None]
    return statistics.pstdev(clean) if len(clean) >= 2 else None


class DriverLearning:
    """Build separate practice, qualifying and race models with quality gates."""

    def __init__(self, database):
        self.db = database

    def _sessions(self, track=None):
        rows = self.db.list_sessions(500)
        if track:
            rows = [row for row in rows if row.get("track_name") == track]
        return [row for row in rows if (row.get("completed_laps") or 0) > 0]

    @staticmethod
    def _phase(session_type):
        name = str(session_type or "").casefold()
        if "time trial" in name:
            return "time_trial"
        if name.startswith("race"):
            return "race"
        if "q" in name or "qual" in name:
            return "qualifying"
        if name.startswith("p") or "practice" in name:
            return "practice"
        return "other"

    def _phase_data(self, sessions, phase):
        chosen = [row for row in sessions if self._phase(row.get("session_type")) == phase]
        all_laps, styles = [], []
        for session in chosen:
            laps = self.db.session_laps(session["id"])
            valid_times = [lap.get("lap_time_ms") for lap in laps
                           if lap.get("valid") and (lap.get("lap_time_ms") or 0) > 30_000]
            centre = _median(valid_times)
            for lap in laps:
                item = dict(lap)
                item["session_id"] = session["id"]
                item["clean_pace"] = bool(
                    item.get("valid") and centre and item.get("lap_time_ms") and
                    .93 * centre <= item["lap_time_ms"] <= 1.07 * centre)
                all_laps.append(item)
            style = self.db.session_style(session["id"])
            if style and (style.get("lap_count") or 0) > 0:
                styles.append(style)
        clean = [lap for lap in all_laps if lap.get("clean_pace")]
        fuel = [lap["fuel_start"] - lap["fuel_end"] for lap in all_laps
                if lap.get("fuel_start") is not None and lap.get("fuel_end") is not None and
                .3 <= lap["fuel_start"] - lap["fuel_end"] <= 4.0]
        wear = [lap["wear_end"] - lap["wear_start"] for lap in all_laps
                if lap.get("wear_start") is not None and lap.get("wear_end") is not None and
                .30 <= lap["wear_end"] - lap["wear_start"] <= 10.0]
        pace = [lap["lap_time_ms"] for lap in clean]
        invalid = [lap for lap in all_laps if not lap.get("valid")]
        return {
            "sessions": len(chosen), "laps": len(all_laps), "clean_laps": len(clean),
            "best_lap_ms": min(pace) if pace else None,
            "median_lap_ms": _median(pace), "pace_consistency_ms": _stdev(pace),
            "fuel_per_lap": _median(fuel), "wear_per_lap": _median(wear),
            "invalid_rate": len(invalid) / len(all_laps) * 100 if all_laps else None,
            "full_throttle_pct": _median([lap.get("full_throttle_pct") for lap in clean]),
            "heavy_brake_pct": _median([lap.get("heavy_brake_pct") for lap in clean]),
            "ers_net_use_j": _median([
                max(0, (lap.get("ers_start") or 0) - (lap.get("ers_end") or 0))
                for lap in clean]),
            "rear_front_temp_delta": _median(
                [style.get("rear_front_temp_delta") for style in styles]),
            "rear_front_wear_delta": _median(
                [style.get("rear_front_wear_delta") for style in styles]),
        }

    @staticmethod
    def _confidence(data):
        laps = data.get("clean_laps") or 0
        return "HIGH" if laps >= 15 else ("MEDIUM" if laps >= 5 else "LOW")

    def profile(self, track=None):
        sessions = self._sessions(track)
        stages = {phase: self._phase_data(sessions, phase)
                  for phase in ("time_trial", "practice", "qualifying", "race")}
        for stage in stages.values():
            stage["confidence"] = self._confidence(stage)
        return {"track": track, "sessions": len(sessions),
                "laps": sum(stage["laps"] for stage in stages.values()),
                "stages": stages, "feedback": self._feedback(stages)}

    def strategy_profile(self, track=None):
        profile = self.profile(track)
        race, practice = profile["stages"]["race"], profile["stages"]["practice"]
        time_trial = profile["stages"]["time_trial"]
        source = race if (race.get("clean_laps") or 0) >= 3 else practice
        pace_source = source if (source.get("clean_laps") or 0) >= 3 else time_trial
        return {
            "sessions": source.get("sessions") or 0,
            "laps": source.get("clean_laps") or 0,
            "fuel_per_lap": source.get("fuel_per_lap"),
            "wear_per_lap": source.get("wear_per_lap"),
            "pace_consistency_ms": pace_source.get("pace_consistency_ms"),
            "rear_front_temp_delta": source.get("rear_front_temp_delta"),
            "rear_front_wear_delta": source.get("rear_front_wear_delta"),
            "confidence": source.get("confidence"),
            "source_phase": "race" if source is race else "practice",
            "pace_source_phase": ("time_trial" if pace_source is time_trial else
                                  ("race" if pace_source is race else "practice")),
        }

    def session_report(self, session_id):
        details = self.db.session_details(session_id)
        laps = self.db.session_laps(session_id)
        style = self.db.session_style(session_id)
        setup = self.db.session_setup(session_id)
        samples = self.db.session_samples(session_id, limit=1200)
        events = self.db.session_race_control_events(session_id)
        decisions = self.db.session_strategy_decisions(session_id)
        valid = [lap for lap in laps if lap.get("valid") and
                 (lap.get("lap_time_ms") or 0) > 30_000]
        median_time = _median([lap.get("lap_time_ms") for lap in valid])
        clean = [lap for lap in valid if median_time and
                 .93 * median_time <= lap["lap_time_ms"] <= 1.07 * median_time]
        theoretical = sum(min((lap.get(key) for lap in valid if lap.get(key)), default=0)
                          for key in ("sector1_ms", "sector2_ms", "sector3_ms"))
        fuel_used = sum(max(0, (lap.get("fuel_start") or 0) -
                                (lap.get("fuel_end") or 0)) for lap in laps)
        positions = [lap.get("position") for lap in laps if lap.get("position")]
        stints, current = [], None
        for lap in laps:
            compound = lap.get("compound") or "Unknown"
            age = lap.get("tyre_age")
            if current is None or compound != current["compound"] or (
                    age is not None and current.get("last_age") is not None and
                    age < current["last_age"]):
                current = {"compound": compound, "start_lap": lap.get("lap_number"),
                           "end_lap": lap.get("lap_number"), "laps": 0,
                           "start_wear": lap.get("wear_start"), "end_wear": lap.get("wear_end"),
                           "times": [], "last_age": age}
                stints.append(current)
            current["end_lap"] = lap.get("lap_number")
            current["laps"] += 1
            current["end_wear"] = lap.get("wear_end")
            current["last_age"] = age
            if lap.get("valid") and lap.get("lap_time_ms"):
                current["times"].append(lap["lap_time_ms"])
        for stint in stints:
            stint["average_lap_ms"] = _mean(stint.pop("times"))
            stint.pop("last_age", None)
            if stint.get("start_wear") is not None and stint.get("end_wear") is not None:
                stint["wear_delta"] = stint["end_wear"] - stint["start_wear"]
        track_profile = self.profile(details.get("track_name")) if details else self.profile()
        phase = self._phase(details.get("session_type"))
        coaching_zones = self._coaching_zones(samples, valid)
        feedback = list(track_profile.get("feedback", {}).get(phase, []))
        for zone in coaching_zones:
            feedback.append({
                "title": f"PACE OPPORTUNITY · {zone['start_pct']}–{zone['end_pct']}% OF LAP",
                "detail": f"{zone['speed_deficit_kmh']:.1f} km/h below your best clean trace. {zone['advice']}"})
        return {
            "details": details, "laps": laps, "style": style, "setup": setup,
            "telemetry": samples, "race_control": events, "strategy": decisions,
            "overview": {
                "valid_laps": len(valid), "clean_laps": len(clean),
                "best_lap_ms": min((lap["lap_time_ms"] for lap in valid), default=None),
                "median_lap_ms": _median([lap["lap_time_ms"] for lap in clean]),
                "theoretical_lap_ms": theoretical or None,
                "consistency_ms": _stdev([lap["lap_time_ms"] for lap in clean]),
                "fuel_used_kg": fuel_used, "start_position": positions[0] if positions else None,
                "finish_position": positions[-1] if positions else None,
                "positions_gained": positions[0] - positions[-1] if positions else None,
                "max_wear": max((lap.get("wear_end") or 0 for lap in laps), default=0),
            },
            "stints": stints, "learning_phase": phase,
            "coaching_zones": coaching_zones,
            "feedback": feedback,
            "learning_profile": track_profile.get("stages", {}).get(phase, {}),
        }

    @staticmethod
    def _coaching_zones(samples, valid_laps, bins=20):
        """Compare representative laps with the driver's own best clean trace."""
        if not samples or len(valid_laps) < 2:
            return []
        best = min(valid_laps, key=lambda lap: lap.get("lap_time_ms") or 10**9)
        clean_numbers = {lap.get("lap_number") for lap in valid_laps}
        distance = max((row.get("lap_distance") or 0 for row in samples), default=0)
        if distance < 500:
            return []
        grouped = {}
        for row in samples:
            lap_number, lap_distance = row.get("lap_num"), row.get("lap_distance")
            if lap_number not in clean_numbers or lap_distance is None or lap_distance < 0:
                continue
            bucket = min(bins - 1, int(lap_distance / distance * bins))
            cell = grouped.setdefault((lap_number, bucket),
                                      {"speed": [], "throttle": [], "brake": []})
            for key, source in (("speed", "speed_kmh"), ("throttle", "throttle"),
                                ("brake", "brake")):
                if row.get(source) is not None:
                    cell[key].append(row[source])
        candidates = []
        for bucket in range(bins):
            reference = grouped.get((best.get("lap_number"), bucket))
            others = [value for (lap_number, index), value in grouped.items()
                      if index == bucket and lap_number != best.get("lap_number")]
            if not reference or not others:
                continue
            ref_speed = _mean(reference["speed"])
            typical_speed = _median([_mean(value["speed"]) for value in others])
            if ref_speed is None or typical_speed is None or ref_speed - typical_speed < 2:
                continue
            ref_throttle = _mean(reference["throttle"], 0)
            typical_throttle = _median([_mean(value["throttle"], 0) for value in others], 0)
            typical_brake = _median([_mean(value["brake"], 0) for value in others], 0)
            if ref_throttle - typical_throttle > .08:
                advice = "Your reference returns to throttle earlier; prioritise exit shape and progressive power."
            elif typical_brake > .12:
                advice = "More braking remains in the typical trace; release the brake progressively through the zone."
            else:
                advice = "Minimum speed is below your reference; test a cleaner entry and preserve momentum."
            candidates.append({"start_pct": round(bucket / bins * 100),
                               "end_pct": round((bucket + 1) / bins * 100),
                               "speed_deficit_kmh": round(ref_speed-typical_speed, 1),
                               "advice": advice})
        return sorted(candidates, key=lambda item: item["speed_deficit_kmh"],
                      reverse=True)[:3]

    @staticmethod
    def _feedback(stages):
        time_trial, practice, qualifying, race = (stages[key] for key in
            ("time_trial", "practice", "qualifying", "race"))
        feedback = {"time_trial": [], "practice": [], "qualifying": [], "race": []}
        tt_spread = time_trial.get("pace_consistency_ms")
        if tt_spread is not None and tt_spread > 500:
            feedback["time_trial"].append({"title": "TURN PEAK PACE INTO A REPEATABLE TRACE",
                "detail": f"Clean Time Trial laps vary by ±{tt_spread/1000:.2f}s. Compare the three largest speed-loss zones with your personal best."})
        tt_invalid = time_trial.get("invalid_rate")
        if tt_invalid is not None and tt_invalid >= 20:
            feedback["time_trial"].append({"title": "REDUCE INVALID-LAP RATE",
                "detail": f"{tt_invalid:.0f}% of recorded Time Trial laps were invalid or incomplete. Build margin at the exits that repeatedly break the lap."})
        rear_temp = practice.get("rear_front_temp_delta")
        if rear_temp is not None and rear_temp > 5:
            feedback["practice"].append({"title": "REAR-LIMITED LONG RUN",
                "detail": f"Rear tyres average {rear_temp:.1f}°C hotter. Use smoother exits and test a calmer rear balance."})
        if practice.get("clean_laps", 0) < 5:
            feedback["practice"].append({"title": "BUILD A CLEAN FIVE-LAP RUN",
                "detail": "The tyre and fuel model needs at least five representative laps on one compound."})
        q_spread = qualifying.get("pace_consistency_ms")
        if q_spread is not None and q_spread > 700:
            feedback["qualifying"].append({"title": "QUALIFYING EXECUTION VARIES",
                "detail": f"Clean-lap spread is ±{q_spread/1000:.2f}s. Prioritise repeatable tyre preparation and the final braking zones."})
        invalid = qualifying.get("invalid_rate")
        if invalid is not None and invalid >= 20:
            feedback["qualifying"].append({"title": "BANK THE FIRST PUSH LAP",
                "detail": f"{invalid:.0f}% of recorded qualifying laps were invalid or incomplete."})
        rear_wear = race.get("rear_front_wear_delta")
        if rear_wear is not None and rear_wear > 1:
            feedback["race"].append({"title": "PROTECT REAR TYRES IN RACE TRIM",
                "detail": f"Rear wear averages {rear_wear:.1f}% above the front. Short-shift traction zones when the stint is marginal."})
        race_ers = race.get("ers_net_use_j")
        if race_ers is not None and race_ers > 900_000:
            feedback["race"].append({"title": "PLAN ERS RECOVERY LAPS",
                "detail": f"Battery state falls about {race_ers/1_000_000:.1f} MJ per representative lap. Recover before the main attack straight."})
        if race.get("clean_laps", 0) < 5:
            feedback["race"].append({"title": "RACE MODEL STILL LOW CONFIDENCE",
                "detail": "Complete five uninterrupted green-flag laps to stabilize pit and degradation forecasts."})
        for phase in feedback:
            if not feedback[phase]:
                feedback[phase].append({"title": "MODEL BALANCED",
                    "detail": "No strong recurring weakness is supported by the current clean-lap sample."})
        return feedback
