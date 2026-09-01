# F1 Telemetry Hub

A Windows race assistant for EA SPORTS F1 25 and the F1 2026 Season Pack. It
turns the game's UDP telemetry into live driving instructions, personal pit
strategy, ERS guidance, tyre management, session learning, and detailed reports.

The normal desktop experience is a native Edge WebView2 window. No browser tab
or Node.js installation is required. The telemetry and strategy engines run
locally and continue to work without an internet connection.

> The application is read-only. It can tell you what to do, but it cannot alter
> car settings or drive the car for you.

## Start here: first-race tutorial

### 1. Start the application

Use the desktop shortcut, open `dist\F1TelemetryHub.exe`, or run from source:

```powershell
.\.venv\Scripts\python.exe .\f1_app.py
```

The desktop build opens directly in **Solo Engineer**, fullscreen. Press `F11`
to toggle fullscreen and `Escape` to leave the focused race view.

Only one copy should be running. One application process owns UDP port `20777`;
the second process visible in Task Manager is the normal PyInstaller one-file
launcher, not another telemetry listener.

### 2. Enable telemetry in the game

In F1, open **Settings → Telemetry Settings** and use:

| Setting | Required value |
|---|---|
| UDP Telemetry | On |
| UDP Broadcast Mode | Off |
| UDP IP Address | `127.0.0.1` when the app is on the same PC |
| UDP Port | `20777` |
| UDP Send Rate | 60 Hz |
| UDP Format | 2025 or 2026 Season Pack |
| Your Telemetry | Public |

For a second telemetry PC, replace `127.0.0.1` with that PC's local IPv4
address and allow UDP `20777` through Windows Firewall.

### 3. Confirm the connection

Enter the garage, track, or session. The top-right indicator changes from
`WAITING` to `LIVE`, the packet counter starts increasing, and the dashboard
shows the current circuit and session.

If it remains on `WAITING`, check the troubleshooting section before changing
anything else.

### 4. Drive the opening laps normally

During the first five representative green-flag laps, the app deliberately
avoids speculative pit calls. You should normally see:

`STAY OUT — DO NOT PIT`

This opening guard is bypassed for real emergencies such as major wing damage,
critical tyre wear, rain crossover, Safety Car, or VSC. A reliable degradation
model needs clean completed laps; partial practice laps are not treated as a
race-wear baseline.

### 5. Read the dashboard from top to bottom

1. **Engineer banner** — the single highest-priority call: attack, defend,
   hold, box, or race-control instruction.
2. **Why am I losing time?** — compares the last completed clean lap with your
   recent clean-lap level. It names the strongest observed cause and gives up to
   two numbered corrections for the next lap.
3. **Driving / ERS / tyre / strategy calls** — four independent instructions.
   A strategy call never replaces an urgent driving or car-health warning.
4. **Delta and micro-sectors** — live delta to your personal reference. Green
   segments gain time; red segments lose time.
5. **Timing, position, fuel, ERS, and car panels** — current state and nearby
   traffic.
6. **Race pace** — clean-lap average, last lap, difference to average, trend,
   graph, pit window, predicted rejoin, and race-control phase.

The complete Solo Engineer screen is designed to fit at 1920×1080 without
scrolling. Narrower windows use a compact responsive layout.

## Understanding the live instructions

### Driving call

| Call | Meaning | What to do |
|---|---|---|
| `ATTACK NOW` | The car ahead is in range and an ERS reserve exists | Prioritise the exit before the best passing straight, deploy under acceleration, and complete the move |
| `WAIT — BUILD BATTERY` | The car is in range but a pass is unlikely to succeed | Stay in the tow, avoid overheating the fronts, and recharge |
| `DEFEND` | A car behind is inside the threat window | Protect the next important exit and spend ERS only where the pass can happen |
| `CONTROL THE LEAD` | No immediate attack is required | Run normal pace, avoid tyre sliding, and rebuild ERS |
| `HOLD POSITION` | No decisive battle window exists | Keep repeatable references and wait for a stronger opportunity |
| `BOX THIS LAP` | The deterministic strategy engine found an urgent stop | Commit to pit entry unless race control changes the situation |

### Why am I losing time?

The diagnosis uses only evidence available in telemetry. It can identify:

- front-wing damage and the resulting braking/front-grip penalty;
- an overheating corner and likely sliding, wheelspin, or locking;
- low ERS and reduced acceleration/defence capability;
- tyre-wear imbalance and the limiting corner;
- dirty air when following closely;
- a sustained clean-lap fade;
- the micro-sectors where the current reference is being lost.

