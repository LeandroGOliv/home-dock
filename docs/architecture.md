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

- `DeviceType` — e.g. `RGB_BULB` (later `AIR_CONDITIONER`).
- `Capability` — `POWER`, `BRIGHTNESS`, `COLOR_HSV`, `COLOR_TEMPERATURE`, `WORK_MODE`
  (later `TEMPERATURE_SETPOINT`, `FAN_SPEED`, `HVAC_MODE`, …).
- `DeviceState` — mapping `Capability → value` in **normalised, device-independent units**
  (e.g. brightness 0–100 %, hue 0–360°, saturation 0–100 %, colour temperature 0–100 %
  warm→cold, work mode `white`/`colour`).
- `Device` (protocol) — `id`, `name`, `type`, `capabilities`, `read_state()`,
  `apply(changes: DeviceState)`, `online`.
- A driver translates normalised values ↔ DPS. For the RGB bulb:
  - power → DPS 20; mode → DPS 21;
  - brightness → DPS 22 in white mode, **V of DPS 24** in colour mode;
  - colour temperature → DPS 23; hue/saturation → DPS 24 (`HHHHSSSSVVVV` hex);
  - turning off/on touches **only DPS 20** (the bulb keeps mode/colour/brightness);
  - DPS 33/34 (power-loss behaviour) are read for diagnostics only.
  - Exact DPS/ranges/protocol version are confirmed by `scripts/diagnose.py` (see
    CLAUDE.md "Device / DPS notes").
- Driver selection: a registry maps tinytuya `category` (and/or DPS signature) to a driver;
  unknown devices are listed as unsupported, not crashed on.

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
