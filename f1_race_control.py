"""Race-control state derived from EA F1 session and event packets."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import time


GREEN = "GREEN"
SC = "SC"
VSC = "VSC"
RED_FLAG = "RED_FLAG"
FORMATION = "FORMATION"
RESTARTING = "RESTARTING"


@dataclass(frozen=True)
class RaceControlEvent:
    code: str
    phase: str
    timestamp: float
    detail: str = ""

    def to_dict(self):
        return asdict(self)


class RaceControlTracker:
    """Small state machine that prevents a red flag falling through to green."""

    EVENT_NAMES = {
        "SSTA": "Session started",
        "SEND": "Session ended",
        "LGOT": "Lights out",
        "CHQF": "Chequered flag",
        "RDFL": "Red flag",
        "PENA": "Penalty issued",
        "DRSE": "Overtaking aid enabled",
        "DRSD": "Overtaking aid disabled",
        "SCAR": "Safety car event",
    }

    def __init__(self):
        self.phase = GREEN
        self.red_flag_active = False
        self.finished = False
        self.last_event = None
        self.events = []
        self._motion_since = None

    def reset(self):
        self.__init__()

    def consume_event(self, code, now=None, detail=""):
        now = float(now or time.time())
        code = (code or "").strip().upper()
        if code == "RDFL":
            self.phase = RED_FLAG
            self.red_flag_active = True
            self.finished = False
            self._motion_since = None
        elif code in ("SSTA", "LGOT"):
            self.phase = RESTARTING if self.red_flag_active else GREEN
            self.finished = False
            self._motion_since = None
        elif code in ("SEND", "CHQF"):
            self.finished = True
        event = RaceControlEvent(
            code=code,
            phase=self.phase,
            timestamp=now,
            detail=detail or self.EVENT_NAMES.get(code, code),
        )
        self.last_event = event
        self.events.append(event)
        self.events = self.events[-80:]
        return event

    def consume_safety_event(self, safety_type, event_type, now=None):
        names = {0: "No safety car", 1: "Safety car", 2: "Virtual safety car",
                 3: "Formation lap safety car"}
        actions = {0: "deployed", 1: "returning", 2: "returned", 3: "resume race"}
        safety_type, event_type = int(safety_type), int(event_type)
        if event_type == 0:
            self.phase = {1: SC, 2: VSC, 3: FORMATION}.get(safety_type, self.phase)
        elif event_type in (1, 2) and not self.red_flag_active:
            self.phase = GREEN
        elif event_type == 3:
            self.phase = RESTARTING if self.red_flag_active else GREEN
            self._motion_since = None
        return self.consume_event(
            "SCAR", now=now,
            detail=f"{names.get(safety_type, 'Safety car')} {actions.get(event_type, 'updated')}")

    def consume_session(self, safety_car_status):
        """Session status can refine state, but never clears a live red flag."""
        if self.red_flag_active:
            if self.phase == RED_FLAG and safety_car_status == 3:
                self.phase = FORMATION
            return self.phase
        self.phase = {1: SC, 2: VSC, 3: FORMATION}.get(safety_car_status, GREEN)
        return self.phase

    def observe_motion(self, speed_kmh, now=None):
        """Clear restart state only after two seconds of sustained movement."""
        now = float(now or time.time())
        if not self.red_flag_active or self.phase == RED_FLAG:
            self._motion_since = None
            return False
        if float(speed_kmh or 0) > 5:
            self._motion_since = self._motion_since or now
            if now - self._motion_since >= 2.0:
                self.red_flag_active = False
                self.phase = GREEN
                self._motion_since = None
                return True
        else:
            self._motion_since = None
        return False

    def snapshot(self):
        return {
            "phase": self.phase,
            "red_flag_active": self.red_flag_active,
            "finished": self.finished,
            "last_event": self.last_event.to_dict() if self.last_event else None,
            "events": [event.to_dict() for event in self.events[-12:]],
        }