`LOSING 0.420s VS RECENT PACE` means the last clean lap was 0.420 seconds slower
than the average of the preceding clean laps. It does **not** compare a Safety
Car lap, pit lap, invalid lap, or extreme outlier with a normal racing lap.

If the app cannot isolate a cause, it says so rather than inventing one. Follow
the numbered **DO THIS NEXT LAP** actions, then use the next comparison to see
whether the correction worked.

### Race pace

- **Average** is the mean of recent representative clean laps.
- **Last** is the most recent accepted completed lap.
- **VS AVG** is the last lap relative to the displayed average. Negative is
  faster; positive is slower.
- **Trend** is `IMPROVING`, `STABLE`, `FADING`, or `LEARNING`.

Outliers more than roughly seven percent from the median are excluded from the
live average. This keeps pit laps, stoppages, and major incidents from corrupting
the useful race-pace number.

### ERS instruction

ERS calls consider battery percentage, deployment mode, throttle/brake state,
speed, lap phase, battle gaps, and the circuit's useful acceleration zones.

- **Deploy** after a good corner exit, while acceleration is still valuable.
- Switch down before top speed or braking; late-straight deployment wastes the
  limited energy budget.
- **Recharge** when a pass is not currently possible.
- Keep a reserve for defence, a planned attack, or the final lap.
- In qualifying, use energy across the timed lap without emptying the battery
  so early that the final acceleration zones are compromised.

The 2026 terminology displayed by the app is `CORNER MODE`, `STRAIGHT MODE`,
`OVERTAKE`, and `BOOST` where the packet format supports it.

### Tyre instruction

The four-corner card shows wear, carcass temperature, predicted wear, compound,
and tyre age. Calls are intentionally specific:

- `COOL FR` — reduce sliding/locking at the front-right, use a progressive brake
  release, and avoid excessive steering scrub.
- `PROTECT RL` — that tyre is wearing faster than the others; reduce the input
  that loads it repeatedly.
- `TYRE SAVE` — wear is approaching a critical threshold; avoid kerbs, lock-up,
  and wheelspin until the pit decision is confirmed.
- `NORMAL PACE` — the tyres are balanced and no saving is currently required.

### Pit strategy

The primary strategy is always one of:

| State | Meaning |
|---|---|
| `PIT NOW` | Stop this lap for a large or urgent advantage |
| `PIT WINDOW` | The preferred stop range is open or approaching |
| `STAY OUT` | Remaining on track is currently faster or strategically safer |
| `REASSESS` | The previous model is invalid or lacks reliable context |

Every call includes a target lap or window, next compound, predicted rejoin,
confidence, estimated advantage, and evidence when those values are available.

The engine recalculates at lap boundaries and after material changes in tyre
wear, degradation, fuel, traffic, position, damage, weather, or race control.
Small model fluctuations do not flip the call: a non-urgent change needs an
advantage greater than `max(0.75 seconds, 25% of projected uncertainty)`.

Damage, critical wear, weather crossover, and race-control opportunities can
override that stability threshold immediately.

## Race-control behavior

The internal phases are `GREEN`, `SC`, `VSC`, `RED_FLAG`, `FORMATION`, and
`RESTARTING`.

During a red flag the app:

- displays an unmistakable red-flag banner;
- suppresses attack, defend, fuel-saving, undercut, and pit-now calls;
- preserves completed laps and useful personal calibration;
- invalidates stale gaps, pit windows, tyre projections, and queued calls;
- waits for restart indicators and fresh moving telemetry;
- reads the new compound, tyre age, position, fuel, damage, and remaining laps;
- builds a new strategy from the restart state.

Do not act on a tactical call left visible in another tool during a stoppage.
The main banner is the authoritative current call.

## A complete weekend workflow

### Time Trial: raw-pace practice

Time Trial is your repeatable pace laboratory. Use it to learn the circuit,
compare personal-best traces, improve sectors, and reduce invalid laps.

The app learns:

- best and median clean lap;
- theoretical best from your sectors;
- consistency and invalid-lap rate;
- repeatable braking and apex patterns;
- micro-sector strengths and losses.

Time Trial fuel, tyre wear, and ERS values are not representative of a race and
are never used to calibrate race consumption or stint life.

Recommended routine:

1. Run five clean laps before chasing a restart-heavy PB.
2. Use the micro-sector strip to find repeatable losses.
3. Correct one problem at a time.
4. Reopen the session in **Sessions** and compare best, theoretical, and median
   pace.

### Practice: validate the race car

Practice is where the race model should learn fuel use and tyre degradation.

1. Load the Pre-Race race setup.
2. Run at least five uninterrupted laps on representative fuel.
3. Avoid repeated flashbacks, pit-lane laps, and deliberate burnouts in the
   calibration run.
