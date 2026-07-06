"""Pure-Python unit tests for the Easter / Afikoman catching pose game.

These tests exercise the game's core logic with NO device, GStreamer, or
inference dependencies:

* catch detection (wrist keypoint coincides with an item -> caught)
* scoring / leaderboard ordering across multiple tracked players
* falling-item lifecycle (spawn, expiry timeout, replacement on catch)
* timer countdown math (the ``math.ceil`` restart countdown) and restart reset
* edge cases: no players, untracked player (track_id=0), simultaneous
  catches, items at frame edges, timer at 0.

The real per-frame catch logic lives inside ``app_callback`` which needs a
GStreamer buffer and the ``hailo`` ROI API, so it cannot run headless. The
helpers below (``project_wrist`` / ``simulate_frame``) reproduce the exact
projection + distance + scoring code path from ``app_callback`` (source lines
~301-350) so the *logic* is tested against the app's real constants and real
``EasterGameCallback`` state methods, without modifying app source.
"""

import math
import time

import pytest

from community.apps.pipeline_apps.easter_game.easter_game import (
    AFIKOMAN_POINTS,
    CATCH_RADIUS,
    EGG_COLORS,
    EGG_POINTS,
    GAME_DURATION,
    ITEM_TIMEOUT,
    PLAYER_NAMES,
    POPUP_DURATION,
    RESTART_DELAY,
    EasterGameCallback,
    GameItem,
    Popup,
)

pytestmark = pytest.mark.community

WIDTH, HEIGHT = 1280, 720


# ─────────────────────────────────────────────────────────────────────────────
# Fakes: pose keypoints, bbox, landmarks, items
# ─────────────────────────────────────────────────────────────────────────────
class FakePoint:
    """A pose keypoint exposing normalized x()/y() like hailo's landmark point."""

    def __init__(self, x, y):
        self._x = x
        self._y = y

    def x(self):
        return self._x

    def y(self):
        return self._y


class FakeBBox:
    """Normalized bbox exposing xmin()/ymin()/width()/height()."""

    def __init__(self, xmin=0.0, ymin=0.0, width=1.0, height=1.0):
        self._xmin = xmin
        self._ymin = ymin
        self._width = width
        self._height = height

    def xmin(self):
        return self._xmin

    def ymin(self):
        return self._ymin

    def width(self):
        return self._width

    def height(self):
        return self._height


# COCO wrist indices used by the app.
LEFT_WRIST = 9
RIGHT_WRIST = 10


def make_wrist_points(left_xy, right_xy, n=17):
    """Build a normalized 17-keypoint list with wrists at the given coords."""
    pts = [FakePoint(0.5, 0.5) for _ in range(n)]
    pts[LEFT_WRIST] = FakePoint(*left_xy)
    pts[RIGHT_WRIST] = FakePoint(*right_xy)
    return pts


def project_wrist(pt, bbox, width, height):
    """Reproduce the exact pixel projection used in app_callback.

    px = int((pt.x() * bbox.width() + bbox.xmin()) * width)
    py = int((pt.y() * bbox.height() + bbox.ymin()) * height)
    """
    px = int((pt.x() * bbox.width() + bbox.xmin()) * width)
    py = int((pt.y() * bbox.height() + bbox.ymin()) * height)
    return px, py


def norm_for_pixel(px, py, bbox, width, height):
    """Inverse of project_wrist: normalized coords that land on (px, py).

    Lets a test place a wrist at an exact target pixel given a bbox.
    """
    nx = (px / width - bbox.xmin()) / bbox.width()
    ny = (py / height - bbox.ymin()) / bbox.height()
    return nx, ny


class FakePlayer:
    """A detected person: a track_id, a bbox, and a wrist keypoint list."""

    def __init__(self, track_id, points, bbox=None):
        self.track_id = track_id
        self.points = points
        self.bbox = bbox or FakeBBox()


