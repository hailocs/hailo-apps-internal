"""Tests for FollowTargetState."""

import threading
import time

import pytest

from drone_follow.follow_api.state import FollowTargetState


class TestFollowTargetState:
    """Test FollowTargetState thread-safe target management."""

    def test_initial_state_is_auto(self):
        """Initial state should be AUTO mode: no target, not paused, not locked."""
        state = FollowTargetState()
        assert state.get_target() is None
        assert state.is_paused() is False
        assert state.is_explicit_lock() is False

    def test_set_and_get_target(self):
        """Should store and retrieve target ID."""
        state = FollowTargetState()
        state.set_target(42)
        assert state.get_target() == 42

    def test_set_target_updates_last_seen(self):
        """Setting a target should update last_seen timestamp."""
        state = FollowTargetState()
        before = time.monotonic()
        state.set_target(10)
        last_seen = state.get_last_seen()
        after = time.monotonic()
        
        assert last_seen is not None
        assert before <= last_seen <= after

    def test_set_none_clears_target(self):
        """Setting None should clear the target."""
        state = FollowTargetState()
        state.set_target(5)
        assert state.get_target() == 5
        
        state.set_target(None)
        assert state.get_target() is None

    def test_update_last_seen_updates_timestamp(self):
        """update_last_seen should refresh the timestamp."""
        state = FollowTargetState()
        state.set_target(15)
        first_time = state.get_last_seen()
        
        time.sleep(0.01)
        state.update_last_seen()
        second_time = state.get_last_seen()
        
        assert second_time > first_time

    def test_get_last_seen_returns_none_initially(self):
        """last_seen should be None before setting a target."""
        state = FollowTargetState()
        assert state.get_last_seen() is None

    def test_get_last_seen_preserved_after_getting_target(self):
        """Reading target doesn't affect last_seen timestamp."""
        state = FollowTargetState()
        state.set_target(20)
        ts = state.get_last_seen()
        
        _ = state.get_target()
        _ = state.get_target()
        
        assert state.get_last_seen() == ts

    def test_concurrent_set_target(self):
        """Multiple threads can safely set target."""
        state = FollowTargetState()
        results = []
        
        def worker(target_id):
            state.set_target(target_id)
            time.sleep(0.001)
            results.append(state.get_target())
        
        threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        # Should have 10 results without crashes
        assert len(results) == 10
        # Final state should be one of the values
        assert state.get_target() in range(10)

    def test_concurrent_read_write(self):
        """Concurrent reads and writes should be safe."""
        state = FollowTargetState()
        state.set_target(100)
        read_results = []
        write_count = [0]
        
        def reader():
            for _ in range(50):
                val = state.get_target()
                read_results.append(val)
                time.sleep(0.0001)
        
        def writer():
            for i in range(50):
                state.set_target(i)
                write_count[0] += 1
                time.sleep(0.0001)
        
        reader_thread = threading.Thread(target=reader)
        writer_thread = threading.Thread(target=writer)
        
        reader_thread.start()
        writer_thread.start()
        reader_thread.join()
        writer_thread.join()
        
        assert len(read_results) == 50
        assert write_count[0] == 50
        # All reads should be valid integers or None
        assert all(isinstance(v, int) or v is None for v in read_results)

    def test_last_seen_persists_after_clearing_target(self):
        """Clearing target (set None) keeps last_seen timestamp."""
        state = FollowTargetState()
        state.set_target(7)
        ts_before = state.get_last_seen()

        time.sleep(0.01)
        state.set_target(None)

        # last_seen should still be the old timestamp
        assert state.get_last_seen() == ts_before
        assert state.get_target() is None

    def test_enter_auto_mode_from_locked(self):
        """enter_auto_mode should reset from locked state to auto."""
        state = FollowTargetState()
        state.set_target(42)
        state.set_paused(False)
        state.set_explicit_lock(True)

        state.enter_auto_mode()

        assert state.get_target() is None
        assert state.is_paused() is False
        assert state.is_explicit_lock() is False

    def test_enter_auto_mode_from_idle(self):
        """enter_auto_mode should clear paused state."""
        state = FollowTargetState()
        state.set_paused(True)
        state.set_target(None)

        state.enter_auto_mode()

        assert state.get_target() is None
        assert state.is_paused() is False
        assert state.is_explicit_lock() is False
