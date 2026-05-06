"""Simulation-based integration tests.

Spawn `sim/start_sim.sh` (PX4 SITL + Gazebo + video bridge) and `drone-follow`
together, capture the per-frame JSONL log via `--test-log`, and assert on it.

These are slow (~1 minute capture per world, plus warmup) and require:
  - `sim/setup_sim.sh` to have been run (PX4-Autopilot built)
  - Gazebo Garden + gz-transport13 + gz-msgs10 installed
  - The repo-owned venv at ./venv with `drone-follow` installed
  - A Hailo accelerator (PCIe on dev box) reachable

Skipped unless RUN_SIM_TESTS=1. Run with `pytest -s` to see live progress.
"""

import json
import os
import signal
import subprocess
import time
from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SIM_SCRIPT = REPO_ROOT / "sim" / "start_sim.sh"
SETUP_ENV = REPO_ROOT / "setup_env.sh"
RECORDINGS_DIR = REPO_ROOT / "drone_follow" / "recordings"

WARMUP_S = 5
RUN_S = 60
SHUTDOWN_S = 10
PROGRESS_TICK_S = 5

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_SIM_TESTS") != "1",
    reason="set RUN_SIM_TESTS=1 to run simulation integration tests",
)


# ---------------------------------------------------------------------------
# Logging helpers
# ---------------------------------------------------------------------------

def _log(msg):
    print(f"[sim-test {time.strftime('%H:%M:%S')}] {msg}", flush=True)


def _size(path):
    try:
        return path.stat().st_size
    except FileNotFoundError:
        return -1


def _fmt_size(path):
    n = _size(path)
    return "missing" if n < 0 else f"{n:>7}B"


def _wait_with_progress(label, total_s, watch=()):
    """Sleep `total_s`, printing progress + sizes of `watch` files every tick."""
    start = time.monotonic()
    while True:
        elapsed = time.monotonic() - start
        remaining = total_s - elapsed
        if remaining <= 0:
            return
        time.sleep(min(PROGRESS_TICK_S, remaining))
        elapsed = time.monotonic() - start
        sizes = "  ".join(f"{p.name}={_fmt_size(p)}" for p in watch)
        _log(f"  {label}: +{elapsed:>4.1f}s / {total_s}s   {sizes}")


def _tail(path, n=25):
    if not path.exists():
        return f"(no file at {path})"
    try:
        data = path.read_bytes()
    except OSError as e:
        return f"(read error: {e})"
    lines = data.decode(errors="replace").splitlines()
    return "\n".join(lines[-n:])


def _kill_group(proc, timeout=SHUTDOWN_S):
    if proc is None or proc.poll() is not None:
        return
    pgid = os.getpgid(proc.pid)
    try:
        os.killpg(pgid, signal.SIGTERM)
        proc.wait(timeout=timeout)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        try:
            os.killpg(pgid, signal.SIGKILL)
        except ProcessLookupError:
            pass


# ---------------------------------------------------------------------------
# Fixture: spin up sim + drone-follow against a world, return the JSONL path
# ---------------------------------------------------------------------------

