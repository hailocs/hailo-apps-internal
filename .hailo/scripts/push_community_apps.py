#!/usr/bin/env python3
"""
Push community apps to hailo-rpi5-examples as pull requests.

Scans community/apps/ for directories with app.yaml, copies each to a flat
community_projects/<app_name>/ layout matching the hailo-rpi5-examples
convention, updates the community index, and opens a PR via `gh` CLI.

Prerequisites:
    - `gh` CLI installed and authenticated (`gh auth login`)
    - Git installed

Usage:
    python .hailo/scripts/push_community_apps.py --dry-run          # Preview
    python .hailo/scripts/push_community_apps.py --app batch_detection  # One app
    python .hailo/scripts/push_community_apps.py                    # All apps
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
from datetime import datetime
from pathlib import Path

import yaml

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
COMMUNITY_APPS_DIR = REPO_ROOT / "community" / "apps"
CONTRIBUTIONS_DIR = REPO_ROOT / "community" / "contributions"

TARGET_REPO = "hailo-ai/hailo-rpi5-examples"
TARGET_BRANCH = "main"
COMMUNITY_DIR_NAME = "community_projects"
INDEX_FILE = "community_projects.md"


class C:
    GREEN = "\033[92m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RESET = "\033[0m"


def run_cmd(cmd, cwd=None, check=True, capture=True):
    """Run a shell command and return stdout."""
    result = subprocess.run(
        cmd, shell=True, cwd=cwd, check=check,
        capture_output=capture, text=True,
    )
    return result.stdout.strip() if capture else ""


def check_gh_cli():
    """Verify gh CLI is installed and authenticated."""
    try:
        run_cmd("gh auth status")
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def find_eligible_apps(app_name=None):
    """Find community apps with app.yaml manifests.

    Args:
        app_name: If specified, only return this app.

    Returns:
        List of (app_dir, manifest) tuples.
    """
    apps = []
    for manifest_path in sorted(COMMUNITY_APPS_DIR.rglob("app.yaml")):
        app_dir = manifest_path.parent
        try:
            manifest = yaml.safe_load(manifest_path.read_text()) or {}
        except Exception:
            continue
        if app_name and app_dir.name != app_name:
            continue
        apps.append((app_dir, manifest))
    return apps


def find_contribution_recipe(app_name):
    """Find the contribution recipe for an app, if any."""
    for recipe_path in CONTRIBUTIONS_DIR.rglob("*.md"):
        if recipe_path.name == "README.md":
            continue
        if app_name in recipe_path.name:
            return recipe_path
    return None


def adapt_readme(app_dir, manifest):
    """Generate a README matching hailo-rpi5-examples template format.

    If the app already has a good README, enhance it with the template sections.
    """
    readme_path = app_dir / "README.md"
    if readme_path.exists():
        existing = readme_path.read_text()
    else:
        existing = ""

    name = manifest.get("name", app_dir.name)
    description = manifest.get("description", "A Hailo community application.")
    title = name.replace("_", " ").title()

    # Check if README already has required sections
    has_overview = "## Overview" in existing
    has_setup = "## Setup" in existing or "## Prerequisites" in existing or "## Quick Start" in existing
    has_usage = "## Usage" in existing

    if has_overview and has_setup and has_usage:
        return existing  # Already good enough

    # Build template-compliant README
    hardware = manifest.get("hardware", ["hailo8", "hailo8l", "hailo10h"])
    if isinstance(hardware, str):
        hardware = [hardware]
    hw_str = ", ".join(hardware)

    readme = f"# {title}\n\n"
    if has_overview:
        readme += existing.split("## Overview")[1].split("\n## ")[0] if "## Overview" in existing else ""
    else:
        readme += f"## Overview\n\n{description}\n\n"
        readme += f"**Supported hardware:** {hw_str}\n\n"

    readme += "## Video\n\n<!-- Add a demo video link here -->\n\n"
    readme += "## Versions\n\nVerified with hailo-apps `feature/gen-ai` branch.\n\n"

    if not has_setup:
        readme += textwrap.dedent(f"""\
        ## Setup Instructions

        ```bash
        # Clone and setup
        git clone https://github.com/hailo-ai/hailo-apps.git
        cd hailo-apps
        source setup_env.sh
        pip install -e .
        ```

        """)

    if not has_usage:
        entry = manifest.get("entry_point", f"{app_dir.name}.py")
        readme += textwrap.dedent(f"""\
        ## Usage

        ```bash
        python {entry}
        ```
        """)

    # Append any remaining content from existing README
    if existing and not existing.startswith("# "):
        readme += f"\n{existing}\n"

    return readme


def generate_requirements(app_dir):
    """Generate a simple requirements.txt from imports if one doesn't exist."""
    req_path = app_dir / "requirements.txt"
    if req_path.exists():
        return req_path.read_text()
    # Return empty — the main repo handles deps
    return "# Dependencies managed by hailo-apps (pip install -e .)\n"


