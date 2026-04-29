# Drone Follow — Design Review

A comprehensive architecture reference for the hailo-drone-follow system.
For control algorithm details see [control-architecture.md](control-architecture.md).
For parameter bridge specifics see [PARAMETERS.md](../PARAMETERS.md).
For setup & deployment see [SETUP_GUIDE.md](../SETUP_GUIDE.md).

---

## 1. System Overview

A vision-based autonomous drone follow application. A Hailo NPU runs real-time
person detection (YOLO) on a camera stream; a control loop converts detections
into body-frame velocity commands sent to PX4 via MAVSDK. Runs on RPi5 +
Hailo-8L on a drone with Cube Orange+ flight controller, or on an x86 dev
machine with Hailo-8 PCIe.

**Key properties:**
- Single 4-DOF output primitive: body-frame velocity + yawrate (no attitude, no waypoints)
- Pure domain logic (`follow_api/`) has zero external dependencies — testable offline
- All Hailo/GStreamer code confined to `pipeline_adapter/`; all MAVSDK code confined to `drone_api/`
- Runtime-tunable via web UI (localhost:5001) and OpenHD ground station (MAVLink parameters)
- Optional OpenHD video streaming, on-board recording, PX4 SITL simulation

---

## 2. System Context Diagram

```mermaid
graph TB
    subgraph Drone["Drone (RPi5 + Hailo-8L + Cube Orange+)"]
        CAM[Camera<br/>RPi CSI / USB / SHM]
        HAILO[Hailo NPU<br/>YOLO person detection]
        APP[drone-follow<br/>Python application]
        FC[Cube Orange+<br/>PX4 firmware]
    end

    subgraph Ground["Ground Station (optional)"]
        QOHD[QOpenHD<br/>Qt GUI]
        GCS[QGroundControl<br/>optional]
    end

    CAM -->|frames| HAILO
    HAILO -->|detections| APP
    APP -->|MAVLink velocity<br/>setpoints| FC
    FC -->|telemetry| APP

    APP <-.->|WFB / OpenHD<br/>video + params| QOHD
    FC <-.->|MAVLink| GCS

    WEB[Web Browser<br/>localhost:5001] <-->|HTTP / MJPEG / SSE| APP

    style Drone fill:#1a1a2e,color:#fff
    style Ground fill:#16213e,color:#fff
```

---

## 3. Software Architecture

```mermaid
graph LR
    subgraph follow_api["follow_api/ — Pure Domain Logic"]
        TYPES["types.py<br/>Detection, VelocityCommand,<br/>FollowMode"]
        CONFIG["config.py<br/>ControllerConfig<br/>(~30 tunable params)"]
        CTRL["controller.py<br/>compute_velocity_command()"]
        STATE["state.py<br/>SharedDetectionState<br/>FollowTargetState"]
    end

    subgraph pipeline_adapter["pipeline_adapter/ — Hailo + GStreamer"]
        DET_MGR["hailo_drone_detection_<br/>manager.py<br/>app_callback()<br/>DroneFollowTilingApp"]
        BT["byte_tracker.py<br/>ByteTracker<br/>KalmanFilter, STrack"]
    end

    subgraph drone_api["drone_api/ — MAVSDK Adapter"]
        MAVSDK_DRV["mavsdk_drone.py<br/>VelocityCommandAPI<br/>live_control_loop()<br/>run_live_drone()"]
    end

    subgraph servers["servers/ — HTTP + UDP"]
        WEB_SRV["web_server.py<br/>WebServer, SharedUIState<br/>MJPEG / SSE / REST"]
        FOLLOW_SRV["follow_server.py<br/>FollowServer<br/>POST /follow/id"]
        OHD_BRIDGE["openhd_bridge.py<br/>OpenHDBridge<br/>UDP JSON 5510/5511"]
    end

    ENTRY["drone_follow_app.py<br/>main() — composition root"]

    ENTRY --> DET_MGR
    ENTRY --> MAVSDK_DRV
    ENTRY --> WEB_SRV
    ENTRY --> FOLLOW_SRV
    ENTRY --> OHD_BRIDGE

    DET_MGR --> BT
    DET_MGR --> STATE
    DET_MGR --> TYPES
    MAVSDK_DRV --> CTRL
    MAVSDK_DRV --> STATE
    MAVSDK_DRV --> TYPES
    MAVSDK_DRV --> CONFIG
    CTRL --> TYPES
    CTRL --> CONFIG
    WEB_SRV --> STATE
    WEB_SRV --> CONFIG
    FOLLOW_SRV --> STATE
    OHD_BRIDGE --> CONFIG
    OHD_BRIDGE --> STATE

    style follow_api fill:#2d6a4f,color:#fff
    style pipeline_adapter fill:#6a4c93,color:#fff
    style drone_api fill:#1982c4,color:#fff
    style servers fill:#f77f00,color:#000
```

