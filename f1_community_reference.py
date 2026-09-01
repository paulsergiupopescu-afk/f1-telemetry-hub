"""User-supplied 2026 community setup/strategy reference (read-only priors)."""

SOURCE_URL = "https://docs.google.com/spreadsheets/d/1fUZKqMpARGJ1XEvsmGlOtN2_NVPOqLehPNiLH-YyYSI/htmlview#gid=2082870794"
SOURCE_LABEL = "F1 2026 community sheet · supplied 2026-08-01"

# aero, differential, suspension, brakes, qualifying/race pressures,
# compound allocation, 50% strategy, notes. Empty fields were empty upstream.
TRACKS = {
    "Australia": ("30-0 Q / 42-15 R", "100-45 Q / 60 R", "41-38-1-5-21-47", "98/56", "29.5/20.5", "29.5/20.5", "C3-C5", "MH 11-13 / HM 16-18 / MHH 8,19", "Heavy lift-and-coast demand"),
    "China": (None, None, None, None, None, None, "C2-C4", "MH 10-12 / HM 16-17", None),
    "Japan": ("45-16", "100-45 Q / 50 R", "41-41-1-1-23-48", "96/56", "25.5/20.5", "25.0/20.5", "C1-C3", "MH 10-12 / HM 15-17 / SMM 7,17", "Soft-Medium not favoured; high lift-and-coast demand"),
    "Bahrain": ("50-26", "100-50", "41-41-1-4-22-46", "97/57", "23.0/20.5", "26.5/20.5", "C1-C3", "HM 17-18 / MH 11-12 / SMM 7,18 / HS 19-20", "Soft and Medium reported at similar pace"),
    "Saudi Arabia": ("41-0", "100-50", "41-41-1-4-20-42", "98/57", "29.5/20.5", "29.5/22.0", "C3-C5", "MH 11-12 / HM 13-14 / MHH 6,16", "Very high energy-management demand"),
    "Miami": ("48-24", "100-70", "41-41-1-1-22-42", "100 Q, 98 R / 57", "26.0/20.5", "29.5/20.5", "C3-C5", "MH 12-13 / HM 16-17 / MHH 7,18", "Qualifying-sensitive circuit"),
    "Canada": ("50-24", "100-55", "41-41-1-4-21-44", "98/57", "26.0/20.5", "29.5/20.5", "C3-C5", "MH 13-15 / HM 20-22 / MHH 9,23", "Sprint allocation may differ; verify compounds in-game"),
    "Monaco": ("50-50", "100-30", "38-41-1-4-21-46", "100/56", "22.5/20.5", "22.5/20.5", "C3-C5", "MH 11-13", "Pit as early as traffic permits; special multi-stop rule applies"),
    "Barcelona": ("50-23", "100-45", "41-38-1-5-21-43", "98/56", "29.5/20.5", "29.5/20.5", "C1-C3", "MH 12-14 / HM 19-21 / SMM 8,20", "Soft not favoured"),
    "Austria": ("50-12 Q / 50-24 R", "100-60", "41-41-1-6-20-47", "98 Q, 97 R / 56-57", "29.5/20.5", "29.5/20.5", "C3-C5", "MH 14-16 / HM 20-23 / MHH 8,22", "One-stop friendly"),
    "Britain": ("36-5", "100-55", "41-41-1-1-21-42", "97/59-60", "29.5/20.5", "29.5/20.5", "C2-C4", "MH 9-11 / HM 15-17", "Significant lift-and-coast demand"),
    "Belgium": ("22-0", "100-45", "41-41-1-5-20-46", "100/57", "29.5/26.5", "29.5/26.5", "C1,C3,C4", "HM 13-15 / MH 7-9", "High lift-and-coast demand"),
    "Hungary": ("50-41", "100-40", "41-41-1-1-22-42", "98/56", "29.0/20.5", "29.5/20.5", "C3-C5", "MH 14-15 / HM 20-21 / MHH 9,23", "Low lift-and-coast demand"),
    "Netherlands": ("50-31", "100-35", "41-41-1-5-20-45", "100/55-57", "29.5/20.5", "29.5/20.5", "C2-C4", "MH 15 / MHH 9,23", None),
    "Monza": ("5-0", "100-55", "41-41-1-1-24-43", "99/57", "29.5/26.5", "29.5/26.5", "C3-C5", "MH 10-11 / MHH 7,17", None),
    "Madrid": ("50-28", "100-55", "41-28-1-12-22-46", "100 Q, 97 R / 56-57", "29.5/20.5", "29.5/20.5", "C3-C5", "MH 6-9 / HM 21-23 / MHH 6,17", "Avoid chicane launch kerbs; large undercut, difficult overtaking"),
    "Azerbaijan": (None, None, None, None, None, None, "C3-C5", "MH 9-11 / HM 16-17 / MHH 6,16", None),
    "Singapore": ("50-39", "100-45", "41-41-1-1-21-44", "98/56", "26.0/20.5", "29.5/20.5", "C3-C5", "MH 11-13", "Low lift-and-coast demand"),
    "Texas": ("50-34", "100-50", "41-41-1-4-20-45", "100 Q, 97 R / 56-57", "29.5/20.5", "29.5/20.5", "C1,C3,C4", "MH 8-11 / HM 16-19", "Hard-Medium favoured; protect traction zones"),
    "Mexico": (None, None, None, None, None, None, "C3-C5", "MH 10-12 / HM 21-23 / MHH 8,22", None),
    "Brazil": ("50-28", "100-35", "41-41-1-4-20-44", "100 Q, 98 R / 55-56", "29.5/20.5", "29.5/20.5", "C2-C4", "MH 12-15 / HM 21-23", "Preserve battery"),
    "Las Vegas": ("15-0", "100-55", "41-41-1-1-24-45", "100 Q, 97 R / 56", "25.5/20.5", "25.5/20.5", "C3-C5", "MH 8-10 / HM 15-17", None),
    "Qatar": ("50-18", "100-40", "41-41-1-7-20-44", "100 Q, 98 R / 56-57", "29.5/20.5", "29.5/20.5", "C1-C3", "SH 10-12 / MH 11-13 / SM 12-14", "One-stop friendly in source data"),
    "Abu Dhabi": (None, None, None, None, None, None, "C3-C5", "MH 9-11 / MHH 9,19", None),
    "Imola": ("50-24", "100-40", "41-41-1-1-22-46", "100 Q, 97 R / 57", "28.5/20.5", "28.5/20.5", "C3-C5", "MH 11-13 / HM 19-20", "Minimum-fuel reference; validate personal consumption"),
}

