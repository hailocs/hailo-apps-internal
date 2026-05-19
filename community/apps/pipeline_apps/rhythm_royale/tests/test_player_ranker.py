"""PlayerRanker — top-K dancer selection by bbox_area * centeredness.

Bboxes are in normalized [0, 1] frame coordinates (the Hailo convention).
"""
import math

from community.apps.pipeline_apps.rhythm_royale.player_ranker import (
    PlayerRanker, Bbox,
)


def test_returns_all_when_under_cap():
    """If fewer detections than max_players, all are selected (and the order
    is still by rank score, biggest-and-most-centered first)."""
    ranker = PlayerRanker(max_players=4)
    players = [
        (1, Bbox(xmin=0.4, ymin=0.1, width=0.2, height=0.6)),  # big & centered
        (2, Bbox(xmin=0.0, ymin=0.1, width=0.1, height=0.3)),  # small & off-center
    ]
    selected = ranker.select(players)
    assert selected == [1, 2]


def test_picks_top_k_by_area_times_centeredness():
    """Big-and-centered beats big-but-edge or small-but-centered."""
    ranker = PlayerRanker(max_players=2)
    players = [
        (1, Bbox(xmin=0.0, ymin=0.1, width=0.4, height=0.8)),  # huge but edge
        (2, Bbox(xmin=0.4, ymin=0.1, width=0.2, height=0.6)),  # medium centered
        (3, Bbox(xmin=0.45, ymin=0.1, width=0.1, height=0.3)),  # small centered
        (4, Bbox(xmin=0.85, ymin=0.1, width=0.1, height=0.3)),  # small edge
    ]
    selected = ranker.select(players)
    assert len(selected) == 2
    # Player 2 is medium+centered — wins.
    assert 2 in selected
    # Player 4 is small & edge — loses.
    assert 4 not in selected


def test_centeredness_formula():
    """A dancer dead-center has centeredness=1; one with bbox center 1 frame-
    width from center has centeredness=exp(-4) ≈ 0.018."""
    ranker = PlayerRanker(max_players=10)
    # bbox center at (0.5, 0.5) — dead center
    score_center = ranker._rank_score(Bbox(0.4, 0.4, 0.2, 0.2))
    # bbox center at (1.0, 0.5) — frame edge
    score_edge = ranker._rank_score(Bbox(0.9, 0.4, 0.2, 0.2))
    assert score_center > score_edge
    # area equal (0.04), centeredness ratio is exp(0) / exp(-1) = e
    # (center x diff 0 vs 0.5; (0.5/0.5)^2 = 1)
    ratio = score_center / score_edge
    assert abs(ratio - math.exp(1.0)) < 0.01


def test_returns_empty_for_no_players():
    ranker = PlayerRanker(max_players=4)
    assert ranker.select([]) == []
