#!/usr/bin/env python3
"""
Curate community contributions and apps into the official .hailo/ knowledge base.

This script is the "self-learning" pipeline for hailo-apps:
1. Scans community/contributions/ for knowledge artifacts
2. Validates format and quality
3. Incorporates valuable findings into .hailo/memory/ and .hailo/knowledge/
4. Deletes curated originals (knowledge now lives in .hailo/)

Also handles community app promotion:
5. Validates community/apps/<name>/ structure and conventions
6. Moves to hailo_apps/python/<category>/<name>/
7. Registers in defines.py and resources_config.yaml

Usage:
    python .hailo/scripts/curate_contributions.py --scan
    python .hailo/scripts/curate_contributions.py --curate
    python .hailo/scripts/curate_contributions.py --curate --auto
    python .hailo/scripts/curate_contributions.py --promote <app_name>
"""

import argparse
import os
import re
import shutil
import sys
import textwrap
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Optional

# Resolve repo root
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]  # .hailo/scripts/ → repo root

CONTRIBUTIONS_DIR = REPO_ROOT / "community" / "contributions"
COMMUNITY_APPS_DIR = REPO_ROOT / "community" / "apps"
HAILO_MEMORY_DIR = REPO_ROOT / ".hailo" / "memory"
HAILO_KNOWLEDGE_DIR = REPO_ROOT / ".hailo" / "knowledge"
DEFINES_PATH = REPO_ROOT / "hailo_apps" / "python" / "core" / "common" / "defines.py"
RESOURCES_CONFIG_PATH = REPO_ROOT / "hailo_apps" / "config" / "resources_config.yaml"

# Category → target .hailo/ file mapping
CATEGORY_TARGET_MAP = {
    "pipeline-optimization": "memory/pipeline_optimization.md",
    "bottleneck-patterns": "memory/pipeline_optimization.md",
    "gen-ai-recipes": "memory/gen_ai_patterns.md",
    "hardware-config": "memory/hailo_platform_api.md",
    "model-tuning": "knowledge/best_practices.yaml",
    "general": "memory/common_pitfalls.md",
}

# Required frontmatter fields
REQUIRED_FIELDS = {"title", "category", "contributor", "date", "tags"}
OPTIONAL_FIELDS = {"hailo_arch", "app", "reproducibility"}

# Required content sections
REQUIRED_SECTIONS = {"Summary", "Context", "Finding", "Solution", "Results", "Applicability"}

# App type → hailo_apps subdirectory
APP_TYPE_DIR = {
    "gen_ai": "hailo_apps/python/gen_ai_apps",
    "pipeline": "hailo_apps/python/pipeline_apps",
    "standalone": "hailo_apps/python/standalone_apps",
}