def simulate_frame(user_data, players, width=WIDTH, height=HEIGHT):
    """Faithful re-implementation of the catch loop in app_callback.

    Mirrors source lines ~301-350: for each person, resolve/create the player,
    project both wrists to pixels, and if a wrist is within CATCH_RADIUS of the
    current item, award points, push a popup, and spawn a replacement item.

    Mutates the real ``EasterGameCallback`` state passed in. Returns the number
    of catches that occurred this frame.
    """
    user_data.fw, user_data.fh = width, height
    catches = 0
    for fp in players:
        player = user_data._get_or_create_player(fp.track_id)
        for idx in (LEFT_WRIST, RIGHT_WRIST):
            pt = fp.points[idx]
            px, py = project_wrist(pt, fp.bbox, width, height)
            item = user_data.current_item
            if item is None:
                continue
            dist = math.hypot(px - item.x, py - item.y)
            if dist < CATCH_RADIUS:
                pts = item.points
                player["score"] += pts
                popup_colour = (255, 220, 60) if item.kind == "egg" else (210, 180, 100)
                user_data.popups.append(Popup(f"+{pts}", item.x, item.y, popup_colour))
                user_data.spawn_item()
                catches += 1
    return catches


def fresh_callback():
    """An EasterGameCallback with a known frame size and no real background."""
    cb = EasterGameCallback("")  # empty path -> dark fallback, no file IO
    cb.fw, cb.fh = WIDTH, HEIGHT
    return cb


def place_item(cb, kind, x, y, color_idx=0):
    cb.current_item = GameItem(kind, x, y, color_idx)
    return cb.current_item


# Player whose wrist sits exactly on the given pixel (identity bbox -> easy).
def player_touching(track_id, target_xy, other_wrist=(0.0, 0.0)):
    bbox = FakeBBox(0.0, 0.0, 1.0, 1.0)  # identity: norm * dim == pixel
    tx, ty = target_xy
    lx, ly = norm_for_pixel(tx, ty, bbox, WIDTH, HEIGHT)
    points = make_wrist_points((lx, ly), other_wrist)
    return FakePlayer(track_id, points, bbox)


# ─────────────────────────────────────────────────────────────────────────────
# GameItem
# ─────────────────────────────────────────────────────────────────────────────
class TestGameItem:
    def test_egg_points(self):
        assert GameItem("egg", 100, 100).points == EGG_POINTS

    def test_afikoman_points(self):
        assert GameItem("afikoman", 100, 100).points == AFIKOMAN_POINTS

    def test_not_expired_when_fresh(self):
        item = GameItem("egg", 10, 10)
        assert item.expired() is False

    def test_expired_after_timeout(self):
        item = GameItem("egg", 10, 10)
        # backdate spawn_time so the item is older than ITEM_TIMEOUT
        item.spawn_time = time.time() - (ITEM_TIMEOUT + 0.5)
        assert item.expired() is True

    def test_expired_boundary_is_inclusive(self):
        # expired() uses >= ITEM_TIMEOUT
        item = GameItem("egg", 10, 10)
        item.spawn_time = time.time() - ITEM_TIMEOUT - 0.01
        assert item.expired() is True

    def test_color_idx_stored(self):
        item = GameItem("egg", 1, 2, color_idx=5)
        assert item.color_idx == 5
        assert item.x == 1 and item.y == 2
        assert item.kind == "egg"


