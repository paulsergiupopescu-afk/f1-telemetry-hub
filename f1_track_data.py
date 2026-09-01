"""Shared access to the imported F1 racing-line data.

The source files contain distance, world-space coordinates, DRS state, and
sector information.  This module keeps file handling and projection in one
place so the live dashboards and generated reports use the same circuit map.
"""

from __future__ import annotations

import csv
import html
import os
import sys
import unicodedata
from bisect import bisect_left
from functools import lru_cache


TRACK_FILE_BY_ID = {
    0: "melbourne", 1: "paul_ricard", 2: "shanghai", 3: "sakhir",
    4: "catalunya", 5: "monaco", 6: "montreal", 7: "silverstone",
    9: "hungaroring", 10: "spa", 11: "monza", 12: "singapore",
    13: "suzuka", 14: "abu_dhabi", 15: "texas", 16: "brazil",
    17: "austria", 18: "sochi", 19: "mexico", 20: "baku",
    25: "hanoi", 26: "zandvoort", 27: "imola", 29: "jeddah",
    30: "miami", 31: "Las Vegas", 32: "losail",
}

_ALIASES = {
    "albert park": "melbourne", "melbourne": "melbourne",
    "paul ricard": "paul_ricard", "shanghai": "shanghai",
    "bahrain": "sakhir", "sakhir": "sakhir", "catalunya": "catalunya",
    "barcelona": "catalunya", "monaco": "monaco", "montreal": "montreal",
    "silverstone": "silverstone", "hungaroring": "hungaroring", "spa": "spa",
    "monza": "monza", "singapore": "singapore", "suzuka": "suzuka",
    "abu dhabi": "abu_dhabi", "cota": "texas", "austin": "texas",
    "interlagos": "brazil", "brazil": "brazil", "brasil": "brazil",
    "sao paulo": "brazil", "red bull ring": "austria",
    "sochi": "sochi", "mexico": "mexico", "baku": "baku", "hanoi": "hanoi",
    "zandvoort": "zandvoort", "imola": "imola", "jeddah": "jeddah",
    "miami": "miami", "las vegas": "Las Vegas", "losail": "losail",
    "qatar": "losail",
}


def _data_dir() -> str:
    """Return the bundled or source-tree track-data directory."""
    roots = [getattr(sys, "_MEIPASS", ""), os.path.dirname(os.path.abspath(__file__))]
    for root in roots:
        candidate = os.path.join(root, "tracks")
        if root and os.path.isdir(candidate):
            return candidate
    return os.path.join(roots[-1], "tracks")


def track_key(track=None, track_id=None):
    """Resolve a game track ID or display name to an imported filename key."""
    if track_id is not None:
        try:
            key = TRACK_FILE_BY_ID.get(int(track_id))
            if key:
                return key
        except (TypeError, ValueError):
            pass
    if not track:
        return None
    name = str(track).casefold().replace("_", " ")
    # Game/localised labels can contain diacritics (for example São Paulo).
    name = "".join(char for char in unicodedata.normalize("NFKD", name)
                   if not unicodedata.combining(char))
    # Report titles may include a country after a middle dot.
    name = name.split("·", 1)[0].strip()
    for alias in sorted(_ALIASES, key=len, reverse=True):
        if alias in name:
            return _ALIASES[alias]
    return None


@lru_cache(maxsize=40)
def load_track(track=None, track_id=None):
    """Load ``(distance, x, z, drs, sector)`` samples for one circuit."""
    key = track_key(track, track_id)
    if not key:
        return ()
    candidates = [f"{key}_2020_racingline.txt", f"{key}_racingline.txt"]
    path = next((os.path.join(_data_dir(), name) for name in candidates
                 if os.path.exists(os.path.join(_data_dir(), name))), None)
    if not path:
        return ()
    samples = []
    with open(path, newline="", encoding="utf-8-sig") as fh:
        rows = csv.reader(fh)
        next(rows, None)
        next(rows, None)
        for row in rows:
            if len(row) < 6:
                continue
            try:
                # Source format: distance, pos_z, pos_x, pos_y, drs, sector.
                sample = (float(row[0]), float(row[2]), float(row[1]),
                          int(float(row[4])), int(float(row[5])))
            except (TypeError, ValueError):
                continue
            if not samples or sample[0] > samples[-1][0]:
                samples.append(sample)
    return tuple(samples)