### Dependency Rules

| Layer | May import from | External deps |
|-------|----------------|---------------|
| `follow_api/` | stdlib, numpy | None (pure domain) |
| `pipeline_adapter/` | follow_api, hailo, gi.repository.Gst, numpy, scipy | Hailo SDK, GStreamer |
| `drone_api/` | follow_api, mavsdk | MAVSDK |
| `servers/` | follow_api, stdlib HTTP/socket | None |
| `drone_follow_app.py` | All of the above | — |

**No circular imports.** The dependency graph is a strict DAG with `follow_api/` at the bottom.

---

## 4. Threading Model

```mermaid
graph TB
    subgraph MainThread["Main Thread"]
        GST["GStreamer MainLoop<br/>(blocking)"]
    end

    subgraph PipelineThread["Pipeline Callback<br/>(GStreamer internal)"]
        CB["app_callback()<br/>ByteTracker.update()<br/>target selection"]
    end

    subgraph DroneThread["Drone Control Thread<br/>(asyncio event loop)"]
        CL["live_control_loop() @ 10 Hz"]
        TEL1["_telemetry_altitude_task()"]
        TEL2["_telemetry_velocity_task()"]
        TEL3["_telemetry_position_task()"]
        TLOG["_telemetry_log_task() @ 1 Hz"]
        WATCH["_watch_offboard_mode()"]
    end

    subgraph ServerThreads["Daemon Threads"]
        WT["WebServer<br/>(ThreadingHTTPServer)"]
        FS["FollowServer<br/>(HTTPServer)"]
        OL["OpenHDBridge listener<br/>(UDP recv)"]
        OR["OpenHDBridge reporter<br/>(UDP send @ 10 Hz)"]
    end

    CB -->|"SharedDetectionState<br/>(Lock)"| CL
    CB -->|"SharedUIState<br/>(Lock)"| WT
    CL -->|"SharedUIState<br/>(Lock)"| WT
    WT -->|"FollowTargetState<br/>(Lock)"| CB
    FS -->|"FollowTargetState<br/>(Lock)"| CB
    OL -->|"ControllerConfig<br/>(direct mutation)"| CL

    SHUTDOWN["shutdown Event"] -.-> CL
    SHUTDOWN -.-> GST

    style MainThread fill:#264653,color:#fff
    style PipelineThread fill:#2a9d8f,color:#fff
    style DroneThread fill:#e9c46a,color:#000
    style ServerThreads fill:#e76f51,color:#fff
```

### Synchronization Points

| Shared Object | Type | Writers | Readers |
|--------------|------|---------|---------|
| `SharedDetectionState` | `threading.Lock` | Pipeline callback | Control loop |
| `FollowTargetState` | `threading.Lock` | Web UI, FollowServer, OpenHD bridge | Pipeline callback, control loop |
| `SharedUIState` | `threading.Lock` | Pipeline callback, control loop | Web server (MJPEG/SSE) |
| `ControllerConfig` | Direct field mutation | Web UI, OpenHD bridge | Control loop (reads every tick) |
| `shutdown` | `asyncio.Event` | Main thread (Ctrl+C) | Drone thread, all tasks |

---

## 5. Data Flows

### 5.1 Detection to Velocity Command (main control path)

