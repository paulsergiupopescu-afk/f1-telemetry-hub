import unittest

from f1_setup_packages import _library, package_data
from f1_strategy import Scenario, StrategyEngine
from f1_web_app import describe_prerace_result


class BrendonSetupPackageTests(unittest.TestCase):
    def test_every_pdf_variant_is_imported_as_structured_data(self):
        tracks = _library()["tracks"]
        self.assertEqual(len(tracks), 25)
        self.assertTrue(all(set(values) == {
            "race", "qualifying", "intermediates", "wets"}
            for values in tracks.values()))

    def test_monza_race_values_match_source_card(self):
        setup = package_data("Monza")["variants"]["race"]
        self.assertEqual((setup["front_wing"], setup["rear_wing"]), (16, 4))
        self.assertEqual((setup["on_throttle_diff"], setup["off_throttle_diff"]),
                         (100, 30))
        self.assertEqual((setup["front_suspension"], setup["rear_suspension"]),
                         (41, 10))
        self.assertEqual((setup["front_ride_height"], setup["rear_ride_height"]),
                         (21, 40))
        self.assertEqual(setup["brake_bias"], [55, 54])
        self.assertEqual((setup["front_left_pressure"], setup["rear_left_pressure"]),
                         (29.5, 22.0))

    def test_game_track_alias_resolves_package(self):
        self.assertEqual(package_data("Netherlands")["track"], "Zandvoort")
        self.assertEqual(package_data("Spa")["track"], "Belgium")

    def test_strategy_result_explains_lap_compound_and_reason(self):
        scenario = Scenario(total_laps=27, current_lap=1,
                            current_compound="Medium", wear_per_lap=1.8,
                            pit_loss=24, traffic=.25)
        result = StrategyEngine().generate(scenario, 1)[0]
        description = describe_prerace_result(result, scenario, {}, 1)
        self.assertIn("START MEDIUM", description["instruction"])
        self.assertGreaterEqual(len(description["why"]), 3)
        self.assertEqual(description["stints"][0]["compound"], "Medium")


if __name__ == "__main__":
    unittest.main()