@pytest.fixture
def sim_run(tmp_path, request):
    procs = []
    state = {}  # populated by _run, consumed in teardown to tag recordings

    objective = (request.node.function.__doc__ or "").strip().splitlines()[0:1]
    objective = objective[0] if objective else ""
    test_name = request.node.name

    def _run(world, run_seconds=RUN_S, extra_args=(), reid=False):
        _log("=" * 72)
        _log(f"TEST       {test_name}")
        _log(f"WORLD      {world}")
        if objective:
            _log(f"OBJECTIVE  {objective}")
        if extra_args:
            _log(f"EXTRA ARGS {' '.join(extra_args)}")
        _log("=" * 72)

        log_path = tmp_path / f"{world}.jsonl"
        sim_log_path = tmp_path / f"{world}.sim.log"
        app_log_path = tmp_path / f"{world}.app.log"
        sim_log = open(sim_log_path, "wb")
        app_log = open(app_log_path, "wb")

        # Snapshot existing recordings so we can identify the new mp4 created
        # by --record after the run.
        state["world"] = world
        state["recordings_before"] = (
            set(RECORDINGS_DIR.glob("*.mp4")) if RECORDINGS_DIR.exists() else set()
        )

        _log(f"artifacts  {tmp_path}")
        _log(f"starting sim: {SIM_SCRIPT.name} --bridge --world {world}")
        sim_env = os.environ.copy()
        sim_env.setdefault("HEADLESS", "1")
        sim = subprocess.Popen(
            [str(SIM_SCRIPT), "--bridge", "--world", world],
            preexec_fn=os.setsid, env=sim_env,
            stdout=sim_log, stderr=subprocess.STDOUT,
        )
        procs.append(sim)
        _log(f"sim pid={sim.pid} — warming up for {WARMUP_S}s")
        _wait_with_progress("warmup", WARMUP_S, watch=(sim_log_path,))
        if sim.poll() is not None:
            _log(f"sim exited early (rc={sim.returncode}); last sim log lines:")
            print(_tail(sim_log_path), flush=True)
            raise RuntimeError(
                f"sim exited early (code={sim.returncode}); see {sim_log_path}"
            )

        # Tile / multi-scale shape comes from drone-follow's own defaults
        # (drone_follow/pipeline_defaults.py). Tests can still override
        # by passing --tiles-x etc. via extra_args (CLI beats default).
        extra = (" " + " ".join(extra_args)) if extra_args else ""
        reid_flag = "" if reid else " --no-reid"
        cmd = (
            f"source {SETUP_ENV} && "
            f"drone-follow --input udp://0.0.0.0:5600 --webui{reid_flag} "
            f"--no-yaw-only --takeoff-landing "
            f"--record --test-log {log_path}{extra}"
        )
        _log(f"starting drone-follow -> {log_path.name}")
        app = subprocess.Popen(
            ["bash", "-lc", cmd],
            preexec_fn=os.setsid,
            stdout=app_log, stderr=subprocess.STDOUT,
        )
        procs.append(app)
        _log(f"drone-follow pid={app.pid} — capturing for {run_seconds}s")
        _wait_with_progress(
            "capture", run_seconds,
            watch=(log_path, app_log_path, sim_log_path),
        )
        if app.poll() is not None:
            _log(f"drone-follow exited early (rc={app.returncode}); last app log lines:")
            print(_tail(app_log_path), flush=True)

        # Shut drone-follow down here — before returning the log path — so the
        # test body sees fully-flushed JSONL, a finalized recording, and any
        # --reid-dump-embeddings file. main()'s `finally:` block (which calls
        # reid_manager.dump_embeddings() and closes the test log) only runs on
        # SIGTERM, so without this the test asserts on a file that hasn't been
        # written yet.
        _log("shutting down drone-follow so artifacts are flushed before assertions")
        _kill_group(app)
        procs.remove(app)
        return log_path

    yield _run

    _log("tearing down processes")
    # Tear down app first so it can flush, then sim
    for p in reversed(procs):
        _kill_group(p)

    # Tag any newly-produced recording with the world name so the user can
    # find it after the run. SIGTERM to the app's process group should have
    # let ffmpeg finalize the mp4 cleanly.
    if state.get("world") and RECORDINGS_DIR.exists():
        before = state.get("recordings_before", set())
        new_files = sorted(set(RECORDINGS_DIR.glob("*.mp4")) - before)
        for src in new_files:
            dst = src.with_name(f"{src.stem}_{state['world']}.mp4")
            try:
                src.rename(dst)
                _log(f"recording  {dst}   ({_fmt_size(dst).strip()})")
            except OSError as e:
                _log(f"recording  rename failed: {e} (file at {src})")
        if not new_files:
            _log("recording  (no new mp4 produced — recording may not have started)")


# ---------------------------------------------------------------------------
# JSONL helpers
# ---------------------------------------------------------------------------

def _read_jsonl(path):
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def _summarize(world, log):
    """Compute and log summary stats from a JSONL frame log."""
    n = len(log)
    n_det = sum(1 for r in log if r["detections"])
    multi = sum(1 for r in log if len(r["detections"]) >= 2)
    ids = {d["id"] for r in log for d in r["detections"] if d["id"] is not None}
    avg_dets = (sum(len(r["detections"]) for r in log) / n) if n else 0.0
    heights = [d["bbox"][3] for r in log for d in r["detections"]]
    h_min = min(heights) if heights else 0.0
    h_max = max(heights) if heights else 0.0
    _log(f"== {world} summary ==")
    _log(f"  frames={n}   frames_with_det={n_det} ({n_det / max(n, 1):.0%})")
    _log(f"  frames_with_>=2_det={multi}   avg_dets/frame={avg_dets:.2f}")
    _log(f"  unique_track_ids={len(ids)} -> {sorted(ids)[:12]}{'...' if len(ids) > 12 else ''}")
    _log(f"  bbox_height range=[{h_min:.3f} .. {h_max:.3f}]  spread={h_max - h_min:.3f}")
    return {"n": n, "n_det": n_det, "multi": multi, "ids": ids,
            "h_min": h_min, "h_max": h_max}