```mermaid
sequenceDiagram
    participant CAM as Camera
    participant GST as GStreamer Pipeline
    participant HAILO as Hailo NPU
    participant CB as app_callback()
    participant BT as ByteTracker
    participant SDS as SharedDetectionState
    participant CL as Control Loop (10 Hz)
    participant CTRL as compute_velocity_command()
    participant VAPI as VelocityCommandAPI
    participant PX4 as PX4 (MAVSDK)

    CAM->>GST: raw frame
    GST->>HAILO: inference request
    HAILO->>CB: detections (Hailo ROI)
    CB->>BT: Nx5 array [x1,y1,x2,y2,conf]
    BT-->>CB: tracks with persistent IDs
    Note over CB: Target selection:<br/>explicit lock > auto (largest) > IDLE
    CB->>SDS: Detection(center_x, center_y,<br/>bbox_height, confidence, timestamp)

    loop Every 100ms
        CL->>SDS: get_latest()
        SDS-->>CL: Detection + frame_count
        Note over CL: Check staleness (0.5s),<br/>search timeout (60s),<br/>IDLE mode
        CL->>CTRL: detection, config
        Note over CTRL: center_x → yaw (sqrt P)<br/>bbox_height → forward (distance P)<br/>down=0 (PX4 alt-hold)
        CTRL-->>CL: VelocityCommand(fwd, right, 0, yaw)
        Note over CL: PX4 alt-hold P-loop on (current_alt − target_altitude)<br/>Altitude floor/ceiling clamp<br/>(min_altitude..max_altitude)
        CL->>VAPI: send(cmd)
        Note over VAPI: Clamp all axes<br/>Per-axis EMA in VelocityCommandAPI
        VAPI->>PX4: set_velocity_body(fwd, right, down, yaw)
    end
```

### 5.2 Web UI Real-Time Sync

```mermaid
sequenceDiagram
    participant CB as app_callback()
    participant UIS as SharedUIState
    participant MJPEG as MJPEG Appsink
    participant SSE as SSE Endpoint
    participant BR as Browser

    CB->>UIS: update_detections(list, following_id)
    MJPEG->>UIS: update_frame(jpeg_bytes)
    Note over UIS: Atomic snapshot:<br/>detections + velocity + frame

    SSE->>UIS: wait_frame_with_detections()
    UIS-->>SSE: (jpeg, {detections, velocity, following_id})
    SSE->>BR: SSE event (JSON)

    BR->>BR: Draw MJPEG frame on canvas
    BR->>BR: SVG overlay: bboxes + IDs

    Note over BR: Click on bbox
    BR->>UIS: POST /follow/id
```

### 5.3 OpenHD Parameter Sync

```mermaid
sequenceDiagram
    participant QO as QOpenHD (ground)
    participant OG as OpenHD Ground
    participant WFB as Wifibroadcast RF
    participant OA as OpenHD Air<br/>(hailo_follow_bridge.cpp)
    participant PY as drone-follow Python
    participant CFG as ControllerConfig

    Note over QO: Operator moves slider
    QO->>OG: MAVLink PARAM_EXT_SET(DF_KP_YAW, 5.5)
    OG->>WFB: relay
    WFB->>OA: relay
    OA->>OA: Persist to disk
    OA->>PY: UDP:5510 {"param":"kp_yaw","value":5.5}
    PY->>CFG: config.kp_yaw = 5.5
    Note over CFG: Takes effect next<br/>control loop tick (~100ms)
    OA-->>QO: MAVLink PARAM_EXT_ACK

    loop Every 100ms
        PY->>OA: UDP:5511 {"params":{...},"bboxes":[...]}
        OA-->>QO: MAVLink PARAM_EXT_VALUE (readback)
    end
```

For the full parameter bridge architecture including `df_params.json` schema,
see [PARAMETERS.md](../PARAMETERS.md).

---

## 6. GStreamer Pipeline Topology

```mermaid
graph LR
    SRC["Source<br/>(rpicamsrc / v4l2src /<br/>shmsrc / udpsrc)"]
    DEC["Decoder<br/>(if needed)"]
    TILE["hailotilecropper<br/>(if tiles > 1x1)"]
    INF["hailonet<br/>(YOLO inference)"]
    CB_EL["identity<br/>(app_callback)"]

    SRC --> DEC --> TILE --> INF --> CB_EL

    subgraph T_PRE["tee (t_pre)"]
        direction TB
        B_MJPEG["MJPEG Branch<br/>(clean frames, no overlay)"]
        B_OVL["Overlay Branch"]
    end

    CB_EL --> T_PRE

    B_MJPEG --> RATE["videorate<br/>(max=ui_fps)"] --> JPEG["jpegenc<br/>(quality=70)"] --> APPSINK1["appsink<br/>(mjpeg_sink)"]

    B_OVL --> OVL["hailooverlay<br/>(bbox rendering)"]

    subgraph T_POST["tee (t_post)"]
        direction TB
        B_PRIMARY["Primary Output"]
        B_REC["Recording Branch"]
    end

    OVL --> T_POST

    B_PRIMARY --> X264["x264enc<br/>(ultrafast, zerolatency)"] --> RTP["rtph264pay"] --> UDP["udpsink :5500"]
    B_PRIMARY -.-> XSINK["ximagesink<br/>(default display)"]
    B_PRIMARY -.-> FAKE["fakesink<br/>(headless)"]

    B_REC --> VALVE["valve<br/>(record_valve)"] --> CONV["videoconvert<br/>(RGB)"] --> APPSINK2["appsink<br/>(record_appsink)"]
    APPSINK2 --> FFMPEG["ffmpeg subprocess<br/>(libx264, 5 Mbps)"]

    style T_PRE fill:#444,color:#fff
    style T_POST fill:#444,color:#fff
```

