import os
import tempfile
import unittest

from f1_26_split_telemetry import Shared
from f1_database import TelemetryDatabase
from f1_web_app import SnapshotBroker


class FakeReceiver:
    def field_snapshot(self):
        return []

    def all_gaps(self, *_args):
        return None, None, []


class SnapshotContractTests(unittest.TestCase):
    def test_disconnected_snapshot_is_complete(self):
        with tempfile.TemporaryDirectory() as folder:
            db = TelemetryDatabase(os.path.join(folder, "test.db"))
            broker = SnapshotBroker(Shared(), FakeReceiver(), db)
            snapshot = broker._build()
            for key in ("schema_version", "connection", "session", "race_control",
                        "player", "lap", "delta", "tyres", "field", "pace",
                        "micro_sectors", "engineer", "strategy", "ers", "track_map"):
                self.assertIn(key, snapshot)
            self.assertFalse(snapshot["connection"]["live"])
            db.close()


if __name__ == "__main__":
    unittest.main()
