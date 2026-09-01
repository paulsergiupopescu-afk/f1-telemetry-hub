import csv

from f1_database import SAMPLE_COLUMNS, TelemetryDatabase


def test_legacy_csv_recovery_is_idempotent_and_restores_session(tmp_path):
    reports = tmp_path / "solo_reports"
    reports.mkdir()
    path = reports / "f1_p1_s7_20260727_194315.csv"
    extra = ["driver", "track", "track_id", "session_type"]
    rows = []
    for lap, last_ms, wall in [(1, 0, 1785170000), (2, 90_000, 1785170090),
                                (3, 89_500, 1785170180)]:
        row = {key: "" for key in SAMPLE_COLUMNS + tuple(extra)}
        row.update({"wall_time": wall, "session_time": wall - 1785170000,
                    "frame": lap, "speed_kmh": 220, "gear": 6, "rpm": 11000,
                    "throttle": .8, "brake": 0, "steer": 0, "position": 4,
                    "lap_num": lap, "sector": 0, "lap_invalid": 0,
                    "cur_lap_ms": 1000, "last_lap_ms": last_ms,
                    "s1_ms": 30_000, "s2_ms": 30_000, "lap_distance": 100,
                    "tyre_visual": "Medium", "tyre_age_laps": lap,
                    "ers_store_j": 2_000_000, "fuel_kg": 30-lap,
                    "tyreTemp_RL": 90, "tyreTemp_RR": 90,
                    "tyreTemp_FL": 91, "tyreTemp_FR": 91,
                    "tyreWear_RL": lap, "tyreWear_RR": lap,
                    "tyreWear_FL": lap, "tyreWear_FR": lap,
                    "driver": "YOU", "track": "Monza", "track_id": 14,
                    "session_type": "Race"})
        rows.append(row)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(SAMPLE_COLUMNS) + extra)
        writer.writeheader(); writer.writerows(rows)

    database = TelemetryDatabase(tmp_path / "f1_telemetry.db")
    first = database.import_legacy_csv_folder(reports)
    second = database.import_legacy_csv_folder(reports)
    sessions = database.list_sessions()
    database.close()

    assert first == {"files": 1, "sessions": 1, "samples": 3}
    assert second == {"files": 1, "sessions": 0, "samples": 0}
    assert len(sessions) == 1
    assert sessions[0]["track_name"] == "Monza"
    assert sessions[0]["session_type"] == "Race"
    assert sessions[0]["samples_count"] == 3
