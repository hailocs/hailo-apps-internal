# x86_64 Ground Station Setup — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Install and build the full OpenHD ground station stack (OpenHD, OpenHD-SysUtils, QOpenHD) on an x86_64 Ubuntu laptop, then update SETUP_GUIDE.md with x86-specific instructions.

**Architecture:** All three repos already support x86_64 builds — no source changes needed. OpenHD detects x86 at runtime, QOpenHD auto-selects `LinuxBuild` config via qmake, and SysUtils has dedicated x86 CI. The work is: clone, install deps, build, deploy config, document.

**Tech Stack:** C++17 (CMake), Qt5 (qmake), GStreamer, FFmpeg, systemd

---

### Task 1: Clone Repositories

**Files:**
- Create: `~/OpenHD/` (clone)
- Create: `~/OpenHD-SysUtils/` (clone)
- Create: `~/qopenHD/` (clone)

- [ ] **Step 1: Clone all three repos**

```bash
cd ~
git clone --recurse-submodules -b feature/hailo-apps-integration \
    https://github.com/barakbk-hailo/OpenHD.git
git clone -b main https://github.com/barakbk-hailo/OpenHD-SysUtils.git
git clone -b fix/rpi4-hw-decode https://github.com/barakbk-hailo/qopenHD.git
```

- [ ] **Step 2: Verify clones**

```bash
ls ~/OpenHD/build_native.sh ~/OpenHD-SysUtils/CMakeLists.txt ~/qopenHD/QOpenHD.pro
```

Expected: all three files exist.

---

### Task 2: Build OpenHD-SysUtils

- [ ] **Step 1: Build and package**

```bash
cd ~/OpenHD-SysUtils
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --config Release -j$(nproc)
cd build && cpack -G DEB
```

- [ ] **Step 2: Install the deb**

```bash
sudo dpkg -i ~/OpenHD-SysUtils/build/*.deb
```

- [ ] **Step 3: Verify**

```bash
which openhd_sys_utils
```

Expected: `/usr/local/bin/openhd_sys_utils`

---

### Task 3: Build OpenHD

- [ ] **Step 1: Install build dependencies**

```bash
cd ~/OpenHD
sudo ./install_build_dep.sh ubuntu-x86
```

- [ ] **Step 2: Build (native x86_64)**

```bash
cd ~/OpenHD
sudo ./build_native.sh build
```

Note: Use `build` target, NOT `all` — the `driver` target builds the rtl88x2bu WiFi DKMS module which may not be needed on this laptop (only needed if using the same monitor-mode adapter as the RPi ground unit). If you DO have the adapter, run `sudo ./build_native.sh all` instead.

- [ ] **Step 3: Install binary**

```bash
sudo cp ~/OpenHD/OpenHD/build_release/openhd /usr/local/bin/openhd
```

- [ ] **Step 4: Verify**

```bash
openhd --help 2>&1 | head -5
```

---

### Task 4: Build QOpenHD

- [ ] **Step 1: Install build dependencies**

```bash
cd ~/qopenHD
sudo ./install_build_dep.sh ubuntu-x86
```

- [ ] **Step 2: Build with qmake**

```bash
cd ~/qopenHD
mkdir -p build/release && cd build/release
qmake ../..
make -j$(nproc)
```

- [ ] **Step 3: Verify binary exists**

```bash
ls -la ~/qopenHD/build/release/QOpenHD*
```

---

### Task 5: Deploy Configuration Files

- [ ] **Step 1: Create openhd directory and copy df_params.json**

```bash
sudo mkdir -p /usr/local/share/openhd
sudo cp ~/hailo-drone-follow/df_params.json /usr/local/share/openhd/df_params.json
```

- [ ] **Step 2: Copy encryption key from air unit**

```bash
scp pi@<air-ip>:/usr/local/share/openhd/txrx.key /tmp/txrx.key
sudo cp /tmp/txrx.key /usr/local/share/openhd/txrx.key
```

Note: Replace `<air-ip>` with the air unit's IP. If no air unit exists yet, generate a new key and copy it to the air unit later:
```bash
sudo dd if=/dev/urandom of=/usr/local/share/openhd/txrx.key bs=32 count=1 2>/dev/null
```

---

### Task 6: Update SETUP_GUIDE.md with x86 Ground Station Section

**Files:**
- Modify: `SETUP_GUIDE.md` — add new section after "Ground Unit Setup"

- [ ] **Step 1: Add x86_64 ground station section**

Add a new section "## x86_64 Ground Station (Laptop/Desktop)" covering:
- Prerequisites (Ubuntu 22.04+, no Hailo needed for ground)
- Same clone step but noting `ubuntu-x86` for dep scripts
- Build commands using `ubuntu-x86` targets
- QOpenHD launch using Wayland/X11 (not EGLFS)
- Note: WiFi driver only needed if using monitor-mode adapter

- [ ] **Step 2: Commit changes**

```bash
git add SETUP_GUIDE.md
git commit -m "docs: add x86_64 ground station setup instructions"
```