TYRE_TEMPERATURES_C = {"C1": (95, 115), "C2": (85, 115), "C3": (85, 95),
                       "C4": (75, 95), "C5": (75, 85), "C6": (65, 85),
                       "Intermediate": (55, 75), "Wet": (55, 65)}
ENGINE_POWER_PCT = {65: 96, 75: 97, 85: 98, 95: 99, 105: 99.7, 115: 100,
                    125: 100, 135: 98.5, 145: 94, 155: 91, 165: 88.5, 175: 85}
ALIASES = {"Melbourne": "Australia", "Shanghai": "China", "Suzuka": "Japan",
           "Jeddah": "Saudi Arabia", "Montreal": "Canada", "Catalunya": "Barcelona",
           "Silverstone": "Britain", "Spa": "Belgium", "Hungaroring": "Hungary",
           "Zandvoort": "Netherlands", "Baku": "Azerbaijan", "COTA": "Texas",
           "Interlagos": "Brazil", "Italy": "Monza", "United States": "Texas"}


def get_reference(track):
    name = ALIASES.get(track, track)
    row = TRACKS.get(name)
    if not row:
        return None
    keys = ("aero", "differential", "suspension", "brakes", "tyres_quali",
            "tyres_race", "compounds", "strategy_50", "notes")
    return {"track": name, "source": SOURCE_LABEL, "source_url": SOURCE_URL,
            **dict(zip(keys, row))}
