"""Structured access to the user-supplied Brendon Leigh F1 26 setup packs."""

from __future__ import annotations

from functools import lru_cache
import glob
import json
import os
import sys


VERSION = "1.5"
SOURCE = "Brendon Leigh complete setup packages · v1.5 · 2026-07-16"
TOKENS = {
    "Australia": "Australia", "China": "China", "Japan": "Japan",
    "Bahrain": "Bahrain", "Saudi Arabia": "Jeddah", "Miami": "Miami",
    "Canada": "Canada", "Monaco": "Monaco", "Barcelona": "Spain",
    "Austria": "Austria", "Britain": "Silverstone", "Belgium": "Spa",
    "Hungary": "Hungary", "Netherlands": "Zandvoort", "Monza": "Monza",
    "Madrid": "Madring", "Azerbaijan": "Baku", "Singapore": "Singapore",
    "Texas": "Texas", "Mexico": "Mexico", "Brazil": "Brazil",
    "Las Vegas": "Vegas", "Qatar": "Qatar", "Abu Dhabi": "Abu Dhabi",
    "Imola": "Imola", "Zandvoort": "Zandvoort",
}
ALIASES = {
    "Melbourne": "Australia", "Shanghai": "China", "Suzuka": "Japan",
    "Jeddah": "Saudi Arabia", "Montreal": "Canada", "Catalunya": "Barcelona",
    "Silverstone": "Britain", "Spa": "Belgium", "Hungaroring": "Hungary",
    "Netherlands": "Zandvoort", "Baku": "Azerbaijan", "COTA": "Texas",
    "Interlagos": "Brazil", "Losail": "Qatar", "Vegas": "Las Vegas",
}


def _root():
    return getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))


def canonical_track(track):
    return ALIASES.get(str(track or "").strip(), str(track or "").strip())


@lru_cache(maxsize=1)
def _library():
    path = os.path.join(_root(), "assets", "brendon_leigh_setups_v1_5.json")
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return {"tracks": {}}


def package_data(track):
    """Return all imported Race/Qualifying/Inter/Wet values for one circuit."""
    values = (_library().get("tracks") or {}).get(canonical_track(track))
    if not values:
        return None
    return {
        "author": "Brendon Leigh", "version": VERSION, "source": SOURCE,
        "track": canonical_track(track), "variants": values,
    }


def package_path(track):
    """Retained for legacy exports; the WebView consumes package_data instead."""
    name = canonical_track(track)
    token = TOKENS.get(name)
    if not token:
        return None
    folder = os.path.join(_root(), "setup_packages", VERSION)
    matches = glob.glob(os.path.join(folder, f"*{token}*.pdf"))
    return matches[0] if matches else None
