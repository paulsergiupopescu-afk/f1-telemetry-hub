from f1_web_app import build_live_coach


def test_live_coach_exposes_explicit_calls_and_average_pace():
    coach = build_live_coach(
        player={"position": 1, "ers_pct": 31,
                "tyre_wear": [2.5, 2.4, 2.3, 3.5],
                "tyre_temps": [82, 84, 78, 91]},
        session={"laps": 71}, race_control={"phase": "GREEN"},
        strategy={"action": "STAY OUT", "headline": "STAY OUT — DO NOT PIT",
                  "detail": "Opening calibration."},
        ers={"action": "RECHARGE", "battery_pct": 31,
             "detail": "Build an attack reserve."}, damage={},
        gap_ahead=None, name_ahead=None, gaps_behind=[("RUSSELL", 1.8)],
        pace=[{"lap": 1, "time_ms": 74_880},
              {"lap": 2, "time_ms": 71_562},
              {"lap": 3, "time_ms": 72_523}],
    )
    assert coach["drive"]["title"] == "CONTROL THE LEAD"
    assert coach["ers"]["title"] == "RECHARGE · 31%"
    assert coach["tyres"]["title"].startswith("PROTECT FR")
    assert coach["strategy"]["title"] == "STAY OUT — DO NOT PIT"
    assert coach["pace"]["average_ms"] == 72_988
    assert coach["pace"]["clean_laps"] == 3


def test_live_coach_prioritizes_attack_and_hot_tyre_warning():
    coach = build_live_coach(
        player={"position": 2, "ers_pct": 58,
                "tyre_wear": [5, 5, 5, 6],
                "tyre_temps": [90, 92, 88, 123]},
        session={}, race_control={"phase": "GREEN"},
        strategy={"action": "STAY OUT", "headline": "STAY OUT"},
        ers={"action": "DEPLOY", "battery_pct": 58, "detail": "Boost now."},
        damage={}, gap_ahead=.72, name_ahead="RUSSELL", gaps_behind=[], pace=[],
    )
    assert coach["drive"]["title"] == "ATTACK NOW"
    assert coach["tyres"]["title"] == "COOL FR · 123°C"


def test_live_coach_explains_loss_and_gives_specific_correction():
    coach = build_live_coach(
        player={"position": 4, "ers_pct": 8,
                "tyre_wear": [12, 13, 17, 12],
                "tyre_temps": [92, 94, 119, 97]},
        session={}, race_control={"phase": "GREEN"},
        strategy={"action": "STAY OUT", "headline": "STAY OUT"},
        ers={"action": "RECHARGE", "battery_pct": 8},
        damage={"front_wing_left": 22, "front_wing_right": 18},
        gap_ahead=.84, name_ahead="LECLERC", gaps_behind=[],
        pace=[{"lap": 1, "time_ms": 71_000},
              {"lap": 2, "time_ms": 71_100},
              {"lap": 3, "time_ms": 72_000}],
        micro=[{"index": 4, "delta": .08}, {"index": 8, "delta": -.03}],
    )
    diagnosis = coach["diagnosis"]
    assert diagnosis["state"] == "losing"
    assert "LOSING" in diagnosis["title"]
    assert "front-wing damage" in diagnosis["summary"]
    assert any("Brake slightly earlier" in action for action in diagnosis["actions"])
    assert any("micro-sectors 5" in item for item in diagnosis["evidence"])


def test_live_coach_does_not_invent_a_loss_cause_when_pace_is_stable():
    coach = build_live_coach(
        player={"position": 7, "ers_pct": 54,
                "tyre_wear": [8, 8, 8, 8],
                "tyre_temps": [91, 92, 90, 92]},
        session={}, race_control={"phase": "GREEN"},
        strategy={"action": "STAY OUT", "headline": "STAY OUT"},
        ers={"action": "HOLD", "battery_pct": 54}, damage={},
        gap_ahead=2.4, name_ahead="PIASTRI", gaps_behind=[],
        pace=[{"lap": 1, "time_ms": 90_000},
              {"lap": 2, "time_ms": 90_080},
              {"lap": 3, "time_ms": 90_120}],
    )
    assert coach["diagnosis"]["state"] == "stable"
    assert coach["diagnosis"]["title"] == "PACE ON TARGET"
    assert "no corrective change" in coach["diagnosis"]["actions"][0]


def test_live_coach_freezes_diagnosis_during_red_flag():
    coach = build_live_coach(
        player={"position": 3, "ers_pct": 44,
                "tyre_wear": [5, 5, 5, 5], "tyre_temps": [80, 80, 80, 80]},
        session={}, race_control={"phase": "RED_FLAG"},
        strategy={"action": "REASSESS", "headline": "WAIT FOR RESTART"},
        ers={"action": "HOLD", "battery_pct": 44}, damage={},
        gap_ahead=.5, name_ahead="NORRIS", gaps_behind=[],
        pace=[{"lap": 1, "time_ms": 90_000}, {"lap": 2, "time_ms": 92_000}],
    )
    assert coach["drive"]["title"] == "STOP — RED FLAG"
    assert coach["diagnosis"]["state"] == "neutral"
    assert "PAUSED" in coach["diagnosis"]["title"]
