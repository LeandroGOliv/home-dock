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

Dependencies point downwards only (devices → core → storage → ui). `ui` talks to `core`;
`core` uses `devices`; `storage` persists the core's groups and scenes; nothing below `ui`
imports Qt.

## Device layer

Modules: `base.py` (generic model), `spec.py` (wizard entry), `tuya.py` (tinytuya
transport), `rgb_bulb.py` (bulb driver, the only place with bulb DPS), `registry.py`
(driver selection), `scan.py` (LAN discovery), `fake.py` (in-memory device for tests).

- `DeviceType` — e.g. `RGB_BULB` (later `AIR_CONDITIONER`).
- `Capability` — `POWER`, `WORK_MODE`, `BRIGHTNESS`, `COLOR_HSV`, `COLOR_TEMPERATURE`
  (later `TEMPERATURE_SETPOINT`, `FAN_SPEED`, `HVAC_MODE`, …). Each value is also the name
  of a `DeviceState` field, so generic code can read/write state by capability.
- `DeviceState` — frozen dataclass with one optional field per capability, in
  **normalised, device-independent units**: `power` bool, `work_mode` `WorkMode.WHITE` /
  `WorkMode.COLOR`, `brightness` 0–100 %, `color_hsv` `Color(hue 0–360°, saturation
  0–100 %)`, `color_temperature` 0–100 % (warm→cold). `None` means unknown/unchanged, so
  the same type is a full state, a partial change or a scene entry. Helpers:
  `capabilities`, `get()`, `restricted_to()`, `merged()`, `to_dict()` / `from_dict()`
  (JSON-compatible, used by storage). Out-of-range values raise.
- `Device` (protocol) — `id`, `name`, `type`, `capabilities`, `online`, `read_state()`,
  `apply(changes) -> DeviceState`, `close()`. Both I/O methods block and raise
  `DeviceError`; unsupported capabilities in `changes` are skipped silently. `close()`
  releases the connection (blocking until the I/O in progress ends); a later call connects
  again.
- `DeviceSpec` — one wizard entry (id, name, local key, IP, version, category, DPS codes);
  its `repr` masks the ID/IP and never shows the key.