# Colors for terminal output
class C:
    GREEN = "\033[92m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RESET = "\033[0m"


def parse_frontmatter(content: str) -> tuple[dict, str]:
    """Parse YAML frontmatter from markdown content.

    Args:
        content: Full markdown file content.

    Returns:
        Tuple of (frontmatter_dict, body_text).
    """
    if not content.startswith("---"):
        return {}, content

    parts = content.split("---", 2)
    if len(parts) < 3:
        return {}, content

    fm = {}
    for line in parts[1].strip().split("\n"):
        if ":" in line:
            key, _, val = line.partition(":")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            # Parse list values
            if val.startswith("[") and val.endswith("]"):
                val = [v.strip().strip('"').strip("'") for v in val[1:-1].split(",")]
            fm[key] = val

    body = parts[2].strip()
    return fm, body


def validate_contribution(filepath: Path) -> tuple[bool, list[str], dict, str]:
    """Validate a contribution file for format compliance.

    Args:
        filepath: Path to the contribution markdown file.

    Returns:
        Tuple of (is_valid, errors, frontmatter, body).
    """
    errors = []
    content = filepath.read_text(encoding="utf-8")
    fm, body = parse_frontmatter(content)

    # Check frontmatter
    if not fm:
        errors.append("Missing YAML frontmatter (--- delimiters)")
        return False, errors, fm, body

    missing = REQUIRED_FIELDS - set(fm.keys())
    if missing:
        errors.append(f"Missing required fields: {', '.join(sorted(missing))}")

    # Check category is valid
    if "category" in fm and fm["category"] not in CATEGORY_TARGET_MAP:
        errors.append(
            f"Invalid category '{fm['category']}'. "
            f"Valid: {', '.join(sorted(CATEGORY_TARGET_MAP.keys()))}"
        )

    # Check required sections
    found_sections = set(re.findall(r"^##\s+(.+)$", body, re.MULTILINE))
    missing_sections = REQUIRED_SECTIONS - found_sections
    if missing_sections:
        errors.append(f"Missing sections: {', '.join(sorted(missing_sections))}")

    # Check minimum content length
    if len(body) < 100:
        errors.append(f"Body too short ({len(body)} chars, minimum 100)")

    is_valid = len(errors) == 0
    return is_valid, errors, fm, body


def check_duplicate(title: str, target_file: Path) -> Optional[str]:
    """Check if a similar finding already exists in the target file.

    Args:
        title: Title of the contribution.
        target_file: Target .hailo/ file to check.

    Returns:
        Matching section title if duplicate found, None otherwise.
    """
    if not target_file.exists():
        return None

    content = target_file.read_text(encoding="utf-8")
    headers = re.findall(r"^##[#]?\s+(.+)$", content, re.MULTILINE)

    for header in headers:
        ratio = SequenceMatcher(None, title.lower(), header.lower()).ratio()
        if ratio > 0.7:
            return header

    return None


def format_contribution_for_memory(fm: dict, body: str) -> str:
    """Format a contribution as a memory file section.

    Args:
        fm: Parsed frontmatter dictionary.
        body: Markdown body content.

    Returns:
        Formatted markdown section ready to append.
    """
    title = fm.get("title", "Untitled")
    contributor = fm.get("contributor", "Unknown")
    date = fm.get("date", "Unknown")
    tags = fm.get("tags", [])
    if isinstance(tags, str):
        tags = [tags]
    tag_str = ", ".join(tags) if tags else "none"

    # Extract sections from body
    sections = {}
    current_section = None
    current_lines = []
    for line in body.split("\n"):
        header_match = re.match(r"^##\s+(.+)$", line)
        if header_match:
            if current_section:
                sections[current_section] = "\n".join(current_lines).strip()
            current_section = header_match.group(1)
            current_lines = []
        elif current_section:
            current_lines.append(line)
    if current_section:
        sections[current_section] = "\n".join(current_lines).strip()

    # Build formatted section
    lines = [
        f"\n### {title}",
        f"*Contributed by {contributor} on {date}. Tags: {tag_str}.*\n",
    ]

    # Include key sections inline
    for section_name in ["Summary", "Finding", "Solution"]:
        if section_name in sections:
            content = sections[section_name]
            if content:
                lines.append(f"**{section_name}**: {content}\n")

    # Results as a block if present
    if "Results" in sections and sections["Results"]:
        lines.append(f"**Results**:\n{sections['Results']}\n")

    return "\n".join(lines)


def append_to_target(target_path: Path, formatted_content: str):
    """Append formatted contribution to target .hailo/ file.

    Args:
        target_path: Path to target file.
        formatted_content: Formatted markdown to append.
    """
    if not target_path.exists():
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(f"# {target_path.stem}\n\n", encoding="utf-8")

    existing = target_path.read_text(encoding="utf-8")
    with target_path.open("a", encoding="utf-8") as f:
        if not existing.endswith("\n\n"):
            f.write("\n")
        f.write(formatted_content)
        f.write("\n")


def scan_contributions() -> list[dict]:
    """Scan all contribution files and return metadata.

    Returns:
        List of dicts with path, frontmatter, validity, errors.
    """
    results = []
    for category_dir in sorted(CONTRIBUTIONS_DIR.iterdir()):
        if not category_dir.is_dir():
            continue
        for filepath in sorted(category_dir.glob("*.md")):
            if filepath.name == "README.md":
                continue
            is_valid, errors, fm, body = validate_contribution(filepath)
            results.append({
                "path": filepath,
                "relative": filepath.relative_to(REPO_ROOT),
                "frontmatter": fm,
                "body": body,
                "is_valid": is_valid,
                "errors": errors,
                "category": category_dir.name,
            })
    return results


def scan_community_apps() -> list[dict]:
    """Scan all community apps and return metadata.

    Recursively searches community/apps/ for directories containing app.yaml,
    handling the nested structure (pipeline_apps/, standalone_apps/, gen_ai_apps/).

    Returns:
        List of dicts with path, manifest, validity info.
    """
    results = []
    if not COMMUNITY_APPS_DIR.exists():
        return results

    # Recursively find all app.yaml manifests
    for manifest_path in sorted(COMMUNITY_APPS_DIR.rglob("app.yaml")):
        app_dir = manifest_path.parent
        manifest = {}
        errors = []

        try:
            import yaml
            manifest = yaml.safe_load(manifest_path.read_text()) or {}
        except Exception as e:
            errors.append(f"Invalid app.yaml: {e}")

        # Check required files
        main_py = app_dir / f"{app_dir.name}.py"
        if not main_py.exists():
            errors.append(f"Missing main file: {app_dir.name}.py")
        if not (app_dir / "README.md").exists():
            errors.append("Missing README.md")

        results.append({
            "path": app_dir,
            "name": app_dir.name,
            "manifest": manifest,
            "errors": errors,
            "is_valid": len(errors) == 0,
        })

    # Also scan for apps WITHOUT app.yaml (legacy) — just list them as invalid
    for child in sorted(COMMUNITY_APPS_DIR.iterdir()):
        if not child.is_dir() or child.name.startswith((".","_")):
            continue
        # Check type subdirs (pipeline_apps/, standalone_apps/, gen_ai_apps/)
        if child.name in ("pipeline_apps", "standalone_apps", "gen_ai_apps"):
            for app_dir in sorted(child.iterdir()):
                if not app_dir.is_dir() or app_dir.name.startswith((".","_")):
                    continue
                # Skip if already found via app.yaml
                if any(r["path"] == app_dir for r in results):
                    continue
                results.append({
                    "path": app_dir,
                    "name": app_dir.name,
                    "manifest": {},
                    "errors": ["Missing app.yaml manifest"],
                    "is_valid": False,
                })

    return results


def cmd_scan():
    """Execute --scan: List all contributions and apps with status."""
    print(f"\n{C.BOLD}=== Community Contributions ==={C.RESET}\n")

    contributions = scan_contributions()
    if not contributions:
        print(f"  {C.DIM}No contribution files found.{C.RESET}")
    else:
        for c in contributions:
            status = f"{C.GREEN}VALID{C.RESET}" if c["is_valid"] else f"{C.RED}INVALID{C.RESET}"
            title = c["frontmatter"].get("title", "Untitled")
            category = c["category"]
            target = CATEGORY_TARGET_MAP.get(category, "?")
            print(f"  [{status}] {C.BOLD}{title}{C.RESET}")
            print(f"         File:     {c['relative']}")
            print(f"         Category: {category} → .hailo/{target}")
            if not c["is_valid"]:
                for err in c["errors"]:
                    print(f"         {C.RED}Error: {err}{C.RESET}")
            print()

    print(f"\n{C.BOLD}=== Community Apps ==={C.RESET}\n")

    apps = scan_community_apps()
    if not apps:
        print(f"  {C.DIM}No community apps found.{C.RESET}")
    else:
        for a in apps:
            status_str = f"{C.GREEN}VALID{C.RESET}" if a["is_valid"] else f"{C.RED}INVALID{C.RESET}"
            app_status = a["manifest"].get("status", "unknown")
            title = a["manifest"].get("title", a["name"])
            print(f"  [{status_str}] {C.BOLD}{title}{C.RESET} ({app_status})")
            print(f"         Path: community/apps/{a['name']}/")
            if a["manifest"]:
                print(f"         Type: {a['manifest'].get('type', '?')}, Arch: {a['manifest'].get('hailo_arch', '?')}")
            if not a["is_valid"]:
                for err in a["errors"]:
                    print(f"         {C.RED}Error: {err}{C.RESET}")
            print()

    # Summary
    valid_contribs = sum(1 for c in contributions if c["is_valid"])
    valid_apps = sum(1 for a in apps if a["is_valid"])
    print(f"{C.BOLD}Summary:{C.RESET}")
    print(f"  Contributions: {len(contributions)} found, {valid_contribs} valid")
    print(f"  Community Apps: {len(apps)} found, {valid_apps} valid")
    print()


def cmd_curate(auto: bool = False):
    """Execute --curate: Process contributions into .hailo/.

    Args:
        auto: If True, auto-accept valid contributions without prompting.
    """
    contributions = scan_contributions()
    if not contributions:
        print(f"\n{C.DIM}No contributions to curate.{C.RESET}")
        return

    curated = 0
    skipped = 0
    rejected = 0

    for c in contributions:
        title = c["frontmatter"].get("title", "Untitled")
        print(f"\n{C.BOLD}{'=' * 60}{C.RESET}")
        print(f"  {C.BOLD}{title}{C.RESET}")
        print(f"  File: {c['relative']}")
        print(f"  Category: {c['category']}")

        if not c["is_valid"]:
            print(f"  {C.RED}INVALID — skipping{C.RESET}")
            for err in c["errors"]:
                print(f"    {C.RED}• {err}{C.RESET}")
            rejected += 1
            continue

        # Check target
        target_rel = CATEGORY_TARGET_MAP.get(c["category"])
        if not target_rel:
            print(f"  {C.RED}No target mapping for category '{c['category']}'{C.RESET}")
            rejected += 1
            continue

        target_path = REPO_ROOT / ".hailo" / target_rel
        print(f"  Target: .hailo/{target_rel}")

        # Check for duplicates
        dup = check_duplicate(title, target_path)
        if dup:
            print(f"  {C.YELLOW}Possible duplicate: '{dup}'{C.RESET}")
            if auto:
                print(f"  {C.YELLOW}Auto-skip (duplicate){C.RESET}")
                skipped += 1
                continue

        # Show preview
        formatted = format_contribution_for_memory(c["frontmatter"], c["body"])
        print(f"\n{C.DIM}--- Preview of what will be appended ---{C.RESET}")
        preview = formatted[:500] + ("..." if len(formatted) > 500 else "")
        print(textwrap.indent(preview, "  "))
        print(f"{C.DIM}--- End preview ---{C.RESET}")

        if auto:
            decision = "y"
        else:
            decision = input(f"\n  {C.BOLD}Accept? [y]es / [n]o / [s]kip: {C.RESET}").strip().lower()

        if decision in ("y", "yes", ""):
            append_to_target(target_path, formatted)
            c["path"].unlink()
            print(f"  {C.GREEN}✓ Curated into .hailo/{target_rel} — original deleted{C.RESET}")
            curated += 1
        elif decision in ("n", "no"):
            c["path"].unlink()
            print(f"  {C.RED}✗ Rejected — original deleted{C.RESET}")
            rejected += 1
        else:
            print(f"  {C.YELLOW}→ Skipped (kept in place){C.RESET}")
            skipped += 1

    print(f"\n{C.BOLD}Curation complete:{C.RESET}")
    print(f"  {C.GREEN}Curated: {curated}{C.RESET}")
    print(f"  {C.YELLOW}Skipped: {skipped}{C.RESET}")
    print(f"  {C.RED}Rejected: {rejected}{C.RESET}")


def cmd_promote(app_name: str):
    """Execute --promote: Move community app to official hailo_apps/.

    Args:
        app_name: Name of the community app to promote.
    """
    app_dir = COMMUNITY_APPS_DIR / app_name
    if not app_dir.exists():
        print(f"{C.RED}Error: community/apps/{app_name}/ does not exist{C.RESET}")
        sys.exit(1)

    # Load manifest
    manifest_path = app_dir / "app.yaml"
    if not manifest_path.exists():
        print(f"{C.RED}Error: Missing app.yaml in community/apps/{app_name}/{C.RESET}")
        sys.exit(1)

    try:
        import yaml
        manifest = yaml.safe_load(manifest_path.read_text()) or {}
    except Exception as e:
        print(f"{C.RED}Error: Invalid app.yaml: {e}{C.RESET}")
        sys.exit(1)

    app_type = manifest.get("type", "gen_ai")
    if app_type not in APP_TYPE_DIR:
        print(f"{C.RED}Error: Unknown app type '{app_type}'. Valid: {list(APP_TYPE_DIR.keys())}{C.RESET}")
        sys.exit(1)

    target_parent = REPO_ROOT / APP_TYPE_DIR[app_type]
    target_dir = target_parent / app_name

    if target_dir.exists():
        print(f"{C.RED}Error: {target_dir.relative_to(REPO_ROOT)} already exists{C.RESET}")
        sys.exit(1)

    print(f"\n{C.BOLD}Promoting: {app_name}{C.RESET}")
    print(f"  From: community/apps/{app_name}/")
    print(f"  To:   {target_dir.relative_to(REPO_ROOT)}/")
    print(f"  Type: {app_type}")

    # Step 1: Validate with existing validation script
    validate_script = REPO_ROOT / ".hailo" / "scripts" / "validate_app.py"
    if validate_script.exists():
        print(f"\n  Running validation...")
        ret = os.system(f"python3 {validate_script} {app_dir}")
        if ret != 0:
            print(f"\n  {C.RED}Validation failed. Fix issues before promoting.{C.RESET}")
            sys.exit(1)
        print(f"  {C.GREEN}Validation passed{C.RESET}")

    # Step 2: Copy directory (don't move yet — we need to clean up)
    print(f"\n  Copying to {target_dir.relative_to(REPO_ROOT)}/...")
    shutil.copytree(app_dir, target_dir)

    # Step 3: Remove community-specific files from target
    for remove_file in ["app.yaml", "run.sh"]:
        rm_path = target_dir / remove_file
        if rm_path.exists():
            rm_path.unlink()
            print(f"  Removed {remove_file} (not needed after promotion)")

    # Step 4: Register in defines.py
    app_const = app_name.upper() + "_APP"
    app_title_const = app_name.upper() + "_APP_TITLE"
    title = manifest.get("title", app_name.replace("_", " ").title())

    defines_content = DEFINES_PATH.read_text(encoding="utf-8")
    if app_const not in defines_content:
        # Find the Gen AI app defaults section and append
        insert_marker = "# Gen AI app defaults"
        if insert_marker in defines_content:
            # Find the end of the Gen AI constants block
            lines = defines_content.split("\n")
            insert_idx = None
            in_genai = False
            for i, line in enumerate(lines):
                if insert_marker in line:
                    in_genai = True
                elif in_genai and line.strip() == "" and i + 1 < len(lines) and lines[i + 1].startswith("#"):
                    insert_idx = i
                    break
                elif in_genai and line.strip() == "" and i + 1 < len(lines) and not lines[i + 1].strip():
                    insert_idx = i
                    break

            if insert_idx:
                new_lines = [
                    f'{app_const} = "{app_name}"',
                    f'{app_title_const} = "{title}"',
                ]
                for new_line in reversed(new_lines):
                    lines.insert(insert_idx, new_line)
                DEFINES_PATH.write_text("\n".join(lines), encoding="utf-8")
                print(f"  {C.GREEN}Registered {app_const} in defines.py{C.RESET}")
            else:
                print(f"  {C.YELLOW}Could not find insertion point in defines.py — add manually:{C.RESET}")
                print(f'    {app_const} = "{app_name}"')
        else:
            print(f"  {C.YELLOW}Could not find Gen AI section in defines.py — add manually{C.RESET}")
    else:
        print(f"  {C.DIM}{app_const} already exists in defines.py{C.RESET}")

    # Step 5: Register in resources_config.yaml
    model = manifest.get("model", "")
    hailo_arch = manifest.get("hailo_arch", "hailo10h")

    config_content = RESOURCES_CONFIG_PATH.read_text(encoding="utf-8")
    if f"{app_name}:" not in config_content:
        # Determine which anchor to alias
        alias = "*vlm_chat_app"
        if "llm" in app_name.lower() or "chat" in app_name.lower():
            alias = "*llm_chat_app"
        elif "whisper" in app_name.lower() or "voice" in app_name.lower():
            alias = "*whisper_chat_app"

        # Find safe insertion point — before the clip section or metadata
        insert_before = "clip: &clip_app"
        if insert_before in config_content:
            config_content = config_content.replace(
                insert_before,
                f"{app_name}: {alias}\n\n{insert_before}",
            )
            RESOURCES_CONFIG_PATH.write_text(config_content, encoding="utf-8")
            print(f"  {C.GREEN}Registered {app_name} in resources_config.yaml{C.RESET}")
        else:
            print(f"  {C.YELLOW}Could not find insertion point in resources_config.yaml — add manually:{C.RESET}")
            print(f"    {app_name}: {alias}")
    else:
        print(f"  {C.DIM}{app_name} already exists in resources_config.yaml{C.RESET}")

    # Step 6: Delete the community app directory
    shutil.rmtree(app_dir)
    print(f"\n  {C.GREEN}Deleted community/apps/{app_name}/{C.RESET}")

    # Validate YAML
    print(f"\n  Validating YAML config...")
    try:
        import yaml
        yaml.safe_load(RESOURCES_CONFIG_PATH.read_text())
        print(f"  {C.GREEN}resources_config.yaml is valid{C.RESET}")
    except Exception as e:
        print(f"  {C.RED}YAML validation failed: {e}{C.RESET}")
        print(f"  {C.RED}Please fix resources_config.yaml manually{C.RESET}")

    print(f"\n{C.BOLD}{C.GREEN}✓ Promotion complete: {app_name} → {target_dir.relative_to(REPO_ROOT)}{C.RESET}")
    print(f"\n  Next steps:")
    print(f"  1. Review the promoted app code")
    print(f"  2. Run: python -m {APP_TYPE_DIR[app_type].replace('/', '.')}.{app_name}.{app_name} --help")
    print(f"  3. Commit the changes")


def main():
    """Entry point for the curation script."""
    parser = argparse.ArgumentParser(
        description="Curate community contributions and apps into .hailo/",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Examples:
              %(prog)s --scan                     List all contributions and apps
              %(prog)s --curate                   Interactive curation
              %(prog)s --curate --auto            Auto-accept valid contributions
              %(prog)s --promote my_app           Promote community app to official
        """),
    )

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--scan",
        action="store_true",
        help="List all contributions and community apps with status",
    )
    group.add_argument(
        "--curate",
        action="store_true",
        help="Process contributions into .hailo/ (interactive or auto)",
    )
    group.add_argument(
        "--promote",
        metavar="APP_NAME",
        help="Promote a community app to official hailo_apps/",
    )

    parser.add_argument(
        "--auto",
        action="store_true",
        help="Auto-accept valid contributions without prompting (with --curate)",
    )

    args = parser.parse_args()

    if args.scan:
        cmd_scan()
    elif args.curate:
        cmd_curate(auto=args.auto)
    elif args.promote:
        cmd_promote(args.promote)


if __name__ == "__main__":
    main()