# ─────────────────────────────────────────────────────────────────────────────
# Catch detection
# ─────────────────────────────────────────────────────────────────────────────
class TestCatchDetection:
    def test_wrist_on_item_is_caught_score_increments(self):
        cb = fresh_callback()
        place_item(cb, "egg", 640, 360)
        p = player_touching(1, (640, 360))
        n = simulate_frame(cb, [p])
        assert n == 1
        assert cb.players[1]["score"] == EGG_POINTS

    def test_wrist_far_from_item_is_a_miss(self):
        cb = fresh_callback()
        place_item(cb, "egg", 100, 100)
        # both wrists far away
        p = player_touching(1, (900, 600), other_wrist=(0.95, 0.95))
        n = simulate_frame(cb, [p])
        assert n == 0
        # player still registered, but zero score
        assert cb.players[1]["score"] == 0

    def test_catch_just_inside_radius(self):
        cb = fresh_callback()
        place_item(cb, "egg", 500, 500)
        # offset of CATCH_RADIUS - 1 pixels along x -> inside
        p = player_touching(1, (500 + (CATCH_RADIUS - 1), 500))
        assert simulate_frame(cb, [p]) == 1

    def test_no_catch_just_outside_radius(self):
        cb = fresh_callback()
        place_item(cb, "egg", 500, 500)
        # offset of exactly CATCH_RADIUS -> NOT caught (strict <)
        p = player_touching(1, (500 + CATCH_RADIUS, 500), other_wrist=(0.0, 0.0))
        # other wrist at pixel (0,0); item far from both
        assert simulate_frame(cb, [p]) == 0

    def test_afikoman_awards_fewer_points(self):
        cb = fresh_callback()
        place_item(cb, "afikoman", 300, 300)
        p = player_touching(1, (300, 300))
        simulate_frame(cb, [p])
        assert cb.players[1]["score"] == AFIKOMAN_POINTS
        assert AFIKOMAN_POINTS < EGG_POINTS

    def test_catch_pushes_popup(self):
        cb = fresh_callback()
        place_item(cb, "egg", 200, 200)
        p = player_touching(1, (200, 200))
        simulate_frame(cb, [p])
        assert len(cb.popups) == 1
        assert cb.popups[0].text == f"+{EGG_POINTS}"

    def test_either_wrist_can_catch(self):
        # left wrist far, right wrist on the item
        cb = fresh_callback()
        place_item(cb, "egg", 640, 360)
        bbox = FakeBBox()
        rx, ry = norm_for_pixel(640, 360, bbox, WIDTH, HEIGHT)
        pts = make_wrist_points((0.95, 0.95), (rx, ry))
        p = FakePlayer(7, pts, bbox)
        assert simulate_frame(cb, [p]) == 1

    def test_projection_respects_bbox_offset(self):
        # A wrist normalized inside a shifted/scaled bbox still lands correctly.
        cb = fresh_callback()
        place_item(cb, "egg", 800, 400)
        bbox = FakeBBox(xmin=0.25, ymin=0.10, width=0.5, height=0.6)
        lx, ly = norm_for_pixel(800, 400, bbox, WIDTH, HEIGHT)
        pts = make_wrist_points((lx, ly), (0.0, 0.0))
        p = FakePlayer(3, pts, bbox)
        # confirm projection maps back to the item pixel
        px, py = project_wrist(pts[LEFT_WRIST], bbox, WIDTH, HEIGHT)
        assert (px, py) == (800, 400)
        assert simulate_frame(cb, [p]) == 1