# Smoke threshold: how many frames out of ~60 s @ 25-50 fps must contain a
# detection before we consider the pipeline functional. Loose on purpose —
# these tests are about "did the sim wire up", not detector quality.
MIN_FRAMES_WITH_DETECTION = 120

# Pairwise cosine-similarity gate for the ReID gallery dump lives in
# _reid_gate.py so test_reid_gallery_coherence_gate.py reads the same
# thresholds and can prove the gate catches a swapped gallery.
from drone_follow.tests._reid_gate import REID_PAIR_MEAN, REID_PAIR_MIN


# ---------------------------------------------------------------------------
# Per-world tests
# ---------------------------------------------------------------------------

def test_person_in_front_holds_one_id(sim_run):
    """Static single person facing the camera — one ByteTracker ID expected."""
    # Tile shape (3x2 + 1x1 multi-scale) comes from sim_run's TILE_FLAGS
    # default — same shape that ``scripts/start_air.sh`` uses in
    # production. Source: ``drone_follow/pipeline_defaults.py``.
    log = _read_jsonl(sim_run("person_in_front"))
    s = _summarize("person_in_front", log)

    assert s["n"] > 0, "no log lines written — drone-follow likely never started"
    assert s["n_det"] > MIN_FRAMES_WITH_DETECTION, (
        f"only {s['n_det']}/{s['n']} frames had detections "
        f"— sim or video bridge probably failed to feed frames"
    )
    # Slack of 3: allow for a couple of bytetracker hiccups over a 60 s run
    assert len(s["ids"]) <= 3, (
        f"ByteTracker produced {len(s['ids'])} IDs ({sorted(s['ids'])}) for a "
        f"single static person — expected <= 3"
    )


def test_2_person_world_sees_both_actors(sim_run):
    """Two stationary actors at (3,0) and (3,3) for the first 20s — should both be visible.

    After t=20 they walk a 22 m rectangular path (max range ~25 m). Test
    only asserts visibility during the loop; geometry of the early static
    phase is intentionally close so the sim's wide-FOV camera frames both
    actors comfortably."""
    log = _read_jsonl(sim_run("2_person_world"))
    s = _summarize("2_person_world", log)

    assert s["n"] > 0
    assert s["n_det"] > MIN_FRAMES_WITH_DETECTION, (
        f"only {s['n_det']}/{s['n']} frames had detections"
    )
    assert s["multi"] > 20, (
        f"only {s['multi']}/{s['n']} frames saw >= 2 persons — expected both "
        f"actors visible together while still side-by-side"
    )


def test_2_persons_diagonal_keeps_initial_target(sim_run, tmp_path):
    """Two actors walk diagonals that cross in front of the drone (~10,0).

    One wears green, the other red, so ReID has a colour cue to disambiguate
    them at the crossing. The drone should lock onto whichever person it
    selects first (largest in frame) and keep following that same one through
    the cross — not silently swap to the other actor.

    Dumps every embedding accepted into the ReID gallery during the run, then
    asserts pairwise cosine similarity is high — if the tracker swapped onto
    the other actor and stored *their* embedding under the same target, the
    gallery would mix two persons and the pairwise stats would tank. Embedding
    file is deleted at the end.
    """
    emb_path = tmp_path / "reid_embeddings.npy"
    try:
        log = _read_jsonl(sim_run(
            "2_persons_diagonal", reid=True,
            extra_args=("--reid-dump-embeddings", str(emb_path)),
        ))
        s = _summarize("2_persons_diagonal", log)

        assert s["n"] > 0
        assert s["n_det"] > MIN_FRAMES_WITH_DETECTION
        assert s["multi"] > 10, (
            f">= 2 persons visible in only {s['multi']}/{s['n']} frames — at "
            f"least some overlap window expected during the diagonal pass"
        )

        followed = [r.get("followed_id") for r in log if r.get("followed_id") is not None]
        assert len(followed) > MIN_FRAMES_WITH_DETECTION, (
            f"only {len(followed)}/{s['n']} frames had a followed_id — drone "
            f"never locked onto anyone, follow logic likely off"
        )

        assert emb_path.exists(), (
            f"no embedding dump at {emb_path} — ReID never accepted a "
            f"single embedding; gallery wiring or extractor likely broken"
        )
        embs = np.load(emb_path)
        assert embs.ndim == 2 and embs.shape[0] >= 4, (
            f"only {embs.shape[0] if embs.ndim == 2 else 0} accepted "
            f"embedding(s) — too few to assess coherence; expected the "
            f"gallery to update through ~60 s of follow"
        )

        # Embeddings are L2-normalized, so a @ b.T is cosine similarity.
        sim = embs @ embs.T
        iu = np.triu_indices(embs.shape[0], k=1)
        pairs = sim[iu]
        min_sim = float(pairs.min())
        mean_sim = float(pairs.mean())
        _log(f"  reid embeddings: n={embs.shape[0]}  pair_min={min_sim:.3f}  "
             f"pair_mean={mean_sim:.3f}")

        # If the gallery silently mixed two distinct people across the cross,
        # cross-person pairs would land in the 0.2–0.4 range and pull both
        # stats down hard. Same person across pose changes typically stays
        # well above 0.5, with mean ≥ 0.7.
        assert min_sim >= REID_PAIR_MIN, (
            f"ReID gallery contains an outlier embedding (min pairwise "
            f"sim={min_sim:.3f}) — likely a frame where the tracker swapped "
            f"to the other actor and that crop got accepted into the gallery"
        )
        assert mean_sim >= REID_PAIR_MEAN, (
            f"ReID gallery embeddings are not coherent (mean pairwise "
            f"sim={mean_sim:.3f}) — gallery probably contains a mix of "
            f"both actors rather than a single person"
        )
    finally:
        try:
            emb_path.unlink()
        except FileNotFoundError:
            pass


