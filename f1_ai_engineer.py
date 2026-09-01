#!/usr/bin/env python3
"""Optional, dependency-free OpenAI race-engineer client.

The API key is accepted for the current process only or read from
OPENAI_API_KEY.  It is never written to the telemetry database or a config
file.  Requests use the Responses API with storage disabled.
"""

from __future__ import annotations

import hashlib
import json
import os
import urllib.error
import urllib.request


DEFAULT_MODEL = "gpt-5.6-luna"
API_URL = "https://api.openai.com/v1/responses"


class AIEngineerError(RuntimeError):
    pass


def _output_text(payload):
    chunks = []
    for item in payload.get("output", []):
        if item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if content.get("type") == "output_text" and content.get("text"):
                chunks.append(content["text"].strip())
    return "\n".join(chunks).strip()


class OpenAIRaceEngineer:
    def __init__(self, api_key=None, model=DEFAULT_MODEL, timeout=35):
        self.api_key = (api_key or os.environ.get("OPENAI_API_KEY") or "").strip()
        self.model = (model or DEFAULT_MODEL).strip()
        self.timeout = timeout

    @property
    def configured(self):
        return bool(self.api_key)

    def advise(self, snapshot, question="Give me the next race calls."):
        if not self.configured:
            raise AIEngineerError(
                "Add an OpenAI API key for this session or set OPENAI_API_KEY.")
        compact = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"),
                             default=str)
        instructions = (
            "You are a concise Formula race engineer inside a live telemetry app. "
            "Use only the supplied telemetry. Never invent a value. Prioritise safety, "
            "damage, tyre state, fuel, battery, pit window, weather, then pace. "
            "Return exactly: CALL, WHY, WATCH, each on one short line. Setup changes are "
            "recommendations for the garage; do not claim the app changed the game."
        )
        safety_id = hashlib.sha256(
            ("f1-race-command:" + os.environ.get("USERNAME", "local")).encode()
        ).hexdigest()[:32]
        body = {
            "model": self.model,
            "instructions": instructions,
            "input": f"DRIVER QUESTION: {question}\nLIVE SNAPSHOT: {compact}",
            "reasoning": {"effort": "low"},
            "text": {"verbosity": "low"},
            "max_output_tokens": 260,
            "store": False,
            "safety_identifier": safety_id,
        }
        request = urllib.request.Request(
            API_URL, data=json.dumps(body).encode("utf-8"), method="POST",
            headers={"Authorization": f"Bearer {self.api_key}",
                     "Content-Type": "application/json",
                     "User-Agent": "F1-Race-Command/2.0"})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            try:
                detail = json.loads(exc.read().decode("utf-8")).get("error", {}).get(
                    "message", str(exc))
            except Exception:
                detail = str(exc)
            raise AIEngineerError(detail) from exc
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            raise AIEngineerError(f"OpenAI connection failed: {exc}") from exc
        text = _output_text(payload)
        if not text:
            raise AIEngineerError("OpenAI returned no engineer message.")
        usage = payload.get("usage") or {}
        return {
            "text": text,
            "model": payload.get("model", self.model),
            "input_tokens": int(usage.get("input_tokens") or 0),
            "output_tokens": int(usage.get("output_tokens") or 0),
            "total_tokens": int(usage.get("total_tokens") or 0),
        }
