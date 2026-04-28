import { useState, useEffect, useRef, useCallback } from "react";

const LOG_POLL_INTERVAL = 500; // ms
const DEBOUNCE_MS = 250;

export default function App() {
  const [detections, setDetections] = useState([]);
  const [followingId, setFollowingId] = useState(null);
  const [velocity, setVelocity] = useState(null);
  const [videoDims, setVideoDims] = useState({ width: 0, height: 0 });
  const [logsOpen, setLogsOpen] = useState(true);
  const [logs, setLogs] = useState([]);
  const [config, setConfig] = useState(null);
  const [recording, setRecording] = useState(false);
  const [perf, setPerf] = useState(null);
  const [paused, setPaused] = useState(false);
  const canvasRef = useRef(null);
  const debounceRef = useRef(null);
  const logSinceRef = useRef(0);
  const logEndRef = useRef(null);

  // Frame-synced detections via SSE (replaces polling)
  useEffect(() => {
    const es = new EventSource("/api/detections/stream");
    es.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        setDetections(data.detections || []);
        setFollowingId(data.following_id);
        setVelocity(data.velocity || null);
        setPerf(data.perf || null);
        setPaused(data.paused ?? false);
      } catch {
        // malformed event
      }
    };
    return () => es.close();
  }, []);

  // Poll recording status
  useEffect(() => {
    let active = true;
    const poll = async () => {
      while (active) {
        try {
          const res = await fetch("/api/status");
          if (res.ok) {
            const data = await res.json();
            if (data.recording !== undefined) setRecording(data.recording);
          }
        } catch {
          // server not ready
        }
        await new Promise((r) => setTimeout(r, 1000));
      }
    };
    poll();
    return () => { active = false; };
  }, []);

  // Fetch config on mount, and refresh on every lock/unlock so the
  // Target Size slider tracks the bbox setpoint that the server captures
  // at lock time (manual click *and* AUTO acquisition both rewrite
  // controller_config.target_bbox_height under the hood).
  useEffect(() => {
    let aborted = false;
    fetch("/api/config")
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (data && !aborted) setConfig(data);
      })
      .catch(() => {});
    return () => { aborted = true; };
  }, [followingId]);

  // Poll logs
  useEffect(() => {
    if (!logsOpen) return;
    let active = true;
    const poll = async () => {
      while (active) {
        try {
          const res = await fetch(`/api/logs?since_id=${logSinceRef.current}`);
          if (res.ok) {
            const data = await res.json();
            if (data.logs && data.logs.length > 0) {
              logSinceRef.current = data.logs[data.logs.length - 1].id;
              setLogs((prev) => {
                const next = [...prev, ...data.logs];
                return next.length > 200 ? next.slice(-200) : next;
              });
            }
          }
        } catch {
          // server not ready
        }
        await new Promise((r) => setTimeout(r, LOG_POLL_INTERVAL));
      }
    };
    poll();
    return () => {
      active = false;
    };
  }, [logsOpen]);

  // Auto-scroll logs
  useEffect(() => {
    if (logEndRef.current) {
      logEndRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [logs]);

  // MJPEG stream via fetch + ReadableStream → canvas
  useEffect(() => {
    const controller = new AbortController();
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");

    const BOUNDARY = "--frame\r\n";
    const HEADER_END = "\r\n\r\n";

    (async () => {
      try {
        const res = await fetch("/api/video", { signal: controller.signal });
        const reader = res.body.getReader();
        let buffer = new Uint8Array(0);

        const concat = (a, b) => {
          const c = new Uint8Array(a.length + b.length);
          c.set(a);
          c.set(b, a.length);
          return c;
        };

        const indexOf = (buf, pattern) => {
          const enc = new TextEncoder();
          const pat = enc.encode(pattern);
          outer: for (let i = 0; i <= buf.length - pat.length; i++) {
            for (let j = 0; j < pat.length; j++) {
              if (buf[i + j] !== pat[j]) continue outer;
            }
            return i;
          }
          return -1;
        };

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer = concat(buffer, value);

          // Process all complete frames in the buffer
          while (true) {
            // Find the first boundary
            const bStart = indexOf(buffer, BOUNDARY);
            if (bStart === -1) break;

            // Find the end of headers after the boundary
            const headerStart = bStart + BOUNDARY.length;
            const headerEnd = indexOf(
              buffer.subarray(headerStart),
              HEADER_END
            );
            if (headerEnd === -1) break;

            const jpegStart = headerStart + headerEnd + HEADER_END.length;

            // Find the next boundary to determine the end of JPEG data
            const nextBoundary = indexOf(
              buffer.subarray(jpegStart),
              BOUNDARY
            );
            if (nextBoundary === -1) break;

            // Extract JPEG bytes (strip trailing \r\n before next boundary)
            let jpegEnd = jpegStart + nextBoundary;
            while (jpegEnd > jpegStart && (buffer[jpegEnd - 1] === 0x0a || buffer[jpegEnd - 1] === 0x0d)) {
              jpegEnd--;
            }
            const jpegData = buffer.slice(jpegStart, jpegEnd);

            // Advance buffer past the current frame (keep from next boundary)
            buffer = buffer.slice(jpegStart + nextBoundary);

            // Draw the frame
            try {
              const blob = new Blob([jpegData], { type: "image/jpeg" });
              const bmp = await createImageBitmap(blob);
              if (canvas.width !== bmp.width || canvas.height !== bmp.height) {
                canvas.width = bmp.width;
                canvas.height = bmp.height;
                setVideoDims({ width: bmp.width, height: bmp.height });
              }
              ctx.drawImage(bmp, 0, 0);
              bmp.close();
            } catch {
              // skip corrupt frame
            }
          }
        }
      } catch (err) {
        if (err.name !== "AbortError") {
          console.error("MJPEG stream error:", err);
        }
      }
    })();

    return () => controller.abort();
  }, []);

  const handleFollow = async (id) => {
    try {
      const port = config?.follow_server_port || 8080;
      const host = window.location.hostname;
      await fetch(`http://${host}:${port}/follow/${id}`, { method: "POST" });
    } catch {
      // ignore
    }
  };

  const handleRecord = async () => {
    try {
      const endpoint = recording ? "/api/record/stop" : "/api/record/start";
      const res = await fetch(endpoint, { method: "POST" });
      if (res.ok) {
        const data = await res.json();
        setRecording(data.recording ?? !recording);
      }
    } catch {
      // ignore
    }
  };

  const handleClear = async () => {
    try {
      const port = config?.follow_server_port || 8080;
      const host = window.location.hostname;
      await fetch(`http://${host}:${port}/follow/clear`, { method: "POST" });
    } catch {
      // ignore
    }
  };

  const [configStatus, setConfigStatus] = useState("");

  const handleConfigSave = async () => {
    try {
      const res = await fetch("/api/config/save", { method: "POST" });
      const data = await res.json().catch(() => ({}));
      if (res.ok && data.saved) {
        setConfigStatus(`Saved → ${data.path}`);
      } else {
        setConfigStatus(`Save failed: ${data.error || res.statusText}`);
      }
    } catch (e) {
      setConfigStatus(`Save error: ${e}`);
    }
    setTimeout(() => setConfigStatus(""), 4000);
  };

  const handleConfigLoad = async () => {
    try {
      const res = await fetch("/api/config/load", { method: "POST" });
      const data = await res.json().catch(() => ({}));
      if (res.ok && data.loaded) {
        // Refresh sliders from the live config after the reload
        const r = await fetch("/api/config");
        if (r.ok) setConfig(await r.json());
        const n = Array.isArray(data.changed) ? data.changed.length : 0;
        setConfigStatus(`Loaded → ${data.path} (${n} changed)`);
      } else {
        setConfigStatus(`Load failed: ${data.error || res.statusText}`);
      }
    } catch (e) {
      setConfigStatus(`Load error: ${e}`);
    }
    setTimeout(() => setConfigStatus(""), 4000);
  };

  // Debounced POST for config changes
  const postConfig = useCallback((updated) => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      fetch("/api/config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(updated),
      })
        .then((r) => (r.ok ? r.json() : null))
        .then((data) => {
          if (data) setConfig(data);
        })
        .catch(() => {});
    }, DEBOUNCE_MS);
  }, []);

  const onSlider = (key, value) => {
    const updated = { ...config, [key]: parseFloat(value) };
    setConfig(updated);
    postConfig({ [key]: parseFloat(value) });
  };

  const onToggle = (key) => {
    const newVal = !config[key];
    const updated = { ...config, [key]: newVal };
    setConfig(updated);
    postConfig({ [key]: newVal });
  };

  const vw = videoDims.width;
  const vh = videoDims.height;

  return (
    <div className="app">
      <div className="status-bar">
        <span className="status-text">
          {followingId != null
            ? `Following: ID ${followingId}`
            : paused ? "Idle (paused)" : "Auto (largest person)"}
        </span>
        {velocity && (
          <span className="velocity-text">
            {velocity.mode} | Fwd {velocity.forward_m_s.toFixed(2)} m/s
            {velocity.right_m_s != null && velocity.right_m_s !== 0
              ? ` | Lat ${velocity.right_m_s.toFixed(2)} m/s`
              : ""}{" "}
            | Down {velocity.down_m_s.toFixed(2)} m/s | Yaw{" "}
            {velocity.yawspeed_deg_s.toFixed(1)} deg/s
          </span>
        )}
        {perf && (
          <span className="perf-text">
            {perf.fps} FPS | {perf.latency_ms} ms
            | CPU {perf.cpu_percent}%
            | Mem {perf.memory_mb} MB
            {perf.hailo_util_percent > 0 ? ` | NN ${perf.hailo_util_percent}%` : ""}
            {perf.hailo_temp_c > 0 ? ` | ${perf.hailo_temp_c}\u00b0C` : ""}
          </span>
        )}
        <button
          className={`record-btn ${recording ? "recording" : ""}`}
          onClick={handleRecord}
        >
          {recording ? "Stop Rec" : "Record"}
        </button>
        <button className="clear-btn" onClick={handleClear}>
          Clear Target
        </button>
        <button className="clear-btn" onClick={handleConfigSave} title="Save current config to df_config.json on the air unit">
          Save Config
        </button>
        <button className="clear-btn" onClick={handleConfigLoad} title="Live-reload config from df_config.json on the air unit">
          Load Config
        </button>
        {configStatus && <span className="config-status">{configStatus}</span>}
      </div>

      <div className="main-layout">
        <div className="side-panel">
          {config && (
            <div className="controls-panel side-card">
              <div className="controls-header">Controls</div>
              <div className="controls-body">
                {/* --- Operational controls --- */}
                <label className={`control-row${config.yaw_only ? " disabled" : ""}`}>
                  <span className="control-label">Target Size</span>
                  <input
                    type="range"
                    min="0.10"
                    max="0.25"
                    step="0.01"
                    value={config.target_bbox_height}
                    disabled={config.yaw_only}
                    onChange={(e) => onSlider("target_bbox_height", e.target.value)}
                  />
                  <span className="control-value">
                    {(config.target_bbox_height * 100).toFixed(0)}%
                  </span>
                </label>
                <label className="control-row">
                  <span className="control-label">Target Alt</span>
                  <input
                    type="range"
                    min="1"
                    max="20"
                    step="0.5"
                    value={config.target_altitude}
                    onChange={(e) => onSlider("target_altitude", e.target.value)}
                  />
                  <span className="control-value">{config.target_altitude.toFixed(1)}m</span>
                </label>
                <label className="control-row">
                  <span className="control-label">KP Distance</span>
                  <input
                    type="range"
                    min="0"
                    max="10"
                    step="0.1"
                    value={config.kp_distance}
                    onChange={(e) => onSlider("kp_distance", e.target.value)}
                  />
                  <span className="control-value">{config.kp_distance.toFixed(1)}</span>
                </label>
                <label className="control-row">
                  <span className="control-label">Min Altitude</span>
                  <input
                    type="range"
                    min="1"
                    max="10"
                    step="0.5"
                    value={config.min_altitude}
                    onChange={(e) => onSlider("min_altitude", e.target.value)}
                  />
                  <span className="control-value">{config.min_altitude.toFixed(1)}m</span>
                </label>
                <label className="control-row">
                  <span className="control-label">Max Altitude</span>
                  <input
                    type="range"
                    min="5"
                    max="50"
                    step="1"
                    value={config.max_altitude}
                    onChange={(e) => onSlider("max_altitude", e.target.value)}
                  />
                  <span className="control-value">{config.max_altitude.toFixed(0)}m</span>
                </label>
                <label className="control-row">
                  <span className="control-label">Yaw Only</span>
                  <div className="toggle-wrapper">
                    <button
                      className={`toggle-btn ${config.yaw_only ? "toggle-on" : ""}`}
                      onClick={() => onToggle("yaw_only")}
                    >
                      {config.yaw_only ? "ON" : "OFF"}
                    </button>
                  </div>
                </label>
                <label className="control-row">
                  <span className="control-label">Auto Select</span>
                  <div className="toggle-wrapper">
                    <button
                      className={`toggle-btn ${config.auto_select ? "toggle-on" : ""}`}
                      onClick={() => onToggle("auto_select")}
                    >
                      {config.auto_select ? "ON" : "OFF"}
                    </button>
                  </div>
                </label>
                <label className="control-row">
                  <span className="control-label">Mode</span>
                  <div className="toggle-wrapper">
                    <button
                      className={`toggle-btn ${config.follow_mode === "follow" ? "toggle-on" : ""}`}
                      onClick={() => {
                        const updated = { ...config, follow_mode: "follow" };
                        setConfig(updated);
                        postConfig({ follow_mode: "follow" });
                      }}
                    >
                      FOLLOW
                    </button>
                    <button
                      className={`toggle-btn ${config.follow_mode === "orbit" ? "toggle-on" : ""}`}
                      onClick={() => {
                        const updated = { ...config, follow_mode: "orbit" };
                        setConfig(updated);
                        postConfig({ follow_mode: "orbit" });
                      }}
                    >
                      ORBIT
                    </button>
                  </div>
                </label>
                {config.follow_mode === "orbit" && (
                  <>
                    <label className="control-row">
                      <span className="control-label">Orbit Speed</span>
                      <input
                        type="range"
                        min="0.2"
                        max="3.0"
                        step="0.1"
                        value={config.orbit_speed_m_s}
                        onChange={(e) => onSlider("orbit_speed_m_s", e.target.value)}
                      />
                      <span className="control-value">{config.orbit_speed_m_s.toFixed(1)} m/s</span>
                    </label>
                    <label className="control-row">
                      <span className="control-label">Direction</span>
                      <div className="toggle-wrapper">
                        <button
                          className={`toggle-btn ${config.orbit_direction === 1 ? "toggle-on" : ""}`}
                          onClick={() => {
                            const updated = { ...config, orbit_direction: 1 };
                            setConfig(updated);
                            postConfig({ orbit_direction: 1 });
                          }}
                        >
                          CW
                        </button>
                        <button
                          className={`toggle-btn ${config.orbit_direction === -1 ? "toggle-on" : ""}`}
                          onClick={() => {
                            const updated = { ...config, orbit_direction: -1 };
                            setConfig(updated);
                            postConfig({ orbit_direction: -1 });
                          }}
                        >
                          CCW
                        </button>
                      </div>
                    </label>
                  </>
                )}
                {/* --- Tuning parameters --- */}
                <label className="control-row">
                  <span className="control-label">KP Yaw</span>
                  <input
                    type="range"
                    min="0"
                    max="20"
                    step="0.1"
                    value={config.kp_yaw}
                    onChange={(e) => onSlider("kp_yaw", e.target.value)}
                  />
                  <span className="control-value">{config.kp_yaw.toFixed(1)}</span>
                </label>
                <label className="control-row">
                  <span className="control-label">Max Yaw Rate</span>
                  <input
                    type="range"
                    min="10"
                    max="360"
                    step="5"
                    value={config.max_yawspeed}
                    onChange={(e) => onSlider("max_yawspeed", e.target.value)}
                  />
                  <span className="control-value">{config.max_yawspeed.toFixed(0)}°/s</span>
                </label>
                <label className="control-row">
                  <span className="control-label">Dead Zone Yaw</span>
                  <input
                    type="range"
                    min="0"
                    max="15"
                    step="0.5"
                    value={config.dead_zone_deg}
                    onChange={(e) => onSlider("dead_zone_deg", e.target.value)}
                  />
                  <span className="control-value">{config.dead_zone_deg.toFixed(1)}°</span>
                </label>
                <label className={`control-row${config.yaw_only ? " disabled" : ""}`}>
                  <span className="control-label">Max Fwd Accel</span>
                  <input
                    type="range"
                    min="0.1"
                    max="10"
                    step="0.1"
                    value={config.max_forward_accel}
                    disabled={config.yaw_only}
                    onChange={(e) => onSlider("max_forward_accel", e.target.value)}
                  />
                  <span className="control-value">{config.max_forward_accel.toFixed(1)} m/s²</span>
                </label>
                <label className={`control-row${config.yaw_only ? " disabled" : ""}`}>
                  <span className="control-label">Dead Zone BBox %</span>
                  <input
                    type="range"
                    min="0"
                    max="50"
                    step="1"
                    value={config.dead_zone_bbox_percent}
                    disabled={config.yaw_only}
                    onChange={(e) => onSlider("dead_zone_bbox_percent", e.target.value)}
                  />
                  <span className="control-value">{config.dead_zone_bbox_percent.toFixed(0)}%</span>
                </label>
                <label className="control-row">
                  <span className="control-label">Yaw Smooth</span>
                  <div className="toggle-wrapper">
                    <button
                      className={`toggle-btn ${config.smooth_yaw ? "toggle-on" : ""}`}
                      onClick={() => onToggle("smooth_yaw")}
                    >
                      {config.smooth_yaw ? "ON" : "OFF"}
                    </button>
                  </div>
                </label>
                <label className="control-row">
                  <span className="control-label">Yaw Alpha</span>
                  <input
                    type="range"
                    min="0.01"
                    max="1.0"
                    step="0.01"
                    value={config.yaw_alpha}
                    onChange={(e) => onSlider("yaw_alpha", e.target.value)}
                  />
                  <span className="control-value">{config.yaw_alpha.toFixed(2)}</span>
                </label>
                <label className={`control-row${config.yaw_only ? " disabled" : ""}`}>
                  <span className="control-label">Fwd Smooth</span>
                  <div className="toggle-wrapper">
                    <button
                      className={`toggle-btn ${config.smooth_forward ? "toggle-on" : ""}`}
                      disabled={config.yaw_only}
                      onClick={() => onToggle("smooth_forward")}
                    >
                      {config.smooth_forward ? "ON" : "OFF"}
                    </button>
                  </div>
                </label>
                <label className={`control-row${config.yaw_only ? " disabled" : ""}`}>
                  <span className="control-label">Fwd Alpha</span>
                  <input
                    type="range"
                    min="0.01"
                    max="1.0"
                    step="0.01"
                    value={config.forward_alpha}
                    disabled={config.yaw_only}
                    onChange={(e) => onSlider("forward_alpha", e.target.value)}
                  />
                  <span className="control-value">{config.forward_alpha.toFixed(2)}</span>
                </label>
                <label className={`control-row${config.yaw_only ? " disabled" : ""}`}>
                  <span className="control-label">Right Smooth</span>
                  <div className="toggle-wrapper">
                    <button
                      className={`toggle-btn ${config.smooth_right ? "toggle-on" : ""}`}
                      disabled={config.yaw_only}
                      onClick={() => onToggle("smooth_right")}
                    >
                      {config.smooth_right ? "ON" : "OFF"}
                    </button>
                  </div>
                </label>
                <label className={`control-row${config.yaw_only ? " disabled" : ""}`}>
                  <span className="control-label">Right Alpha</span>
                  <input
                    type="range"
                    min="0.01"
                    max="1.0"
                    step="0.01"
                    value={config.right_alpha}
                    disabled={config.yaw_only}
                    onChange={(e) => onSlider("right_alpha", e.target.value)}
                  />
                  <span className="control-value">{config.right_alpha.toFixed(2)}</span>
                </label>
                <label className="control-row">
                  <span className="control-label">Down Smooth</span>
                  <div className="toggle-wrapper">
                    <button
                      className={`toggle-btn ${config.smooth_down ? "toggle-on" : ""}`}
                      onClick={() => onToggle("smooth_down")}
                    >
                      {config.smooth_down ? "ON" : "OFF"}
                    </button>
                  </div>
                </label>
                <label className="control-row">
                  <span className="control-label">Down Alpha</span>
                  <input
                    type="range"
                    min="0.01"
                    max="1.0"
                    step="0.01"
                    value={config.down_alpha}
                    onChange={(e) => onSlider("down_alpha", e.target.value)}
                  />
                  <span className="control-value">{config.down_alpha.toFixed(2)}</span>
                </label>
              </div>
            </div>
          )}
        </div>

        <div className="video-column">
          <div className="video-container">
        <canvas
          ref={canvasRef}
          className="video-feed"
        />
        {vw > 0 && vh > 0 && (
          <svg className="overlay" viewBox={`0 0 ${vw} ${vh}`}>
            {detections.map((det) => {
              const x = det.bbox.x * vw;
              const y = det.bbox.y * vh;
              const w = det.bbox.w * vw;
              const h = det.bbox.h * vh;
              const isFollowing =
                det.id != null && det.id === followingId;
              const hasId = det.id != null;

              return (
                <g
                  key={det.id ?? `${det.bbox.x}-${det.bbox.y}`}
                  onClick={hasId ? () => handleFollow(det.id) : undefined}
                  style={{ cursor: hasId ? "pointer" : "default", pointerEvents: "auto" }}
                >
                  <rect
                    x={x}
                    y={y}
                    width={w}
                    height={h}
                    fill="transparent"
                    stroke={isFollowing ? "#00ff00" : "#ffffff"}
                    strokeWidth={isFollowing ? 3 : 2}
                    strokeOpacity={0.9}
                  />
                  <text
                    x={x + 4}
                    y={y - 6}
                    fill={isFollowing ? "#00ff00" : "#ffffff"}
                    fontSize={14}
                    fontFamily="monospace"
                    fontWeight="bold"
                    style={{
                      textShadow: "1px 1px 2px rgba(0,0,0,0.8)",
                    }}
                  >
                    {hasId ? `ID: ${det.id}` : "person"}{" "}
                    ({Math.round(det.confidence * 100)}%) h:{det.bbox.h.toFixed(2)}
                  </text>
                </g>
              );
            })}
          </svg>
        )}
          </div>

          <div className="logs-panel side-card">
            <button
              className="controls-toggle"
              onClick={() => setLogsOpen((o) => !o)}
            >
              Logs {logsOpen ? "▲" : "▼"}
            </button>
            {logsOpen && (
              <div className="logs-body">
                {logs.map((entry) => (
                  <div key={entry.id} className="log-line">
                    {entry.msg}
                  </div>
                ))}
                <div ref={logEndRef} />
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
