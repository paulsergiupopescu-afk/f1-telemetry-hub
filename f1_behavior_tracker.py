"""Local, privacy-conscious behavior diagnostics for future debugging."""

from __future__ import annotations

from collections import Counter, deque
from datetime import datetime, timezone
import json
import os
import platform
import threading
import time
import uuid


class BehaviorTracker:
    """Write small structured events to a rotating local JSONL log."""

    MAX_BYTES = 2_000_000
    BACKUPS = 3

    def __init__(self, base, app_version=3):
        self.folder = os.path.join(os.path.abspath(base), "diagnostics")
        os.makedirs(self.folder, exist_ok=True)
        self.path = os.path.join(self.folder, "app-behavior.jsonl")
        self.run_id = uuid.uuid4().hex[:12]
        self.started = time.time()
        self._lock = threading.RLock()
        self._counts = Counter()
        self._recent = deque(maxlen=30)
        self.log("app_start", version=app_version, python=platform.python_version(),
                 windows=platform.platform())

    @staticmethod
    def _safe(value, depth=0):
        if depth > 3:
            return "[nested]"
        if value is None or isinstance(value, (bool, int, float)):
            return value
        if isinstance(value, str):
            return value[:400]
        if isinstance(value, (list, tuple)):
            return [BehaviorTracker._safe(item, depth + 1) for item in value[:30]]
        if isinstance(value, dict):
            clean = {}
            for key, item in list(value.items())[:40]:
                name = str(key)[:80]
                if any(secret in name.casefold() for secret in
                       ("password", "api_key", "token", "secret")):
                    clean[name] = "[redacted]"
                else:
                    clean[name] = BehaviorTracker._safe(item, depth + 1)
            return clean
        return str(value)[:400]

    def _rotate(self):
        try:
            if not os.path.exists(self.path) or os.path.getsize(self.path) < self.MAX_BYTES:
                return
            oldest = f"{self.path}.{self.BACKUPS}"
            if os.path.exists(oldest):
                os.remove(oldest)
            for number in range(self.BACKUPS - 1, 0, -1):
                source, target = f"{self.path}.{number}", f"{self.path}.{number + 1}"
                if os.path.exists(source):
                    os.replace(source, target)
            os.replace(self.path, f"{self.path}.1")
        except OSError:
            pass

    def log(self, event, level="info", **details):
        name = str(event or "unknown")[:80]
        level = level if level in {"debug", "info", "warning", "error"} else "info"
        row = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "run_id": self.run_id, "uptime_s": round(time.time() - self.started, 3),
            "level": level, "event": name, "details": self._safe(details),
        }
        with self._lock:
            self._counts[f"{level}:{name}"] += 1
            self._recent.append(row)
            try:
                self._rotate()
                with open(self.path, "a", encoding="utf-8") as handle:
                    handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
            except OSError:
                pass
        return row

    def summary(self):
        with self._lock:
            return {
                "enabled": True, "run_id": self.run_id,
                "uptime_seconds": round(time.time() - self.started, 1),
                "folder": self.folder, "log_file": self.path,
                "counts": dict(self._counts), "recent": list(self._recent)[-12:],
                "privacy": "Local app behavior only; API keys and secrets are redacted.",
            }