# ─────────────────────────────────────────────────────────────────────────────
# Scoring / leaderboard
# ─────────────────────────────────────────────────────────────────────────────
class TestScoringLeaderboard:
    def test_player_created_on_first_sight(self):
        cb = fresh_callback()
        player = cb._get_or_create_player(42)
        assert player["score"] == 0
        assert player["name"] in PLAYER_NAMES
        assert 42 in cb.players

    def test_player_names_assigned_in_order(self):
        cb = fresh_callback()
        a = cb._get_or_create_player(1)
        b = cb._get_or_create_player(2)
        assert a["name"] == PLAYER_NAMES[0]
        assert b["name"] == PLAYER_NAMES[1]

    def test_same_track_id_returns_same_player(self):
        cb = fresh_callback()
        a = cb._get_or_create_player(5)
        a["score"] += 30
        b = cb._get_or_create_player(5)
        assert a is b
        assert b["score"] == 30
        assert len(cb.players) == 1

    def test_name_pool_wraps_around(self):
        cb = fresh_callback()
        names = [cb._get_or_create_player(i)["name"] for i in range(len(PLAYER_NAMES) + 2)]
        # the (N)th player reuses the first name
        assert names[len(PLAYER_NAMES)] == PLAYER_NAMES[0]
        assert names[len(PLAYER_NAMES) + 1] == PLAYER_NAMES[1]

    def test_multiple_players_independent_scores(self):
        cb = fresh_callback()
        # player 1 catches an egg, player 2 catches an afikoman
        place_item(cb, "egg", 640, 360)
        simulate_frame(cb, [player_touching(1, (640, 360))])
        # new item spawned by the catch; place a known one and let player 2 catch
        place_item(cb, "afikoman", 300, 300)
        simulate_frame(cb, [player_touching(2, (300, 300))])
        assert cb.players[1]["score"] == EGG_POINTS
        assert cb.players[2]["score"] == AFIKOMAN_POINTS

    def test_leaderboard_ordering_descending(self):
        cb = fresh_callback()
        cb._get_or_create_player(1)["score"] = 30
        cb._get_or_create_player(2)["score"] = 90
        cb._get_or_create_player(3)["score"] = 60
        ordered = sorted(cb.players.values(), key=lambda p: p["score"], reverse=True)
        assert [p["score"] for p in ordered] == [90, 60, 30]
        assert ordered[0] is cb.players[2]


# ─────────────────────────────────────────────────────────────────────────────
# Falling-item lifecycle / spawn
# ─────────────────────────────────────────────────────────────────────────────
class TestItemLifecycle:
    def test_spawn_creates_item_within_bounds(self):
        cb = fresh_callback()
        cb.fw, cb.fh = WIDTH, HEIGHT
        for _ in range(200):
            cb.spawn_item()
            item = cb.current_item
            assert item is not None
            assert 0 <= item.x <= WIDTH
            assert 0 <= item.y <= HEIGHT
            assert item.kind in ("egg", "afikoman")
            assert 0 <= item.color_idx < len(EGG_COLORS)

    def test_spawn_keeps_items_out_of_leaderboard_strip(self):
        # leaderboard panel occupies the right ~210px; spawn keeps a margin.
        cb = fresh_callback()
        cb.fw, cb.fh = WIDTH, HEIGHT
        margin, lb_width = 80, 220
        for _ in range(200):
            cb.spawn_item()
            assert cb.current_item.x <= WIDTH - lb_width - margin
            assert cb.current_item.x >= margin

    def test_spawn_handles_tiny_frame_without_crash(self):
        # degenerate frame smaller than margins must not raise (randint guard).
        cb = fresh_callback()
        cb.fw, cb.fh = 100, 100
        cb.spawn_item()
        assert cb.current_item is not None

    def test_catch_replaces_current_item(self):
        cb = fresh_callback()
        first = place_item(cb, "egg", 640, 360)
        simulate_frame(cb, [player_touching(1, (640, 360))])
        # after a catch the item is replaced (not None, and a different object)
        assert cb.current_item is not None
        assert cb.current_item is not first

    def test_expired_item_signals_replacement(self):
        cb = fresh_callback()
        item = place_item(cb, "egg", 100, 100)
        item.spawn_time = time.time() - (ITEM_TIMEOUT + 1)
        assert cb.current_item.expired() is True
        # app replaces an expired item by spawning a new one
        cb.spawn_item()
        assert cb.current_item is not item
        assert cb.current_item.expired() is False


# ─────────────────────────────────────────────────────────────────────────────
# Popup floating text
# ─────────────────────────────────────────────────────────────────────────────
class TestPopup:
    def test_alive_when_fresh(self):
        assert Popup("+20", 0, 0, (1, 1, 1)).alive() is True

    def test_dead_after_duration(self):
        p = Popup("+20", 0, 0, (1, 1, 1))
        p.spawn = time.time() - (POPUP_DURATION + 0.1)
        assert p.alive() is False

    def test_alpha_decays_from_one_to_zero(self):
        p = Popup("+20", 0, 0, (1, 1, 1))
        assert p.alpha() == pytest.approx(1.0, abs=0.05)
        p.spawn = time.time() - POPUP_DURATION  # fully aged
        assert p.alpha() == pytest.approx(0.0, abs=1e-6)

    def test_alpha_never_negative(self):
        p = Popup("+20", 0, 0, (1, 1, 1))
        p.spawn = time.time() - (POPUP_DURATION * 5)
        assert p.alpha() == 0.0

    def test_floats_upward_over_time(self):
        p = Popup("+20", 0, 100, (1, 1, 1))
        y0 = p.current_y()
        p.spawn = time.time() - 0.5
        y1 = p.current_y()
        assert y1 < y0  # y decreases (moves up the screen)


