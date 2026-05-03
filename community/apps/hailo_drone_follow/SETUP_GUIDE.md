# Hailo Drone-Follow + OpenHD — Setup Guide

> **See also:**
> [PARAMETERS.md](PARAMETERS.md) — architecture, parameter flow, df_params.json schema
> | [RESOLUTION_CONTROL.md](RESOLUTION_CONTROL.md) — resolution change mechanism
> | [TROUBLESHOOTING.md](TROUBLESHOOTING.md) — common issues & debug commands

---

## Hardware

| Unit   | Board | Extras |
|--------|-------|--------|
| Air    | RPi5  | Hailo8 M.2, RPi Camera Module 3 (IMX708), monitor-mode Wi-Fi adapter |
| Ground | RPi4/5 | Same Wi-Fi adapter model, HDMI display |

Both: Raspberry Pi OS Bookworm 64-bit.

---

## Repositories

| Repo | Branch | Where |
|------|--------|-------|
| [OpenHD](https://github.com/giladnah/OpenHD.git) | `feature/hailo-apps-integration` | Air + Ground |
| [OpenHD-SysUtils](https://github.com/giladnah/OpenHD-SysUtils.git) | `main` | Air + Ground |
| [QOpenHD](https://github.com/giladnah/QOpenHD.git) | `fix/rpi4-hw-decode` | Ground |
| [hailo-drone-follow](git@github.com:guyzigdons-apps/hailo-drone-follow.git) | `feature/openhd-integration-new` | Air |

> **Clone layout:** The OpenHD/QOpenHD repos are cloned **inside the
> drone-follow repo root** (alongside `scripts/`, `drone_follow/`, etc.) — not
> in `$HOME`. They're listed in `.gitignore`. `scripts/install_ground_station.sh`
> handles cloning automatically.

> **Two repo layouts.** drone-follow ships two ways:
> 1. **Standalone clone** of `hailo-drone-follow` at `~/hailo-drone-follow`
>    (the historic layout — paths in this guide use it).
> 2. **In-repo** under `hailo-apps-internal/community/apps/hailo_drone_follow/`
>    (the layout used by recent installs).
>
> Both `install.sh` and `scripts/install_air.sh` resolve `APP_ROOT` from their
> own location, so they work in either layout. If you're on layout (2),
> substitute `~/hailo-apps-internal/community/apps/hailo_drone_follow` for
> `~/hailo-drone-follow` everywhere below — and skip the standalone clone in
> §1 (you already have the code).

---

## Air Unit Setup

### 1. Clone drone-follow (layout 1 only)

Skip if you're using layout 2 (in-repo under `hailo-apps-internal`).

```bash
cd ~
git clone -b feature/openhd-integration-new \
    git@github.com:guyzigdons-apps/hailo-drone-follow.git
```

### 2. Automated install (recommended)

The install is **three scripts in order**:

1. `~/hailo-apps-internal/install.sh` (layout 2 only) — sets up the parent venv
   `venv_hailo_apps` and writes `HAILO_APPS_PATH=…` into
   `/usr/local/hailo/resources/.env`. Both later scripts read this.
2. `<drone-follow>/install.sh` — installs the `drone-follow` package into the
   parent venv, downloads ReID HEFs, builds the UI.
3. `<drone-follow>/scripts/install_air.sh` (sudo) — installs `hailo-all`,
   clones OpenHD + OpenHD-SysUtils into the drone-follow repo root, builds
   OpenHD (with the WiFi driver), deploys `df_params.json`, and configures
   `primary_camera_type` + `/boot/openhd/hailo.txt` to match `--mode`.

```bash
# Layout 1 (standalone clone):
cd ~/hailo-drone-follow
./install.sh
sudo ./scripts/install_air.sh                  # Mode A (default)
# or:                       --mode shm         # Mode B (SHM)
# or:                       --mode shm --camera-type 32   # Mode B + IMX708

# Layout 2 (in-repo under hailo-apps-internal):
cd ~/hailo-apps-internal
./install.sh                                   # parent venv + .env
cd community/apps/hailo_drone_follow
./install.sh                                   # drone-follow into parent venv
sudo ./scripts/install_air.sh [--mode shm [--camera-type 32]]
```

> **Camera mode (`--mode`):**
> - `stream` (default) — Mode A. drone-follow owns the camera, encodes the
>   overlay, and pushes RTP to OpenHD. Sets `primary_camera_type=5`
>   (HAILO_AI) and removes `/boot/openhd/hailo.txt`. See [Camera Modes](#camera-modes).
> - `shm` — Mode B. OpenHD owns the camera and tees raw NV12 to
>   `/tmp/openhd_raw_video`; drone-follow does AI only. Sets
>   `primary_camera_type` to the libcamera value (`--camera-type`, default
>   `31` = IMX219; pass `32` for IMX708) and creates `/boot/openhd/hailo.txt`.
>
> Pass the same `--mode` to `scripts/start_air.sh` afterwards.

> **Encryption key (`txrx.key`):** The WFB radio link requires the **same** key
> on air and ground.
> - **First unit being set up?** Pass `--generate-key`, then `scp` the key from
>   `/usr/local/share/openhd/txrx.key` to the other unit.
> - **Ground was set up first?** Copy the existing key first
>   (`sudo scp <ground>:/usr/local/share/openhd/txrx.key /tmp/txrx.key &&
>   sudo install -m 644 /tmp/txrx.key /usr/local/share/openhd/txrx.key`),
>   then run the install script normally — it will keep the existing key.

> **Reboot after fresh `hailo-all`:** If `hailortcli fw-control identify` fails
> after install, reboot once and re-run `scripts/start_air.sh`.

### 3. Manual install (step-by-step)

If you'd rather drive each step yourself:

**Install Hailo prerequisites:**
```bash
sudo apt update
sudo apt install -y dkms hailo-all
hailortcli fw-control identify
sudo chmod 644 /usr/local/hailo/resources/json/*.json
```

**Clone OpenHD into the drone-follow repo root:**
```bash
cd ~/hailo-drone-follow
git clone --recurse-submodules -b feature/hailo-apps-integration \
    https://github.com/giladnah/OpenHD.git
git clone -b main https://github.com/giladnah/OpenHD-SysUtils.git
```

**Build OpenHD:**
```bash
cd ~/hailo-drone-follow/OpenHD && sudo ./build_native.sh all
```

> **Important — WiFi driver & reboot:** The `all` target builds the WiFi
> driver (rtl88x2bu via DKMS). A kernel update or `apt upgrade` on the next
> reboot can overwrite the driver module. If Wi-Fi stops working after a
> reboot, rebuild **only** the driver:
> ```bash
> cd ~/hailo-drone-follow/OpenHD && sudo ./build_native.sh driver
> sudo reboot
> ```

Rebuilding after code changes only:
```bash
cd ~/hailo-drone-follow/OpenHD/OpenHD
sudo cmake --build build_release -j$(nproc)
sudo cp build_release/openhd /usr/local/bin/openhd
```

**Install drone-follow:**
```bash
cd ~/hailo-drone-follow && ./install.sh
```

**Deploy df_params.json & encryption key** (see the key callout in §2 — same
options apply: copy from ground unit, or generate fresh and `scp` to ground):
```bash
sudo mkdir -p /usr/local/share/openhd
sudo cp ~/hailo-drone-follow/df_params.json /usr/local/share/openhd/df_params.json
```

### 4. Enable SHM passthrough (for SHM mode)

See the [Camera Modes](#camera-modes) section below for choosing and
configuring Mode A or Mode B.

---

## Ground Unit Setup

### 1. Install system prerequisites

```bash
sudo apt install -y dkms
```

### 2. Clone

Clone the OpenHD repos into the drone-follow repo root (matches what
`scripts/install_ground_station.sh` does automatically):

```bash
cd ~/hailo-drone-follow
git clone --recurse-submodules -b feature/hailo-apps-integration \
    https://github.com/giladnah/OpenHD.git
git clone -b main https://github.com/giladnah/OpenHD-SysUtils.git
git clone -b fix/rpi4-hw-decode https://github.com/giladnah/QOpenHD.git
```

### 3. Build OpenHD

```bash
cd ~/hailo-drone-follow/OpenHD && sudo ./build_native.sh all
```

> **Important — WiFi driver & reboot:** Same caveat as the air unit.
> If Wi-Fi breaks after a reboot, rebuild the driver alone:
> ```bash
> cd ~/hailo-drone-follow/OpenHD && sudo ./build_native.sh driver
> sudo reboot
> ```

### 4. Build QOpenHD

```bash
cd ~/hailo-drone-follow/qopenHD && sudo ./install_build_dep.sh rpi
mkdir -p build/release && cd build/release
qmake ../.. && make -j$(nproc)
```

Binary: `~/hailo-drone-follow/qopenHD/build/release/QOpenHD`

### 5. Deploy df_params.json & encryption key

```bash
sudo mkdir -p /usr/local/share/openhd
sudo cp ~/path/to/df_params.json /usr/local/share/openhd/df_params.json
scp pi@<air-ip>:/usr/local/share/openhd/txrx.key /tmp/txrx.key
sudo cp /tmp/txrx.key /usr/local/share/openhd/txrx.key
```

### 6. CLI-only mode (recommended)

```bash
sudo systemctl set-default multi-user.target && sudo reboot
```

---

## x86_64 Ground Station (Laptop / Desktop)

An x86_64 Ubuntu machine can run the full ground station stack. No Hailo
hardware is needed on the ground side — video is decoded in software via
FFmpeg/libavcodec. The build system auto-detects x86_64 and configures
everything accordingly (SSSE3 FEC, `LinuxBuild` Qt config, `__desktoplinux__`
define).

### Prerequisites

- Ubuntu 22.04+ (64-bit)
- Monitor-mode USB WiFi adapter (same model as the air unit — e.g. rtl88x2bu)
- System packages:
  ```bash
  sudo apt install -y dkms iw
  ```

### 1. Clone

Same layout as the RPi ground unit — clone into the drone-follow repo root
(skip this step if you plan to run the automated installer in §2; it clones
on its own). Use `--recurse-submodules` for QOpenHD on x86_64:
```bash
cd ~/hailo-drone-follow
git clone --recurse-submodules -b feature/hailo-apps-integration \
    https://github.com/giladnah/OpenHD.git
git clone -b main https://github.com/giladnah/OpenHD-SysUtils.git
git clone --recurse-submodules -b fix/rpi4-hw-decode \
    https://github.com/giladnah/QOpenHD.git
```

> If you forgot `--recurse-submodules` on qopenHD:
> ```bash
> cd ~/hailo-drone-follow/qopenHD && git submodule update --init --recursive
> ```

### 2. Automated install (recommended)

A bundled script in this repo handles cloning, deps, builds, and config deployment in one step.
It auto-detects the platform (x86_64 / RPi5 / RPi4), or you can override with `--platform`:
```bash
cd ~/hailo-drone-follow
sudo ./scripts/install_ground_station.sh
# Or explicitly: sudo ./scripts/install_ground_station.sh --platform ubuntu-x86
```

> **Encryption key (`txrx.key`):** The WFB radio link requires the **same** key
> on air and ground. The script will not generate one silently:
> - **First unit being set up?** Pass `--generate-key`, then `scp` the file
>   from `/usr/local/share/openhd/txrx.key` to the other unit.
> - **Second unit?** Copy the existing key first
>   (`sudo scp <first-unit>:/usr/local/share/openhd/txrx.key /tmp/txrx.key &&
>   sudo install -m 644 /tmp/txrx.key /usr/local/share/openhd/txrx.key`),
>   then run the install script normally — it will keep the existing key.

> **Radio channel (`wb_frequency`):** The installer normalises both units to
> **5180 MHz (channel 36, UNII-1)** — the only 5 GHz channel that's allowed in
> every regulatory domain (including country 00) and is non-DFS. Override per
> install with `WB_DEFAULT_FREQUENCY=<MHz> sudo ./scripts/install_ground_station.sh`.
> The persistent regulatory-domain config files (`/etc/default/crda`,
> `/etc/modprobe.d/{cfg80211,openhd}-regdomain.conf`) are written automatically.

### 3. Manual install (step-by-step)

If you prefer to run each step yourself:

**Install OpenHD dependencies + build:**
```bash
cd ~/hailo-drone-follow/OpenHD
sudo ./install_build_dep.sh ubuntu-x86
sudo ./build_native.sh build        # builds SysUtils + OpenHD, installs to /usr/local/bin/
```

> **Note:** Use `build` to compile OpenHD only. You also need the WiFi driver
> for the monitor-mode USB adapter:
> ```bash
> sudo ./build_native.sh driver
> sudo reboot
> ```
> Or run `sudo ./build_native.sh all` to do deps + build + driver in one step.

**Install QOpenHD dependencies + build:**
```bash
cd ~/hailo-drone-follow/qopenHD
sudo ./install_build_dep.sh ubuntu-x86

# Compile Qt translation files (required before build):
lrelease translations/*.ts
cp translations/*.qm qml/

mkdir -p build/release && cd build/release
qmake ../.. && make -j$(nproc)
```

> **Note:** Older `install_build_dep.sh` scripts hardcoded the noble/trixie
> `libqt5*5t64` package names, which fail on jammy/bookworm. The patched
> version in `giladnah/QOpenHD` (`fix/rpi4-hw-decode`) detects the Ubuntu /
> Debian codename and rewrites to the correct names automatically.

Binary location: `~/hailo-drone-follow/qopenHD/build/release/release/QOpenHD`
(note the double `release` — qmake puts the output one level deeper on Linux).

**Deploy config files:**
```bash
sudo mkdir -p /usr/local/share/openhd
sudo cp ~/hailo-drone-follow/df_params.json /usr/local/share/openhd/df_params.json

# Copy encryption key from air unit (must match):
scp pi@<air-ip>:/usr/local/share/openhd/txrx.key /tmp/txrx.key
sudo cp /tmp/txrx.key /usr/local/share/openhd/txrx.key
```

### 4. Running

Use the bundled start script (launches both OpenHD ground + QOpenHD):
```bash
./scripts/start_ground.sh
```

Or manually:
```bash
# Terminal 1 — OpenHD ground:
sudo /usr/local/bin/openhd --ground

# Terminal 2 — QOpenHD (Wayland):
WAYLAND_DISPLAY=wayland-0 XDG_RUNTIME_DIR=/run/user/1000 \
    ~/hailo-drone-follow/qopenHD/build/release/release/QOpenHD -platform wayland

# Or under X11:
~/hailo-drone-follow/qopenHD/build/release/release/QOpenHD
```

> **Differences from RPi ground:**
> - Video decoding uses software libavcodec (FFmpeg) instead of RPi MMAL hardware decoder
> - No EGLFS — use Wayland or X11 platform
> - Reboot required after WiFi driver install (`build_native.sh driver`)

### NetworkManager and OpenHD

OpenHD uses the USB WiFi adapter in monitor mode. When OpenHD exits,
NetworkManager detects the adapter is available and tries to reconfigure it,
triggering a credentials popup. To prevent this, tell NetworkManager to
ignore USB WiFi adapters (`wlx*` — only matches USB devices, not built-in WiFi):

```bash
sudo tee /etc/NetworkManager/conf.d/openhd-unmanaged.conf <<'EOF'
[keyfile]
unmanaged-devices=interface-name:wlx*
EOF
sudo systemctl restart NetworkManager
```

---

## Camera Modes

There are two integration modes; both are supported by `scripts/install_air.sh` and `scripts/start_air.sh` via `--mode <stream|shm>`. Both use the Hailo8 for AI detection. In both modes, drone-follow's controller parameters are reachable from QOpenHD via the OpenHD parameter bridge (UDP 5510/5511) and from the local web UI (`--ui`, port 5001). Both surfaces edit the same in-process `ControllerConfig` — see [PARAMETERS.md](PARAMETERS.md) for the bridge protocol.

| | Mode A — `--mode stream` | Mode B — `--mode shm` |
|---|---|---|
| Camera owner | drone-follow | OpenHD |
| `primary_camera_type` | `5` (HAILO_AI) | libcamera value (`31`=IMX219, `32`=IMX708) |
| `/boot/openhd/hailo.txt` | absent | present |
| Overlay in WFB stream | ✅ burned in | ❌ (rendered by QOpenHD) |
| drone-follow input | `--input rpi --openhd-stream` | `--input shm:///tmp/openhd_raw_video --no-display` |

Pick one and pass the same `--mode` to both `install_air.sh` (configures camera type + flag file) and `start_air.sh` (selects the drone-follow CLI args). Today `start_air.sh` defaults to `stream`.

### Mode A — `--mode stream` (Camera Type 5, `X_CAM_TYPE_HAILO_AI`)

drone-follow **owns the camera** — it captures directly from the RPi camera,
runs Hailo inference, draws overlay, encodes to H.264, and streams RTP to
OpenHD which treats it as an external video source.

**Manual command** (or just `scripts/start_air.sh`):
```bash
drone-follow --input rpi --openhd-stream --horizontal-mirror \
    --connection tcpout://127.0.0.1:5760
```
> **Note:** `--horizontal-mirror` is only for selfie mode (front-facing camera).
> Omit for rear-facing.

**Configuration** (handled automatically by `install_air.sh --mode stream`):
1. `primary_camera_type=5` in `/usr/local/share/openhd/video/air_camera_generic.json`
   (or via QOpenHD: Settings → Camera → Primary Camera Type = 5).
2. `/boot/openhd/hailo.txt` must NOT exist.
3. Resolution is controlled by drone-follow CLI arguments (`--width`, `--height`).

### Mode B — `--mode shm` (Shared Memory, `hailo.txt` flag)

OpenHD **owns the camera** — it captures from libcamera as normal, encodes
for WFB transmission, and also tees raw NV12 frames to a shared-memory socket.
drone-follow reads from SHM and performs AI inference only (no encoding).

**Manual command** (or `scripts/start_air.sh --mode shm`):
```bash
drone-follow --input shm:///tmp/openhd_raw_video --no-display \
    --connection tcpout://127.0.0.1:5760
```

**Configuration** (handled automatically by
`install_air.sh --mode shm [--camera-type 32]`):
1. `primary_camera_type` set to the libcamera value matching your sensor:
   `31` = IMX219, `32` = IMX708.
2. `/boot/openhd/hailo.txt` present.
3. Resolution changes via QOpenHD work seamlessly (auto-detected via SHM metadata).

---

## Running the System

### Step 1 — Air: Start OpenHD

```bash
sudo /usr/local/bin/openhd --air
```

### Step 2 — Air: Start drone-follow

Easiest is `scripts/start_air.sh` (which also starts OpenHD — skip Step 1 if
you use it):

```bash
scripts/start_air.sh             # Mode A (stream — default)
scripts/start_air.sh --mode shm  # Mode B (SHM)
```

Manual invocation:

```bash
# Layout 1: cd ~/hailo-drone-follow && source venv/bin/activate
# Layout 2: source ~/hailo-apps-internal/setup_env.sh

# Mode A (Camera Type 5):
drone-follow --input rpi --openhd-stream --horizontal-mirror \
    --connection tcpout://127.0.0.1:5760 \
    --tiles-x 1 --tiles-y 1

# Mode B (SHM):
drone-follow --input shm:///tmp/openhd_raw_video --no-display \
    --connection tcpout://127.0.0.1:5760 \
    --tiles-x 1 --tiles-y 1
```

> Start drone-follow **after** OpenHD.

> **Local debug UI alongside OpenHD:** add `--ui` to either invocation to expose the air-side web UI on port 5001 — useful when SSH'd into the drone for bench testing. Web UI sliders edit the same `ControllerConfig` as QOpenHD's sliders, so changes are visible in both places. See [PARAMETERS.md](PARAMETERS.md) for the bridge protocol.

### Step 3 — Ground: Start OpenHD

```bash
sudo /usr/local/bin/openhd --ground
```

### Step 4 — Ground: Start QOpenHD

**CLI-only (EGLFS)**:
```bash
cd ~/hailo-drone-follow/qopenHD
sudo env -u DISPLAY -u WAYLAND_DISPLAY \
    QT_QPA_PLATFORM=eglfs QT_QPA_EGLFS_KMS_ATOMIC=1 \
    QT_QPA_EGLFS_KMS_CONFIG=$HOME/hailo-drone-follow/qopenHD/rpi_qt_eglfs_kms_config.json \
    XDG_RUNTIME_DIR=/tmp/runtime-root \
    ./build/release/QOpenHD_hailo_dynamic -platform eglfs
```

**With desktop (Wayland)**:
```bash
WAYLAND_DISPLAY=wayland-0 XDG_RUNTIME_DIR=/run/user/1000 \
    ./build/release/QOpenHD_hailo_dynamic -platform wayland
```

---

## Recording

drone-follow supports two complementary capture mechanisms — one on the air unit, one on the ground unit. Pick based on what you care about:

| Aspect | Air-side (`--record`) | Ground-side (QOpenHD) |
|---|---|---|
| Stored on | Drone (RPi SD) | Ground unit (`~/Videos/`) |
| Source | Post-overlay frames at the camera | Raw H.264 demuxed from WFB tee |
| Compression artifacts | Single encode at the source — **lower artifacts** | Round-trip through WFB radio link |
| Survives RF dropouts | ✅ | ❌ (loses frames during link loss) |
| Requires offline embedding | No — bboxes already burned in | Yes — `embed_recording.py` composites `.jsonl` + `.osd` |
| Triggered by | `--record` CLI flag, web UI Record button | QOpenHD Ground Recording panel |

For archival captures, prefer **air-side** — it's higher quality and link-independent. For in-the-field review with selectable overlays, **ground-side** is more convenient.

### Air-side recording

Add `--record` to either Mode A or Mode B startup. The video is encoded by an ffmpeg subprocess (libx264, ultrafast preset, 5 Mbps) writing to `~/hailo-drone-follow/drone_follow/recordings/rec_<timestamp>.mp4`. Recording auto-starts ~1 s after the GStreamer pipeline reaches PLAYING; it can also be toggled at any time from the web UI's Record button (with `--ui`). On Ctrl-C / EOS / shutdown the file is finalised cleanly.

```bash
# Mode A + air-side recording:
drone-follow --input rpi --openhd-stream --record \
    --connection tcpout://127.0.0.1:5760 \
    --tiles-x 1 --tiles-y 1
```

> **QOpenHD remote trigger:** in `--openhd-stream` mode the recording branch is built into the pipeline automatically, so QOpenHD's Record toggle (param `DF_RECORDING`) can start/stop air-side capture mid-flight even without `--record` at launch. `--record` is only required when you want recording to **auto-start** as soon as the pipeline reaches PLAYING. The OpenHD C++ side needs no recompile — `hailo_follow_bridge.cpp` is fully data-driven from `df_params.json`. Just redeploy the JSON to `/usr/local/share/openhd/` on both units and restart OpenHD (air) + QOpenHD (ground) + drone-follow.

### Ground-side recording (QOpenHD) & offline embedding

QOpenHD records the live video stream on the ground unit along with detection metadata and HUD overlay data. Embedding (compositing BBs and HUD onto the video) is done offline with a Python script.

#### Recording (in QOpenHD)

Open the **Ground Recording** sidebar panel (Panel 9). Controls:

- **Start/Stop Recording** — tees the raw H.264 stream to file (zero CPU overhead)
- **Save HUD overlay** toggle — when ON, captures HUD graphics as sparse RGBA
  tiles alongside the video (`.osd` file)

On stop, the raw `.h264` is automatically muxed to `.mp4` and the raw file is
deleted. Recordings are saved to `~/Videos/`:

| File | Contents |
|------|----------|
| `ground_YYYYMMDD_HHMMSS.mp4` | Raw video (H.264 in MP4 container) |
| `ground_YYYYMMDD_HHMMSS.jsonl` | Detection bounding boxes (one JSON line per frame) |
| `ground_YYYYMMDD_HHMMSS.osd` | HUD overlay (OSD3 binary — sparse RGBA tiles) |

#### Embedding (offline Python script)

The embed tool composites detections and/or HUD overlay onto the recorded
video. It runs on the Pi (when OpenHD is off) or on any machine with
`ffmpeg`, `numpy`, and `Pillow`.

**Location:** `~/hailo-drone-follow/qopenHD/tools/embed_recording.py`

**Install dependencies** (if not already available):
```bash
pip install numpy Pillow
```

**Basic usage:**
```bash
# Embed latest recording — detections + HUD at 1080p (defaults):
python3 ~/hailo-drone-follow/qopenHD/tools/embed_recording.py ~/Videos/ground_20260324_165522.mp4

# Detections only, keep original resolution:
python3 ~/hailo-drone-follow/qopenHD/tools/embed_recording.py ~/Videos/ground_20260324_165522.mp4 \
    --no-hud -r original

# HUD only, no bounding boxes:
python3 ~/hailo-drone-follow/qopenHD/tools/embed_recording.py ~/Videos/ground_20260324_165522.mp4 \
    --no-detections

# Process all recordings in a directory:
python3 ~/hailo-drone-follow/qopenHD/tools/embed_recording.py ~/Videos/ --all
```

**CLI flags:**

| Flag | Default | Description |
|------|---------|-------------|
| `--detections` / `--no-detections` | on | Include detection bounding boxes |
| `--hud` / `--no-hud` | on | Include HUD overlay |
| `-r WxH` | `1920x1080` | Output resolution (`original` to keep source res) |
| `--crf N` | 20 | H.264 quality (lower = better, 0–51) |
| `--preset` | fast | x264 speed/quality tradeoff |
| `--suffix` | `_embed` | Output filename suffix |
| `--all` | off | Process all recordings in directory |

**To use on another machine**, copy the recording files (`.mp4`, `.jsonl`,
`.osd`) and the script to the host — no QOpenHD build required.

---

## Rebuilding After Code Changes

| Component | Command |
|-----------|---------|
| OpenHD (C++) | `cd ~/hailo-drone-follow/OpenHD/OpenHD && sudo cmake --build build_release -j$(nproc) && sudo cp build_release/openhd /usr/local/bin/openhd` |
| QOpenHD (C++/QML) | `cd ~/hailo-drone-follow/qopenHD/build/release && make -j$(nproc)` |
| drone-follow (Python) | No build — just restart the process |
| df_params.json | `sudo cp ~/hailo-drone-follow/df_params.json /usr/local/share/openhd/df_params.json` — redeploy on **both** air and ground units after any parameter changes |
