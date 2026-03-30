#!/usr/bin/env python3
"""
Curate community contributions and propose updates to .hailo/ via PR.

Runs the full pipeline:
1. Pulls external contributions from hailo-rpi5-examples (--pull-external)
2. Runs curate_contributions.py --curate --auto to process findings into .hailo/memory/
3. Syncs platforms (.hailo/ → .github/, .claude/)
4. If any files changed, creates a branch and opens a PR

Prerequisites:
    - `gh` CLI installed and authenticated (`gh auth login`)
    - Git installed
    - Working tree is clean (no uncommitted changes in .hailo/)

Usage:
    python .hailo/scripts/curate_and_propose.py --dry-run    # Preview
    python .hailo/scripts/curate_and_propose.py               # Run + PR
"""

import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
CURATE_SCRIPT = SCRIPT_DIR / "curate_contributions.py"
GENERATE_PLATFORMS_SCRIPT = SCRIPT_DIR / "generate_platforms.py"
TARGET_REPO = "hailocs/hailo-apps-internal"
TARGET_BRANCH = "dev"


class C:
    GREEN = "\033[92m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RESET = "\033[0m"


def run_cmd(cmd, cwd=None, check=True):
    """Run a shell command and return stdout."""
    result = subprocess.run(
        cmd, shell=True, cwd=str(cwd or REPO_ROOT),
        check=check, capture_output=True, text=True,
    )
    return result.stdout.strip()


def check_gh_cli():
    """Verify gh CLI is installed and authenticated."""
    try:
        run_cmd("gh auth status")
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def get_hailo_diff():
    """Get git diff for .hailo/ and .github/ directories. Returns diff string or empty."""
    return run_cmd("git diff --stat .hailo/ .github/", check=False)


def run_platform_sync():
    """Run generate_platforms.py to sync .hailo/ changes to .github/ and .claude/."""
    if not GENERATE_PLATFORMS_SCRIPT.exists():
        print(f"{C.YELLOW}Warning: generate_platforms.py not found — skipping platform sync{C.RESET}")
        return False
    print(f"\n{C.BOLD}Syncing .hailo/ → .github/ and .claude/...{C.RESET}")
    result = subprocess.run(
        f"python3 {GENERATE_PLATFORMS_SCRIPT} --generate",
        shell=True, cwd=str(REPO_ROOT), check=False,
    )
    if result.returncode == 0:
        print(f"  {C.GREEN}Platform sync complete{C.RESET}")
    else:
        print(f"  {C.YELLOW}Platform sync had issues — check output{C.RESET}")
    return result.returncode == 0


def run_pull_external(dry_run=False):
    """Run curate_contributions.py --pull-external to fetch from hailo-rpi5-examples.

    Args:
        dry_run: If True, run with --dry-run.

    Returns:
        True if pull ran successfully.
    """
    cmd = f"python3 {CURATE_SCRIPT} --pull-external"
    if dry_run:
        cmd += " --dry-run"

    print(f"\n{C.BOLD}Pulling external contributions from hailo-rpi5-examples...{C.RESET}")
    result = subprocess.run(
        cmd, shell=True, cwd=str(REPO_ROOT),
        check=False,
    )
    return result.returncode == 0


def run_curation(dry_run=False):
    """Run curate_contributions.py --curate --auto.

    Args:
        dry_run: If True, run --scan instead of --curate.

    Returns:
        True if curation ran successfully.
    """
    if dry_run:
        cmd = f"python3 {CURATE_SCRIPT} --scan"
    else:
        cmd = f"python3 {CURATE_SCRIPT} --curate --auto"

    print(f"\n{C.BOLD}Running curation...{C.RESET}")
    result = subprocess.run(
        cmd, shell=True, cwd=str(REPO_ROOT),
        check=False,
    )
    return result.returncode == 0


def main():
    parser = argparse.ArgumentParser(
        description="Curate contributions and propose .hailo/ updates via PR",
    )
    parser.add_argument("--dry-run", action="store_true",
                       help="Scan contributions without curating or creating PR")
    args = parser.parse_args()

    # Step 1: Pull external contributions from hailo-rpi5-examples
    run_pull_external(dry_run=args.dry_run)

    # Step 2: Run curation
    success = run_curation(dry_run=args.dry_run)
    if not success:
        print(f"{C.RED}Curation had issues — check output above{C.RESET}")

    if args.dry_run:
        print(f"\n{C.YELLOW}[DRY RUN] No changes made. Run without --dry-run to curate and propose.{C.RESET}")
        return

    # Step 3: Sync platforms (.hailo/ → .github/, .claude/)
    run_platform_sync()

    # Step 4: Check if .hailo/ or .github/ changed
    diff = get_hailo_diff()
    if not diff:
        print(f"\n{C.DIM}No changes to .hailo/ or .github/ after curation. Nothing to propose.{C.RESET}")
        return

    print(f"\n{C.BOLD}Changes:{C.RESET}")
    print(diff)

    # Step 5: Check gh CLI
    if not check_gh_cli():
        print(f"\n{C.RED}Error: gh CLI not authenticated. Run: gh auth login{C.RESET}")
        print(f"{C.DIM}Changes are staged locally — commit manually if needed.{C.RESET}")
        sys.exit(1)

    # Step 6: Create branch and commit
    date_str = datetime.now().strftime("%Y%m%d-%H%M")
    branch_name = f"curate/{date_str}"

    print(f"\n{C.BOLD}Creating branch: {branch_name}{C.RESET}")
    run_cmd(f"git checkout -b {branch_name}")
    run_cmd("git add .hailo/ .github/ .claude/")

    # Build commit message from changed files
    changed_files = run_cmd("git diff --cached --name-only .hailo/ .github/ .claude/")
    commit_msg = f"curate: auto-incorporate community contributions\n\nUpdated files:\n{changed_files}"
    run_cmd(f'git commit -m "{commit_msg}"')

    # Step 7: Push and create PR
    print(f"\n{C.BOLD}Pushing and creating PR...{C.RESET}")
    run_cmd(f"git push origin {branch_name}")

    pr_title = f"[Curate] Knowledge base update {date_str}"
    pr_body = (
        "## Auto-curated knowledge base update\\n\\n"
        "Community contribution recipes have been processed into `.hailo/` files "
        "using the tiered curation system:\\n"
        "- **Tier 1**: Full content appended to memory/ and knowledge/ files\\n"
        "- **Tier 2**: Summaries added to Community Findings sections in skill/toolset/instruction files\\n"
        "- Platform mirrors (.github/, .claude/) regenerated via generate_platforms.py\\n\\n"
        f"### Changed files\\n```\\n{changed_files}\\n```\\n\\n"
        "---\\n*Generated by `curate_and_propose.py`*"
    )

    try:
        result = run_cmd(
            f'gh pr create --repo {TARGET_REPO} --base {TARGET_BRANCH} '
            f'--head {branch_name} --title "{pr_title}" --body "{pr_body}"',
        )
        print(f"\n{C.GREEN}PR created: {result}{C.RESET}")
    except subprocess.CalledProcessError as e:
        print(f"\n{C.YELLOW}Could not create PR: {e}{C.RESET}")
        print(f"{C.DIM}Changes committed on branch {branch_name} — create PR manually{C.RESET}")

    # Return to previous branch
    run_cmd("git checkout -", check=False)

    print(f"\n{C.BOLD}{C.GREEN}Done!{C.RESET}")


if __name__ == "__main__":
    main()
