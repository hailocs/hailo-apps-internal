# Troubleshooting Guide

Quick triage runbook for the common ways drone-follow + OpenHD fail.
Paths assume the canonical layout: hailo-apps-infra cloned anywhere, drone-follow at `<hailo-apps-infra>/community/apps/hailo_drone_follow/`. On the Pi we use `~/hailo-app` for `<hailo-apps-infra>`; on the laptop `~/tappas_apps/repos/hailo-apps-infra`. The runtime scripts resolve everything via `$HAILO_APPS_PATH` (sourced from `/usr/local/hailo/resources/.env`), so the absolute paths don't matter as long as that env is set.

---

## Quick health check

Run on each machine after install:

```bash
# 1. Parent venv + drone-follow installed?
cd <hailo-apps-infra>
source setup_env.sh
which drone-follow                           # → <root>/venv_hailo_apps/bin/drone-follow
echo "HAILO_APPS_PATH=$HAILO_APPS_PATH"      # → matches the dir you're sourcing from

# 2. OpenHD artefacts present?
ls /usr/local/bin/openhd /usr/local/bin/openhd_sys_utils
ls /usr/local/share/openhd/txrx.key /usr/local/share/openhd/df_params.json

# 3. WiFi driver loaded?
lsmod | grep 88x2bu_ohd                       # must show one entry
iw dev | grep -i type | grep -c monitor       # must be ≥ 1 (radio in monitor mode)

# 4. Pi-only — OpenHD knows it's Mode A?
sudo grep primary_camera_type /usr/local/share/openhd/video/air_camera_generic.json
# → "primary_camera_type": 5
```

Any line that prints nothing or a different value is the lead in your investigation.

---

## Radio link not coming up

This is the most common failure on first end-to-end test. Symptoms in QOpenHD: "Restarting camera…", no video, no MAVLink heartbeats, link-status indicator red/yellow.

**Diagnose top-down — physical → driver → frequency → key → camera mode.**

### A. Physical & driver

```bash
# Both machines — is the WFB USB dongle even visible?
lsusb | grep -iE 'realtek|rtl88|2604:0d29'    # RTL8812BU should show

# Both machines — is the OpenHD driver module loaded?
lsmod | grep 88x2bu_ohd
# If not, depmod + modprobe + replug:
sudo depmod -a && sudo modprobe 88x2bu_ohd
# Or just unplug/replug the USB dongle.
```

If the module isn't there at all (no `.ko` file under `/lib/modules/$(uname -r)`), the driver build silently failed during `install_air.sh` / `install_ground_station.sh`. On x86 the symptom is `gcc-12: error: unrecognized argument in option '-mabi=apcs-gnu'` during the rtl88x2bu build — that means OpenHD's `build_native.sh` cloned the wrong rtl88x2bu branch (the ARM-default one) onto an x86 host. Reinstall after pulling the latest OpenHD branch (`2.6.4-hailo` ≥ `e8f6f7da`) which uses `master-hailo` for RPi and `x86-hailo` for x86.

### B. Regulatory domain (5 GHz only works if the country code allows it)

```bash
# Both machines:
cat /etc/default/crda                                          # → REGDOMAIN=US
cat /etc/modprobe.d/cfg80211-regdomain.conf                    # → ieee80211_regdom=US
cat /etc/modprobe.d/openhd-regdomain.conf                      # → rtw_country_code=US
iw reg get | head -3                                           # → country US
```

Country `00` (world) disables 5 GHz channels OpenHD needs. The install scripts deploy these configs; if they're missing, run `sudo modprobe -r 88x2bu_ohd && sudo modprobe 88x2bu_ohd` after fixing them — module-init time is when the country gets applied.

### C. Frequency mismatch (air ≠ ground = silent failure)

```bash
# Both machines:
sudo cat /usr/local/share/openhd/interface/wifibroadcast_settings.json | grep wb_frequency
# Both must show the same value, default 5180 (channel 36, UNII-1, non-DFS).
```

If they differ, fix the wrong one and restart OpenHD on that side. `5180` is the safest default — non-DFS, allowed in every regdomain including `00`.

