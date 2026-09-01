import unittest

from f1_live_strategy import LiveStrategyEngine
from f1_strategy import Scenario, StrategyEngine


def context(**overrides):
    base = {
        "session": {"track": "Monza", "type": "Race", "laps": 27,
                    "weather": 0, "trackTemp": 34, "pit_ideal_lap": 12,
                    "pit_latest_lap": 14, "weather_forecast": []},
        "race_control": {"phase": "GREEN"},
        "player": {"lap_num": 10, "position": 7, "compound": "Medium",
                   "tyre_age": 9, "pit_stops": 0, "tyre_wear": [31, 32, 28, 29],
                   "fuel_kg": 31, "fuel_delta_laps": .5, "best_lap_ms": 81000},
        "profile": {"fuel_per_lap": 1.7, "wear_per_lap": 2.8,
                    "pace_consistency_ms": 420},
        "damage": {},
        "field": [
            {"position": 6, "name": "RIVAL", "gap_to_player": -1.2, "tyre_age": 12},
            {"position": 8, "name": "CHASER", "gap_to_player": 3.4, "tyre_age": 8},
            {"position": 9, "name": "TRAFFIC", "gap_to_player": 22.0, "tyre_age": 6},
        ],
    }
    base.update(overrides)
    return base


class LiveStrategyTests(unittest.TestCase):
    def test_red_flag_suppresses_pit_call(self):
        value = context(race_control={"phase": "RED_FLAG"})
        recommendation = LiveStrategyEngine().update(value, force=True)
        self.assertEqual(recommendation["action"], "REASSESS")
        self.assertIn("RED FLAG", recommendation["headline"])
        self.assertTrue(recommendation["critical"])

    def test_critical_wear_boxes_immediately(self):
        value = context()
        value["player"] = {**value["player"], "tyre_wear": [78, 77, 73, 75]}
        recommendation = LiveStrategyEngine().update(value, force=True)
        self.assertEqual(recommendation["action"], "PIT NOW")
        self.assertEqual(recommendation["target_lap"], 11)

    def test_monaco_requires_two_remaining_stops(self):
        scenario = Scenario(total_laps=20, current_lap=1, current_compound="Medium",
                            min_stops=2, min_dry_compounds=2)
        results = StrategyEngine().generate(scenario, 40)
        self.assertTrue(results)
        self.assertTrue(all(len(result.stops) >= 2 for result in results))

    def test_result_contains_explainable_options(self):
        recommendation = LiveStrategyEngine().update(context(), force=True)
        self.assertIn(recommendation["action"], {"PIT NOW", "PIT WINDOW", "STAY OUT"})
        self.assertGreaterEqual(len(recommendation["evidence"]), 2)
        self.assertGreater(len(recommendation["options"]), 0)

    def test_safety_car_brings_the_stop_forward(self):
        green = LiveStrategyEngine().update(context(), force=True)
        caution = context(race_control={"phase": "SC"})
        safety_car = LiveStrategyEngine().update(caution, force=True)
        self.assertLessEqual(safety_car["target_lap"], green["target_lap"])
        self.assertTrue(any("reduces effective pit loss" in item
                            for item in safety_car["evidence"]))

    def test_rain_crossover_selects_wet_weather_tyre(self):
        value = context()
        value["session"] = {**value["session"], "weather": 3}
        recommendation = LiveStrategyEngine().update(value, force=True)
        self.assertEqual(recommendation["action"], "PIT NOW")
        self.assertIn(recommendation["compound"], {"Intermediate", "Wet"})

    def test_wing_damage_is_an_immediate_override(self):
        value = context(damage={"front_wing_left": 45, "front_wing_right": 20})
        recommendation = LiveStrategyEngine().update(value, force=True)
        self.assertEqual(recommendation["action"], "PIT NOW")
        self.assertTrue(recommendation["critical"])

    def test_live_traffic_changes_predicted_rejoin(self):
        clear = LiveStrategyEngine().update(context(), force=True)
        value = context(field=[
            {"position": 6, "name": "RIVAL", "gap_to_player": -1, "tyre_age": 12},
            {"position": 8, "name": "TRAFFIC", "gap_to_player": 20.5, "tyre_age": 6},
        ])
        traffic = LiveStrategyEngine().update(value, force=True)
        self.assertNotEqual(traffic["predicted_rejoin"], clear["predicted_rejoin"])

    def test_red_flag_restart_holds_until_green_and_uses_fresh_context(self):
        engine = LiveStrategyEngine()
        red = engine.update(context(race_control={"phase": "RED_FLAG"}))
        self.assertEqual(red["action"], "REASSESS")
        formation = engine.update(context(race_control={"phase": "FORMATION"}))
        self.assertEqual(formation["action"], "REASSESS")
        restarting = engine.update(context(race_control={"phase": "RESTARTING"}))
        self.assertEqual(restarting["action"], "REASSESS")
        fresh = context(race_control={"phase": "GREEN"})
        fresh["player"] = {**fresh["player"], "compound": "Hard", "tyre_age": 0,
                           "tyre_wear": [0, 0, 0, 0], "position": 4,
                           "fuel_kg": 24.5}
        green = engine.update(fresh)
        self.assertNotEqual(green["action"], "REASSESS")
        self.assertEqual(green["lap"], fresh["player"]["lap_num"])

    def test_race_control_change_bypasses_noncritical_hysteresis(self):
        engine = LiveStrategyEngine()
        engine.update(context(), force=True)
        safety_car = engine.update(context(race_control={"phase": "SC"}))
        self.assertTrue(any("reduces effective pit loss" in item
                            for item in safety_car["evidence"]))

    def test_finish_event_closes_tactical_strategy(self):
        recommendation = LiveStrategyEngine().update(
            context(race_control={"phase": "GREEN", "finished": True}))
        self.assertEqual(recommendation["action"], "REASSESS")
        self.assertIn("SESSION COMPLETE", recommendation["headline"])

    def test_weather_crossover_is_an_immediate_override(self):
        engine = LiveStrategyEngine()
        engine.update(context(), force=True)
        wet = context()
        wet["session"] = {**wet["session"], "weather": 4}
        recommendation = engine.update(wet)
        self.assertEqual(recommendation["action"], "PIT NOW")
        self.assertTrue(recommendation["critical"])

    def test_red_bull_ring_lap_two_hard_does_not_trigger_early_soft_stop(self):
        value = context()
        value["session"] = {
            **value["session"], "track": "Red Bull Ring", "laps": 71,
            "pit_ideal_lap": 27, "pit_latest_lap": 50, "weather": 0,
            "weather_forecast": [{"minutes": 10, "rain": 3}],
        }
        value["player"] = {
            **value["player"], "lap_num": 2, "position": 3,
            "compound": "Hard", "tyre_age": 1, "pit_stops": 0,
            "tyre_wear": [3, 3, 1, 3], "fuel_kg": 76.06,
            "fuel_delta_laps": 5.3, "best_lap_ms": 77207,
        }
        value["profile"] = {
            "laps": 1, "fuel_per_lap": .96, "wear_per_lap": .1225,
            "pace_consistency_ms": 500,
        }
        recommendation = LiveStrategyEngine().update(value, force=True)
        self.assertEqual(recommendation["action"], "STAY OUT")
        self.assertIsNone(recommendation["target_lap"])
        self.assertEqual(recommendation["headline"], "STAY OUT — DO NOT PIT")
        value["damage"] = {"front_wing_left": 58, "front_wing_right": 58}
        emergency = LiveStrategyEngine().update(value, force=True)
        self.assertEqual(emergency["action"], "PIT NOW")
        self.assertEqual(emergency["compound"], "Medium")

    def test_low_sample_wear_rate_uses_conservative_fallback(self):
        value = context()
        value["profile"] = {**value["profile"], "laps": 1, "wear_per_lap": .12}
        scenario = LiveStrategyEngine()._scenario(value)
        self.assertEqual(scenario.wear_per_lap, 1.6)

    def test_overcast_is_not_treated_as_wet_weather(self):
        value = context()
        value["session"] = {**value["session"], "weather": 2}
        scenario = LiveStrategyEngine()._scenario(value)
        self.assertEqual(scenario.rain, 0.0)


if __name__ == "__main__":
    unittest.main()
