#!/usr/bin/env python3
"""
Framework Integrity Validator for Hailo Agentic Development.

Validates cross-references, file existence, path consistency, and structural
integrity across the .hailo/ and .github/ agentic knowledge base.

This catches issues that generate_platforms.py --check misses:
  - Routing table references to non-existent files
  - File tree listings that don't match actual filenames
  - .hailo/ path leaks in .github/ generated files
  - Agent handoff targets that don't exist
  - Skill/toolset files missing required sections

Usage:
    python .hailo/scripts/validate_framework.py              # Full validation
    python .hailo/scripts/validate_framework.py --platform copilot  # Single platform
    python .hailo/scripts/validate_framework.py --verbose     # Show all checks (not just failures)

Exit codes:
    0 = All checks pass
    1 = One or more checks failed
"""

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
HAILO_DIR = REPO_ROOT / ".hailo"
GITHUB_DIR = REPO_ROOT / ".github"
CLAUDE_DIR = REPO_ROOT / ".claude"

# ---------------------------------------------------------------------------
# Validation checks
# ---------------------------------------------------------------------------


class ValidationResult:
    """Collects pass/fail results across checks."""

    def __init__(self, verbose: bool = False) -> None:
        self.passed: list[str] = []
        self.failed: list[str] = []
        self.verbose = verbose

    def ok(self, msg: str) -> None:
        self.passed.append(msg)
        if self.verbose:
            print(f"  ✓ {msg}")

    def fail(self, msg: str) -> None:
        self.failed.append(msg)
        print(f"  ✗ {msg}")

    @property
    def clean(self) -> bool:
        return len(self.failed) == 0

    def summary(self) -> str:
        total = len(self.passed) + len(self.failed)
        return f"{len(self.passed)}/{total} checks passed, {len(self.failed)} failed"


def validate_routing_table(result: ValidationResult) -> None:
    """Check that every path in copilot-instructions.md routing table resolves."""
    print("\n[1/7] Routing table path references")
    ci_path = GITHUB_DIR / "copilot-instructions.md"
    if not ci_path.exists():
        result.fail("copilot-instructions.md not found")
        return

    content = ci_path.read_text()

    # Extract backtick-quoted paths from routing table rows (lines with |)
    path_pattern = re.compile(r"\|\s*\*\*.*?\*\*\s*\|.*?\|")
    ref_pattern = re.compile(r"`([^`]+\.(md|yaml))`")

    for line in content.split("\n"):
        if not path_pattern.match(line.strip()):
            continue
        for match in ref_pattern.finditer(line):
            ref = match.group(1)
            # Skip glob patterns
            if "*" in ref:
                continue
            full = GITHUB_DIR / ref
            if full.exists():
                result.ok(f"routing: {ref}")
            else:
                result.fail(f"routing: {ref} → file not found at .github/{ref}")


def validate_file_tree(result: ValidationResult) -> None:
    """Check that the file tree listing in copilot-instructions.md matches reality."""
    print("\n[2/7] File tree listing accuracy")
    ci_path = GITHUB_DIR / "copilot-instructions.md"
    if not ci_path.exists():
        result.fail("copilot-instructions.md not found")
        return

    content = ci_path.read_text()

    # Extract filenames from tree lines (├── or └── prefix)
    tree_pattern = re.compile(r"[├└]── (.+?)(?:\s+←|$)")
    # Find the file tree block (between the ``` markers in the Agentic Development Files section)
    in_tree = False
    tree_dir_stack = [GITHUB_DIR]

    for line in content.split("\n"):
        if "Agentic Development Files" in line:
            in_tree = True
            continue
        if in_tree and line.strip() == "```":
            # Toggle: first ``` starts the block, second ends it
            if tree_dir_stack:
                in_tree = not in_tree
            continue
        if not in_tree:
            continue

        m = tree_pattern.search(line)
        if not m:
            continue

        entry = m.group(1).strip()
        # Skip directory entries (end with /) and non-.github paths
        if entry.endswith("/") or entry.startswith("CLAUDE") or entry.startswith("community"):
            continue

        # Determine which directory this file is in by indentation / section context
        # We check the most specific paths we can
        if ".agent.md" in entry:
            check_path = GITHUB_DIR / "agents" / entry
        elif ".prompt.md" in entry:
            check_path = GITHUB_DIR / "prompts" / entry
        elif ".instructions.md" in entry:
            check_path = GITHUB_DIR / "instructions" / entry
        elif "SKILL.md" in entry:
            # These are in subdirs — skip, validated by routing table
            continue
        elif entry.endswith(".py"):
            check_path = GITHUB_DIR / "scripts" / entry
        elif entry.endswith(".yaml"):
            check_path = GITHUB_DIR / "knowledge" / entry
        else:
            # Could be in skills/, toolsets/, memory/, instructions/
            # Try multiple locations
            found = False
            for subdir in ["skills", "toolsets", "memory", "instructions"]:
                if (GITHUB_DIR / subdir / entry).exists():
                    found = True
                    result.ok(f"tree: {entry}")
                    break
            if not found:
                result.fail(f"tree: {entry} → not found in any .github/ subdirectory")
            continue

        if check_path.exists():
            result.ok(f"tree: {entry}")
        else:
            result.fail(f"tree: {entry} → not found at {check_path.relative_to(REPO_ROOT)}")


