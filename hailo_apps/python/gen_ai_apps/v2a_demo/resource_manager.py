"""Resource management for v2a demo.

Uses the same model-resolution flow used by standalone apps:
resolve model names via the shared resources config and auto-download
missing HEF files on first run.
"""

from __future__ import annotations

import sys
from pathlib import Path


def _find_repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "hailo_apps" / "config" / "config_manager.py").exists():
            return parent
    raise RuntimeError("Could not locate repository root for resource resolution")


REPO_ROOT = _find_repo_root()
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from hailo_apps.python.core.common.core import resolve_hef_path  # noqa: E402
from hailo_apps.python.core.common.defines import HAILO10H_ARCH, V2A_DEMO_APP  # noqa: E402

APP_DIR = Path(__file__).resolve().parent
RESOURCES_DIR = APP_DIR / "resources"

HEF_MODEL_NAMES = {
    "stt": "Whisper-Base",
    "llm": "Qwen2.5-Coder-1.5B-Instruct",
    "tool_selector": "all_minilm_l6_v2",
}


def resolve_v2a_hef(stage: str) -> str:
    """Resolve a v2a HEF path and auto-download if missing."""
    if stage not in HEF_MODEL_NAMES:
        raise ValueError(f"Unknown stage '{stage}'. Expected one of: {list(HEF_MODEL_NAMES)}")

    model_name = HEF_MODEL_NAMES[stage]
    resolved = resolve_hef_path(
        hef_path=model_name,
        app_name=V2A_DEMO_APP,
        arch=HAILO10H_ARCH,
    )
    if resolved is None:
        raise RuntimeError(f"Failed to resolve HEF for stage '{stage}' (model '{model_name}')")
    return str(resolved)
