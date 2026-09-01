# Architecture and maintenance guide

## Runtime data flow

```text
EA F1 UDP at 60 Hz
        │
        ▼
SoloReceiver / packet parser
        │ owns mutable packet state
        ▼
Shared receiver state ───────► SQLite session recorder
        │
        ▼  copied under lock
SnapshotBroker at 10 Hz
        ├── DeltaEngine
        ├── RaceEngineer and ERS coach
        ├── RaceControlStateMachine
        ├── LiveStrategyEngine
        ├── DriverLearning
        └── Pace and time-loss diagnosis
        │
        ▼
Versioned JSON-ready LiveSnapshot
        │
        ▼
Narrow pywebview bridge
        │
        ▼
HTML/CSS/JavaScript UI with in-place DOM patching
```

The UDP thread must never wait for the frontend. The frontend never reads
receiver-owned objects directly. `SnapshotBroker` copies packet state under the
receiver lock and publishes an immutable presentation snapshot under its own
lock.

## Thread ownership

| Component | Responsibility | May block? |
|---|---|---|
| UDP receiver | Parse packets and update shared car/session state | No |
| Snapshot broker | Build a stable UI snapshot every 100 ms | Brief local work only |
| Database/report path | Persist completed telemetry and decisions | Never on the WebView render loop |
| WebView UI | Poll snapshots and patch visible values | No receiver access |

## Main contracts

The live snapshot contains:

- connection and session metadata;
- race-control phase and event history;
- player car, timing, delta, tyres, fuel, ERS, and damage;
- complete field context and nearby gaps;
- micro-sectors and pace history;
- structured engineer calls;
- structured strategy recommendation;
- structured coach diagnosis and next-lap actions;
- track map, split-screen state, and learning summary.

Human-readable banner text is a presentation field. Strategy state must use the
structured action (`PIT NOW`, `PIT WINDOW`, `STAY OUT`, `REASSESS`) rather than
parsing the banner.

## Strategy lifecycle

`LiveStrategyEngine` retains the last accepted recommendation. Material events
cause immediate evaluation; ordinary lap-to-lap noise is filtered by
confidence-aware hysteresis. Every accepted primary change records its reason.

A red flag invalidates tactical gaps and projections. The engine publishes
`REASSESS` until restart indicators and fresh moving telemetry establish the
new compound, tyre age, fuel, position, damage, and remaining distance.

## Personal learning boundaries

Profiles are separated into Time Trial, Practice, Qualifying, and Race.

- Time Trial calibrates pace execution, sectors, consistency, and validity.
- Practice can calibrate long-run wear, fuel, setup balance, and consistency.
- Qualifying calibrates one-lap execution and tyre/ERS preparation.
- Race calibrates stint behavior, fuel, wear, ERS, traffic, and decisions.

Quality filters reject partial laps, pit laps, implausible wear rates, and major
outliers. Until enough representative data exists, conservative defaults are
used and displayed as low confidence.

## Persistence

`f1_database.py` owns additive SQLite migration. Never rename or remove an
existing column/table without a migration and compatibility test. Important
records include sessions, laps, telemetry samples, setups, race-control events,
strategy decisions, and learned profiles.

Runtime data belongs beside a standalone packaged executable. For the checked-out
repository build in `project\dist`, it deliberately stays in the project root
so rebuilding the executable cannot hide or overwrite the existing database and
reports. Generated builds must never overwrite runtime data.

## Frontend update rules

- Poll at 10 Hz; do not render at UDP frequency.
- Patch existing DOM nodes on live routes to prevent flicker.
- Keep the primary engineer instruction visible without scrolling.
- Treat race-control and safety instructions as higher priority than tactical
  coaching.
- Keep the 1920×1080 focused Solo Engineer layout on one screen.
- Any new displayed strategy field must come from structured snapshot data.

## Adding a telemetry field

1. Decode and validate the correct packet offset for both supported formats.
2. Store it in receiver-owned state.
3. Copy it inside the broker's receiver lock.
4. Add it to the snapshot with a safe disconnected default.
5. Render it without assuming the field is present.
6. Add complete, partial, and disconnected contract tests.
7. Add a scenario harness case if it changes visible behavior.

## Release checklist

1. Run `python -m pytest -q`.
2. Run the browser scenario harness.
3. Check Solo Engineer at 1920×1080 and 1366×768.
4. Test red flag → stopped → formation/restart → green.
5. Confirm one UDP owner on port 20777.
6. Build from `F1TelemetryHub.spec`.
7. Launch the packaged executable and confirm `client_frontend_ready` in the
   diagnostics log.
8. Confirm the desktop shortcut targets `dist\F1TelemetryHub.exe`.
9. Preserve the existing database and reports when deploying.
