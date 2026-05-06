"""Canonical pipeline-shape defaults applied to drone-follow's parser.

The upstream tiling pipeline parser registers ``--tiles-x`` etc. with
``default=None`` (which triggers auto-mode). Drone-follow overrides
those defaults from this module via ``parser.set_defaults(**TILE_DEFAULTS)``
in ``DroneFollowTilingApp._add_tiling_arguments`` (in
``hailo_drone_detection_manager.py``) — that hook runs immediately
after upstream registers the args and before ``parse_args`` fires, so
the defaults take effect. Production flights and the simulation tests
run identical pipeline geometry without duplicating CLI flags in
``scripts/start_air.sh`` and the test fixture.

To change the default tile shape for both production and tests, edit
this module — the change propagates everywhere on next launch.

To override for a single run, pass the relevant flag on the
``drone-follow`` command line as usual (argparse honours the CLI value
over ``set_defaults``).

Note: ``--multi-scale`` is a ``store_true`` action upstream, so there is
no ``--no-multi-scale`` CLI escape hatch. If you need to disable
multi-scale, set ``multi_scale=False`` here and rerun.

Separation from :class:`drone_follow.follow_api.config.ControllerConfig`:
that owns *follow-controller* tuning (gains, dead-zones, smoothing),
which is loaded from JSON at runtime; this module owns
*pipeline-shape* flags, which are CLI-only and never reload.
"""

from __future__ import annotations

# 3x2 manual grid + level-1 multi-scale (adds a 1x1 whole-frame pass).
# The 3x2 grid has a vertical seam down the centre of the frame; a target
# straddling that seam splits across two tiles and can be missed by both.
# The 1x1 multi-scale pass is the cheapest insurance against that.
# Total inferences per frame: 3*2 + 1 = 7.
TILE_DEFAULTS: dict = {
    "tiles_x":      3,
    "tiles_y":      2,
    "multi_scale":  True,
    "scale_levels": 1,
}