### D. Encryption key mismatch (air ≠ ground = silent failure)

```bash
# Pi:
sudo md5sum /usr/local/share/openhd/txrx.key
# Laptop:
sudo md5sum /usr/local/share/openhd/txrx.key
```

The two MD5s **must be identical**. If they're not:

```bash
# On the laptop — copy the Pi's key:
scp rpi_home_drone:/usr/local/share/openhd/txrx.key /tmp/txrx.key
sudo install -m 644 /tmp/txrx.key /usr/local/share/openhd/txrx.key
rm /tmp/txrx.key
```

If neither machine has the file: install it on ONE side with `sudo ./scripts/install_air.sh --generate-key` (or `install_ground_station.sh --generate-key`), then `scp` it to the other. **Never use `--generate-key` on both** — they'll generate different random keys and the link will silently fail.

### E. Camera mode (Mode A) on the Pi

If A–D are all good but you still get "Restarting camera due to no frame after 10 seconds" in QOpenHD:

```bash
# Pi:
sudo cat /usr/local/share/openhd/video/air_camera_generic.json
```

**`primary_camera_type` must be `5`** (HAILO_AI). If it's `31` (IMX219) or anything else, OpenHD is grabbing the camera itself and never receives the external RTP stream from drone-follow → the "restarting camera" loop. Fix:

```bash
sudo python3 -c '
import json, pathlib
p = pathlib.Path("/usr/local/share/openhd/video/air_camera_generic.json")
d = json.loads(p.read_text())
d["primary_camera_type"] = 5
p.write_text(json.dumps(d, indent=4) + "\n")
'
# Then restart drone-follow + OpenHD:
sudo pkill -KILL -f 'start_air.sh|openhd|drone-follow|Hailo Tiling|mavsdk_server'
cd ~/hailo-app/community/apps/hailo_drone_follow && bash scripts/start_air.sh
# Look for "Using external camera type (HAILO_AI)" in the log.
```

If `air_camera_generic.json` doesn't exist at all and you're on a fresh install, your `install_air.sh` is older than `02800859` (which pre-seeds the full schema). Pull and reinstall, OR pre-seed manually:

```bash
sudo mkdir -p /usr/local/share/openhd/video
sudo tee /usr/local/share/openhd/video/air_camera_generic.json <<'JSON'
{
    "dualcam_primary_video_allocated_bandwidth_perc": 60,
    "enable_audio": 1,
    "primary_camera_type": 5,
    "secondary_camera_type": 255,
    "switch_primary_and_secondary": false
}
JSON
```

### F. Boot-service race

If `~/Desktop/drone-follow.conf` has `ENABLED=true`, the systemd `drone-follow-boot.service` may be auto-launching `start_air.sh` on every boot — and it'll fight any manual run for the camera. While debugging, set `ENABLED=false` and either reboot or `sudo systemctl stop drone-follow-boot.service`.

---

## Camera grabs by another process

### `Failed to acquire camera: Device or resource busy` (drone-follow side)

OpenHD or a stale process owns `/dev/media0`. Diagnose:

```bash
# Pi:
sudo fuser /dev/video0 /dev/media0 2>&1
sudo lsof /dev/media0 2>&1 | head
ps -ef | grep -iE 'openhd|drone-follow|Hailo Tiling|libcamera' | grep -v grep
```

