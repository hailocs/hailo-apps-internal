# CLAUDE.md — Project Context for drone-follow

## Project Overview

A Hailo-based drone-follow application that uses an AI pipeline (GStreamer + Hailo NPU) for person detection and MAVSDK for PX4 drone control. Runs on a Raspberry Pi 5 with Hailo-8L accelerator mounted on a drone with a Cube Orange+ flight controller.

## Architecture

- **`drone_follow/follow_api/`** — Pure domain logic (follow controller, geometry, shared state)
- **`drone_follow/drone_api/mavsdk_drone.py`** — MAVSDK adapter; CLI args, connection, control loop
- **`drone_follow/pipeline_adapter/`** — Hailo/GStreamer detection pipeline, ByteTracker, ReID manager
- **`drone_follow/servers/`** — HTTP servers (follow API, web UI + MJPEG, OpenHD bridge)
- **`drone_follow/drone_follow_app.py`** — Main entry point (`main()`), wires everything together
- **`reid_analysis/`** — ReID embedding extraction and gallery matching strategies
- **`sim/`** — PX4 SITL simulation (Gazebo, video bridge, MAVLink relay, world files)

## Key CLI Flags

- `--serial [DEVICE]` — Connect via USB serial (default: `/dev/ttyACM0`); overrides `--connection`
- `--serial-baud RATE` — Baud rate (default: 57600)
- `--connection URL` — MAVSDK connection string (default: `udpin://0.0.0.0:14540` for simulation)
- `--takeoff-landing` — Enable auto arm/takeoff/land (default: off — drone must already be airborne)
- `--target-altitude M` — Target altitude in metres (default: 3.0). Held by a fixed-altitude P loop; also used as takeoff height with `--takeoff-landing`. Adjustable mid-flight via UI.
- `--target-bbox-height` — Desired person size in frame 0–0.25 (default: 0.25). Drives forward/backward distance. Adjustable mid-flight via UI "Target Size" slider.
- `--yaw-only` / `--no-yaw-only` — Yaw only mode (default: on). Use `--no-yaw-only` for full follow with forward/backward movement.
- `--horizontal-mirror` / `--vertical-mirror` — Both default to off (camera right-side up). Pass both flags for 180° rotation if camera is mounted upside-down. The pipeline also passes `mirror_image=False` to `SOURCE_PIPELINE()`.
- `--ui` / `--ui-port` / `--ui-fps` — Enable the web UI (port 5001 default, 10 FPS MJPEG default). Live video, click-to-follow, and slider-based controller tuning.
- `--record` — Capture post-overlay frames to `drone_follow/recordings/rec_<timestamp>.mp4` via an ffmpeg subprocess (libx264, 5 Mbps). Auto-starts ~1 s after PLAYING; can also be toggled mid-flight from the web UI's Record button. Saved on the drone — fewer compression artifacts than a ground-side capture, and survives RF dropouts.
- `--openhd-stream` — Send overlay video to OpenHD via UDP RTP instead of an X11 display sink. Uses x264 software encode (the RPi5 has no HW H.264).
- `--openhd-port` (default: 5500) / `--openhd-bitrate` (default: 3917 kbps) — OpenHD UDP destination and x264 starting bitrate. Bitrate is updated dynamically from QOpenHD's WFB link recommendation via the OpenHD bridge.
- `--no-display` — Headless mode (no X11 window). Pair with `--openhd-stream` or SHM input for SSH/bench sessions.

## Drone Connection

### USB Serial (real hardware)
The Cube Orange+ connects via USB as `/dev/ttyACM0`. Using `--serial` builds the connection string `serial:///dev/ttyACM0:57600` and passes it to MAVSDK.

### UDP (simulation)
Without `--serial`, defaults to `udpin://0.0.0.0:14540` for SITL/Gazebo.

## Follow Modes

The app has three follow modes:

- **AUTO** (default) — Automatically follows the largest person in frame. No operator input needed. The drone starts in this mode on boot. ReID gallery is built so the target can be recovered after temporary occlusion.
- **LOCKED** — Operator explicitly clicks a person in the UI to lock onto them. ReID gallery is also built for recovery.
- **IDLE** — Drone holds position, ignores all detections. Entered via OpenHD ground station (`follow_id = -1`).

### Auto mode behavior
- Selects the person with the largest bounding box area each frame
- ReID gallery is built while following, so the target can be recovered after occlusion
- If ReID search times out, the gallery is cleared and the next biggest person is selected
- Clicking "Clear Target" in the UI returns to auto mode

### ReID search timeout
When a locked target is lost, ReID searches for a configurable duration (`--reid-timeout`, default 20s). If the target is not re-identified within that time, the app returns to auto mode (not idle). The timeout applies both when other persons are visible (ReID compares embeddings each frame) and when no persons are visible (holding position).

