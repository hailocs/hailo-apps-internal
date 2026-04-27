"""WorldLoader — swap PX4 default.sdf with a custom SDF world.

Usage:
    loader = WorldLoader("~/Desktop/PX4-Autopilot", "2_person_world")
    with loader:
        # PX4 default.sdf is now symlinked to the chosen world.
        # After drone connects, call loader.restore() to revert.
        ...

World resolution (--world):
    - Bare name without extension (e.g. ``2_person_world``) -> ``sim/worlds/<name>.sdf``
    - Relative path with ``.sdf`` suffix -> tries ``sim/worlds/`` first, then CWD
    - Absolute path -> used as-is

Known limitation:
    If the process is killed with SIGKILL, ``__exit__`` never runs and the
    symlink + backup are left on disk.  The next run detects this (backup
    exists while default.sdf is a symlink) and recovers automatically.
"""

import logging
import os
import shutil
import tempfile
from pathlib import Path

LOGGER = logging.getLogger(__name__)

_SDF_EXAMPLES_DIR = Path(__file__).resolve().parent / "worlds"
_PX4_WORLD_REL = Path("Tools/simulation/gz/worlds/default.sdf")


class WorldLoader:
    """Context manager that symlinks a custom SDF world as PX4's default.sdf.

    On enter: backs up the original default.sdf and creates a symlink.
    restore() removes the symlink and reverts the backup (called after drone
    connects, meaning Gazebo has read the world file).
    On exit (__exit__): ensures restore() runs even on crash.

    The backup/restore logic handles stale state from a prior SIGKILL:
    if a ``.sdf.bak`` already exists and ``default.sdf`` is a symlink,
    we skip the backup step (the existing ``.bak`` *is* the real original)
    and only replace the symlink.
    """

    def __init__(self, px4_path: str, world: str):
        self._px4_path = Path(px4_path).expanduser().resolve()
        self._default_sdf = self._px4_path / _PX4_WORLD_REL
        self._backup_sdf = self._default_sdf.with_suffix(".sdf.bak")
        self._restored = False

        # Resolve world: bare name -> sim/worlds/<name>.sdf
        # Relative path with suffix -> try sim/worlds/ first, then CWD
        # Absolute path -> use as-is
        world_path = Path(world)
        if not world_path.suffix:
            world_path = _SDF_EXAMPLES_DIR / f"{world}.sdf"
        elif not world_path.is_absolute():
            candidate = _SDF_EXAMPLES_DIR / world_path
            if candidate.exists():
                world_path = candidate
        self._world_sdf = world_path.expanduser().resolve()

    def validate(self):
        """Check preconditions without side effects. Raises on failure."""
        if not self._world_sdf.is_file():
            raise FileNotFoundError(f"World SDF not found: {self._world_sdf}")
        if not self._default_sdf.parent.is_dir():
            raise FileNotFoundError(
                f"PX4 worlds directory not found: {self._default_sdf.parent}")

    def __enter__(self):
        self.validate()

        # Recover from a prior SIGKILL: backup exists and default.sdf is a
        # stale symlink from the previous run.  The backup IS the real
        # original — do NOT overwrite it.
        if self._backup_sdf.exists() and self._default_sdf.is_symlink():
            LOGGER.warning(
                "[world] Detected stale state from a prior crash — "
                "keeping existing backup as the real original.")
            self._default_sdf.unlink()
        elif self._default_sdf.exists() or self._default_sdf.is_symlink():
            # Normal case: back up existing default.sdf
            if self._backup_sdf.exists():
                self._backup_sdf.unlink()

            # Preserve symlinks as symlinks (don't follow with copy2)
            if self._default_sdf.is_symlink():
                link_target = os.readlink(self._default_sdf)
                self._backup_sdf.symlink_to(link_target)
            else:
                shutil.copy2(self._default_sdf, self._backup_sdf)

            self._default_sdf.unlink()
            LOGGER.info("[world] Backed up %s", self._default_sdf)

        # Atomic-ish symlink: create with a temp name, then rename over target.
        # os.replace is atomic on the same filesystem.
        tmp_link = Path(tempfile.mktemp(
            dir=self._default_sdf.parent,
            prefix=".world_loader_",
            suffix=".tmp"))
        try:
            tmp_link.symlink_to(self._world_sdf)
            os.replace(tmp_link, self._default_sdf)
        except BaseException:
            tmp_link.unlink(missing_ok=True)
            raise
        LOGGER.info("[world] Symlinked %s -> %s", self._default_sdf.name, self._world_sdf.name)
        return self

    def restore(self):
        """Remove symlink and restore original default.sdf from backup."""
        if self._restored:
            return
        self._restored = True
        try:
            if self._default_sdf.is_symlink():
                self._default_sdf.unlink()
                LOGGER.info("[world] Removed symlink %s", self._default_sdf.name)
        except OSError as e:
            LOGGER.warning("[world] Failed to remove symlink: %s", e)
        try:
            if self._backup_sdf.is_symlink():
                # Restore a symlink backup as a symlink
                link_target = os.readlink(self._backup_sdf)
                self._default_sdf.symlink_to(link_target)
                self._backup_sdf.unlink()
                LOGGER.info("[world] Restored original symlink %s", self._default_sdf.name)
            elif self._backup_sdf.exists():
                shutil.move(self._backup_sdf, self._default_sdf)
                LOGGER.info("[world] Restored original %s", self._default_sdf.name)
        except OSError as e:
            LOGGER.warning("[world] Failed to restore backup: %s", e)

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.restore()
