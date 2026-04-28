"""Controller configuration — pure dataclass, no third-party dependencies."""

import argparse
import json
import os
from dataclasses import dataclass, fields, asdict

# Default path for live save/load from the web UI and QOpenHD triggers.
# Lives at the repo root next to the schema `df_params.json` so the pair is
# easy to find. .gitignored — the JSON holds the operator's tuning, not
# something to be committed.
DEFAULT_CONFIG_PATH = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)),
                 "..", "..", "df_config.json")
)


@dataclass
class ControllerConfig:
    hfov: float = 66.0
    vfov: float = 41.0
    # --- Yaw (horizontal centering): center_x → yawspeed ---
    kp_yaw: float = 5
    dead_zone_deg: float = 2.0
    max_yawspeed: float = 90.0
    # --- Forward (distance via bbox): bbox_height → forward_m_s ---
    max_forward: float = 2.0
    max_backward: float = 3.0
    max_forward_accel: float = 1.5      # slew-rate cap on forward (m/s²); tilt-transient safety
    # Distance-error P. Operates on (target/bbox - 1), the relative distance
    # error (bbox ∝ 1/distance). Scale-invariant: factor=1 means person is 2×
    # target distance regardless of absolute bbox size.
    kp_distance: float = 1.0            # gain for distance error → forward
    target_bbox_height: float = 0.25    # desired person size in frame (0-0.25)
    dead_zone_bbox_percent: float = 10.0  # dead zone: |factor| as fraction (10 → ±10% of target)
    max_climb_speed: float = 1.0        # max altitude change rate (m/s)
    max_down_speed: float = 1.5         # safety clamp in VelocityCommandAPI
    min_altitude: float = 2.0           # hard floor (m)
    max_altitude: float = 4.0           # hard ceiling (m)
    # Altitude-hold P gain: drives down axis from (current_alt - target_altitude)
    # whenever not yaw_only. Applied in live_control_loop where current altitude
    # is available; controller stays pure.
    kp_alt_hold: float = 0.5
    # --- Safety ---
    max_bbox_height_safety: float = 0.8  # bbox > this → emergency climb + reverse
    # Frame-edge safety: when bbox top/bottom breaches a margin from the frame
    # edge, override forward to keep the person framed.
    #   bbox bottom enters bottom margin → person too close → max backward
    #   bbox top    enters top    margin → person too far  → max forward
    # A pre-margin fade zone of equal width sits just outside the margin: the
    # bbox-driven natural command in the offending direction fades linearly to
    # zero across that zone, so when the bbox arrives at the margin boundary
    # the natural command is already 0. This removes the binary handoff that
    # caused approach/back-off oscillation around the boundary.
    # 0 disables the override on that edge.
    top_margin_safety: float = 0.10
    bottom_margin_safety: float = 0.10
    # --- Modes ---
    yaw_only: bool = True
    auto_select: bool = True          # when False: clear/loss → IDLE (hold position); no autonomous re-acquisition
    follow_mode: str = "follow"       # "follow" or "orbit"
    orbit_speed_m_s: float = 1.0      # lateral velocity for orbit (m/s)
    orbit_direction: int = 1          # +1 = clockwise, -1 = counter-clockwise
    max_orbit_speed: float = 3.0      # max lateral speed limit
    # --- Search ---
    detection_timeout_s: float = 0.5
    search_enter_delay_s: float = 2.0
    search_timeout_s: float = 60.0
    search_yawspeed_slow: float = 10.0  # yaw speed during search (slower than tracking)
    control_loop_hz: float = 10.0
    # --- Per-axis EMA smoothing ---
    smooth_yaw: bool = True
    yaw_alpha: float = 0.3              # 0=very smooth, 1=no smoothing
    smooth_forward: bool = True
    forward_alpha: float = 0.15         # moderate smoothing on forward velocity
    smooth_right: bool = True           # smooth lateral axis (orbit transitions)
    right_alpha: float = 0.3            # moderate smoothing for orbit transitions
    smooth_down: bool = True            # smooth bbox_height-driven altitude output
    down_alpha: float = 0.2             # moderate smoothing to reduce alt jitter
    # --- Takeoff/misc ---
    target_altitude: float = 3.0        # initial altitude for --takeoff-landing; UI "Target Alt" adjusts this as a soft reference
    log_verbosity: str = "normal"  # quiet | normal | debug

    def __post_init__(self):
        self.validate()

    def validate(self):
        """Raise ValueError if the configuration is internally inconsistent."""
        if self.min_altitude >= self.max_altitude:
            raise ValueError(f"min_altitude ({self.min_altitude}) must be < max_altitude ({self.max_altitude})")

    # ── JSON serialization ──────────────────────────────────────────

    def to_dict(self) -> dict:
        """Return config as a plain dict (JSON-safe)."""
        return asdict(self)

    def save_json(self, path: str) -> None:
        """Write current config to a JSON file."""
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)

    @classmethod
    def from_json(cls, path: str) -> "ControllerConfig":
        """Load config from a JSON file.  Unknown keys are silently ignored."""
        with open(path) as f:
            data = json.load(f)
        valid_names = {field.name for field in fields(cls)}
        filtered = {k: v for k, v in data.items() if k in valid_names}
        return cls(**filtered)

    def load_from_file(self, path: str) -> list:
        """Mutate this ControllerConfig in place from a JSON file.

        Used for live reload from the web UI / QOpenHD trigger, where other
        components (servers, control loop) hold a reference to the same object
        and must see the new values. Existing fields not present in the file
        are left alone. Unknown keys in the file are ignored.

        Returns the list of field names that actually changed (useful for
        logging / UI status). Raises on invalid JSON, missing file, or
        post-load validation failure (in which case previous values are restored).
        """
        with open(path) as f:
            data = json.load(f)
        valid_names = {field.name for field in fields(self)}
        updates = {k: v for k, v in data.items() if k in valid_names}
        snapshot = {k: getattr(self, k) for k in updates}
        changed = []
        for k, v in updates.items():
            if getattr(self, k) != v:
                setattr(self, k, v)
                changed.append(k)
        try:
            self.validate()
        except ValueError:
            # roll back on validation error
            for k, old_val in snapshot.items():
                setattr(self, k, old_val)
            raise
        return changed

    @staticmethod
    def add_args(parser: argparse.ArgumentParser) -> None:
        """Register controller-related CLI flags on *parser*."""
        defaults = ControllerConfig()
        group = parser.add_argument_group("follow-controller")

        group.add_argument("--config", default=None, metavar="JSON",
                           help="Path to a JSON config file. CLI flags override JSON values. "
                                "Use --save-config to dump current defaults.")
        group.add_argument("--save-config", default=None, metavar="JSON",
                           help="Save the effective config to a JSON file and exit.")

        # Framing and target geometry
        group.add_argument("--hfov", type=float, default=defaults.hfov)
        group.add_argument("--vfov", type=float, default=defaults.vfov)
        group.add_argument("--target-bbox-height", type=float, default=None,
                           help=f"Target bbox height (0-1) for distance control. "
                                f"Used as the pre-lock default; when a target is locked (manual click or AUTO "
                                f"acquisition) the current bbox height is captured as the setpoint so the drone "
                                f"holds its current distance. Operator can adjust via the UI slider at any time "
                                f"(default: {defaults.target_bbox_height}).")

        # Distance control (bbox_height → forward)
        group.add_argument("--distance-gain", dest="kp_distance", type=float, default=defaults.kp_distance,
                           help=f"Gain for (target/bbox - 1) → forward. "
                                f"Default {defaults.kp_distance} saturates max_forward at factor=1 "
                                f"(person at 2× target distance).")
        group.add_argument("--dead-zone-bbox-percent", type=float, default=defaults.dead_zone_bbox_percent,
                           help=f"Distance dead zone as %% of target bbox height (default: {defaults.dead_zone_bbox_percent})")
        group.add_argument("--max-climb-speed", type=float, default=defaults.max_climb_speed,
                           help=f"Max altitude change rate m/s (default: {defaults.max_climb_speed})")
        group.add_argument("--min-altitude", type=float, default=defaults.min_altitude,
                           help=f"Hard altitude floor in metres (default: {defaults.min_altitude})")
        group.add_argument("--max-altitude", type=float, default=defaults.max_altitude,
                           help=f"Hard altitude ceiling in metres (default: {defaults.max_altitude})")

        # Controller gains and loop behavior
        group.add_argument("--control-loop-hz", type=float, default=defaults.control_loop_hz)
        group.add_argument("--yaw-gain", dest="kp_yaw", type=float, default=defaults.kp_yaw)

        # Flight mode
        group.add_argument("--yaw-only", action=argparse.BooleanOptionalAction, default=defaults.yaw_only,
                           help="Yaw only mode: no forward/backward or altitude movement (default: True). Use --no-yaw-only for full follow.")
        group.add_argument("--auto-select", action=argparse.BooleanOptionalAction, default=defaults.auto_select,
                           help=f"When on, AUTO mode re-acquires the biggest person whenever the target is cleared or lost. "
                                f"When off, the drone holds position on loss/clear — pilot-led workflow "
                                f"(default: {defaults.auto_select}). Use --no-auto-select to disable.")

        # Search/follow behavior
        group.add_argument("--search-enter-delay", type=float, default=defaults.search_enter_delay_s,
                           help="Seconds without detection before active search starts (default: 2.0)")
        group.add_argument("--search-timeout", type=float, default=defaults.search_timeout_s,
                           help="Seconds before landing if no person is found (default: 60.0)")

        # Smoothing
        group.add_argument("--smooth-forward", action=argparse.BooleanOptionalAction, default=defaults.smooth_forward,
                           help=f"Enable/disable forward velocity smoothing (default: {defaults.smooth_forward})")
        group.add_argument("--forward-alpha", type=float, default=defaults.forward_alpha,
                           help=f"EMA smoothing factor for forward velocity (0=sluggish, 1=no smoothing, default: {defaults.forward_alpha})")
        group.add_argument("--smooth-right", action=argparse.BooleanOptionalAction, default=defaults.smooth_right,
                           help=f"Enable/disable lateral velocity smoothing (default: {defaults.smooth_right})")
        group.add_argument("--right-alpha", type=float, default=defaults.right_alpha,
                           help=f"EMA smoothing factor for lateral velocity (0=sluggish, 1=no smoothing, default: {defaults.right_alpha})")
        group.add_argument("--smooth-down", action=argparse.BooleanOptionalAction, default=defaults.smooth_down,
                           help=f"Enable/disable vertical velocity smoothing (default: {defaults.smooth_down})")
        group.add_argument("--down-alpha", type=float, default=defaults.down_alpha,
                           help=f"EMA smoothing factor for vertical velocity (0=sluggish, 1=no smoothing, default: {defaults.down_alpha})")

        # Safety limits
        group.add_argument("--max-forward", type=float, default=defaults.max_forward,
                           help=f"Max forward speed in m/s (default: {defaults.max_forward})")
        group.add_argument("--max-backward", type=float, default=defaults.max_backward,
                           help=f"Max backward speed in m/s (default: {defaults.max_backward})")
        group.add_argument("--max-forward-accel", type=float, default=defaults.max_forward_accel,
                           help=f"Slew-rate cap on forward velocity in m/s² (tilt-transient safety). "
                                f"Independent of EMA and of --max-forward (default: {defaults.max_forward_accel}).")
        group.add_argument("--max-bbox-height-safety", type=float, default=defaults.max_bbox_height_safety,
                           help="Safety limit: stop/retreat if bbox height > limit (0.0-1.0) (default: 0.8)")
        group.add_argument("--top-margin-safety", type=float, default=defaults.top_margin_safety,
                           help=f"Frame-top safety: bbox top closer than this fraction of frame "
                                f"(0-1) → force max forward. 0 disables (default: {defaults.top_margin_safety}).")
        group.add_argument("--bottom-margin-safety", type=float, default=defaults.bottom_margin_safety,
                           help=f"Frame-bottom safety: bbox bottom closer than this fraction of frame "
                                f"(0-1) → force max backward. 0 disables (default: {defaults.bottom_margin_safety}).")

        # Orbit mode
        group.add_argument("--follow-mode", choices=["follow", "orbit"], default=defaults.follow_mode,
                           help="Follow mode: 'follow' (default) or 'orbit' (circle around target)")
        group.add_argument("--orbit-speed", type=float, default=defaults.orbit_speed_m_s,
                           help=f"Lateral velocity for orbit mode in m/s (default: {defaults.orbit_speed_m_s})")
        group.add_argument("--orbit-direction", type=int, choices=[1, -1], default=defaults.orbit_direction,
                           help="Orbit direction: 1=clockwise (default), -1=counter-clockwise")

        # Logging
        group.add_argument("--log-verbosity", choices=["quiet", "normal", "debug"], default=defaults.log_verbosity,
                           help="Console log verbosity (default: normal)")

    @classmethod
    def from_args(cls, args):
        # If a JSON config was supplied, use it as the base defaults.
        json_path = getattr(args, "config", None)
        if json_path:
            defaults = cls.from_json(json_path)
        else:
            defaults = cls()

        def _arg(*names, default):
            for name in names:
                value = getattr(args, name, None)
                if value is not None:
                    return value
            return default

        # yaw_only: only True when user explicitly passed --yaw-only.
        yaw_only = _arg("yaw_only", default=defaults.yaw_only)
        if not isinstance(yaw_only, bool):
            yaw_only = bool(yaw_only)

        return cls(
            hfov=_arg("hfov", default=defaults.hfov),
            vfov=_arg("vfov", default=defaults.vfov),
            kp_yaw=_arg("kp_yaw", "yaw_gain", default=defaults.kp_yaw),
            target_bbox_height=_arg("target_bbox_height", default=defaults.target_bbox_height),
            kp_distance=_arg("kp_distance", "distance_gain", default=defaults.kp_distance),
            dead_zone_bbox_percent=_arg("dead_zone_bbox_percent", default=defaults.dead_zone_bbox_percent),
            max_climb_speed=_arg("max_climb_speed", default=defaults.max_climb_speed),
            min_altitude=_arg("min_altitude", default=defaults.min_altitude),
            max_altitude=_arg("max_altitude", default=defaults.max_altitude),
            yaw_only=yaw_only,
            auto_select=bool(_arg("auto_select", default=defaults.auto_select)),
            detection_timeout_s=_arg("detection_timeout", "detection_timeout_s", default=defaults.detection_timeout_s),
            search_enter_delay_s=_arg("search_enter_delay", "search_enter_delay_s", default=defaults.search_enter_delay_s),
            control_loop_hz=_arg("control_loop_hz", default=defaults.control_loop_hz),
            max_forward=_arg("max_forward", default=defaults.max_forward),
            max_backward=_arg("max_backward", default=defaults.max_backward),
            max_forward_accel=_arg("max_forward_accel", default=defaults.max_forward_accel),
            max_bbox_height_safety=_arg("max_bbox_height_safety", default=defaults.max_bbox_height_safety),
            top_margin_safety=_arg("top_margin_safety", default=defaults.top_margin_safety),
            bottom_margin_safety=_arg("bottom_margin_safety", default=defaults.bottom_margin_safety),
            search_timeout_s=_arg("search_timeout", "search_timeout_s", default=defaults.search_timeout_s),
            smooth_yaw=_arg("smooth_yaw", default=defaults.smooth_yaw),
            yaw_alpha=_arg("yaw_alpha", default=defaults.yaw_alpha),
            smooth_forward=_arg("smooth_forward", default=defaults.smooth_forward),
            forward_alpha=_arg("forward_alpha", default=defaults.forward_alpha),
            smooth_right=_arg("smooth_right", default=defaults.smooth_right),
            right_alpha=_arg("right_alpha", default=defaults.right_alpha),
            smooth_down=_arg("smooth_down", default=defaults.smooth_down),
            down_alpha=_arg("down_alpha", default=defaults.down_alpha),
            follow_mode=_arg("follow_mode", default=defaults.follow_mode),
            orbit_speed_m_s=_arg("orbit_speed", "orbit_speed_m_s", default=defaults.orbit_speed_m_s),
            orbit_direction=_arg("orbit_direction", default=defaults.orbit_direction),
            max_orbit_speed=_arg("max_orbit_speed", default=defaults.max_orbit_speed),
            target_altitude=_arg("target_altitude", default=defaults.target_altitude),
            kp_alt_hold=_arg("kp_alt_hold", default=defaults.kp_alt_hold),
            log_verbosity=_arg("log_verbosity", default=defaults.log_verbosity),
        )
