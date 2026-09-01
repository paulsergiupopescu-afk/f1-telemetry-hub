import json
from pathlib import Path

from f1_behavior_tracker import BehaviorTracker


def test_behavior_tracker_writes_structured_events_and_redacts_secrets(tmp_path):
    tracker = BehaviorTracker(tmp_path, app_version=99)
    tracker.log("strategy_changed", action="PIT NOW", api_key="never-store-this",
                nested={"access_token": "also-secret", "lap": 18})

    rows = [json.loads(line) for line in Path(tracker.path).open(encoding="utf-8")]
    event = rows[-1]
    assert event["event"] == "strategy_changed"
    assert event["details"]["action"] == "PIT NOW"
    assert event["details"]["api_key"] == "[redacted]"
    assert event["details"]["nested"]["access_token"] == "[redacted]"
    assert event["details"]["nested"]["lap"] == 18

    summary = tracker.summary()
    assert summary["enabled"] is True
    assert summary["counts"]["info:strategy_changed"] == 1
    assert summary["run_id"] == event["run_id"]


def test_behavior_tracker_rotates_small_logs(tmp_path):
    tracker = BehaviorTracker(tmp_path)
    tracker.MAX_BYTES = 200
    tracker.BACKUPS = 2
    for index in range(8):
        tracker.log("large_event", index=index, message="x" * 180)

    assert Path(tracker.path).exists()
    assert (tmp_path / "diagnostics" / "app-behavior.jsonl.1").exists()
    assert not (tmp_path / "diagnostics" / "app-behavior.jsonl.3").exists()