def validate_no_hailo_leaks(result: ValidationResult) -> None:
    """Check that .github/ generated files don't reference .hailo/ paths (except headers)."""
    print("\n[3/7] No .hailo/ path leaks in .github/ files")

    # Patterns that are OK — these legitimately reference .hailo/ as a concept or destination
    ok_patterns = [
        "AUTO-GENERATED from .hailo/",
        "Source: .hailo/",
        "Run: python .hailo/",
        ".hailo/ → .github/",
        "`.hailo/` (source of truth)",
        "syncs `.hailo/`",
        "canonical knowledge base in .hailo/",
        "from `.hailo/`",
        # Curation workflow: .hailo/ is the target of curated knowledge
        "curated into `.hailo/`",
        "into `.hailo/`",
        "curate → .hailo/",
        "changes to `.github/`",
        # Memory/context notes about local docs
        "`.hailo/` docs",
        "`.hailo/` documentation",
    ]

    for md_file in sorted(GITHUB_DIR.rglob("*.md")):
        # Skip copilot-instructions.md — it's manually maintained and may legitimately
        # reference .hailo/ in the file tree or explanatory text
        if md_file.name == "copilot-instructions.md":
            continue

        content = md_file.read_text()
        rel = md_file.relative_to(REPO_ROOT)

        for i, line in enumerate(content.split("\n"), 1):
            if ".hailo/" not in line:
                continue
            # Check if this is an allowed pattern
            if any(pat in line for pat in ok_patterns):
                continue
            result.fail(f"{rel}:{i} — leaked .hailo/ reference: {line.strip()[:100]}")

    if not result.failed or all(".hailo/" not in f for f in result.failed):
        result.ok("No .hailo/ leaks found in .github/ generated files")


def validate_agent_handoffs(result: ValidationResult) -> None:
    """Check that agent handoff targets exist."""
    print("\n[4/7] Agent handoff targets")
    agents_dir = GITHUB_DIR / "agents"
    if not agents_dir.is_dir():
        result.fail("agents/ directory not found")
        return

    # Map agent names to filenames
    agent_files = {f.stem.replace(".agent", ""): f for f in agents_dir.glob("*.agent.md")}

    for agent_file in sorted(agents_dir.glob("*.agent.md")):
        content = agent_file.read_text()
        # Look for handoff agent references
        handoff_pattern = re.compile(r'agent:\s*"?(@?hl-[\w-]+)"?')
        for match in handoff_pattern.finditer(content):
            target = match.group(1).lstrip("@")
            if target in agent_files:
                result.ok(f"handoff: {agent_file.name} → {target}")
            else:
                result.fail(f"handoff: {agent_file.name} → {target} (agent not found)")


def validate_skill_sections(result: ValidationResult) -> None:
    """Check that build skill files have required sections."""
    print("\n[5/7] Skill file required sections")
    skills_dir = GITHUB_DIR / "skills"
    if not skills_dir.is_dir():
        result.fail("skills/ directory not found")
        return

    required_sections = ["## Build Process", "## Reference Implementation"]

    for skill_dir in sorted(skills_dir.iterdir()):
        skill_file = skill_dir / "SKILL.md" if skill_dir.is_dir() else None
        if not skill_file or not skill_file.exists():
            continue

        content = skill_file.read_text()
        for section in required_sections:
            if section in content:
                result.ok(f"section: {skill_dir.name} has '{section}'")
            else:
                result.fail(f"section: {skill_dir.name} missing '{section}'")


