# CLAUDE.md

Guidance for Claude Code (and any AI agent) working in this repository.

## Overview

HomeDock is a Windows system-tray app that controls Tuya smart-home devices over the
**local network only** (no cloud), using `tinytuya`. v1 targets Positivo Casa Inteligente
RGB Wi-Fi bulbs (Tuya white label), N devices, user-defined groups and scenes. The
architecture must stay extensible to other device types (e.g. air conditioners) without
touching the core.

- Architecture details: [docs/architecture.md](docs/architecture.md)
- End-user setup (pt-BR): [README.md](README.md), [docs/configuracao.md](docs/configuracao.md)
- UI references: [docs/ui/](docs/ui/) — PNGs rendered at 2x (720 px wide = 360 px flyout).
  Use them for layout, colors and sizes; they are visual references, not code.

## Stack

Python 3.12+ (dev on 3.14) · tinytuya · PySide6-Essentials (tray + UI) · PyInstaller
(`HomeDock.exe`) · uv (env, lockfile) · ruff (lint/format) · pytest + pytest-qt ·
pre-commit (ruff, gitleaks, block-tuya-secrets, conventional-pre-commit).

## Layout

```
src/homedock/
  devices/   generic Device/capability interface + concrete drivers (DPS live ONLY here)
  core/      control service, groups, scenes (generic devices only)
  storage/   config/persistence under %APPDATA%\HomeDock
  ui/        tray, flyout pages, per-type control panels, custom QPainter widgets
scripts/     dev tooling (diagnostics, performance probe, pre-commit hooks, exe icon)
packaging/   PyInstaller spec of HomeDock.exe (one folder: dist\HomeDock\)
tests/       pytest suite (no network, no real devices)
```

## Commands

```powershell
uv sync                                                    # install / update env
uv run pre-commit install --hook-type pre-commit --hook-type commit-msg
uv run homedock                                            # run the app
uv run pytest                                              # tests
uv run ruff check . ; uv run ruff format --check .         # lint / format check
uv run pre-commit run --all-files                          # every hook
uv run python scripts/diagnose.py --dry-run                # read real bulbs (no changes)
uv run python scripts/diagnose.py --only 1 --tests power   # exercise one bulb (restores state)
uv run python scripts/dials_demo.py                        # hue ring / CCT arc demo window
uv run pyinstaller packaging/HomeDock.spec                 # build dist\HomeDock\HomeDock.exe
uv run python scripts/perf_probe.py exe                    # start-up, RAM, idle CPU of the exe
uv run python scripts/perf_probe.py flyout                 # also paint / drag (fake bulbs)
```

## Architecture rules (non-negotiable)

- Layers: **devices → core (control service, groups, scenes) → storage → ui**. Lower
  layers never import higher ones.
- The device layer exposes a **generic interface**: each device has a `type` and a set of
  **capabilities** (`power`, `brightness`, `color_hsv`, `color_temperature`; later
  `temperature_setpoint`, `fan_speed`, `hvac_mode`, …).
- The RGB bulb is just the first implementation. **All DPS numbers, codes, ranges and
  encodings live inside the bulb driver** — never in core, storage or ui.
- Groups, scenes, the target selector and the tray menu work on generic devices. Never
  import or special-case the bulb driver outside `devices/`.
- Groups may be mixed (bulb + AC). Commanding a group sends each device only the commands
  its capabilities support; others are skipped silently.
- The control panel is chosen by device type/capabilities through a registry, so a new
  device type brings its own panel.
- Do **not** implement air-conditioner support until its backlog issue is scheduled.
- The UI wording is bulb-focused in v1 ("Todas as lâmpadas" / "All bulbs"). Future device
  types will get their own tabs; the "all" automatic group is **per device type**.

## Security rules (mandatory)

Nothing sensitive may reach GitHub (the repo is **public**): credentials, local keys,
device IDs, IPs of the home network, wizard dumps, logs, local configs.