### OpenHD follow_id semantics
- `-1` = IDLE (drone holds position)
- `0` = AUTO (follow largest person)
- `N` = LOCKED to person N

## PX4 Offboard Mode

### How it works in this app
By default (no `--takeoff-landing`), the app streams zero setpoints and waits for the pilot to switch to OFFBOARD mode via GCS or RC. The app never commands the mode switch itself. Use `--takeoff-landing` to enable auto arm/takeoff/land.

### Required PX4 Parameters (set via QGroundControl)
- `COM_RC_IN_MODE = 4` — Allow flight without RC transmitter
- `COM_RCL_EXCEPT` bit 2 set — Ignore RC loss in offboard mode
- `COM_OF_LOSS_T` — Offboard signal loss timeout (default ~1 s)
- `COM_OBL_RC_ACT` — Failsafe action on offboard loss

### PX4 Documentation
- Main docs: https://docs.px4.io/main/en/
- Offboard mode: https://docs.px4.io/main/en/flight_modes/offboard.html

## Running

```bash
# Real drone with OpenHD (RPi — starts OpenHD air + drone-follow):
scripts/start_air.sh
# (script invokes: drone-follow --input rpi --openhd-stream \
#                                --connection tcpout://127.0.0.1:5760 --tiles-x 1 --tiles-y 1)

# Manual OpenHD-mode invocation (e.g. with debug UI on the air unit):
drone-follow --input rpi --openhd-stream --ui --no-display \
    --connection tcpout://127.0.0.1:5760 --tiles-x 1 --tiles-y 1

# Dev machine with USB camera + flight controller:
source setup_env.sh
drone-follow --input usb --serial --ui

# Simulation (see Simulation section for full setup):
source setup_env.sh
drone-follow --input udp://0.0.0.0:5600 --takeoff-landing --ui
```

## OpenHD Camera Modes (Air Unit)

`scripts/start_air.sh` runs **Mode A**: drone-follow owns the CSI camera (`--input rpi`), runs Hailo inference, encodes the overlay with x264, and pushes RTP to OpenHD on UDP 5500 (`--openhd-stream`). OpenHD relays that stream over the WFB radio link.

For Mode A to work, OpenHD's primary camera type must be **5** (`X_CAM_TYPE_HAILO_AI`). Any other value (e.g. `31` = IMX219, the OpenHD default after a fresh build) makes OpenHD acquire the CSI camera itself at startup, and drone-follow's Picamera2 then fails with `Device or resource busy`.

Two ways to set it:

- **From QOpenHD (ground station):** Settings → Camera → Primary Camera Type = `5`. QOpenHD pushes the change via MAVLink and OpenHD persists it to the JSON below. Requires a paired radio link.
- **Locally on the air unit:** edit `/usr/local/share/openhd/video/air_camera_generic.json` and set `"primary_camera_type": 5`. `scripts/install_air.sh` does this automatically on a fresh install (Step 7); only needed manually on units that pre-date that patch.

Either way, OpenHD must be fully restarted after the change — the camera handle is opened once at OpenHD startup.

**Mode B** (legacy, not used by `start_air.sh`): OpenHD owns the camera and tees raw NV12 frames to a SHM socket. drone-follow reads from SHM (`--input shm:///tmp/openhd_raw_video`) and does AI only — no encoding, no overlay baked into the radio stream. To enable: keep `primary_camera_type` at the libcamera value matching your sensor (31 = IMX219, 32 = IMX708, etc.) and `sudo touch /boot/openhd/hailo.txt`.

See `OpenHD/HAILO_INTEGRATION.md` for the full architecture, parameter list, and the binary detection payload format.

## Virtual Environment

This repo owns its own venv at `./venv/` (created with `--system-site-packages` so apt-installed Hailo bindings are visible). `drone-follow` is installed as an editable package, and `hailo-apps` is pip-installed from GitHub (the `[hailo]` extra in `pyproject.toml`). Always `source setup_env.sh` before running — it activates `./venv/`, exports `PYTHONPATH`, runs the RPi kernel-compatibility check, and loads `/usr/local/hailo/resources/.env`.

## Development Machine Setup (x86_64)

This repo can also run on an x86_64 development machine instead of the RPi target. Differences from RPi:

- **Camera:** Use `--input usb` instead of `--input rpi` (auto-detects USB webcam).
- **Hailo:** Requires a Hailo-8 PCIe card with `hailort` and `hailo-tappas-core` system deb packages installed.
- **Flight controller:** The Cube Orange+ connects via USB serial at `/dev/ttyACM0`, same as on the RPi.
- **Simulation:** Bundled PX4 SITL + Gazebo Garden (see Simulation section below).

