import unittest

from f1_26_split_telemetry import HEADER_SIZE, Receiver, Shared
from f1_race_control import GREEN, RED_FLAG, RESTARTING, RaceControlTracker


class RaceControlTests(unittest.TestCase):
    def test_red_flag_freezes_until_restart_motion_is_stable(self):
        tracker = RaceControlTracker()
        tracker.consume_event("RDFL", now=10)
        self.assertEqual(tracker.phase, RED_FLAG)
        self.assertTrue(tracker.red_flag_active)
        tracker.consume_session(0)
        self.assertEqual(tracker.phase, RED_FLAG)
        tracker.consume_event("SSTA", now=20)
        self.assertEqual(tracker.phase, RESTARTING)
        self.assertFalse(tracker.observe_motion(20, now=21))
        self.assertTrue(tracker.observe_motion(20, now=23.1))
        self.assertEqual(tracker.phase, GREEN)

    def test_receiver_parses_event_code(self):
        shared = Shared()
        receiver = Receiver(shared, 0, ".")
        receiver._parse_event(bytes(HEADER_SIZE) + b"RDFL")
        self.assertEqual(shared.race_control["phase"], RED_FLAG)
        self.assertEqual(shared.race_control["last_event"]["code"], "RDFL")

    def test_safety_car_resume_starts_red_flag_restart(self):
        tracker = RaceControlTracker()
        tracker.consume_event("RDFL", now=1)
        event = tracker.consume_safety_event(3, 3, now=2)
        self.assertEqual(tracker.phase, RESTARTING)
        self.assertIn("resume race", event.detail)


if __name__ == "__main__":
    unittest.main()