### Primary Output Modes

A single `hailooverlay` sits between `t_pre` and `t_post`, so both the primary output and the recording branch share the same overlay rendering. The MJPEG branch splits off before the overlay (clean frames for web UI SVG overlays).

The primary branch output from `t_post` depends on CLI flags:
- `--openhd-stream`: x264enc + rtph264pay + udpsink (port 5500)
- `--no-display`: fakesink
- default: ximagesink (X11 window)

### Named Elements

| Element | Type | Purpose |
|---------|------|---------|
| `mjpeg_sink` | appsink | Captures JPEG frames for web UI MJPEG stream |
| `record_valve` | valve | Gate for recording branch (drop=true until recording starts) |
| `record_appsink` | appsink | Captures raw RGB for ffmpeg stdin |
| `openhd_stream_encoder` | x264enc | H.264 encode for OpenHD RTP (bitrate live-adjustable) |

### Recording Lifecycle

1. `--record` flag or OpenHD "Record" button calls `start_recording()`
2. Opens `record_valve` (drop=false), spawns ffmpeg subprocess
3. `record_appsink` callback pipes raw RGB frames to ffmpeg stdin
4. `stop_recording()` closes valve, finalizes ffmpeg in background thread
5. Output: `recordings/rec_<timestamp>.mp4` (H.264, 5 Mbps)

---

## 7. External Interfaces