If OpenHD is holding the camera and drone-follow needs it, `primary_camera_type` is likely wrong (see [Radio link / E. Camera mode](#e-camera-mode-mode-a-on-the-pi)).

### `Pipeline handler in use by another process` (OpenHD side, harmless)

This is OpenHD trying to open the camera that drone-follow already correctly owns in Mode A. The error appears in the log but Mode A continues to work — OpenHD then waits for the external RTP stream from drone-follow's `--openhd-stream` instead. Ignore unless paired with "Restarting camera" symptoms.

---

## Stale processes / port already in use

`drone-follow`'s GStreamer subprocess **renames itself** to `Hailo Tiling App` (Linux truncates the comm to 15 chars). `pkill -f drone-follow` doesn't match it, so it survives a "kill" and keeps `/dev/video0`, port 8080, etc. busy.

```bash
# Find leftover processes after a crash:
pgrep -fa "Hailo Tiling|drone-follow|mavsdk_server"
sudo ss -tlnp | grep -E ':5001|:8080|:5510|:14540'

# Nuke them all:
sudo pkill -KILL -f "start_air.sh|openhd|drone-follow|Hailo Tiling|mavsdk_server"

# If a stale mavsdk_server is still listed:
sudo kill -KILL <pid>   # mavsdk_server doesn't trap signals well
```

`mavsdk_server` zombies (`<defunct>` in `ps`) without an explicit parent are harmless — they're waiting for their original shell to reap them and consume zero resources.

---

## Install gotchas

### `apt-get upgrade` hangs forever

`install_build_dep.sh` (called by `install_air.sh` / `install_ground_station.sh`) runs `apt-get upgrade`, which can re-trigger postinst on any pending package on the host (we hit this with `code-insiders.postinst` waiting for "Configure Microsoft apt repository?" → 52-minute hang). Both install scripts now `export DEBIAN_FRONTEND=noninteractive` to default-decline. If you've forked them or are on an older revision:

```bash
# Kill the stuck install:
sudo pkill -KILL -f 'install_air|install_ground_station|apt-get|dpkg'
sudo dpkg --configure -a --force-confdef --force-confold

# Re-run with the env var:
sudo DEBIAN_FRONTEND=noninteractive ./scripts/install_air.sh
```

### Build fails: `unrecognized argument in option '-mabi=apcs-gnu'`

The rtl88x2bu driver Makefile is being built with the wrong platform default. ARM flags ended up in an x86 build (or vice versa). Pull the latest `OpenHD#2.6.4-hailo` (≥ `e8f6f7da`) which selects `master-hailo` (RPi default) vs `x86-hailo` (I386_PC default) per `$PLATFORM`, then re-run install.

### `HAILO_APPS_PATH not resolvable`

The runtime scripts (`setup_env.sh` shim, `install.sh`, `start_air.sh`, etc.) need `HAILO_APPS_PATH` either in the env or in `/usr/local/hailo/resources/.env`. The parent installer writes it; verify:

```bash
grep -i HAILO_APPS_PATH /usr/local/hailo/resources/.env
# → hailo_apps_path=<absolute path to your hailo-apps-infra checkout>
```

If it points at a stale path (e.g. an old hailo-drone-follow venv site-packages), the parent `install.sh` wasn't re-run after re-cloning. Fix:

```bash
sudo sed -i 's|^hailo_apps_path=.*|hailo_apps_path=<correct/absolute/path>|' /usr/local/hailo/resources/.env
```

Or simpler: `sudo <hailo-apps-infra>/install.sh` again (idempotent).

### `pytest: command not found` after install

Pytest is dev-only and not in the parent `pyproject.toml`'s default deps. Install it once into the venv:

```bash
source <hailo-apps-infra>/setup_env.sh
pip install pytest
pytest community/apps/hailo_drone_follow/drone_follow/tests/
```

---

## Running drone-follow standalone for camera/pipeline debugging

If you suspect the issue is on drone-follow's side (not OpenHD) and want to bypass the radio link entirely:

```bash
ssh rpi_home_drone   # or work locally
cd ~/hailo-app
source setup_env.sh
# Pi (CSI camera) with X11 display on the attached monitor:
DISPLAY=:0 drone-follow --input rpi --connection tcpout://127.0.0.1:5760 --tiles-x 2 --tiles-y 2
# x86 dev machine with USB webcam:
drone-follow --input usb --yaw-only --ui --no-display
# Then http://localhost:5001/ in a browser for the web UI.
```

If the standalone run shows live overlays + tracking but `start_air.sh` doesn't, the bug is in OpenHD or in the air↔ground integration, not in the pipeline. Use this to bisect.

---

## QOpenHD-specific issues

### Resolution menu empty or wrong

The resolution list is compiled into the QOpenHD binary. After updating QOpenHD, rebuild:

```bash
cd <hailo-apps-infra>/community/apps/hailo_drone_follow/qopenHD
sudo systemctl stop qopenhd 2>/dev/null
git pull --ff-only
cd build/release && qmake ../.. && make -j$(nproc)
sudo install -m755 release/QOpenHD /usr/local/bin/QOpenHD
```

### df_params (DF_KP_YAW etc.) not appearing

```bash
# Verify file is deployed to BOTH machines:
ls /usr/local/share/openhd/df_params.json
md5sum /usr/local/share/openhd/df_params.json   # should match the repo's df_params.json
```

If missing, copy from the repo:

```bash
sudo install -m644 community/apps/hailo_drone_follow/df_params.json /usr/local/share/openhd/df_params.json
```

QOpenHD reads it at startup — restart QOpenHD after copying.

---

## Hailo / detection issues

### No detections at all

```bash
# Hailo device visible?
hailortcli fw-control identify
# HEFs present?
ls /usr/local/hailo/resources/models/hailo8/repvgg_a0_person_reid_512.hef
ls /usr/local/hailo/resources/models/hailo8/osnet_x1_0.hef
ls /usr/local/hailo/resources/models/hailo8/hailo_yolov8n_4_classes_vga.hef
# Hailo busy?
sudo lsof /dev/hailo0 2>&1 | head
```

If a HEF is missing, the per-app `install.sh` skipped or failed the wget step. Re-run with `./install.sh --skip-python --skip-ui` (HEFs only).

### Detection runs but bbox tracker keeps switching IDs

ReID gallery may not be building. Check `--reid-timeout` (default 20s) — too short means the gallery is cleared before re-acquisition. See `PARAMETERS.md`.

---

## Useful commands

```bash
# Watch air-side log live:
ssh rpi_home_drone 'tail -f /tmp/start_air.log'

# Monitor OpenHD radio stats (air-side):
ssh rpi_home_drone 'sudo journalctl -u openhd -f'

# Quick pipeline restart on Pi (without restarting OpenHD):
ssh rpi_home_drone "sudo pkill -KILL -f 'Hailo Tiling|drone-follow' && sleep 1 && cd ~/hailo-app && source setup_env.sh && DISPLAY=:0 nohup drone-follow --input rpi --openhd-stream --connection tcpout://127.0.0.1:5760 --tiles-x 2 --tiles-y 2 > /tmp/df.log 2>&1 < /dev/null &"

# Tear-down on Pi:
ssh rpi_home_drone "sudo pkill -KILL -f 'start_air.sh|openhd|drone-follow|Hailo Tiling|mavsdk_server'"
```

---

## Log locations

| Component | Log |
|-----------|-----|
| `start_air.sh` (Pi) | `/tmp/start_air.log` |
| OpenHD systemd unit | `journalctl -u openhd` (only if started via systemd, not `start_air.sh`) |
| QOpenHD systemd unit | `journalctl -u qopenhd` |
| drone-follow (foreground) | stdout; also `/tmp/openhd_bridge.log` if openhd-stream enabled |
| Boot-service launcher | `journalctl -u drone-follow-boot.service` |
| HailoRT | `~/hailort.log`, `~/pyhailort.log` (in user's home) |
| Camera config | `/usr/local/share/openhd/video/air_camera_generic.json` |
| Radio config | `/usr/local/share/openhd/interface/wifibroadcast_settings.json` |
| .env | `/usr/local/hailo/resources/.env` |

---

## Last-resort: clean reinstall

If you've fought the install too long and want to start fresh without nuking HailoRT/hailo-apps:

```bash
cd <hailo-apps-infra>/community/apps/hailo_drone_follow
sudo ./scripts/uninstall_air.sh                # Pi
# OR
sudo ./scripts/uninstall_ground_station.sh     # laptop

# Then reinstall — see README.md "Step 5: OpenHD radio link".
```

The uninstall scripts wipe `/usr/local/bin/openhd*`, `/usr/local/share/openhd/`, the `88x2bu_ohd` module, regdomain configs, and the cloned `OpenHD/`, `OpenHD-SysUtils/`, `qopenHD/` dirs. They preserve HailoRT, `hailo-all`, the parent `venv_hailo_apps`, the drone-follow Python install, and `/usr/local/hailo/resources/`.
