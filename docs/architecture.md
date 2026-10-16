# HomeDock architecture

This document describes the intended design of HomeDock v1. Issues implement it
incrementally; when an implementation decision changes the design, update this file in the
same PR.

## Goals

- Control Tuya devices over the LAN only (tinytuya). No cloud access at runtime.
- v1 device type: RGB bulb. N devices, user groups, scenes.
- Adding a new device type (e.g. air conditioner) means adding a driver and a control
  panel — **no changes to core, storage, tray menu or target selector**.

## Layers

```
┌──────────────────────────────────────────────────────────────┐
│ ui        tray icon + menu, flyout (page stack), panel        │
│           registry, custom widgets (hue ring, CCT arc), theme │
├──────────────────────────────────────────────────────────────┤
│ storage   %APPDATA%\HomeDock: device import, config (names,   │
│           groups, scenes, settings)                           │
├──────────────────────────────────────────────────────────────┤
│ core      ControlService (async command dispatch, state       │
│           cache), groups, scenes, targets                     │
├──────────────────────────────────────────────────────────────┤
│ devices   Device interface + capabilities; drivers (RgbBulb)  │
│           wrapping tinytuya. DPS knowledge lives ONLY here.   │
└──────────────────────────────────────────────────────────────┘
```

Dependencies point downwards only. `ui` talks to `core`; `core` uses `devices` and
`storage`; nothing below `ui` imports Qt widgets.

## Device layer

Modules: `base.py` (generic model), `spec.py` (wizard entry), `tuya.py` (tinytuya
transport), `rgb_bulb.py` (bulb driver, the only place with bulb DPS), `registry.py`
(driver selection), `fake.py` (in-memory device for tests).

- `DeviceType` — e.g. `RGB_BULB` (later `AIR_CONDITIONER`).
- `Capability` — `POWER`, `WORK_MODE`, `BRIGHTNESS`, `COLOR_HSV`, `COLOR_TEMPERATURE`
  (later `TEMPERATURE_SETPOINT`, `FAN_SPEED`, `HVAC_MODE`, …). Each value is also the name
  of a `DeviceState` field, so generic code can read/write state by capability.
- `DeviceState` — frozen dataclass with one optional field per capability, in
  **normalised, device-independent units**: `power` bool, `work_mode` `WorkMode.WHITE` /
  `WorkMode.COLOR`, `brightness` 0–100 %, `color_hsv` `Color(hue 0–360°, saturation
  0–100 %)`, `color_temperature` 0–100 % (warm→cold). `None` means unknown/unchanged, so
  the same type is a full state, a partial change or a scene entry. Helpers:
  `capabilities`, `get()`, `restricted_to()`, `merged()`. Out-of-range values raise.
- `Device` (protocol) — `id`, `name`, `type`, `capabilities`, `online`, `read_state()`,
  `apply(changes) -> DeviceState`. Both I/O methods block and raise `DeviceError`;
  unsupported capabilities in `changes` are skipped silently.
- `DeviceSpec` — one wizard entry (id, name, local key, IP, version, category, DPS codes);
  its `repr` masks the ID/IP and never shows the key.
- `TuyaLink` — raw DPS transport. `TinyTuyaLink` opens a **persistent socket lazily**
  (protocol 3.4 negotiates a session key per TCP connection), turns tinytuya `Err`
  responses and exceptions into `DeviceError` (without the library message, which may
  contain the IP) and drops/reopens the socket after any error and after 20 s idle (Tuya
  devices drop idle connections). It accepts protocol versions 3.1/3.3/3.4/3.5 (default
  3.4) and undoes tinytuya's sticky "one DPS per command" fallback after every write.
- A driver translates normalised values ↔ DPS. For the RGB bulb:
  - power → DPS 20; mode → DPS 21;
  - brightness → DPS 22 in white mode, **V of DPS 24** in colour mode (raw = % × 10,
    minimum 10); colour temperature → DPS 23; hue/saturation → DPS 24
    (`HHHHSSSSVVVV` hex);
  - turning off/on touches **only DPS 20** (the bulb keeps mode/colour/brightness);
  - target mode: an explicit `work_mode` wins; otherwise a colour change implies colour
    mode and a temperature change implies white mode. Only the DPS of the target mode are
    written — DPS 22/23 never in colour mode, DPS 24 never in white mode — because writing
    them switches the bulb's mode. Values for the other mode are dropped;
  - mode and values go in one `set_multiple_values` call (verified on hardware);
  - the driver keeps a DPS cache: `read_state()` merges the **partial status pushes** a
    persistent socket may return and retries until a full status arrives; `apply()`
    re-reads first when the cache is empty or older than 10 s (the Tuya app or a power
    cut may have changed the mode), then merges the reply and what was written (the
    payload wins: the reply may be an older queued push); any `DeviceError` clears it;
  - a lock serialises I/O per device (devices accept one TCP client at a time);
  - DPS 33/34 (power-loss behaviour) are read for diagnostics only (33 is not reported
    by the PSBAM bulbs).
  - DPS/ranges/protocol version confirmed by `scripts/diagnose.py` (see CLAUDE.md
    "Device / DPS notes").