- Never create, copy or read secrets into the repo tree. Real data lives only in
  `%APPDATA%\HomeDock\` (app data) and `%USERPROFILE%\tuya-wizard\` (wizard outputs).
- Only `devices.example.json` (fictitious values, IPs from 192.0.2.0/24) is committed.
- Never print local keys or credentials — in logs, tests, scripts, PR text or chat. Mask
  them (e.g. `ab…ef`). Device IDs and IPs are also masked in logs.
- The app writes data **only** to `%APPDATA%\HomeDock\`, never to the repo folder. The
  one exception is its own `HomeDock` value under `HKCU\…\CurrentVersion\Run` ("Iniciar
  com o Windows"), plus clearing its Task Manager flag under
  `…\Explorer\StartupApproved\Run`; tests use an in-memory registry, never the real keys.
- `HomeDock.exe` bundles code only — never `devices.json`, `config.json`, logs or wizard
  files (the spec refuses to build otherwise).
- Tests never use real devices or real secrets; use fakes and fictitious values. The
  conftest refuses tinytuya devices and LAN scans and isolates `%APPDATA%`, the registry
  and the hook's secret sources: never call `monkeypatch.undo()` (it undoes all of that).
- Before every commit run `git status` and inspect the staged file list. Never use
  `git add -A`/`git add .` blindly. Never bypass hooks (`--no-verify`).
- `block-tuya-secrets` compares staged files with the real local values; gitleaks covers
  generic secrets. If a hook blocks a commit, fix the cause — do not work around it.

## Device / DPS notes

Positivo bulb model **PSBAM** (category `dj`, protocol **3.4**). **Confirmed on both
real bulbs** with `scripts/diagnose.py` (2026-10-15, issue #3). Re-run it for any new
model — never assume.

| DPS | Code | Type / range | Confirmed |
|---|---|---|---|
| 20 | `switch_led` | bool | ✔ |
| 21 | `work_mode` | `white` / `colour` / `scene` / `music` | ✔ white, colour |
| 22 | `bright_value_v2` | int 10–1000 (white-mode brightness) | ✔ 10, 500, 1000 |
| 23 | `temp_value_v2` | int 0–1000 (0 = warm, 1000 = cold) | ✔ 0, 500, 1000 |
| 24 | `colour_data_v2` | 12-hex string `HHHHSSSSVVVV`: H 0–360, S 0–1000, V 0–1000 | ✔ |
| 25 | `scene_data_v2` | hex string, built-in scenes | reported, unused |
| 26 | `countdown_1` | int seconds | reported, unused |
| 33 | `power_memory` | raw — behaviour after mains power loss | **not reported** in status |
| 34 | `do_not_disturb` | bool — don't turn on after a power outage | reported, read-only for us |

- Brightness depends on mode: white mode → DPS 22; colour mode → the **V** of DPS 24
  (changing V leaves DPS 22 untouched). One slider in the UI, different commands.
- **Writing DPS 22 while in colour mode switches the bulb to white mode** (DPS 24 is
  kept). The driver must never send DPS 22 in colour mode.
- Power on/off sends **only DPS 20**; DPS 21–24 are preserved across off/on (verified).
- Every write is read back exactly as sent (no rounding).
- Mode and values can go in one write (`{21: "colour", 24: …}`, `{21: "white", 22: …,
  23: …}`) — verified through the `RgbBulb` driver on a real bulb (2026-10-16, issue #4).
- With a **persistent socket**, a write is answered by an ack plus **one push per changed
  DPS**, and tinytuya reads only one message per call: the other pushes (and the answer
  to a retried query) wait on the socket and the next call would read them as its answer.
  `TinyTuyaLink` reads every waiting message first, in order (issue #11). Never treat a
  partial dict as the full state.
- `{20: False, 21: …, 24: …}` in one write keeps the bulb off and stores the mode/colour
  for the next power-on (verified 2026-10-17, issue #11) — how scenes restore an off bulb.
- Discovery (`scan_lan`) listens for the UDP broadcasts (ports 6666/6667/7000; tinytuya
  also sends its discovery request) with `poll=False`: it **never connects** to a device,
  whose single TCP connection the control service may hold. Both PSBAM bulbs broadcast
  protocol 3.4 and are found within ~8 s (verified 2026-10-18, issue #12).
- A device IP must be a private unicast IPv4 (`is_lan_address`): the scan drops any other
  and `TinyTuyaLink` refuses it (broadcasts are unauthenticated; `Auto`/`0.0.0.0` would
  make tinytuya scan and read a `devices.json` from the working folder) — issue #36.
- Device I/O never blocks the UI thread (workers/threads). Group commands run **in
  parallel**. Slider and ring drags are debounced/throttled.
- Read the real device state when the flyout opens. Offline / IP change → show status and
  try to rediscover via tinytuya scan.

## Code conventions

- Code, identifiers, comments, docstrings, commit messages, PR titles and AI files
  (CLAUDE.md, `docs/architecture.md`, `.claude/agents/`) in **English**.
- UI strings in **pt-BR and English**, following the display language of Windows (any
  `pt-*` → pt-BR, anything else → English). User docs — README, `docs/configuracao.md` —
  in **pt-BR** only. GitHub issue and PR bodies in pt-BR. Logs in English.
- UI strings centralised in the strings modules (no scattered literals): UI code reads
  `homedock.ui.strings`, a facade over `strings_pt_br.py` and `strings_en.py`. Every new
  text goes into **both** with the same name and signature (a test enforces it).
- Type hints everywhere; small modules; dataclasses/enums for domain types.
- ruff is the source of truth for style (line length 100).

## Testing

- Core (capabilities, DPS mapping, groups, scenes, persistence): unit tests with an
  in-memory **fake device**, test-first (TDD).
- Widget math (angle ↔ hue/temperature, HSV ↔ hex) as pure functions with unit tests.
- UI: `pytest-qt` only where it pays off (e.g. dragging a marker emits the right value).
- Real hardware: only the diagnostics script and the manual validation step of each issue.

## Workflow

1. Work on **one issue at a time**. Never commit to `main`.
2. Branch `issue-<n>-<slug>` from an up-to-date `main`.
3. Commits follow **Conventional Commits** in English (`feat(ui): add hue ring widget`);
   enforced by the commit-msg hook. Split the issue into **logical commits** that are
   reviewable on their own — e.g. tooling/config, each unit of behaviour with its tests,
   docs — never one commit mixing everything, nor dozens of trivial ones. Each commit
   should leave tests and lint green.
4. Before finishing: `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`,
   `uv run pre-commit run --all-files` — all green.
5. Push the branch and open a PR (title = Conventional Commit, body in pt-BR with
   `Closes #<n>` and the acceptance-criteria checklist).
6. **Stop** and wait for the user to validate. The user reviews and merges — never merge.

## Agents

Project subagents live in `.claude/agents/`:

- `test-engineer` — designs/writes/reviews tests, drives TDD on the core.
- `security-auditor` — audits the diff before a PR for secrets, unsafe logging, staged
  sensitive files; also holds the full (a)–(e) audit checklist to run before a release.

Each issue has a "Agentes sugeridos" section; a new agent proposed there is created as
part of that issue.
