#!/usr/bin/env python3
"""
Validate a Scaffolded Hailo VLM App

Checks that a scaffolded app has all required files, valid Python syntax,
resolvable imports, correct conventions, and no common mistakes.

Usage:
    python validate_app.py hailo_apps/python/gen_ai_apps/my_app
    python validate_app.py hailo_apps/python/gen_ai_apps/my_app --verbose
"""
import argparse
import os
import py_compile
import re
import sys
from pathlib import Path


class ValidationResult:
    """Collects pass/fail results for validation checks."""

    def __init__(self):
        self.checks = []

    def add(self, name, passed, detail=""):
        self.checks.append({"name": name, "passed": passed, "detail": detail})

    @property
    def all_passed(self):
        return all(c["passed"] for c in self.checks)

    def summary(self):
        lines = []
        for c in self.checks:
            icon = "PASS" if c["passed"] else "FAIL"
            line = f"  [{icon}] {c['name']}"
            if c["detail"]:
                line += f" — {c['detail']}"
            lines.append(line)
        passed = sum(1 for c in self.checks if c["passed"])
        total = len(self.checks)
        lines.append(f"\n  Result: {passed}/{total} checks passed")
        return "\n".join(lines)


def check_required_files(app_dir, app_name, result):
    """Check that all required files exist."""
    required = [f"{app_name}.py", "__init__.py"]
    for filename in required:
        filepath = app_dir / filename
        result.add(
            f"File exists: {filename}",
            filepath.exists(),
            str(filepath) if not filepath.exists() else "",
        )

    readme = app_dir / "README.md"
    result.add("README.md exists", readme.exists(), "(required for production apps)")


def check_python_syntax(app_dir, result):
    """Check Python syntax for all .py files."""
    py_files = list(app_dir.glob("*.py"))
    if not py_files:
        result.add("Python files found", False, "No .py files in directory")
        return

    for py_file in py_files:
        try:
            py_compile.compile(str(py_file), doraise=True)
            result.add(f"Syntax valid: {py_file.name}", True)
        except py_compile.PyCompileError as e:
            result.add(f"Syntax valid: {py_file.name}", False, str(e))


def check_no_relative_imports(app_dir, result):
    """Ensure no relative imports are used — all must be absolute."""
    for py_file in app_dir.glob("*.py"):
        if py_file.name == "__init__.py":
            continue
        content = py_file.read_text()
        lines = content.split("\n")
        relative_imports = []
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped.startswith("from .") or (
                stripped.startswith("import .") and not stripped.startswith("import os")
            ):
                relative_imports.append(f"  line {i}: {stripped}")

        if relative_imports:
            result.add(
                f"No relative imports: {py_file.name}",
                False,
                f"Found {len(relative_imports)} relative imports:\n" + "\n".join(relative_imports),
            )
        else:
            result.add(f"No relative imports: {py_file.name}", True)


def check_logger_usage(app_dir, app_name, result):
    """Check that get_logger is used (not print statements for logging)."""
    main_file = app_dir / f"{app_name}.py"
    if not main_file.exists():
        result.add("Logger check", False, f"{main_file} not found")
        return

    content = main_file.read_text()
    has_logger = "get_logger" in content
    result.add(
        "Uses get_logger",
        has_logger,
        "Missing: from hailo_apps.python.core.common.hailo_logger import get_logger" if not has_logger else "",
    )


def check_required_imports(app_dir, app_name, result):
    """Check for required framework imports in main app file."""
    main_file = app_dir / f"{app_name}.py"
    if not main_file.exists():
        return

    content = main_file.read_text()

    required = {
        "Backend import": "from hailo_apps.python.gen_ai_apps.vlm_chat.backend import Backend",
        "resolve_hef_path": "resolve_hef_path",
        "get_standalone_parser": "get_standalone_parser",
        "get_logger": "get_logger",
    }

    for name, pattern in required.items():
        found = pattern in content
        result.add(
            f"Import: {name}",
            found,
            f"Not found in {app_name}.py" if not found else "",
        )


def check_entry_point(app_dir, app_name, result):
    """Check that the app has a proper entry point."""
    main_file = app_dir / f"{app_name}.py"
    if not main_file.exists():
        return

    content = main_file.read_text()
    has_main_block = 'if __name__ == "__main__"' in content or "if __name__ == '__main__'" in content
    has_main_func = "def main(" in content

    result.add(
        "Has entry point",
        has_main_block or has_main_func,
        'Missing if __name__ == "__main__" block or main() function' if not (has_main_block or has_main_func) else "",
    )


def check_signal_handler(app_dir, app_name, result):
    """Check that SIGINT handler is registered for graceful shutdown."""
    main_file = app_dir / f"{app_name}.py"
    if not main_file.exists():
        return

    content = main_file.read_text()
    has_signal = "signal.SIGINT" in content or "signal.signal" in content
    result.add(
        "SIGINT handler",
        has_signal,
        "Missing signal handler for graceful shutdown" if not has_signal else "",
    )


def check_no_hardcoded_paths(app_dir, result):
    """Check for hardcoded paths that should use resolve_hef_path."""
    for py_file in app_dir.glob("*.py"):
        if py_file.name == "__init__.py":
            continue
        content = py_file.read_text()
        issues = []

        if "/home/" in content:
            issues.append("Contains /home/ path")
        if "/tmp/" in content and "tempfile" not in content:
            issues.append("Contains /tmp/ path")
        if re.search(r'["\'].*\.hef["\']', content) and "resolve_hef_path" not in content:
            issues.append("Hardcoded .hef path without resolve_hef_path")

        if issues:
            result.add(f"No hardcoded paths: {py_file.name}", False, "; ".join(issues))
        else:
            result.add(f"No hardcoded paths: {py_file.name}", True)


def check_readme_standards(app_dir, result):
    """Check README.md for documentation standards."""
    readme = app_dir / "README.md"
    if not readme.exists():
        return

    content = readme.read_text()

    if "/home/" in content or "~/." in content:
        result.add("README: no absolute paths", False, "Contains absolute paths")
    else:
        result.add("README: no absolute paths", True)

    if "/dev/video" in content:
        result.add("README: uses --input usb", False, "Uses /dev/videoN — should use --input usb")
    else:
        result.add("README: uses --input usb", True)

    sections = ["#", "usage", "requirements", "description"]
    found_sections = sum(1 for s in sections if s.lower() in content.lower())
    result.add(
        "README: has key sections",
        found_sections >= 3,
        f"Found {found_sections}/4 expected sections (heading, usage, requirements, description)",
    )


def main():
    parser = argparse.ArgumentParser(description="Validate a scaffolded Hailo VLM app")
    parser.add_argument("app_dir", type=str, help="Path to the app directory")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show all details")
    args = parser.parse_args()

    app_dir = Path(args.app_dir).resolve()
    if not app_dir.is_dir():
        print(f"Error: {app_dir} is not a directory")
        sys.exit(1)

    app_name = app_dir.name

    print(f"Validating VLM app: {app_dir}")
    print(f"App name: {app_name}")
    print()

    result = ValidationResult()

    check_required_files(app_dir, app_name, result)
    check_python_syntax(app_dir, result)
    check_no_relative_imports(app_dir, result)
    check_logger_usage(app_dir, app_name, result)
    check_required_imports(app_dir, app_name, result)
    check_entry_point(app_dir, app_name, result)
    check_signal_handler(app_dir, app_name, result)
    check_no_hardcoded_paths(app_dir, result)
    check_readme_standards(app_dir, result)

    print(result.summary())
    sys.exit(0 if result.all_passed else 1)


if __name__ == "__main__":
    main()