- Driver selection: `DriverRegistry.load(entries)` builds one device per wizard entry by
  tinytuya `category` + DPS signature (the RGB bulb needs category `dj` and the v2 codes on
  DPS 20/21/22/24; DPS 23 adds `COLOR_TEMPERATURE`). Loading never connects. Invalid
  entries and devices without a driver become `UnsupportedDevice` (reason
  `invalid_entry` / `unknown_type`), never an exception.
- `homedock.masking` (layer-independent): `mask()`, `redact()` and `RedactingFilter` for
  logs. A test guards that no DPS code, `tinytuya` or driver module is referenced outside
  `devices/`.

## Core

- **ControlService** — owns devices, runs all I/O on a worker pool (never on the UI
  thread), keeps a state cache, emits state-changed / online-changed events.
  - Group commands fan out to all members **in parallel**.
  - Each device receives only the capabilities it supports (mixed groups).
  - Rapid updates (slider/ring drags) are coalesced: latest value wins, throttled per
    device.
- **Targets** — what the flyout controls: a single device, a user group, or an
  **automatic group per device type** ("Todas as lâmpadas" = all `RGB_BULB` devices).
  The target exposes the intersection/union of capabilities needed by the panel.
- **Groups** — user-defined (e.g. Sala, Quarto), stored locally; a device may belong to
  many groups; mixed types allowed. Tuya groups are not used.
- **Scenes** — named snapshots, generic per capability:

  ```json
  {
    "id": "scene-uuid",
    "name": "Leitura",
    "devices": {
      "<device-id>": { "power": true, "work_mode": "white", "brightness": 80,
                       "color_temperature": 30 }
    }
  }
  ```

  "Salvar atual" captures only the devices of the **current target**. Applying a scene
  skips offline devices (and reports them) and sends each device only supported
  capabilities.

## Storage

All files under `%APPDATA%\HomeDock\` (never in the repo):

- `devices.json` — imported tinytuya wizard output (IDs, local keys, IPs). Read-only for
  the app except IP refresh after a scan.
- `config.json` — display names, groups, scenes, settings (start with Windows, last
  target). Versioned schema (`"schema": 1`) with migrations.
- logs — keys/credentials masked; IDs/IPs masked.

"Recarregar dispositivos" re-imports `devices.json`, runs a local `tinytuya` scan to fill or
refresh IPs, and warns when a Tuya device on the LAN is missing from `devices.json`
("rode o wizard de novo").

## UI

- **Tray icon** — left click toggles the flyout. Right-click menu: Abrir painel · Ligar
  todos · Desligar todos · per-device toggle (with current state) · Cenas ▸ · Iniciar com o
  Windows ☑ · Sair.
- **Flyout** — ~360 px wide, anchored near the tray, Windows 11 style, closes when it loses
  focus. One window with a **page stack**:
  - Main: target selector (groups + devices with online status) + power button for the
    target; control panel for the target type; scenes grid (3 columns, scroll) with
    "+ Salvar atual"; right-click on a scene → Renomear / Sobrescrever / Excluir.
  - Gerenciar grupos e lâmpadas → Editar grupo (name, members, delete).
- **Panel registry** — maps device type/capabilities → panel widget. `RgbBulbPanel`:
  tabs Branco | Cor; white = CCT arc (~270°, open at the bottom, warm left → cold right);
  colour = hue ring (360°) with a centre preview + hex; brightness slider (both modes);
  saturation slider (colour only).
- **Custom widgets** — hue ring and CCT arc drawn with `QPainter`
  (`QConicalGradient`), click + drag, pure-function geometry/maths tested separately.
- **Theme** — follows Windows light/dark and the Windows accent colour, live-updating.
- **Strings** — pt-BR, centralised in one module.

## Resilience

- Per-device online status, timeouts, retries with backoff.
- On repeated failure: rescan the LAN to find the device's new IP, update `devices.json`
  IP, retry. README recommends DHCP reservations.

## Extending with a new device type

1. Add capabilities to `Capability` if needed.
2. Implement a driver in `devices/` and register it.
3. Implement a control panel in `ui/` and register it for the type.
4. Optionally add a tab for the type in the flyout.

No changes to core, storage, groups, scenes, target selector or tray menu should be
required.