def test_walk_across_then_approach_holds_target_through_approach(sim_run):
    """Actor walks sideways then approaches the camera (Phase 3, t_world=40..53).

    The whole point of this world is to stress what happens as the target
    grows in frame, so the assertion targets the approach window itself: the
    contiguous span of frames where the largest bbox height >= 0.15 of frame.
    Within that window we expect detections and tracker IDs to remain
    near-continuous — losing the target while it's close + centred is the
    failure mode this test exists to catch.
    """
    # 90 s captures: sideways walk (~30 s) + approach (~13 s) + offscreen
    # loop reset (~14 s) + return into view from the loop restart (~10 s).
    log = _read_jsonl(sim_run("walk_across_then_approach", run_seconds=90))
    s = _summarize("walk_across_then_approach", log)

    assert s["n"] > 0
    assert s["n_det"] > MIN_FRAMES_WITH_DETECTION

    # Find the approach window: first..last frame whose largest bbox height
    # crosses the "close" threshold. Including the gaps between qualifying
    # frames means a mid-approach dropout counts against us.
    APPROACH_H = 0.15
    big = [
        i for i, r in enumerate(log)
        if r["detections"] and max(d["bbox"][3] for d in r["detections"]) >= APPROACH_H
    ]
    assert big, (
        f"no frames had bbox h >= {APPROACH_H} — actor never came close enough, "
        f"sim wiring may be off"
    )
    window = log[big[0]:big[-1] + 1]
    n_w = len(window)
    n_det_w = sum(1 for r in window if r["detections"])
    n_id_w = sum(1 for r in window if any(d["id"] is not None for d in r["detections"]))
    _log(f"  approach window: {n_w} frames  with_det={n_det_w}  with_id={n_id_w}")

    # Approach is ~13 s of world time -> ~390 frames at 30 fps. Demand at
    # least ~3 s of close-frames so we know the actor really did approach.
    assert n_w >= 90, (
        f"approach window only {n_w} frames — actor barely got close, world or "
        f"camera framing may be off"
    )
    # During the approach the detector should keep firing on the (large,
    # centred) target. A 14-s dropout at the end of the existing 60-s run is
    # exactly what this catches.
    assert n_det_w / n_w >= 0.9, (
        f"approach window: only {n_det_w}/{n_w} frames had a detection — "
        f"target lost while close to the drone"
    )
    # And ByteTracker should hold an ID across the approach. id=None
    # detections (detector fired but tracker dropped the track) count as a
    # failure here — that's the regression mode the prior run exhibited.
    assert n_id_w / n_w >= 0.8, (
        f"approach window: only {n_id_w}/{n_w} frames had a tracker ID — "
        f"ByteTracker dropped the target during the close approach"
    )


def test_circle_around_keeps_target_in_view(sim_run):
    """Actor walks a 5 m circle around origin — visible most of the time."""
    log = _read_jsonl(sim_run("circle_around"))
    s = _summarize("circle_around", log)

    assert s["n"] > 0
    assert s["n_det"] > MIN_FRAMES_WITH_DETECTION, (
        f"only {s['n_det']}/{s['n']} frames saw the circling actor — drone view "
        f"may be misaligned"
    )


def test_random_walk_produces_detections(sim_run):
    """Random-walk actor — smoke test that the pipeline detects something."""
    log = _read_jsonl(sim_run("random_walk"))
    s = _summarize("random_walk", log)

    assert s["n"] > 0
    assert s["n_det"] > 80, (
        f"only {s['n_det']}/{s['n']} frames saw the random-walk actor"
    )
