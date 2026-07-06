"""SpectrumScheduler — round-robin FFT budgeting across (player, kp, axis).

Tested with a mock compute_fn so we can verify ordering and budget enforcement
without standing up the full motion analyzer.
"""
import numpy as np

from community.apps.pipeline_apps.rhythm_royale.spectrum_scheduler import (
    SpectrumScheduler,
)


def _fake_compute(player_id, kp_name, axis):
    # Returns a unique-but-deterministic tiny array so we can prove the right
    # spectrum landed in the cache.
    return np.array([float(player_id), hash(kp_name) % 1000, ord(axis)],
                    dtype=np.float32)


def test_runs_full_budget_after_1_second():
    sch = SpectrumScheduler(fft_budget_per_sec=40.0)
    sch.register(1, ["nose", "L_wrist", "R_wrist"])  # 6 keys (3 kp x 2 axis)
    # First tick establishes the baseline; no FFTs run.
    assert sch.tick(t_now=0.0, compute_fn=_fake_compute) == 0
    # Second tick at +1.0 s: 40 budget; queue has 6 keys, so we should
    # round-robin and run 40 FFTs total (each key refreshed ~6-7×).
    n = sch.tick(t_now=1.0, compute_fn=_fake_compute)
    assert n == 40


def test_fractional_budget_accumulates_across_short_ticks():
    """At 30 ticks/s and budget=30/s, each tick runs ~1 FFT on average via
    debt-tracking."""
    sch = SpectrumScheduler(fft_budget_per_sec=30.0)
    sch.register(1, ["nose"])  # 2 keys
    sch.tick(0.0, _fake_compute)
    total = 0
    for i in range(1, 31):
        total += sch.tick(i / 30.0, _fake_compute)
    # 30 ticks * 1 FFT/tick = 30 total, within a small fractional rounding
    # tolerance.
    assert abs(total - 30) <= 1


def test_cache_holds_latest_spectrum():
    sch = SpectrumScheduler(fft_budget_per_sec=100.0)
    sch.register(1, ["nose"])
    sch.tick(0.0, _fake_compute)
    sch.tick(1.0, _fake_compute)
    cached = sch.get(player_id=1, kp_name="nose", axis="x")
    assert cached is not None
    spec, t_stamp = cached
    np.testing.assert_array_equal(spec, _fake_compute(1, "nose", "x"))
    assert t_stamp == 1.0


def test_unregister_removes_player():
    sch = SpectrumScheduler(fft_budget_per_sec=100.0)
    sch.register(1, ["nose"])
    sch.register(2, ["nose"])
    sch.tick(0.0, _fake_compute)
    sch.tick(1.0, _fake_compute)
    assert sch.get(1, "nose", "x") is not None
    assert sch.get(2, "nose", "x") is not None
    sch.unregister(1)
    assert sch.get(1, "nose", "x") is None
    # Player 2's cache is untouched.
    assert sch.get(2, "nose", "x") is not None


def test_round_robin_order():
    """Consecutive ticks must refresh keys round-robin, not always the same."""
    sch = SpectrumScheduler(fft_budget_per_sec=2.0)  # 2 FFTs per second
    sch.register(1, ["nose", "L_wrist"])  # 4 keys total
    sch.tick(0.0, _fake_compute)
    sch.tick(1.0, _fake_compute)  # 2 FFTs
    # Get cache timestamps for all 4 keys.
    keys = [(1, "nose", "x"), (1, "nose", "y"),
            (1, "L_wrist", "x"), (1, "L_wrist", "y")]
    cached_after_first = [sch.get(*k) for k in keys]
    fresh_count_1 = sum(1 for c in cached_after_first if c is not None and c[1] == 1.0)
    assert fresh_count_1 == 2
    # Another tick: the OTHER two keys should now be fresh.
    sch.tick(2.0, _fake_compute)  # 2 more
    cached_after_second = [sch.get(*k) for k in keys]
    fresh_count_2 = sum(1 for c in cached_after_second if c is not None and c[1] == 2.0)
    assert fresh_count_2 == 2
    # The two keys fresh at t=1.0 should now be stale (still 1.0).
    fresh_keys_1 = {keys[i] for i, c in enumerate(cached_after_first)
                    if c is not None and c[1] == 1.0}
    fresh_keys_2 = {keys[i] for i, c in enumerate(cached_after_second)
                    if c is not None and c[1] == 2.0}
    assert fresh_keys_1.isdisjoint(fresh_keys_2)
