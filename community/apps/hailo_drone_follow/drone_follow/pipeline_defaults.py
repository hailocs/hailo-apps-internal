"""Canonical pipeline-level CLI defaults shared between production
(``scripts/start_air.sh``) and the simulation test fixture
(``drone_follow/tests/test_sim_worlds.py:sim_run``).

Anything that should stay in lock-step between the air unit and the sim
tests lives here. ControllerConfig (in ``follow_api/config.py``) is the
right home for *follow-controller* tuning (gains, dead-zones, smoothing)
and is loaded from JSON; this module is the home for *pipeline-shape*
flags (tile grid, multi-scale, etc.) that don't have a JSON config
representation today.

Bash callers consume this via a one-liner subshell::

    PIPELINE_ARGS=( $(python3 -c \\
        'from drone_follow.pipeline_defaults import TILE_FLAGS; \\
         print(" ".join(TILE_FLAGS))') )
"""

from __future__ import annotations

# Tiling / multi-scale flags.
#
# 3x2 manual grid + level-1 multi-scale (adds a 1x1 whole-frame pass).
# The 3x2 grid has a vertical seam down the centre of the frame; a
# target straddling that seam splits across two tiles and can be missed
# by both. The 1x1 multi-scale pass is the cheapest way to insure
# against that — total inferences per frame: 3*2 + 1 = 7.
#
# Originally hand-picked for the simulation ``person_in_front`` test
# and verified empirically; promoted to the production default after
# confirming the RPi5 + Hailo-8L pair sustains framerate at 7 tiles.
TILE_FLAGS: list[str] = [
    "--tiles-x", "3",
    "--tiles-y", "2",
    "--multi-scale",
    "--scale-levels", "1",
]
