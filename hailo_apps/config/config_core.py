"""
config_core.py

Pure configuration logic for Hailo Apps Infrastructure.

This module is the single source of truth for:
- Loading YAML configuration files
- Resolving models, inputs, resources
- Providing structured accessors

IMPORTANT:
- No CLI
- No argparse
- No sys.exit
- No printing
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

import yaml


# =============================================================================
# Exceptions
# =============================================================================

class ConfigError(Exception):
    """Raised when configuration files are missing or invalid."""
    pass


# =============================================================================
# Dataclasses
# =============================================================================

@dataclass(frozen=True)
class ModelEntry:
    name: str
    source: str
    url: Optional[str] = None


# =============================================================================
# Path Resolution
# =============================================================================

class ConfigPaths:
    """
    Centralized config path resolver.
    Works both in:
    - editable repo
    - installed package
    """

    _repo_root: Optional[Path] = None

    @classmethod
    def repo_root(cls) -> Path:
        if cls._repo_root is None:
            cls._repo_root = Path(__file__).resolve().parents[2]
        return cls._repo_root

    @classmethod
    def config_dir(cls) -> Path:
        return cls.repo_root() / "hailo_apps" / "config"

    @classmethod
    def main_config(cls) -> Path:
        return cls.config_dir() / "config.yaml"

    @classmethod
    def resources_config(cls) -> Path:
        return cls.config_dir() / "resources_config.yaml"


# =============================================================================
# YAML Loading
# =============================================================================

def _is_none(value: Any) -> bool:
    return value is None or (isinstance(value, str) and value.lower() == "none")


@lru_cache(maxsize=16)
def _load_yaml(path: Path) -> dict:
    if not path.exists():
        raise ConfigError(f"Missing config file: {path}")
    try:
        with open(path, "r") as f:
            return yaml.safe_load(f) or {}
    except yaml.YAMLError as e:
        raise ConfigError(f"Invalid YAML in {path}: {e}") from e


# =============================================================================
# Main Config
# =============================================================================

def get_main_config() -> dict:
    return _load_yaml(ConfigPaths.main_config())


def get_resources_path_config() -> dict:
    cfg = get_main_config()
    return cfg.get("resources", {})


def get_model_zoo_mapping() -> dict:
    cfg = get_main_config()
    return cfg.get("model_zoo_mapping", {})


# =============================================================================
# Resources Config
# =============================================================================

def get_resources_config() -> dict:
    return _load_yaml(ConfigPaths.resources_config())


def get_available_apps() -> list[str]:
    cfg = get_resources_config()
    skip = {"videos", "images", "json", "inputs", "inputs_aliases"}
    return sorted(k for k, v in cfg.items() if isinstance(v, dict) and k not in skip)


def get_supported_architectures(app: str) -> list[str]:
    cfg = get_resources_config()
    models = cfg.get(app, {}).get("models", {})
    return sorted(k for k, v in models.items() if isinstance(v, dict))


# =============================================================================
# Model Resolution
# =============================================================================

def _extract_models(entry: Any) -> list[ModelEntry]:
    if _is_none(entry):
        return []
    entries = entry if isinstance(entry, list) else [entry]
    out: list[ModelEntry] = []

    for e in entries:
        if _is_none(e):
            continue
        if isinstance(e, dict):
            name = e.get("name")
            if not _is_none(name):
                out.append(ModelEntry(
                    name=name,
                    source=e.get("source", "mz"),
                    url=e.get("url"),
                ))
        elif isinstance(e, str):
            out.append(ModelEntry(name=e, source="mz"))

    return out


def get_default_models(app: str, arch: str) -> list[ModelEntry]:
    cfg = get_resources_config()
    return _extract_models(cfg.get(app, {}).get("models", {}).get(arch, {}).get("default"))


def get_extra_models(app: str, arch: str) -> list[ModelEntry]:
    cfg = get_resources_config()
    return _extract_models(cfg.get(app, {}).get("models", {}).get(arch, {}).get("extra"))


def get_all_models(app: str, arch: str) -> list[ModelEntry]:
    return get_default_models(app, arch) + get_extra_models(app, arch)


def get_model_info(app: str, arch: str, model: str) -> Optional[ModelEntry]:
    for m in get_all_models(app, arch):
        if m.name == model:
            return m
    return None


# =============================================================================
# Inputs (Images / Videos)
# =============================================================================

def get_inputs_config() -> dict:
    cfg = get_resources_config()
    return cfg.get("inputs", {})


def resolve_inputs_app(app: str) -> str:
    cfg = get_resources_config()
    aliases = cfg.get("inputs_aliases", {})
    return aliases.get(app, app)


def get_inputs_for_app(app: str) -> dict:
    inputs = get_inputs_config()
    resolved = resolve_inputs_app(app)
    return inputs.get(resolved, {})


def get_shared_images() -> list[dict]:
    cfg = get_resources_config()
    return cfg.get("images", [])


def get_shared_videos() -> list[dict]:
    cfg = get_resources_config()
    return cfg.get("videos", [])


def get_shared_json_files() -> list[dict]:
    cfg = get_resources_config()
    return cfg.get("json", [])


# =============================================================================
# Gen-AI Detection
# =============================================================================

def is_gen_ai_app(app: str) -> bool:
    for arch in get_supported_architectures(app):
        for m in get_all_models(app, arch):
            if m.source == "gen-ai-mz":
                return True
    return False
