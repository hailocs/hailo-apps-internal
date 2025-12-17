#!/usr/bin/env python3
"""
config_handler.py

Unified CLI for configuration inspection and single-resource operations.

This file:
- Replaces config_manager.py CLI
- Replaces resources_cli.py
- Imports ONLY config_core.py for logic
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from hailo_apps.config.config_core import (
    ConfigError,
    get_available_apps,
    get_supported_architectures,
    get_all_models,
    get_model_info,
    get_inputs_for_app,
    get_shared_images,
    get_shared_videos,
)
from hailo_apps.installation.download_resources import (
    DownloadConfig,
    DownloadTask,
    ResourceDownloader,
)
from hailo_apps.python.core.common.defines import (
    HAILO8_ARCH,
    HAILO8L_ARCH,
    HAILO10H_ARCH,
    HAILO_FILE_EXTENSION,
)

SUPPORTED_ARCHES = (HAILO8_ARCH, HAILO8L_ARCH, HAILO10H_ARCH)


# =============================================================================
# Helpers
# =============================================================================

def die(msg: str) -> None:
    print(f"Error: {msg}", file=sys.stderr)
    raise SystemExit(1)


def validate_arch(arch: str) -> str:
    arch = arch.lower()
    if arch not in SUPPORTED_ARCHES:
        die(f"Invalid arch '{arch}', supported: {', '.join(SUPPORTED_ARCHES)}")
    return arch


def make_downloader(
    arch: str,
    target_dir: Path,
    *,
    force: bool,
    dry_run: bool,
) -> ResourceDownloader:
    return ResourceDownloader(
        config=None,
        hailo_arch=arch,
        resource_root=target_dir,
        download_config=DownloadConfig(
            force_redownload=force,
            dry_run=dry_run,
            parallel_workers=1,
            show_progress=not dry_run,
        ),
    )


# =============================================================================
# Commands
# =============================================================================

def cmd_list_apps(_: argparse.Namespace) -> None:
    for app in get_available_apps():
        print(app)


def cmd_show_models(args: argparse.Namespace) -> None:
    arch = validate_arch(args.arch)
    models = get_all_models(args.app, arch)
    if not models:
        die(f"No models found for app '{args.app}' arch '{arch}'")
    for m in models:
        print(m.name)


def cmd_hef_get(args: argparse.Namespace) -> None:
    arch = validate_arch(args.arch)
    model = get_model_info(args.app, arch, args.model)
    if not model:
        die(f"Model '{args.model}' not found for app '{args.app}' arch '{arch}'")

    downloader = make_downloader(
        arch,
        Path(args.target_dir),
        force=args.force,
        dry_run=args.dry_run,
    )

    url = model.url or downloader._build_model_url(
        {"name": model.name}, model.source
    )
    if not url:
        die(f"Failed to resolve URL for model '{model.name}'")

    dest = Path(args.target_dir) / f"{model.name}{HAILO_FILE_EXTENSION}"
    task = DownloadTask(
        url=url,
        dest_path=dest,
        resource_type="model",
        name=model.name,
    )

    result = downloader._download_file_with_retry(task)
    if not result.success:
        die(result.message)

    print(dest.resolve())


def cmd_hef_verify_arch(args: argparse.Namespace) -> None:
    hef = Path(args.file)
    if not hef.is_file():
        die(f"HEF not found: {hef}")

    try:
        output = subprocess.check_output(
            ["hailortcli", "parse-hef", str(hef)],
            text=True,
            stderr=subprocess.STDOUT,
        )
    except FileNotFoundError:
        die("hailortcli not found in PATH")
    except subprocess.CalledProcessError as e:
        die(e.output)

    for line in output.splitlines():
        if "Architecture HEF was compiled for" in line:
            print(line.split(":")[-1].strip())
            return

    die("Could not determine HEF architecture")


def cmd_input_list(args: argparse.Namespace) -> None:
    inputs = get_inputs_for_app(args.app)
    if not inputs:
        die(f"No inputs defined for app '{args.app}'")

    for kind in ("images", "videos"):
        for item in inputs.get(kind, []):
            if isinstance(item, dict):
                print(f"{kind[:-1]}: {item.get('name')}")


def _resolve_shared_input(kind: str, name: str) -> dict | None:
    pool = get_shared_images() if kind == "image" else get_shared_videos()
    for entry in pool:
        if isinstance(entry, dict) and entry.get("name") == name:
            return entry
    return None


def cmd_input_get(args: argparse.Namespace) -> None:
    inputs = get_inputs_for_app(args.app)
    if not inputs:
        die(f"No inputs defined for app '{args.app}'")

    item = None
    kind = None

    for k in ("images", "videos"):
        for entry in inputs.get(k, []):
            if isinstance(entry, dict) and entry.get("name") == args.id:
                item = entry
                kind = k[:-1]
                break

    if not item:
        die(f"Input '{args.id}' not found for app '{args.app}'")

    shared = _resolve_shared_input(kind, item.get("ref") or item.get("name"))
    url = item.get("url") or (shared and shared.get("url"))
    if not url:
        die(f"No URL found for input '{args.id}'")

    target = Path(args.target_dir)
    target.mkdir(parents=True, exist_ok=True)

    downloader = make_downloader(
        HAILO8_ARCH,
        target,
        force=args.force,
        dry_run=args.dry_run,
    )

    dest = target / Path(url).name
    task = DownloadTask(
        url=url,
        dest_path=dest,
        resource_type=kind,
        name=dest.name,
    )

    result = downloader._download_file_with_retry(task)
    if not result.success:
        die(result.message)

    print(dest.resolve())


# =============================================================================
# CLI
# =============================================================================

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Hailo unified configuration & resource handler"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list-apps").set_defaults(func=cmd_list_apps)

    p = sub.add_parser("show-models")
    p.add_argument("--app", required=True)
    p.add_argument("--arch", required=True)
    p.set_defaults(func=cmd_show_models)

    p = sub.add_parser("hef-get")
    p.add_argument("--app", required=True)
    p.add_argument("--arch", required=True)
    p.add_argument("--model", required=True)
    p.add_argument("--target-dir", default=".")
    p.add_argument("--force", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_hef_get)

    p = sub.add_parser("hef-verify-arch")
    p.add_argument("--file", required=True)
    p.set_defaults(func=cmd_hef_verify_arch)

    p = sub.add_parser("input-list")
    p.add_argument("--app", required=True)
    p.set_defaults(func=cmd_input_list)

    p = sub.add_parser("input-get")
    p.add_argument("--app", required=True)
    p.add_argument("--id", required=True)
    p.add_argument("--target-dir", default=".")
    p.add_argument("--force", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_input_get)

    return parser


def main() -> None:
    try:
        parser = build_parser()
        args = parser.parse_args()
        args.func(args)
    except ConfigError as e:
        die(str(e))


if __name__ == "__main__":
    main()