### Installation

Prerequisites:
- Ubuntu 22.04 with Python 3.10+
- HailoRT driver deb installed and device detected (`hailortcli fw-control identify`)
- Node.js / npm (optional, for the web UI)

```bash
# 1. Install HailoRT driver first (download from Hailo Developer Zone):
sudo dpkg -i hailort_<version>_<arch>.deb
sudo reboot
hailortcli fw-control identify  # verify device detected

# 2. Build the repo-owned venv with drone-follow + hailo-apps from GitHub:
./install.sh

# Options:
#   --skip-ui              Skip UI npm install and build
#   --skip-python          Skip Python dependency installation
```

`install.sh` creates `./venv/` (no sudo), installs `drone-follow` as editable, and pulls `hailo-apps` from GitHub via the `[hailo]` extra. Re-run after pulling drone-follow updates.

Verify: `source setup_env.sh && drone-follow --help`

### Running on a dev machine

```bash
source setup_env.sh

# With USB camera + real flight controller over serial:
drone-follow --input usb --serial --ui

# With Gazebo camera + PX4 SITL (see Simulation section):
drone-follow --input udp://0.0.0.0:5600 --takeoff-landing --ui

# With USB camera + PX4 SITL (yaw only — forward commands unsafe with real webcam):
drone-follow --input usb --yaw-only --ui
```

### Simulation (Bundled PX4 SITL)

PX4 SITL + Gazebo Garden runs natively using a bundled PX4-Autopilot git submodule (v1.14.0) at `sim/PX4-Autopilot`. A video bridge pipes the Gazebo camera feed to the Hailo pipeline via UDP.

**Prerequisites:** Gazebo Garden (`gz-garden`), `python3-gz-transport13`, `python3-gz-msgs10`

```bash
# One-time setup (inits submodule + builds PX4 — takes 10-20 min first time):
sim/setup_sim.sh

# Terminal 1 — Start PX4 SITL + Gazebo + video bridge:
sim/start_sim.sh --bridge --world 2_person_world

# Terminal 2 — Run drone-follow:
source setup_env.sh
drone-follow --input udp://0.0.0.0:5600 --takeoff-landing --ui
```

### Remote Simulation (sim on one machine, drone-follow on another)

```bash
# Sim machine — starts PX4, Gazebo, video bridge + MAVLink relay targeting the remote IP:
sim/start_sim.sh --remote <DRONE_APP_IP> --world 2_person_world

# Drone-follow machine:
source setup_env.sh
drone-follow --input udp://0.0.0.0:5600 --takeoff-landing --ui
```

`--remote <IP>` implies `--bridge` and also starts a MAVLink UDP relay (`sim/mavlink_relay.py`) so both video (5600) and MAVLink (14540) reach the remote machine.

**Key ports:**
- `14540/udp` — MAVLink (PX4 MAVSDK API, default `--connection`)
- `5600/udp` — Video feed from Gazebo (via video bridge)

**Bundled worlds** in `sim/worlds/`: `2_person_world`, `2_persons_diagonal`, `random_walk`
Pass `--world NAME` to `start_sim.sh` to load a custom world (uses PX4's native `PX4_GZ_WORLD` env var).

**Simulation configs** in `sim/configs/`: `simulation.json` (yaw-only, safe for SITL), `simulation_follow.json` (full follow with reduced speeds).

**USB camera with sim:** If using `--input usb` instead of the Gazebo camera, always add `--yaw-only` — forward commands based on bbox size are unsafe because the webcam sees the real world, not the sim.

## Networking (Dual-Interface: Home WiFi + Field AP)

The Pi has two WiFi interfaces:
- **wlan0 (built-in RPi WiFi)** — Connects to home/dev WiFi networks
- **wlan1 (TP-Link USB adapter)** — Dedicated AP mode for field ops (5GHz, channel 36, better antenna/range)

A udev rule pins the TP-Link adapter to `wlan1` by MAC address. Both interfaces can operate simultaneously — e.g., SSH via home WiFi (wlan0) while phone connects to drone AP (wlan1).

**Known networks:** Any WiFi saved in NetworkManager. Add new ones with `nmcli device wifi connect <SSID> password <pass>`.

## Boot Service

A systemd service (`drone-follow-boot.service`) auto-starts drone-follow + OpenHD at boot, controlled by a desktop config file.

- **Config:** `~/Desktop/drone-follow.conf` — set `ENABLED=true` or `ENABLED=false`
- **Install:** `sudo scripts/boot/install.sh`
- **Uninstall:** `sudo scripts/boot/uninstall.sh`
- **Flow:** systemd → `drone-follow-boot.sh` → reads config → if enabled, runs `scripts/start_air.sh` as hailo user
