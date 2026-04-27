# DroneFollow Parameter System — Architecture Reference

## Overview

The drone-follow parameter control path spans three software layers across
two Raspberry Pi units connected via wifibroadcast. The same parameter set is
also editable from the air-side web UI (`--ui`, port 5001) — Web UI sliders
write to the same in-process `ControllerConfig` that this bridge edits, so
both control surfaces stay in sync automatically.

```
┌──────────────────────── AIR UNIT (RPi5 + Hailo8) ─────────────────────────┐
│                                                                            │
│  ┌──────────────────────┐    UDP JSON      ┌───────────────────────────┐  │
│  │  drone-follow        │◄────────────────►│  OpenHD air               │  │
│  │  (Python)            │  port 5510/5511  │  hailo_follow_bridge.cpp  │  │
│  │                      │                  │                           │  │
│  │  • Applies params    │  5510: OpenHD→Py │  • Loads df_params.json   │  │
│  │    to control loop   │  5511: Py→OpenHD │  • MAVLink param server   │  │
│  │  • Reports current   │                  │  • Persists values to disk│  │
│  │    values back       │                  │  • Translates MAVLink ↔   │  │
│  └──────────────────────┘                  │    UDP JSON               │  │
│                                            └─────────────┬─────────────┘  │
│                                              wifibroadcast (MAVLink relay) │
└──────────────────────────────────────────────────────────┼─────────────────┘
                                                           │ RF link
┌──────────────────────────────────────────────────────────┼─────────────────┐
│                                          GROUND (RPi4)   │                 │
│                                            ┌─────────────▼─────────────┐  │
│                                            │  OpenHD ground            │  │
│                                            │  • MAVLink relay          │  │
│                                            └─────────────┬─────────────┘  │
│                                                          │                 │
│                                            ┌─────────────▼─────────────┐  │
│                                            │  QOpenHD                  │  │
│                                            │  • Loads df_params.json   │  │
│                                            │    (UI metadata only)     │  │
│                                            │  • DroneFollow settings   │  │
│                                            │    tab: sliders/switches  │  │
│                                            │  • PARAM_EXT_SET/GET      │  │
│                                            └───────────────────────────┘  │
└───────────────────────────────────────────────────────────────────────────┘
```

---

## Parameter Set Flow

```
QOpenHD slider
  → MAVLink PARAM_EXT_SET
    → OpenHD ground (relay)
      → wifibroadcast RF
        → OpenHD air / hailo_follow_bridge
          → persist value to disk
          → UDP JSON {"param": "kp_yaw", "value": 5.1} to port 5510
            → drone-follow Python (applies immediately)
          → MAVLink PARAM_EXT_ACK back to QOpenHD
```

## Parameter Readback Flow

```
drone-follow Python
  → UDP JSON {"params": {"kp_yaw": 5.1, ...}} to port 5511
    → OpenHD air / hailo_follow_bridge (updates cache)
      → MAVLink PARAM_EXT_VALUE
        → wifibroadcast RF
          → OpenHD ground (relay)
            → QOpenHD (updates slider position)
```

---

## The Bridge (hailo_follow_bridge.cpp)

The bridge sits inside OpenHD on the air unit and translates between:

- **MAVLink side**: Registers all DF_ parameters from `df_params.json` as
  MAVLink extended parameters. QOpenHD can get/set them using standard
  PARAM_EXT_SET/PARAM_EXT_REQUEST_READ messages.

- **UDP JSON side**: Communicates with drone-follow on localhost:
  - Port **5510** (OpenHD → Python): `{"param": "kp_yaw", "value": 5.1}`
  - Port **5511** (Python → OpenHD): `{"params": {"kp_yaw": 5.1, ...}}`

---

## The df_params.json Schema

A single JSON file defines every DF_ parameter. All three layers read it:

- **OpenHD air** (C++): Loads at startup to register MAVLink params
- **QOpenHD** (QML): Loads at tab open to generate UI controls
- **drone-follow** (Python): Can read defaults from this file

**Location:** `/usr/local/share/openhd/df_params.json` (deployed on both units)

### Example