def validate_community_dirs(result: ValidationResult) -> None:
    """Check that community directories referenced in agent instructions exist."""
    print("\n[6/7] Community directory structure")

    expected_dirs = [
        "community/apps/gen_ai_apps",
        "community/apps/pipeline_apps",
        "community/apps/standalone_apps",
        "community/contributions/gen-ai-recipes",
        "community/contributions/pipeline-optimization",
        "community/contributions/bottleneck-patterns",
        "community/contributions/hardware-config",
        "community/contributions/camera-display",
        "community/contributions/voice-audio",
        "community/contributions/general",
    ]

    for d in expected_dirs:
        full = REPO_ROOT / d
        if full.is_dir():
            result.ok(f"dir: {d}")
        else:
            result.fail(f"dir: {d} → directory not found")


def validate_hailo_source_files(result: ValidationResult) -> None:
    """Check that .hailo/ source files referenced by the generator exist."""
    print("\n[7/7] .hailo/ source file integrity")

    expected_files = [
        # Agents
        "agents/hl-app-builder.md",
        "agents/hl-vlm-builder.md",
        "agents/hl-pipeline-builder.md",
        "agents/hl-standalone-builder.md",
        "agents/hl-agent-builder.md",
        "agents/hl-llm-builder.md",
        "agents/hl-voice-builder.md",
        # Build skills
        "skills/hl-build-vlm-app.md",
        "skills/hl-build-pipeline-app.md",
        "skills/hl-build-standalone-app.md",
        "skills/hl-build-agent-app.md",
        "skills/hl-build-llm-app.md",
        "skills/hl-build-voice-app.md",
        # Utility skills
        "skills/hl-monitoring.md",
        "skills/hl-event-detection.md",
        "skills/hl-camera.md",
        "skills/hl-model-management.md",
        "skills/hl-plan-and-execute.md",
        "skills/hl-validate.md",
        # Contextual rules
        "contextual-rules/gen-ai-apps.md",
        "contextual-rules/pipeline-apps.md",
        "contextual-rules/standalone-apps.md",
        "contextual-rules/core-framework.md",
        "contextual-rules/tests.md",
        # Instructions
        "instructions/coding-standards.md",
        "instructions/orchestration.md",
        "instructions/agent-protocols.md",
        "instructions/architecture.md",
        "instructions/gen-ai-development.md",
        "instructions/gstreamer-pipelines.md",
        "instructions/testing-patterns.md",
        # Toolsets
        "toolsets/hailo-sdk.md",
        "toolsets/gstreamer-elements.md",
        "toolsets/vlm-backend-api.md",
        "toolsets/core-framework-api.md",
        "toolsets/gen-ai-utilities.md",
        # Memory
        "memory/MEMORY.md",
        "memory/common_pitfalls.md",
        "memory/gen_ai_patterns.md",
        "memory/pipeline_optimization.md",
        "memory/camera_and_display.md",
        "memory/hailo_platform_api.md",
        # Knowledge
        "knowledge/knowledge_base.yaml",
        # Scripts
        "scripts/generate_platforms.py",
        "scripts/validate_app.py",
        "scripts/curate_contributions.py",
    ]

    for f in expected_files:
        full = HAILO_DIR / f
        if full.exists():
            result.ok(f".hailo/{f}")
        else:
            result.fail(f".hailo/{f} → not found")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate agentic framework cross-references and integrity"
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Show passing checks too (not just failures)",
    )
    parser.add_argument(
        "--platform", choices=["copilot", "claude", "all"], default="all",
        help="Which platform to validate (default: all)",
    )
    args = parser.parse_args()

    result = ValidationResult(verbose=args.verbose)

    print("=" * 60)
    print("  Hailo Agentic Framework Integrity Validator")
    print("=" * 60)

    # Always validate .hailo/ source
    validate_hailo_source_files(result)
    validate_community_dirs(result)

    # Platform-specific checks
    if args.platform in ("copilot", "all"):
        validate_routing_table(result)
        validate_file_tree(result)
        validate_no_hailo_leaks(result)
        validate_agent_handoffs(result)
        validate_skill_sections(result)

    # Summary
    print("\n" + "=" * 60)
    if result.clean:
        print(f"  ALL CHECKS PASSED — {result.summary()}")
    else:
        print(f"  CHECKS FAILED — {result.summary()}")
        print("\n  Failed checks:")
        for f in result.failed:
            print(f"    ✗ {f}")
    print("=" * 60)

    sys.exit(0 if result.clean else 1)


if __name__ == "__main__":
    main()