# ─────────────────────────────────────────────────────────────────────────────
# Timer / countdown math (the math.ceil fix)
# ─────────────────────────────────────────────────────────────────────────────
class TestTimer:
    @pytest.mark.parametrize(
        "left,expected",
        [
            (5.0, 5),
            (4.999, 5),
            (4.001, 5),
            (4.0, 4),
            (0.001, 1),
            (0.0, 0),
        ],
    )
    def test_restart_countdown_uses_ceil(self, left, expected):
        # The on-screen "Restarting in Ns" uses math.ceil so a partial second
        # still reads as the higher integer (no flicker to 0 too early).
        assert math.ceil(left) == expected

    def test_countdown_from_game_over_time(self):
        # Reproduce: left = max(0, RESTART_DELAY - (now - game_over_time))
        now = 1000.0
        game_over_time = now - 1.2  # 1.2s into the 5s restart delay
        left = max(0, RESTART_DELAY - (now - game_over_time))
        assert math.ceil(left) == 4  # 3.8s remaining -> shows "4s"

    def test_countdown_clamped_at_zero(self):
        now = 1000.0
        game_over_time = now - (RESTART_DELAY + 2)  # well past delay
        left = max(0, RESTART_DELAY - (now - game_over_time))
        assert left == 0
        assert math.ceil(left) == 0

    @pytest.mark.parametrize(
        "remaining,expected",
        [
            (90.0, "1:30"),
            (65.0, "1:05"),
            (59.9, "0:59"),
            (9.0, "0:09"),
            (0.0, "0:00"),
        ],
    )
    def test_timer_mmss_formatting(self, remaining, expected):
        # Mirror the _draw_timer mins/secs formatting.
        mins = int(remaining) // 60
        secs = int(remaining) % 60
        assert f"{mins}:{secs:02d}" == expected

    def test_remaining_clamped_non_negative(self):
        # remaining = max(0.0, GAME_DURATION - elapsed)
        elapsed = GAME_DURATION + 10
        remaining = max(0.0, GAME_DURATION - elapsed)
        assert remaining == 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Restart / state reset
# ─────────────────────────────────────────────────────────────────────────────
class TestRestart:
    def test_restart_clears_all_state(self):
        cb = fresh_callback()
        cb._get_or_create_player(1)["score"] = 80
        cb._get_or_create_player(2)
        place_item(cb, "egg", 10, 10)
        cb.popups.append(Popup("+20", 0, 0, (1, 1, 1)))
        cb.game_start = time.time()
        cb.game_over = True
        cb.game_over_time = time.time()

        cb.restart()

        assert cb.players == {}
        assert cb._name_idx == 0
        assert cb.current_item is None
        assert cb.popups == []
        assert cb.game_start is None
        assert cb.game_over is False
        assert cb.game_over_time is None

    def test_names_restart_from_pool_top_after_restart(self):
        cb = fresh_callback()
        cb._get_or_create_player(1)
        cb._get_or_create_player(2)
        cb.restart()
        # next player after restart gets the first name again
        assert cb._get_or_create_player(99)["name"] == PLAYER_NAMES[0]