```json
{
  "version": 1,
  "groups": [
    {"id": "yaw", "label": "YAW CONTROL", "order": 1}
  ],
  "params": [
    {
      "id": "kp_yaw",
      "mavlink_id": "DF_KP_YAW",
      "type": "float",
      "default": 5.0,
      "min": 0.0,
      "max": 20.0,
      "step": 0.1,
      "group": "yaw",
      "order": 1,
      "label": "Kp Yaw",
      "description": "Proportional gain for yaw tracking.",
      "read_only": false
    }
  ]
}
```

### Field Reference

| Field | Description |
|-------|-------------|
| `id` | Internal Python field name (used in UDP JSON IPC) |
| `mavlink_id` | MAVLink parameter name (max 16 chars, must start with `DF_`) |
| `type` | `"float"` → slider, `"int"` → spin box, `"bool"` → toggle |
| `default` | Default value (used when no persisted value exists) |
| `min`/`max` | Range limits |
| `step` | Increment step for the UI control |
| `group` | Must match a group `id` from the `groups` array |
| `order` | Sort order within the group |
| `label` | Display name in QOpenHD |
| `description` | Tooltip / help text |
| `read_only` | If `true`, displayed as read-only text |
| `hidden` | If `true`, registered in MAVLink but hidden from DroneFollow tab |

### Adding a New Parameter

1. Add entry to `df_params.json`
2. Copy to `/usr/local/share/openhd/df_params.json` on both units
3. Restart OpenHD (air) and QOpenHD (ground) — no recompilation needed
4. (Optional) Handle in Python: `controller_config.get("my_param", 1.0)`

---

## Special params (not in `ControllerConfig`)

A few params are wired directly in `OpenHDBridge` instead of being mirrored to `ControllerConfig`. Each one requires both ends to know about it: the C++ `hailo_follow_bridge.cpp` forwards the value to UDP 5510, and `OpenHDBridge._listen_loop` dispatches it to the correct handler.

| Param (`id`) | MAVLink | Direction | Handler in `openhd_bridge.py` | Effect |
|---|---|---|---|---|
| `follow_id` | `DF_FOLLOW_ID` | ground → air | `_apply_follow_id` | `-1` = IDLE (hold), `0` = AUTO (largest), `>0` = lock to that detection ID. Mirrored back so the badge reflects operator intent. |
| `active_id` | `DF_ACTIVE_ID` | air → ground (read-only) | reported in `_send_report` | Currently active tracking ID (`0` = no one in view). Used by QOpenHD to distinguish AUTO-tracking-someone from no-target. |
| `bitrate_kbps` | `DF_BITRATE` | ground → air | `_apply_bitrate` | Sets the `openhd_stream_encoder` x264enc bitrate dynamically from QOpenHD's WFB link recommendation. No-op outside `--openhd-stream` mode. |
| `recording` | `DF_RECORDING` | ground → air, mirrored back | `_apply_recording` | Idempotent toggle for air-side recording (`1` = start, `0` = stop). Recording branch is auto-built in `--openhd-stream` mode, so the button works without `--record` at launch. State is reported back so the QOpenHD button reflects the true `is_recording` state (covers `--record` autostart, EOS, shutdown). |
| `save_config` | `DF_SAVE` | ground → air (momentary) | `_apply_save_config` | Write the live `ControllerConfig` to `df_config.json` on the air unit. Always reported back as `0` so the QOpenHD toggle returns to rest. See "Saving / Loading Controller Config" below. |
| `load_config` | `DF_LOAD` | ground → air (momentary) | `_apply_load_config` | Live-reload `ControllerConfig` in place from `df_config.json` on the air unit. Sliders (web + QOpenHD) refresh via the next periodic report. Always reported back as `0`. |

When adding another special param: register the constant in `openhd_bridge.py` (`_FOO_PARAM = "foo"`), add the dispatch branch in `_listen_loop`, write the handler, optionally include it in `_send_report`, and add the entry to `df_params.json`. **No OpenHD C++ change is required for QOpenHD-initiated params**: `load_param_defs_from_json` and `get_all_settings` in `hailo_follow_bridge.cpp` are fully data-driven from `df_params.json`, and `on_udp_data` generically syncs back any known key. C++ only needs a code change when OpenHD itself originates the value (e.g. `bitrate_kbps` is pushed from the WFB bitrate algorithm via `OHDVideoAir::handle_change_bitrate_request` calling `m_hailo_bridge->update_param(...)`).

To activate a new param after editing `df_params.json`:

```bash
sudo cp ~/hailo-drone-follow/df_params.json /usr/local/share/openhd/df_params.json   # on BOTH units
# Restart OpenHD on the air unit and QOpenHD on the ground unit; restart drone-follow.
```

---

## Saving / Loading Controller Config

There are **three related JSON files** to keep straight:

| File | What it is | Location(s) | Tracked in git? | When it changes |
|---|---|---|---|---|
| `df_params.json` | **Schema** — field defs, labels, groups, slider min/max/step, initial defaults. Read by OpenHD C++ at startup to register MAVLink parameters and by QOpenHD to render the slider tab. | Repo copy (`~/hailo-drone-follow/df_params.json`) and **deployed** copy (`/usr/local/share/openhd/df_params.json`) on both air and ground. | ✅ committed | When a developer adds/edits a param, followed by manual `sudo cp` + restart. |
| `df_config.example.json` | **Starter template** — a dump of `ControllerConfig()` defaults. Committed so newcomers can bootstrap without running the app. Never read at runtime; exists purely to be copied. | Repo root: `~/hailo-drone-follow/df_config.example.json`. | ✅ committed | When `ControllerConfig` defaults change and a maintainer regenerates it (see below). |
| `df_config.json` | **Live tuned values** — what `start_air.sh` auto-loads and what Save writes. Per-operator tuning. | **Air unit only**, at the repo root. | ❌ `.gitignore`-d | Each time the operator presses Save (web UI / QOpenHD) or runs `drone-follow --save-config`. |

The ground station has **no persistent store** for DF_* values. All persistence happens on the air unit.

### First-time setup on a fresh drone

On a fresh clone of the repo, `df_config.json` does not exist — `start_air.sh` will log "No df_config.json found — using ControllerConfig defaults" and run with the hardcoded defaults. To bootstrap:

```bash
cp ~/hailo-drone-follow/df_config.example.json ~/hailo-drone-follow/df_config.json
```

Then launch, tune in the field, and press **Save Config** — subsequent boots pick up your values automatically via `start_air.sh`.

### Regenerating `df_config.example.json`

When `ControllerConfig` gets new fields or changed defaults, regenerate the template so newcomers start from an up-to-date baseline:

```bash
source setup_env.sh
python -c 'from drone_follow.follow_api.config import ControllerConfig; \
           ControllerConfig().save_json("df_config.example.json")'
git add df_config.example.json && git commit -m "chore: regen df_config.example.json"
```

### Flow — Save

1. Operator tunes sliders (web UI or QOpenHD) while the drone is running. Values mutate the live `ControllerConfig` in `drone-follow`'s memory.
2. Operator presses **Save Config** (web UI) or toggles **Save config (air)** ON in QOpenHD.
3. Handler (`_handle_config_save` in `web_server.py` or `_apply_save_config` in `openhd_bridge.py`) calls `cfg.save_json(DEFAULT_CONFIG_PATH)` → writes `~/hailo-drone-follow/df_config.json` on the air Pi.
4. (QOpenHD path) The next periodic report sends `save_config: 0`, returning the toggle to rest.

### Flow — Load

1. Operator presses **Load Config** (web UI) or toggles **Load config (air)** ON in QOpenHD.
2. Handler calls `cfg.load_from_file(DEFAULT_CONFIG_PATH)` — mutates the existing `ControllerConfig` **in place** (the control loop and all servers hold the same object, so the change takes effect immediately).
3. The next `_send_report` pushes the new values → QOpenHD sliders refresh. The web UI additionally refetches `GET /api/config` to refresh its own sliders.
4. On validation error, the previous values are rolled back and the HTTP response returns 400 / log warning is emitted (OpenHD path).

### Flow — CLI boot

`drone-follow --config ~/hailo-drone-follow/df_config.json --input rpi --openhd-stream ...`
- Loads the saved file as the pre-CLI defaults.
- CLI flags still override. No QOpenHD / UI action needed for the initial values to take effect on startup.

### Notes

- The CLI flag `--save-config <path>` still exists but **exits immediately after writing** — useful for dumping a template, not for in-flight saves.
- `df_config.json` only persists fields that exist in `ControllerConfig` (everything serialised by `asdict(cfg)`). Momentary triggers like `save_config` / `load_config` / `recording` are **not** part of the config and aren't saved.
- If no `df_config.json` exists, a Load request returns 404 (web UI) / a warning in the logs (QOpenHD).
