import os
import tempfile
import unittest

from f1_database import TelemetryDatabase
from f1_driver_learning import DriverLearning


class DriverLearningTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.db = TelemetryDatabase(os.path.join(self.folder.name, "learning.db"))

    def tearDown(self):
        self.db.close()
        self.folder.cleanup()

    def _session(self, uid, session_type, lap_times):
        session_id = self.db.begin_session(uid)
        self.db.update_session({"type": session_type, "track": "Monza",
                                "laps": len(lap_times), "session_length": 6})
        for index, lap_time in enumerate(lap_times, 1):
            self.db.conn.execute(
                """INSERT INTO laps(session_id,player,lap_number,lap_time_ms,
                   sector1_ms,sector2_ms,sector3_ms,valid,position,compound,tyre_age,
                   wear_start,wear_end,fuel_start,fuel_end,ers_start,ers_end,
                   full_throttle_pct,heavy_brake_pct)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (session_id, "p1", index, lap_time, 27000, 28000,
                 lap_time - 55000, 1, 8-index, "Medium", index-1,
                 10+index*2, 12+index*2, 30-index*1.6, 28.4-index*1.6,
                 3_500_000-index*100_000, 3_400_000-index*100_000, 55, 9))
        self.db.conn.execute(
            "UPDATE sessions SET completed_laps=?,best_lap_ms=? WHERE id=?",
            (len(lap_times), min(lap_times), session_id))
        self.db.conn.commit()
        return session_id

    def test_learning_separates_phases_and_rejects_outlier_pace(self):
        self._session("practice", "P1", [90000, 90200, 89900, 120000, 90100])
        self._session("race", "Race", [91000, 91200, 90900, 91100, 91300])
        profile = DriverLearning(self.db).profile("Monza")
        self.assertEqual(profile["stages"]["practice"]["clean_laps"], 4)
        self.assertEqual(profile["stages"]["race"]["clean_laps"], 5)
        self.assertLess(profile["stages"]["practice"]["pace_consistency_ms"], 200)

    def test_time_trial_is_a_separate_pace_only_model(self):
        self._session("tt", "Time Trial", [80000, 80100, 79950])
        profile = DriverLearning(self.db).profile("Monza")
        self.assertEqual(profile["stages"]["time_trial"]["clean_laps"], 3)
        self.assertEqual(profile["stages"]["practice"]["clean_laps"], 0)
        strategy = DriverLearning(self.db).strategy_profile("Monza")
        self.assertEqual(strategy["pace_source_phase"], "time_trial")
        self.assertEqual(strategy["source_phase"], "practice")

    def test_session_report_and_monthly_number_are_structured(self):
        session_id = self._session("report", "Race", [91000, 90800, 90600])
        row = self.db.session_details(session_id)
        report = DriverLearning(self.db).session_report(session_id)
        self.assertRegex(row["display_name"], r"[A-Z]+ .* SESSION \d{2}")
        self.assertEqual(report["overview"]["valid_laps"], 3)
        self.assertEqual(report["learning_phase"], "race")
        self.assertTrue(report["stints"])


if __name__ == "__main__":
    unittest.main()