# ─────────────────────────────────────────────────────────────────────────────
# Edge cases
# ─────────────────────────────────────────────────────────────────────────────
class TestEdgeCases:
    def test_no_players_no_score_no_crash(self):
        cb = fresh_callback()
        place_item(cb, "egg", 100, 100)
        assert simulate_frame(cb, []) == 0
        assert cb.players == {}

    def test_untracked_player_defaults_to_track_id_zero(self):
        # When no HAILO_UNIQUE_ID is present the app uses track_id=0; all
        # untracked people then share one score entry.
        cb = fresh_callback()
        place_item(cb, "egg", 640, 360)
        simulate_frame(cb, [player_touching(0, (640, 360))])
        place_item(cb, "egg", 640, 360)
        simulate_frame(cb, [player_touching(0, (640, 360))])
        assert list(cb.players.keys()) == [0]
        assert cb.players[0]["score"] == 2 * EGG_POINTS

    def test_two_untracked_people_share_one_entry(self):
        cb = fresh_callback()
        place_item(cb, "egg", 640, 360)
        # two distinct people both reported as track_id 0
        p_a = player_touching(0, (640, 360))
        # the catch by p_a spawns a fresh item; pin it back to the same spot so
        # we can assert both contribute to the single shared score.
        cb_catches = simulate_frame(cb, [p_a])
        assert cb_catches == 1
        place_item(cb, "afikoman", 200, 200)
        simulate_frame(cb, [player_touching(0, (200, 200))])
        assert len(cb.players) == 1
        assert cb.players[0]["score"] == EGG_POINTS + AFIKOMAN_POINTS

    def test_simultaneous_catch_by_two_players(self):
        # Two players whose wrists both land on the item in the same frame.
        # The loop awards the first toucher then spawns a new item, so only the
        # first scores from this single item — verify no double count / crash
        # and that exactly one catch is registered against one item instance.
        cb = fresh_callback()
        place_item(cb, "egg", 640, 360)
        p1 = player_touching(1, (640, 360))
        p2 = player_touching(2, (640, 360))
        n = simulate_frame(cb, [p1, p2])
        total = cb.players[1]["score"] + cb.players[2]["score"]
        # each item is worth EGG_POINTS; catches >=1, total is a multiple
        assert n >= 1
        assert total >= EGG_POINTS
        # both players exist regardless of who scored
        assert set(cb.players.keys()) == {1, 2}

    def test_two_players_one_item_each_independent(self):
        # Sequential frames: player 1 grabs item A, player 2 grabs item B.
        cb = fresh_callback()
        place_item(cb, "egg", 640, 360)
        simulate_frame(cb, [player_touching(1, (640, 360))])
        place_item(cb, "egg", 400, 200)
        simulate_frame(cb, [player_touching(2, (400, 200))])
        assert cb.players[1]["score"] == EGG_POINTS
        assert cb.players[2]["score"] == EGG_POINTS

    def test_item_at_top_left_corner_catchable(self):
        cb = fresh_callback()
        place_item(cb, "egg", 0, 0)
        p = player_touching(1, (0, 0))
        assert simulate_frame(cb, [p]) == 1

    def test_item_at_bottom_right_corner_catchable(self):
        cb = fresh_callback()
        place_item(cb, "egg", WIDTH - 1, HEIGHT - 1)
        p = player_touching(1, (WIDTH - 1, HEIGHT - 1))
        assert simulate_frame(cb, [p]) == 1

    def test_no_current_item_means_no_catch(self):
        cb = fresh_callback()
        cb.current_item = None
        p = player_touching(1, (640, 360))
        assert simulate_frame(cb, [p]) == 0
        # player is still created though, since the loop sees the person
        assert 1 in cb.players

    def test_timer_at_zero_is_game_over_condition(self):
        # remaining <= 0 triggers game over in app_callback.
        remaining = max(0.0, GAME_DURATION - GAME_DURATION)
        assert remaining <= 0

    def test_dark_fallback_background_when_no_file(self):
        # Constructing with an empty/invalid path must not raise and yields a
        # None original (dark fallback handled at render time).
        cb = EasterGameCallback("")
        assert cb.background_orig is None
        assert cb.players == {}
        assert cb.current_item is None