@lru_cache(maxsize=64)
def projected_track(track=None, track_id=None, width=240, height=150,
                    padding=10, max_points=500):
    """Return projected ``(distance, x, y, drs, sector)`` drawing samples.

    Cached: the projection is static for a circuit/viewport, but the live
    broker requests it on every 10 Hz snapshot. Without the cache each call
    re-ran the full min/max/scale pass over the racing line.
    """
    raw = load_track(track, track_id)
    if not raw:
        return ()
    step = max(1, len(raw) // max_points)
    chosen = list(raw[::step])
    if chosen[-1] != raw[-1]:
        chosen.append(raw[-1])
    xs = [p[1] for p in chosen]
    zs = [p[2] for p in chosen]
    xspan = max(max(xs) - min(xs), 1.0)
    zspan = max(max(zs) - min(zs), 1.0)
    scale = min((width - 2 * padding) / xspan, (height - 2 * padding) / zspan)
    ox = (width - xspan * scale) / 2 - min(xs) * scale
    oy = (height - zspan * scale) / 2 + max(zs) * scale
    return tuple((d, x * scale + ox, oy - z * scale, drs, sector)
                 for d, x, z, drs, sector in chosen)


def point_at_distance(points, distance):
    """Find the projected point nearest to a lap distance."""
    if not points or distance is None:
        return None
    end = points[-1][0]
    if end <= 0:
        return None
    distance = max(0.0, float(distance)) % end
    distances = [p[0] for p in points]
    index = min(bisect_left(distances, distance), len(points) - 1)
    return points[index][1], points[index][2]


def track_svg(track=None, track_id=None, width=420, height=260,
              stroke="#b8c2d8", accent="#27c4f5"):
    """Build an accessible inline SVG circuit map for HTML reports."""
    points = projected_track(track, track_id, width, height, 18, 650)
    if not points:
        return ""
    path = " ".join(f"{x:.1f},{y:.1f}" for _, x, y, _, _ in points)
    start_x, start_y = points[0][1:3]
    label = html.escape(str(track or "Circuit map"))
    return (
        f'<svg viewBox="0 0 {width} {height}" width="100%" role="img" '
        f'aria-label="{label} circuit map" xmlns="http://www.w3.org/2000/svg">'
        f'<polyline points="{path}" fill="none" stroke="#0a0d13" '
        f'stroke-width="9" stroke-linecap="round" stroke-linejoin="round"/>'
        f'<polyline points="{path}" fill="none" stroke="{stroke}" '
        f'stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round"/>'
        f'<circle cx="{start_x:.1f}" cy="{start_y:.1f}" r="6" fill="{accent}"/>'
        f'<circle cx="{start_x:.1f}" cy="{start_y:.1f}" r="2" fill="#ffffff"/>'
        '</svg>')


class LiveTrackMap:
    """Controller that draws an imported racing line on a Tk canvas."""

    def __init__(self, canvas, width, height, line="#59657a", background="#0d1017"):
        self.canvas = canvas
        self.width = width
        self.height = height
        self.line = line
        self.background = background
        self.points = ()
        self.identity = None
        self.markers = {}

    def set_track(self, track=None, track_id=None):
        identity = (track_key(track, track_id), track_id)
        if identity == self.identity:
            return bool(self.points)
        self.identity = identity
        self.points = projected_track(track, track_id, self.width, self.height, 9, 360)
        self.canvas.delete("all")
        self.markers.clear()
        if not self.points:
            self.canvas.create_text(self.width / 2, self.height / 2,
                                    text="MAP UNAVAILABLE", fill="#59657a",
                                    font=("Segoe UI", 8))
            return False
        coords = [value for p in self.points for value in p[1:3]]
        self.canvas.create_line(*coords, fill="#090c12", width=7,
                                smooth=True, splinesteps=2)
        self.canvas.create_line(*coords, fill=self.line, width=2,
                                smooth=True, splinesteps=2)
        x, y = self.points[0][1:3]
        self.canvas.create_line(x - 5, y, x + 5, y, fill="#ffffff", width=2)
        return True

    def update_car(self, key, distance, color, label=""):
        point = point_at_distance(self.points, distance)
        if not point:
            return
        x, y = point
        if key not in self.markers:
            dot = self.canvas.create_oval(x - 5, y - 5, x + 5, y + 5,
                                          fill=color, outline="#ffffff", width=1)
            text = self.canvas.create_text(x + 9, y - 8, text=label, fill=color,
                                           anchor="sw", font=("Segoe UI", 8, "bold"))
            self.markers[key] = (dot, text)
        dot, text = self.markers[key]
        self.canvas.coords(dot, x - 5, y - 5, x + 5, y + 5)
        self.canvas.coords(text, x + 9, y - 8)
        self.canvas.itemconfig(dot, fill=color)
        self.canvas.itemconfig(text, text=label, fill=color)