4. Review wear per lap, fuel per lap, temperature balance, and consistency.
5. Apply setup advice only when the same imbalance repeats across several laps.

### Qualifying: prepare and execute one lap

The qualifying profile is separate from race pace. Use the app to check tyre
preparation, ERS deployment, invalid laps, and the gap between best and
theoretical pace. The goal is not tyre conservation; it is a complete lap with
energy available through the final acceleration zone.

### Race: execute and adapt

1. Open **Pre-Race** and choose circuit, distance, starting tyre, rain chance,
   and expected traffic.
2. Enter the recommended setup values into the game manually.
3. Read the primary pit plan and its explanation.
4. Start the race and follow the live banner first.
5. Use the four supporting cards to manage ERS, tyres, and strategy.
6. After the race, open **Sessions** for the detailed report and driver-learning
   feedback.

## Application screens

### Solo Engineer

The primary cockpit display. It combines the live command, diagnosis, delta,
micro-sectors, timing, field, car state, tyres, pace, and pit strategy.

### Split Screen

Shows both local players from `m_playerCarIndex` and
`m_secondaryPlayerCarIndex`. One UDP listener captures the shared session.

### Pre-Race

Select the race context and receive:

- a directly imported Brendon Leigh setup for Race, Qualifying, Intermediate,
  or Wet conditions;
- exact setup values—wings, differential, suspension, anti-roll bars, ride
  height, brakes, and tyre pressures;
- ranked pit plans with stint lengths, total time, finish wear, uncertainty,
  and a plain-language explanation;
- personal adaptations from previous sessions when enough evidence exists.

The normalized runtime library is
`assets\brendon_leigh_setups_v1_5.json`. The original PDFs remain in
`setup_packages\1.5` as source/reference material and are not bundled into the
executable. The app presents the imported values directly; it does not send the
driver to a setup image.

### Live Strategy

Expands the current primary plan into ranked alternatives, projected time,
finish wear, rejoin position, confidence, and the evidence behind the decision.
The deterministic strategy remains available offline.

### Sessions

Sessions are numbered by month, for example `AUGUST · SESSION 01`. A report
contains:

- best, theoretical, median, and clean-lap pace;
- lap-by-lap sectors, compound, tyre age, wear, fuel, and position;
- stint averages and degradation;
- setup values captured from the game;
- race-control and strategy-decision timeline;
- personal feedback for the relevant session type.

### Driver Profile

Time Trial, Practice, Qualifying, and Race are learned separately. Circuit
filters expose track-specific strengths and weaknesses. The model becomes more
confident as clean representative laps accumulate; it never needs an online AI
service to produce the main advice.

### Reports

The app keeps reports inside the same visual system. CSV/XLSX/HTML exports
remain available for external analysis and compatibility with older sessions.

## Data, privacy, and diagnostics

The SQLite database stores session metadata, laps, sampled telemetry, setups,
race-control events, strategy decisions, and learned profiles. Existing tables
are migrated additively.

The diagnostics recorder writes small structured JSONL events to
`diagnostics\app-behavior.jsonl` beside the executable or source entry point.
It records startup, frontend readiness, navigation, strategy transitions, and
errors. Files rotate automatically. API keys, passwords, tokens, and secrets
are redacted.

OpenAI is optional and used only for a manually requested explanation. The key
is held for the current process and is not written to the telemetry database.
The primary live call is deterministic and local.

Back up these items before replacing a machine or deleting runtime data:

- `f1_telemetry.db`
- `solo_reports\`
- `reports\`
- `diagnostics\` when investigating a problem

## Troubleshooting

### The app says WAITING

1. Confirm UDP Telemetry is on and the port is `20777`.
2. Confirm the IP is `127.0.0.1` on the same PC.
3. Set **Your Telemetry** to Public.
4. Close duplicate copies of F1 Telemetry Hub.
5. Check the packet counter after entering an active session.
6. Allow the app through Windows Firewall if telemetry arrives over the network.

Check the UDP owner in PowerShell:

```powershell
Get-NetUDPEndpoint -LocalPort 20777 | Select-Object LocalAddress,LocalPort,OwningProcess
```

### The window does not appear

Install or repair Microsoft Edge WebView2 Runtime. The packaged app shows a
native recovery message if WebView2 cannot start.

### A pit call looks wrong

Check the evidence first:

- Is there front-wing damage?
- Did weather or race control just change?
- Is the current lap a clean completed lap?
- Are fewer than five representative laps available?
- Is the suggested stop actually reacting to critical wear or damage?

During the opening calibration, a normal dry race should show
`STAY OUT — DO NOT PIT`. Record the diagnostics log and session report if an
incorrect urgent call appears again.

### The interface flickers

The live route patches existing DOM nodes at 10 Hz instead of recreating the
page. If visible flicker returns, save `diagnostics\app-behavior.jsonl` and note
the route, session type, resolution, and time of the problem.

### The interface is too small

Use the Solo Engineer route and press `F11`. The focused layout removes the
sidebar and enlarges tactical text. Windows display scaling between 100% and
150% is supported.

## Developer setup

### Requirements

- Windows 10 or 11
- Python 3.11 or newer
- Microsoft Edge WebView2 Runtime

Create the environment:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Run the current application:

```powershell
.\.venv\Scripts\python.exe .\f1_app.py
.\.venv\Scripts\python.exe .\f1_app.py --mode solo --fullscreen
```

Run the retired Tkinter interface only when testing compatibility:

```powershell
.\.venv\Scripts\python.exe .\f1_app.py --legacy-ui --mode solo
.\.venv\Scripts\python.exe .\f1_app.py --legacy-ui --mode split
```

Run all tests:

```powershell
python -m pytest -q
```

The browser scenario harness is available by serving `web\` and opening
`?demo&selftest#solo`. It cycles through green flag, SC, VSC, red flag, restart,
finish, pit, weather, damage, wear, fuel, ERS, session types, partial packets,
disconnects, large fields, and message pressure.

### Build the Windows executable

```powershell
powershell -ExecutionPolicy Bypass -File .\build_exe.ps1
```

Or use the checked-in spec for reproducible incremental builds:

```powershell
.\.venv\Scripts\python.exe -m PyInstaller .\F1TelemetryHub.spec --noconfirm
```

The result is `dist\F1TelemetryHub.exe`. It bundles the WebView frontend,
tracks, normalized setup library, fonts, icons, parser, database migrations,
reports, and strategy engines. Original setup PDFs and generated caches are not
embedded.

When this repository build runs from `dist`, it continues using
`f1_telemetry.db`, `solo_reports`, and `diagnostics` in the project root. A
standalone copy placed elsewhere keeps its runtime data beside the executable.

## Repository layout

```text
f1-telemetry-hub/
├── f1_app.py                    # Windows entry point
├── f1_web_app.py                # snapshot broker and WebView bridge
├── f1_26_split_telemetry.py     # EA UDP parsing and receiver state
├── f1_engineer.py               # tactical, ERS, fuel, tyre coaching
├── f1_live_strategy.py          # stateful remaining-race strategy
├── f1_strategy.py               # strategy simulation primitives
├── f1_race_control.py           # race-control state machine
├── f1_driver_learning.py        # personal models and feedback
├── f1_database.py               # SQLite schema and persistence
├── f1_track_data.py             # track normalization and map projection
├── f1_setup_packages.py         # normalized Brendon setup access
├── f1_*report*.py               # report and export engines
├── f1_hub.py / f1_solo.py       # legacy Tkinter views
├── web/                          # current HTML/CSS/JavaScript interface
├── assets/                       # production icons and normalized setup JSON
├── tracks/                       # bundled circuit racing lines
├── setup_packages/1.5/          # original setup PDFs; source material
├── scripts/                      # data-import utilities
├── tests/                        # parser, strategy, coaching, setup tests
├── F1TelemetryHub.spec           # reproducible PyInstaller definition
├── build_exe.ps1                 # clean Windows build script
└── docs/                          # architecture and maintenance notes
```

The Python modules remain flat intentionally: older reports and saved tooling
import their existing module names. Generated folders (`build*`, `dist*`,
`__pycache__`, `.pytest_cache`) are disposable and ignored.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the data flow, thread
ownership, contracts, persistence boundaries, and extension guide.

## Technical references

- [EA F1 25 / 2026 Season Pack UDP specification](https://forums.ea.com/blog/f1-games-game-info-hub-en/ea-sports%E2%84%A2-f1%C2%AE25-udp-specification/12187347)
- [FIA Formula One regulations](https://www.fia.com/regulation/category/110)
- [Formula 1 strategy: undercut, overcut, and going long](https://www.formula1.com/en/latest/article/jolyon-palmers-analysis-singapore-and-the-art-of-undercutting.1NgVyVsZnHTDEA9wi0s5lW/)
- [F1 26 Season Pack ERS guide](https://simracingconfigs.com/f1-26-season-pack-ers-guide/)
- [F1 Game Setup 2026 library](https://www.f1gamesetup.com/car-setup/f1-2026)

Community information is a starting prior. Live telemetry, current race state,
and the driver's measured behavior take precedence. See
`THIRD_PARTY_NOTICES.md` for bundled-source acknowledgements.
