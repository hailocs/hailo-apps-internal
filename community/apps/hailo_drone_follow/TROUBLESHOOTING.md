# Troubleshooting Guide

## Common Issues

### 1. "Restarting camera…" hangs in QOpenHD

**Cause:** OpenHD restarted the camera pipeline but the new resolution
failed to produce frames.

**Check on air unit:**
```bash
journalctl -u openhd --no-pager -n 100
# Look for "GStreamer ERROR" or "stream_ended"
```

If the log shows _"ISP returned zero frames"_ or _"stream ended
unexpectedly"_, the requested framerate exceeds what the sensor supports
in full-FOV mode. The FullFovMode fix (see RESOLUTION_CONTROL.md)
prevents this for the standard resolution list.

**Fix:** Reboot the air unit to reset to the persisted resolution:
```bash
ssh pi@192.168.0.117
sudo reboot
```
Or delete the camera config to return to factory defaults:
```bash
ssh pi@192.168.0.117
sudo rm /usr/local/share/openhd/video/*.json
sudo reboot
```

---

### 2. drone-follow pipeline fails after resolution change

**Symptoms:** Python log shows GStreamer error from `shmsrc`, then
"SHM socket lost" and starts polling.

**Expected behaviour:** After about 2-3 seconds the pipeline should
auto-rebuild with the new resolution (read from metadata file).

**If it stays stuck:**
```bash
# Check the SHM socket exists
ls -la /tmp/openhd_raw_video

# Check the metadata file
cat /tmp/openhd_raw_video.meta
# Should show {"width":1280,"height":720,"fps":30}

# If metadata is missing, OpenHD may not have the latest build.
# Rebuild and redeploy OpenHD.
```

---

### 3. Hailo produces no detections

```bash
# Verify the Hailo device is visible
hailortcli fw-control identify

# Check the HEF file exists
ls /home/pi/hailo-drone-follow/drone_follow/pipeline_adapter/*.hef
```

Common causes:
- Wrong `--input-src` — for SHM mode use `shm` (not a URI)
- Caps mismatch: metadata says one resolution but pipeline expects another
- Hailo device busy (another process using it) — kill stale processes:
  ```bash
  sudo pkill -f drone_follow
  ```

---

### 4. No video in QOpenHD

```bash
# On air unit — verify openhd is running
ssh pi@192.168.0.117 systemctl status openhd

# Check wifibroadcast link
# In QOpenHD: look for link status indicator
```

---

### 5. QOpenHD resolution menu empty or wrong

The resolution list is compiled into the QOpenHD binary.
If you see the old short list, rebuild QOpenHD:
```bash
cd ~/hailo-drone-follow/qopenHD/build/release
make -j4
sudo cp release/QOpenHD /usr/local/bin/QOpenHD
sudo systemctl restart qopenhd
```

---

### 6. DroneFollow parameters not appearing in QOpenHD

1. Verify `df_params.json` is deployed:
   ```bash
   ls /usr/local/share/openhd/df_params.json
   ```
2. Restart QOpenHD after deploying
3. Check that the DroneFollow settings tab is visible (enabled via camera
   type being set to Hailo(5) or SHM passthrough being active)

---

### 7. Build fails

```bash
# OpenHD — missing dependencies
cd ~/hailo-drone-follow/OpenHD/OpenHD
./install_build_dep.sh

# QOpenHD — Qt5 not found
sudo apt install qtbase5-dev qtdeclarative5-dev qml-module-qtquick2

# drone-follow — Python deps
cd ~/hailo-drone-follow
pip install -e .
```

---

## Useful Debug Commands

```bash
# Watch OpenHD logs live
journalctl -u openhd -f

# Watch QOpenHD logs live
journalctl -u qopenhd -f

# Monitor SHM socket activity
watch -n1 'ls -la /tmp/openhd_raw_video*'

# Check camera detection
ssh pi@192.168.0.117 libcamera-hello --list-cameras

# Test a resolution directly (air unit)
ssh pi@192.168.0.117 libcamera-vid -t 3000 --width 1280 --height 720 --framerate 30

# View current camera config
cat /usr/local/share/openhd/video/RPIF_V3_IMX708_0.json
```

---

## Log Locations

| Component | Log |
|-----------|-----|
| OpenHD | `journalctl -u openhd` |
| QOpenHD | `journalctl -u qopenhd` |
| drone-follow | stdout (run in foreground to see) |
| SHM metadata | `/tmp/openhd_raw_video.meta` |
| Camera config | `/usr/local/share/openhd/video/*.json` |