def update_index(clone_dir, app_name, manifest):
    """Update the community_projects.md index file with a new entry."""
    index_path = clone_dir / COMMUNITY_DIR_NAME / INDEX_FILE
    if not index_path.exists():
        return

    content = index_path.read_text()
    description = manifest.get("description", "").strip().split("\n")[0][:100]
    tags = manifest.get("tags", [])
    if isinstance(tags, str):
        tags = [tags]
    tags_str = ", ".join(tags) if tags else ""
    author = manifest.get("author", "community")
    link = f"[{app_name}](./{app_name}/)"

    # Check if already in index
    if app_name in content:
        print(f"  {C.DIM}App already in index, skipping{C.RESET}")
        return

    # Find the table and append
    new_row = f"| {link} | {description} | {tags_str} | {author} |\n"

    # If there's a table, append to it. Otherwise append at end.
    if "| --- |" in content or "|---|" in content:
        # Find last table row
        lines = content.split("\n")
        last_table_idx = -1
        for i, line in enumerate(lines):
            if line.startswith("|"):
                last_table_idx = i
        if last_table_idx >= 0:
            lines.insert(last_table_idx + 1, new_row.rstrip())
            content = "\n".join(lines)
        else:
            content += f"\n{new_row}"
    else:
        # No table yet — create one
        content += textwrap.dedent(f"""
        ## Community Apps from hailo-apps

        | App | Description | Tags | Author |
        |-----|-------------|------|--------|
        {new_row}""")

    index_path.write_text(content)
    print(f"  {C.GREEN}Updated index: {app_name}{C.RESET}")


