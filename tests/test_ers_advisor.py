import unittest

from f1_engineer import ErsAdvisor


def status(percent=50, mode=1, deployed=500_000):
    values = [0] * 26
    values[19], values[20], values[23], values[24] = (
        percent / 100 * 4_000_000, mode, 2_000_000, deployed)
    return values


def telemetry(speed=180, throttle=.9, brake=0):
    values = [0] * 30
    values[0], values[1], values[3] = speed, throttle, brake
    return values


def lap(number=5, distance=1200):
    values = [0] * 30
    values[10], values[14] = distance, number
    return values


class ErsAdvisorTests(unittest.TestCase):
    def test_low_battery_requests_recovery(self):
        advisor = ErsAdvisor()
        advisor.messages(status(8, 3), telemetry(), None, 1, 2026,
                         lap(), {"type": "Race", "laps": 20}, [])
        self.assertEqual(advisor.snapshot()["action"], "RECHARGE")

    def test_close_battle_deploys_during_acceleration(self):
        advisor = ErsAdvisor()
        advisor.messages(status(60), telemetry(210), .7, 1, 2026,
                         lap(), {"type": "Race", "laps": 20}, [])
        self.assertEqual(advisor.snapshot()["action"], "DEPLOY")

    def test_top_speed_call_saves_for_next_exit(self):
        advisor = ErsAdvisor()
        advisor.messages(status(60), telemetry(310), .7, 1, 2026,
                         lap(), {"type": "Race", "laps": 20}, [])
        self.assertEqual(advisor.snapshot()["action"], "SAVE")

    def test_qualifying_uses_energy_on_exit(self):
        advisor = ErsAdvisor()
        advisor.messages(status(70), telemetry(170), None, 1, 2026,
                         lap(), {"type": "Q1", "laps": 8}, [])
        self.assertEqual(advisor.snapshot()["action"], "DEPLOY")


if __name__ == "__main__":
    unittest.main()