- `TuyaLink` — raw DPS transport. `TinyTuyaLink` opens a **persistent socket lazily**
  (protocol 3.4 negotiates a session key per TCP connection), turns tinytuya `Err`
  responses and exceptions into `DeviceError` (without the library message, which may
  contain the IP) and drops/reopens the socket after any error and after 20 s idle (Tuya
  devices drop idle connections). It accepts protocol versions 3.1/3.3/3.4/3.5 (default
  3.4) and undoes tinytuya's sticky "one DPS per command" fallback after every write.
  tinytuya reads one message per call without matching it to the request, and a write is
  answered by an ack plus **one status push per changed DPS**, so pushes stay on the
  socket; a read retried after one would leave its own answer there too, and a later call
  took that old full status as current. So every call first reads, without waiting
  (`select`), each message already on the socket, oldest first, and returns their DPS
  under its own answer (verified on hardware, issue #11).
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
- **LAN discovery** — `scan_lan(scan_time=18)` returns a `FoundDevice(id, ip, version)`
  per Tuya device whose UDP broadcast arrived in time (ports 6666/6667/7000, tinytuya's
  scanner). It only **listens**: `poll=False`, never a TCP connection (the bulbs accept one
  client, which the control service may hold). tinytuya loads a `devices.json` from the
  working directory when given no devices, so it gets a placeholder list. A scan that
  cannot run (e.g. a port taken) raises `DeviceError` without the library message; the
  `FoundDevice` repr hides the ID and IP. Blocks: callers run it off the UI thread.
- `homedock.masking` (layer-independent): `mask()`, `redact()` and `RedactingFilter` for
  logs. A test guards that no DPS code, `tinytuya` or driver module is referenced outside
  `devices/`.

## Core

Modules: `control.py` (`ControlService`), `targets.py`, `groups.py`, `scenes.py`,
`events.py` (Qt-free observer), `naming.py`. The core only knows the generic `Device`
protocol; tests guard that it never mentions `RgbBulb`, imports only the public
`homedock.devices` API and never imports `storage`, `ui` or Qt.

- **ControlService** — owns a fixed list of devices, runs all I/O on a worker pool (never
  on the UI thread; at least one worker per device) and keeps a state/online cache.
  - API: `send(target, changes)`, `refresh(target)` and `apply_scene(scene)` return a
    `Future[CommandResult]` (`succeeded` / `failed` / `skipped` / `unknown` device ids,
    in target order); `capture(target)` returns a future snapshot. None of them block. `state(id)`,
    `is_online(id)` (`None` until the first I/O) and `capabilities(target)` (union of the
    members') read the cache.
  - Events `state_changed(id, state)` and `online_changed(id, online)` fire on worker
    threads, only when the cached value changes; the UI must marshal them to its thread.
    A failing listener is logged and ignored.
  - Group commands fan out to all members **in parallel**; each device receives only the
    capabilities it supports (mixed groups) — a device supporting none is `skipped`.
  - Each device has a **lane**: a FIFO of writes and reads drained by one worker task at
    a time, so I/O to a device is serialised and keeps its order. A write queued behind
    a pending write of the **same capabilities** replaces it — latest value wins, so
    slider/ring drags collapse into few writes; consecutive reads merge. (A wider change
    is kept apart: it may imply another bulb mode than the pending one.)
    Writes to a device are spaced by `THROTTLE_INTERVAL` (0.1 s after the previous write
    ends); values arriving during that wait coalesce too. Executor, clock and sleep are
    injectable for deterministic tests.
  - `DeviceError` → the device is `failed` and marked offline (a later success marks it
    online again), and the jobs already queued for it fail at once instead of each
    waiting for a timeout; any other exception is logged and fails only that job. A
    partial state returned by a device is merged into the cached one. Logs mask device
    IDs.
  - `replace_devices(devices)` swaps the device list (after "Procurar lâmpadas novas"
    re-imported `devices.json`, e.g. with new IPs). A device keeping its id keeps its lane
    (queued jobs run on the new object) and its cache; a removed one has its queued jobs
    failed and its cache dropped; added ones get new lanes (the pool keeps its size, so a
    long list may share workers). The objects left over are **closed on their lane's
    worker**, after the I/O running on them and before the next job, since a device may
    accept only one connection. A job for a device removed meanwhile fails at once.
  - `shutdown()` fails every queued job, makes later calls fail immediately
    (`ServiceClosedError`) and stops the pool it created (an injected executor is left
    running); no future is ever left pending.
- **Targets** — `Target.device(id)`, `Target.group(id)` or `Target.all_of(type)`: the
  **automatic group per device type** ("Todas as lâmpadas" = all `RGB_BULB` devices).
  `resolve()` returns the known members (a stale target resolves to nothing);
  `available_targets()` lists automatic groups (types present), user groups, devices.
- **Groups** — `GroupBook` of `Group(id, name, members)`: create, rename, set members,
  delete, restore (undo a delete, at its position); a device may belong to many groups;
  mixed types allowed. Tuya groups are not used. Names are trimmed and must not be blank.
  `ControlService.groups` is the book in use; the UI replaces it after each saved change.
- **Scenes** — `SceneBook` of `Scene(id, name, devices: {device id: DeviceState})`:
  create, rename, overwrite, delete, restore (undo a delete, at its position). Stored (by
  `storage`) as:

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

  "Salvar atual" = `SceneBook.create(name, service.capture(target).result())` (awaited off
  the UI thread): `capture` reads the devices of the **current target** — queued behind
  pending writes, so the end of a drag is included — and keeps those that answered, each
  restricted to its capabilities. `apply_scene` sends every entry in parallel, each device only its
  supported capabilities; offline devices fail alone and are reported (`failed`), devices
  no longer known are reported as `unknown` — the rest of the scene is applied.

## Storage

Modules: `files.py` (`AppPaths`, `write_atomic`), `devices.py` (device import),
`config.py` (`config.json`), `logs.py` (log files), `app_data.py` (start-up). Storage may
use `core`, the public `homedock.devices` API and `masking`; tests guard that it never
imports `ui`, Qt or a concrete driver.

All files under `%APPDATA%\HomeDock\` (`AppPaths.default()`; the roaming profile folder
when `APPDATA` is unset), never in the repo or the working directory:

- `devices.json` — imported tinytuya wizard output (IDs, local keys, IPs). Read-only for
  the app except IP refresh after a scan. `import_devices()` builds the devices through
  the driver registry (never connects, never raises) and reports a problem (`missing`,
  `unreadable`, `invalid`) instead of failing; it also returns every sensitive value of
  the file (ID, key, IP, MAC, UUID, serial) so the logs can mask it. A UTF-8 BOM is
  accepted. `update_ips(path, found)` writes the IPs of a scan into the entries whose IP
  is empty or another one (and the protocol version found when an entry has none); it
  rewrites the file atomically, in the wizard's 4-space layout, only when something
  changed, keeps every other field, leaves an unreadable file alone and returns
  `IpUpdate(updated, not_imported)` — `not_imported` counts Tuya devices on the LAN that
  the file does not list. Display names never go to this file.
- `config.json` — display names, groups, scenes, settings (start with Windows, last
  target), as the frozen `Config` / `Settings` dataclasses:

  ```json
  {
    "schema": 1,
    "names": { "<device-id>": "Abajur" },
    "groups": [{ "id": "…", "name": "Sala", "members": ["<device-id>"] }],
    "scenes": [{ "id": "…", "name": "Leitura", "devices": { "<device-id>": { … } } }],
    "settings": { "start_with_windows": false,
                  "last_target": { "kind": "group", "key": "…" } }
  }
  ```

  Scene states use `DeviceState.to_dict()` / `from_dict()` (defined in the device layer,
  so a new capability brings its own encoding). Missing sections take their defaults and
  unknown keys are ignored. `MIGRATIONS[n]` upgrades a schema-n document to n + 1;
  `migrate()` applies them in order on load (a missing step is a `ConfigError`). Saving always writes the current schema.
- **Atomic writes** — `write_atomic()` writes a temporary file in the same folder,
  fsyncs it and renames it over the target (`os.replace`); on failure the old file is
  kept and the temporary file removed.
- **Corrupt config** — `load_config()` never raises: an unreadable, invalid or newer-schema
  file is moved to `config.corrupt-<timestamp>.json` (kept for the user) and the app
  starts from the defaults (`LoadedConfig.backup` tells the UI). Validation is
  all-or-nothing: one invalid entry makes the whole file corrupt.
- **Logs** — `logs\homedock.log`, rotating (1 MB × 3 backups), UTF-8, attached to the
  root logger so library logs are covered too (calling `setup_logging()` again replaces
  the handler). A `RedactingFilter` on the handler masks the secrets imported from
  `devices.json` (ignoring letter case) and **any IPv4 address** in the message, the
  exception text and the stack info. Load errors log only the error type, never values
  read from the files.
- **Start-up** — `open_app_data()` sets up the logs, imports the devices (registering
  their secrets in the log filter), loads the config and writes the default `config.json`
  when there is none. `AppData.save(config)` persists changes. The UI start-up
  (`ui/app.py`) calls it once.
- **Device reload** ("Procurar lâmpadas novas") — `AppData.reload_devices(scan)` runs the
  scan, registers the IDs and IPs found in the log filter, `update_ips()`, then imports
  `devices.json` again and returns a `DeviceReload(devices, updated_ips, not_imported,
  scan_failed, write_failed)`. A failed scan still re-imports the file; when the file
  cannot be read, `AppData.devices` keeps the devices imported before (`devices.problem`
  tells). Blocks for the whole scan and never raises.

## UI

Modules so far: `app.py` (start-up), `single_instance.py`, `bridge.py`, `tray.py`,
`icons.py`, `flyout.py`, `placement.py`, `target_model.py`, `selector.py`, `panels.py`,
`bulb_panel.py`, `controls.py`, `scenes.py`, `manage.py`, `theme.py`, `widgets.py`,
`dial_math.py`, `dials.py`, `strings.py`. The UI may import `core`, `storage`,
`masking` and the public `homedock.devices` API only (guarded by a test).

- **Start-up** — `homedock` (`__main__` → `ui.app.run()`): takes the single-instance lock
  (a named Windows mutex, `Local\HomeDock.SingleInstance`; a second launch exits at once,
  before touching any file — also when the first one runs with other rights, e.g.
  elevated, and the mutex cannot even be opened), runs the storage start-up, builds the `ControlService` over
  the imported devices and shows the tray. The app does not quit when a window closes;
  "Sair" quits, and the service is shut down on the way out. It persists what the flyout
  changes (`config.json`: last target, scenes, names, groups) and runs the device reload
  on a **daemon thread** (`run_in_thread`: quitting never waits for a scan): scan,
  `AppData.reload_devices()`, then `ControlService.replace_devices()` with the new import.
- **Thread bridge** — `ServiceBridge` (a `QObject` on the UI thread) re-emits the service
  events (`state_changed`, `online_changed`) as Qt signals and runs future callbacks
  (`when_done`) on the UI thread, always queued (never re-entrant). Widgets are never
  touched from workers. Events and callbacks share one queue, so after `detach()` nothing
  more is delivered, not even what was already posted: closing the tray while a bulb is
  still answering is safe.
- **Tray icon** — painted bulb icon (no image files), tooltip "HomeDock". Left click
  toggles the flyout. Right-click menu: Abrir painel · Ligar todos · Desligar todos ·
  per-device toggle · Cenas ▸ · Iniciar com o Windows ☑ · Sair.
  - Generic: every device with the `power` capability gets a checkable item (checked =
    on), labelled with the user's display name (`config.names`, else the wizard name) and
    "· offline" when its last I/O failed. "Ligar/Desligar todos" send `power` to the
    automatic group of every device type present.
  - Opening the menu re-reads names, scenes and the setting from the config and queues a
    `refresh` of every device; the items update live as the answers arrive. After any
    command the items show the cached state again, so a failed toggle reverts.
  - "Iniciar com o Windows" only saves `settings.start_with_windows` for now (the Windows
    `Run` entry comes with the packaging issue); a failed save reverts the check mark.
  - `&` in names is escaped so it is not taken as a keyboard shortcut.
  - Checkable items (the device toggles, "Iniciar com o Windows") keep the menu open, by
    mouse or keyboard (Enter or space; holding the key toggles once), so several devices
    can be toggled in a row (`StayOpenMenu`). The rule is the item being checkable, not
    the device type. Every other item closes the menu as usual, and so do Esc and a click
    outside it.
  - The device list is read from the service when the menu opens; after a reload of the
    devices (different objects or ids) the menu is rebuilt.
- **Flyout** (`flyout.py`) — a frameless 360 px tool window with painted rounded corners.
  It opens in the tray corner of the screen under the cursor, on the taskbar's side
  (`placement.py`: bottom-right, top-right with the taskbar on top, bottom-left with it on
  the left; an auto-hidden taskbar counts as bottom), 12 px from the edges, and grows
  upwards with its content (one geometry change, so it does not jump), never taller than
  the available area (a manage page caps its height there and scrolls its middle part).
  Before measuring, the size hints of the current page are refreshed: a hidden window
  does not handle layout requests, and the pages change while it is closed (each opening
  starts on the main page). It hides on Esc and when it loses focus; a tray click within
  0.5 s of such a hide does not reopen it (that click is what took the focus away).
  "Abrir painel" always opens it. `toggle()` / `open()` are what the tray calls;
  `shutdown()` detaches its bridge when the app quits.
  - **Page stack** — `PageStack` shows only its top page; the main page is the base and
    never popped. Each opening starts on the main page with the list closed.
    "Gerenciar grupos e lâmpadas" pushes the manage page; a group pushes the group page.
    Going back to the main page reloads it (groups, names or devices may have changed).
  - **Main page** — the target selector button (title + subtitle, chevron) and the
    round power button, then the panel of the target. Opening the flyout re-reads names
    and groups, keeps the target if it still exists (else the last target saved in
    `settings.last_target`, else the first automatic group) and queues a `refresh` of
    every device; the page updates live from the bridge events. Choosing a target closes
    the list, saves it as `last_target` (a failed save is only logged) and re-reads it.
  - **Target selector** — `target_model.build_model()` turns the service cache into
    sections: "Grupos" (one automatic group per device type present, with its device
    count, then the user groups with their members' display names) and one section per
    device type (each device with a dot — filled when on and reachable — its groups and
    "offline"). Header subtitles: "Grupo · 2 de 3 online" (or "Grupo · 3 lâmpadas" before
    any member answered), "Lâmpada · online/offline". Wording per type comes from
    `strings.noun()` ("Lâmpada", "Todas as lâmpadas"); other types get generic words. The
    list (`selector.py`) replaces the panel while open, scrolls beyond 520 px (less on a
    small screen) and updates its rows in place when only state changed.
  - **Power button** — checked when some reachable member of the target is on; a click
    sends `power` (the toggled value) to **the selected target only**, so a partly-on
    group is switched off. While the command runs the button keeps the requested state
    (members answer one by one; tracked per target, so another target shows its own
    state); afterwards it shows the cached state again, so a failure
    reverts it. Disabled when no member has the `power` capability.
- **Panel registry** (`panels.py`) — `PanelRegistry.register(device_type, factory)`; the
  main page asks `create(PanelContext(service, bridge, target))` on every target change
  and every opening (the members may have changed).
  A target whose members are all of one registered type gets that type's panel; mixed
  groups, empty targets and types without a panel get the power button only.
  `default_panels()` registers every panel (so far `RgbBulbPanel` for `RGB_BULB`).
- **RGB bulb panel** (`bulb_panel.py`) — `RgbBulbPanel`: the Branco | Cor switch, then
  the temperature arc (white) or the hue ring (colour), the **Brilho** slider (both modes)
  and the **Saturação** slider right below it (colour only; hidden in white mode but
  keeping its room, so the flyout does not jump between modes).
  - Each control sends only its own capability to the target: a tab click
    `work_mode`, the arc `color_temperature`, the ring and the saturation slider
    `color_hsv` (hue + the shown saturation), the brightness slider `brightness`. The
    driver turns them into the bulb's commands (the same brightness value becomes the
    white brightness or the colour's V, by the bulb's mode; a colour or temperature change
    also switches the mode). In a group each member gets the command in its own mode.
  - Every drag step is sent at once; the control service's lanes keep only the latest
    pending value per device and space the writes (`THROTTLE_INTERVAL`), so a continuous
    drag never floods the bulbs.
  - It shows the state of the **first online member** of the target (else the first one
    with a known state), live from the bridge events. While a command of the panel runs,
    its controls keep what the user set (answers to earlier drag steps would move them
    back); afterwards — and when a held control is released — they show the cached state
    again, so a failure reverts them. In a group with an unreachable member this holds the
    controls until that member times out (intended: the end state is right). An answer
    arriving after the panel was replaced is ignored.
  - A mode the panel does not know (the bulb is in a Tuya scene or music mode) selects no
    tab, so either tab switches the bulb to it.
  - Controls whose capability no member supports are disabled (e.g. the arc of a bulb
    without colour temperature).
- **Controls** (`controls.py`) — generic Windows 11 widgets: `Slider` (a press anywhere
  jumps there and starts a drag; arrows, Page Up/Down, Home/End, with a focus ring when
  reached with the keyboard; `moved` / `released` and `set_value()` like the dials, also
  ending a drag when hidden or disabled), `SliderRow` (title + value in percent),
  `SegmentedControl` (exclusive options, or none; `chosen` only for the user's picks),
  `LinkButton` (accent text link), `NameEditor` (inline name field with ✓ / ✕) and
  `Notice` (discreet message with an optional action, hiding after 6 s but not under the
  pointer), shared by the scenes and the manage pages.
- **Scenes in the flyout** (`scenes.py`) — `ScenesSection`, below the panel (hidden while
  the target list is open, shown for every target, also mixed groups). Generic: it only
  calls `apply_scene()` / `capture()` and edits a `SceneBook`; the tray menu reads the
  same `config.scenes`, so both show the same list.
  - Header "Cenas" + "+ Salvar atual", then `SceneStrip`: the scenes in **one row, three
    in view** (each a third of the width; the rounding goes to the gaps, so the third ends
    on the panel's edge). More scroll **sideways**: a thin bar shows below the row only
    then, the wheel (vertical or sideways) moves one scene per notch, releasing the bar
    snaps to a scene, and a button reached with Tab scrolls just enough to be whole.
    "Nenhuma cena salva" when empty. A click applies the scene.
  - Names are typed in an **inline field** that takes the header's place (same height):
    a dialog would take the focus and close the flyout. Enter or ✓ accepts, Esc or ✕
    cancels (Esc there, also on ✓/✕, does not close the flyout; the field has no Qt
    context menu, which would be in English); the suggestion is "Cena n", the first free
    number. "Salvar atual" captures the **current target** when the name is accepted; while
    a capture runs, saving and overwriting are disabled (no duplicate "Cena n"). Closing
    the field puts the focus on the renamed scene or on "+ Salvar atual".
  - Right click or the menu key → Renomear | Sobrescrever com o estado atual | Excluir (a
    `QMenu` popup does not deactivate the flyout). "Sobrescrever" makes the scene the
    current state of the **selected target's** devices that answered, like "Salvar atual";
    nothing changes when none answers. Saving and overwriting are disabled for a target
    without devices. Deleting a focused scene moves the focus to its neighbour.
  - A discreet **notice** above the scenes (so they stay under the pointer while the
    flyout grows upwards) hides after 6 s, but not while the pointer is on it (the flyout
    would shrink under the pointer reaching for the action): offline devices left out when
    applying or saving ("Filme · 1 lâmpada offline ficou de fora"), nothing saved when no
    device answered, a failed save, and "“X” excluída" with **Desfazer**, which puts the
    scene back at its position (`SceneBook.restore`). Devices removed since a scene was
    saved are skipped silently.
  - Every change is persisted at once through `save_scenes` (`AppData.save`); the row
    then shows what is saved, so a failed save (`OSError`) leaves the old list. Opening the
    flyout re-reads the scenes, scrolls back to the first ones, closes the name field and hides the
    notice.
- **Manage pages** (`manage.py`) — generic: sections per device type, worded by
  `strings.noun()`.
  - **Grupos e lâmpadas** (`ManagePage`) — "Grupos (cômodos)" with "+ Novo grupo", a card
    per group (name, members' display names or "Vazio", chevron), the hint that the
    automatic group always includes every device, then one section per device type: a row
    per device with its status (green dot when its last I/O succeeded, a ring and
    "· offline" when it failed; live from the bridge) and a pencil. The pencil swaps the
    row for the inline name field (`NameEditor`, one at a time; Enter/✓ saves, Esc/✕
    cancels without closing the flyout). Names are **local**: `save_names` writes
    `config.names`; the wizard's own name removes the entry; `devices.json` is never
    touched. "Procurar lâmpadas novas" starts the device reload (`DeviceReloader`: one at
    a time, off the UI thread through the app's `reload_devices`; the button says
    "Procurando lâmpadas na rede…" and is disabled meanwhile, also on a page opened while it
    runs). When it ends the page rebuilds its lists and a notice tells the result: "2
    lâmpadas · 1 IP atualizado" / "IPs em dia", a scan or read failure, IPs that could not
    be saved, and "n dispositivos Tuya na rede não estão no devices.json: rode o wizard de
    novo." If it ends while the main page is shown, the main page reloads.
  - **Editar grupo / Novo grupo** (`GroupPage`) — the name (a text box; Enter saves), a
    check-box row per device of each type with its other groups ("também em Quarto"), the
    hint that a device may be in many groups, "Excluir grupo" (existing groups only) and
    "Salvar" (disabled for a blank name). Saving keeps the members' order, appends the
    newly checked ones and keeps members no longer known (removed from `devices.json`).
    Back discards the changes. Deleting returns to the manage page with "“Sala” excluído"
    and **Desfazer** (`GroupBook.restore` at its position).
  - Every change goes through `Groups.change()`: applied to a copy of
    `ControlService.groups`, persisted with `save_groups` (`config.groups`), then the copy
    becomes the service's book — a failed save (`OSError`) changes nothing and shows "Não
    foi possível salvar os grupos".
  - A widget must get its parent before `setVisible(True)`: shown without one, it opens
    as a window of its own, which takes the activation and closes the flyout.
- **Theme** (`theme.py`) — colours, sizes and fonts measured on the mockups (dark theme,
  accent `#F2B544`, Segoe UI Variable/Segoe UI, 14/13 px). Widgets read them only from
  there; following the Windows theme and accent (issue #13) replaces these values.
- **Hue ring and temperature arc** (`dials.py`) — `HueRing` and `TemperatureArc`, 220 px
  dials painted with `QPainter` (`QConicalGradient` band, white marker with a faint dark
  outline so it shows on the light whites). The hue ring goes round 360°, red at the top
  and clockwise; its centre shows one preview circle of the colour at full brightness
  (hue + saturation) and the hex code. The arc spans 270°, open at the bottom, warm
  (0 %) on the left → neutral at the top → cold (100 %) on the right; its centre shows the
  tint of the white and "Quente" / "Neutro" / "Frio". Both share the `Dial` base:
  - a press on the band starts a drag and moves the marker there; a press on the marker
    grabs it without moving it (the drag keeps the grab offset); presses elsewhere — and
    in the arc's opening — are ignored. The marker then follows the pointer's angle, also
    off the band; a drag into the arc's opening stays at the end it came from until the
    pointer comes back onto that end's half, so it never jumps from cold to warm;
  - `moved(int)` reports every new value while the button is held, `released(int)` the
    final one when the value changed during the press (a click is a press + release).
    Hiding or disabling a dial mid-drag (the flyout closing) ends the drag the same way;
  - `set_value()` (state from the device) emits nothing and is ignored during a drag, so
    a late answer does not make the marker jump back under the pointer.

  The maths (`dial_math.py`, no Qt) are pure functions: compass angles, angle ↔ hue,
  angle ↔ temperature with the dead zone and the drag across it, positions on a conical gradient, HSV ↔ hex and
  colour blending. `scripts/dials_demo.py` shows both dials in a window (no device).
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