def push_app(app_dir, manifest, dry_run=False, clone_dir=None):
    """Push a single app to hailo-rpi5-examples as a PR.

    Args:
        app_dir: Path to the community app directory.
        manifest: Parsed app.yaml dict.
        dry_run: If True, only show what would happen.
        clone_dir: Pre-cloned repo dir (reused across apps).
    """
    app_name = app_dir.name
    branch_name = f"community/{app_name}"

    print(f"\n{C.BOLD}=== {app_name} ==={C.RESET}")
    print(f"  Source: {app_dir.relative_to(REPO_ROOT)}")
    print(f"  Type: {manifest.get('type', '?')}")
    print(f"  Description: {manifest.get('description', '?')[:80]}")

    if dry_run:
        print(f"  {C.YELLOW}[DRY RUN] Would push to {TARGET_REPO} branch {branch_name}{C.RESET}")
        recipe = find_contribution_recipe(app_name)
        if recipe:
            print(f"  {C.DIM}Would include contribution: {recipe.relative_to(REPO_ROOT)}{C.RESET}")
        return

    # Create target directory in clone
    target_dir = clone_dir / COMMUNITY_DIR_NAME / app_name
    if target_dir.exists():
        shutil.rmtree(target_dir)
    target_dir.mkdir(parents=True)

    # Copy app files (flat — no type subdirs)
    for item in app_dir.iterdir():
        if item.name in ("__pycache__", ".pyc", "app.yaml"):
            continue
        if item.is_dir():
            shutil.copytree(item, target_dir / item.name,
                          ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        else:
            shutil.copy2(item, target_dir / item.name)

    # Generate/adapt README
    readme_content = adapt_readme(app_dir, manifest)
    (target_dir / "README.md").write_text(readme_content)

    # Generate requirements.txt if missing
    req_content = generate_requirements(app_dir)
    (target_dir / "requirements.txt").write_text(req_content)

    # Copy contribution recipe if exists
    recipe = find_contribution_recipe(app_name)
    if recipe:
        contrib_dir = target_dir / "contributions"
        contrib_dir.mkdir(exist_ok=True)
        shutil.copy2(recipe, contrib_dir / recipe.name)
        print(f"  {C.GREEN}Included contribution recipe{C.RESET}")

    # Update index
    update_index(clone_dir, app_name, manifest)

    # Git operations
    run_cmd(f"git checkout -b {branch_name}", cwd=clone_dir, check=False)
    run_cmd("git add -A", cwd=clone_dir)

    description = manifest.get("description", "New community app").strip().split("\n")[0]
    commit_msg = f"community: add {app_name}\n\n{description}"
    run_cmd(f'git commit -m "{commit_msg}"', cwd=clone_dir)
    run_cmd(f"git push origin {branch_name} --force", cwd=clone_dir)

    # Create PR
    pr_title = f"[Community] {app_name.replace('_', ' ').title()}"
    pr_body = textwrap.dedent(f"""\
        ## New Community App: {app_name}

        {description}

        **Type:** {manifest.get('type', 'unknown')}
        **Hardware:** {manifest.get('hardware', 'unknown')}
        **Author:** {manifest.get('author', 'community')}

        ---
        *Auto-generated by `push_community_apps.py` from [hailo-apps].*
    """)

    try:
        result = run_cmd(
            f'gh pr create --repo {TARGET_REPO} --base {TARGET_BRANCH} '
            f'--head {branch_name} --title "{pr_title}" --body "{pr_body}"',
            cwd=clone_dir, check=True,
        )
        print(f"  {C.GREEN}PR created: {result}{C.RESET}")
    except subprocess.CalledProcessError:
        print(f"  {C.YELLOW}PR may already exist for {branch_name}{C.RESET}")
    finally:
        # Return to main branch for next app
        run_cmd(f"git checkout {TARGET_BRANCH}", cwd=clone_dir, check=False)


def main():
    parser = argparse.ArgumentParser(
        description="Push community apps to hailo-rpi5-examples as PRs",
    )
    parser.add_argument("--dry-run", action="store_true",
                       help="Show what would be pushed without doing it")
    parser.add_argument("--app", type=str, default=None,
                       help="Push only this app (by directory name)")
    parser.add_argument("--clone-dir", type=str, default=None,
                       help="Reuse an existing clone of hailo-rpi5-examples")
    args = parser.parse_args()

    # Find eligible apps
    apps = find_eligible_apps(args.app)
    if not apps:
        if args.app:
            print(f"{C.RED}No app.yaml found for '{args.app}'{C.RESET}")
        else:
            print(f"{C.DIM}No community apps with app.yaml found{C.RESET}")
        sys.exit(1)

    print(f"{C.BOLD}Found {len(apps)} eligible app(s):{C.RESET}")
    for app_dir, manifest in apps:
        print(f"  • {app_dir.name} ({manifest.get('type', '?')})")

    if args.dry_run:
        print(f"\n{C.YELLOW}=== DRY RUN ==={C.RESET}")
        for app_dir, manifest in apps:
            push_app(app_dir, manifest, dry_run=True)
        print(f"\n{C.YELLOW}No changes made.{C.RESET}")
        return

    # Check gh CLI
    if not check_gh_cli():
        print(f"{C.RED}Error: gh CLI not authenticated. Run: gh auth login{C.RESET}")
        sys.exit(1)

    # Clone target repo
    if args.clone_dir:
        clone_dir = Path(args.clone_dir)
        run_cmd(f"git checkout {TARGET_BRANCH}", cwd=clone_dir, check=False)
        run_cmd("git pull", cwd=clone_dir, check=False)
    else:
        clone_dir = Path(tempfile.mkdtemp(prefix="hailo-rpi5-"))
        print(f"\n{C.DIM}Cloning {TARGET_REPO} to {clone_dir}...{C.RESET}")
        run_cmd(f"gh repo clone {TARGET_REPO} {clone_dir}", check=True)

    try:
        for app_dir, manifest in apps:
            push_app(app_dir, manifest, dry_run=False, clone_dir=clone_dir)
    finally:
        if not args.clone_dir:
            print(f"\n{C.DIM}Temp clone at: {clone_dir}{C.RESET}")
            print(f"{C.DIM}(delete manually or reuse with --clone-dir){C.RESET}")

    print(f"\n{C.BOLD}{C.GREEN}Done! {len(apps)} app(s) pushed.{C.RESET}")


if __name__ == "__main__":
    main()