### 7.1 Web UI API (port 5001)

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/api/video` | MJPEG stream (multipart/x-mixed-replace) |
| GET | `/api/detections/stream` | SSE — frame-synced detections + velocity |
| GET | `/api/detections` | JSON detection snapshot (polling fallback) |
| GET | `/api/status` | Follow status + recording state |
| GET | `/api/config` | Current ControllerConfig as JSON |
| POST | `/api/config` | Update config fields (partial JSON body) |
| POST | `/api/record/start` | Start on-board recording |
| POST | `/api/record/stop` | Stop on-board recording |
| GET | `/api/logs?since_id=N` | Log entries newer than N |
| GET | `/*` | React SPA static files |

### 7.2 Follow Server API (port 8080)

| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/follow/<id>` | Lock to tracking ID |
| POST | `/follow/clear` | Clear lock, auto-follow largest |
| GET | `/status` | Current following state |

### 7.3 OpenHD Bridge (UDP)

| Port | Direction | Format | Purpose |
|------|-----------|--------|---------|
| 5510 | OpenHD to Python | `{"param":"<name>","value":<n>}` | Parameter set |
| 5511 | Python to OpenHD | `{"params":{...},"bboxes":[...]}` | State report (10 Hz) |

### 7.4 MAVSDK / MAVLink

| Interface | Details |
|-----------|---------|
| Setpoint | `VelocityBodyYawspeed` mapped to `SET_POSITION_TARGET_LOCAL_NED` (body frame) |
| Rate | 10 Hz (control loop), 20 Hz (pre-offboard keep-alive) |
| Telemetry | `position()`, `velocity_ned()`, `flight_mode()` streams |
| Actions | `arm()`, `takeoff()`, `land()`, `offboard.start/stop()` |
| Connection | UDP `udpin://0.0.0.0:14540`, serial `/dev/ttyACM0:57600`, TCP `tcpout://host:port` |

### 7.5 Control Output Primitive

```python
@dataclass
class VelocityCommand:
    forward_m_s: float      # +X body (nose)
    down_m_s: float         # +Z body (down positive, NED)
    yawspeed_deg_s: float   # +ve = clockwise from above
```

3-DOF output per control tick. No attitude, no position targets, no thrust.
The MAVSDK 4-tuple's right (+Y body) slot is a literal 0.0 at the boundary —
the orbit-era `right_m_s` field was dropped along with the orbit feature.
`down_m_s` is now vision-driven from `bbox_height` (plain P: person too small →
descend, too big → climb), with floor/ceiling clamping in `live_control_loop`.
See [control-architecture.md](control-architecture.md) for the control math.

---

## 8. Dependencies

### 8.1 System Dependencies

```mermaid
graph TB
    subgraph System["System Packages (apt / deb)"]
        HAILORT["hailort<br/>(driver + Python bindings)"]
        GST_SYS["GStreamer 1.0<br/>+ plugins-good/bad"]
        FFMPEG["ffmpeg<br/>(libx264)"]
        NODE["Node.js / npm<br/>(optional, for UI)"]
    end

    subgraph HailoApps["hailo-apps (git, editable)"]
        HA_PY["Python pipeline builders<br/>(GStreamerTilingApp, etc.)"]
        HA_CPP["C++ postprocess modules<br/>(compiled by install.sh)"]
        HA_HEF["HEF models<br/>(/usr/local/hailo/resources/)"]
    end

    subgraph DroneFollow["drone-follow (this repo)"]
        DF_PY["Python application"]
        DF_UI["React web UI"]
        DF_VENV["./venv/<br/>(--system-site-packages)"]
    end

    subgraph PyPI["Python Packages (pip)"]
        MAVSDK_PY["mavsdk"]
        NUMPY["numpy"]
        SCIPY["scipy"]
    end

    DF_PY --> HA_PY
    DF_PY --> MAVSDK_PY
    DF_PY --> NUMPY
    HA_PY --> HAILORT
    HA_PY --> GST_SYS
    DF_PY --> FFMPEG
    DF_UI --> NODE
    DF_VENV --> HAILORT

    style System fill:#264653,color:#fff
    style HailoApps fill:#2a9d8f,color:#fff
    style DroneFollow fill:#e9c46a,color:#000
    style PyPI fill:#e76f51,color:#fff
```

### 8.2 Python Import Boundaries

| Module | External imports |
|--------|-----------------|
| `follow_api/` | stdlib, numpy only |
| `pipeline_adapter/` | `hailo`, `gi.repository.Gst`, `gi.repository.GLib`, numpy, scipy |
| `drone_api/` | `mavsdk` |
| `servers/` | stdlib (`http.server`, `socket`, `json`) |
| `drone_follow_app.py` | All of the above |

### 8.3 Installation Flow

```mermaid
flowchart TD
    A["1. Install HailoRT driver (deb)"] --> B["sudo reboot"]
    B --> C["hailortcli fw-control identify"]
    C --> D{"Device detected?"}
    D -->|no| A
    D -->|yes| E["2. sudo hailo-apps/install.sh<br/>(one-time: C++ postprocess,<br/>HEF models to /usr/local/hailo/)"]
    E --> F["3. ./install.sh<br/>(creates ./venv/, editable pip install,<br/>builds React UI)"]
    F --> G["source setup_env.sh"]
    G --> H["drone-follow --help"]

    style A fill:#e63946,color:#fff
    style E fill:#457b9d,color:#fff
    style F fill:#2a9d8f,color:#fff
```

| Step | Scope | Frequency | Requires sudo |
|------|-------|-----------|---------------|
| 1. HailoRT driver | System kernel module + libs | Once per machine | Yes |
| 2. hailo-apps install | `/usr/local/hailo/` (HEFs, C++ .so) | Once per machine | Yes |
| 3. `./install.sh` | `./venv/` (Python + UI) | After each pull | No |
| 4. `source setup_env.sh` | Shell env (venv + PYTHONPATH) | Each terminal session | No |

For detailed setup instructions, see [SETUP_GUIDE.md](../SETUP_GUIDE.md).

---

## 9. Control Modes

```mermaid
stateDiagram-v2
    [*] --> IDLE: startup (no target)

    IDLE --> TRACK: detection arrives
    TRACK --> SEARCH_WAIT: detection lost (less than 2s)
    SEARCH_WAIT --> TRACK: detection returns
    SEARCH_WAIT --> SEARCH: still lost 2s+
    SEARCH --> TRACK: detection returns
    SEARCH --> LANDING: lost 60s+
    TRACK --> IDLE: operator pauses or lock lost
    IDLE --> TRACK: operator resumes

    LANDING --> [*]
```

| Mode | Behaviour |
|------|-----------|
| **TRACK** | yaw (center_x → yawspeed) + forward (bbox_height → distance), altitude held by PX4 |
| **SEARCH_WAIT** | Hold last velocity command (< 2s buffer) |
| **SEARCH** | Slow yaw spin (10 deg/s) toward last-seen side, dampened forward |
| **IDLE** | Zero velocity — hover in place |
| **LANDING** | Shutdown then `action.land()` |

For the control math behind each mode, see
[control-architecture.md](control-architecture.md) sections 3-4.

---

## 10. Safety Features

| Feature | Trigger | Response |
|---------|---------|----------|
| Emergency climb + reverse | `bbox_height > 0.8` | Max climb (`-max_climb_speed`) + full reverse (`-max_backward`) |
| Search timeout | No detection for 60s | Land |
| Explicit lock loss | Locked target disappears | IDLE (hover), not auto-switch |
| Offboard mode loss | Pilot switches out of OFFBOARD | Pause control, wait for re-entry |
| Landing protection | Ctrl+C during `action.land()` | SIGINT ignored until touchdown |
| Altitude limits | Always active | Floor/ceiling clamp at `min_altitude`..`max_altitude` (default 2--20 m) |
| Axis clamping | Every tick | All axes clamped to configured max speeds |

---

## 11. Boot and Deployment

### RPi Air Unit Boot Sequence

```mermaid
flowchart TD
    BOOT["systemd boot"] --> SVC["drone-follow-boot.service"]
    SVC --> SCRIPT["drone-follow-boot.sh"]
    SCRIPT --> CONF{{"~/Desktop/drone-follow.conf<br/>ENABLED=true?"}}
    CONF -->|no| SKIP["Exit (no-op)"]
    CONF -->|yes| AIR["scripts/start_air.sh"]
    AIR --> OHD["Start OpenHD --air<br/>(background)"]
    AIR --> DF["drone-follow<br/>--input rpi --openhd-stream<br/>--connection tcpout://127.0.0.1:5760"]
```

### Execution Modes

| Mode | Command | Use case |
|------|---------|----------|
| Real drone + OpenHD | `scripts/start_air.sh` | Flight (RPi air unit) |
| Dev machine + USB camera | `drone-follow --input usb --serial --ui` | Bench testing |
| Simulation | `sim/start_sim.sh` + `drone-follow --input udp://... --takeoff-landing --ui` | Development |
| Headless OpenHD | `drone-follow --input rpi --openhd-stream --no-display` | SSH sessions |

---

## 12. Key Files Reference

| File | Lines | Purpose |
|------|-------|---------|
| `drone_follow/drone_follow_app.py` | ~270 | Composition root, CLI, threading |
| `drone_follow/follow_api/types.py` | ~35 | Domain primitives |
| `drone_follow/follow_api/config.py` | ~230 | ControllerConfig (all parameters) |
| `drone_follow/follow_api/controller.py` | ~170 | Pure control math |
| `drone_follow/follow_api/state.py` | ~100 | Thread-safe shared state |
| `drone_follow/drone_api/mavsdk_drone.py` | ~780 | MAVSDK adapter, control loop, flight lifecycle |
| `drone_follow/pipeline_adapter/hailo_drone_detection_manager.py` | ~820 | GStreamer pipeline, detection callback |
| `drone_follow/pipeline_adapter/byte_tracker.py` | ~500 | Multi-object tracker |
| `drone_follow/servers/web_server.py` | ~440 | Web UI server |
| `drone_follow/servers/follow_server.py` | ~130 | REST target selection |
| `drone_follow/servers/openhd_bridge.py` | ~370 | OpenHD parameter bridge |
| `drone_follow/ui/src/App.jsx` | ~600 | React frontend |

---

## 13. Related Documentation

| Document | Covers |
|----------|--------|
| [control-architecture.md](control-architecture.md) | Control math, parameter tuning guide, algorithm details |
| [PARAMETERS.md](../PARAMETERS.md) | OpenHD parameter bridge, df_params.json schema |
| [SETUP_GUIDE.md](../SETUP_GUIDE.md) | End-to-end deployment with OpenHD |
| [README.md](../README.md) | Installation, CLI flags, quick start |
| [TROUBLESHOOTING.md](../TROUBLESHOOTING.md) | Common issues and fixes |
