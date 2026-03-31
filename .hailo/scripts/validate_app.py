#!/usr/bin/env python3
"""
Validate a Scaffolded Hailo App

Checks that a scaffolded app has all required files, valid Python syntax,
resolvable imports, correct conventions, and no common mistakes.
Works for any app type: VLM, pipeline, standalone, agent, voice.

With --smoke-test, also runs runtime checks (CLI --help, module import)
that gracefully skip on non-Hailo systems.

Usage:
    python3 validate_app.py hailo_apps/python/gen_ai_apps/my_app
    python3 validate_app.py hailo_apps/python/pipeline_apps/my_app --verbose
    python3 validate_app.py hailo_apps/python/pipeline_apps/my_app --smoke-test
"""
import argparse
import os
import py_compile
import re
import subprocess
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

    # Common imports required for all app types
    required = {
        "get_logger": "get_logger",
    }

    # Add type-specific imports based on content heuristics
    if "resolve_hef_path" in content or ".hef" in content:
        required["resolve_hef_path"] = "resolve_hef_path"

    # Check for appropriate parser usage
    has_pipeline_parser = "get_pipeline_parser" in content
    has_standalone_parser = "get_standalone_parser" in content
    has_any_parser = has_pipeline_parser or has_standalone_parser or "argparse" in content
    result.add(
        "Has CLI parser",
        has_any_parser,
        "No CLI parser found (expected get_pipeline_parser, get_standalone_parser, or argparse)" if not has_any_parser else "",
    )

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


def check_unused_imports(app_dir, result):
    """Check for unused imports — common when agents iterate and leave behind old attempts."""
    for py_file in app_dir.glob("*.py"):
        if py_file.name == "__init__.py":
            continue
        content = py_file.read_text()
        lines = content.split("\n")

        # Collect all imported names
        imported_names = []
        for line in lines:
            stripped = line.strip()
            # Skip comments and strings
            if stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith("'''"):
                continue
            # from X import Y, Z
            m = re.match(r"from\s+\S+\s+import\s+(.+)", stripped)
            if m:
                names_part = m.group(1)
                # Handle 'import X as Y' — track Y
                for name in names_part.split(","):
                    name = name.strip()
                    if not name or name.startswith("#") or name.startswith("("):
                        continue
                    if " as " in name:
                        name = name.split(" as ")[-1].strip()
                    # Remove trailing comments
                    name = name.split("#")[0].strip().rstrip(")")
                    if name and name.isidentifier():
                        imported_names.append(name)
            # import X, import X as Y
            elif stripped.startswith("import ") and "from" not in stripped:
                names_part = stripped[7:]
                for name in names_part.split(","):
                    name = name.strip()
                    if " as " in name:
                        name = name.split(" as ")[-1].strip()
                    # For 'import os.path', track 'os'
                    name = name.split(".")[0].strip()
                    name = name.split("#")[0].strip()
                    if name and name.isidentifier():
                        imported_names.append(name)

        # Check usage — remove import lines from search space
        non_import_content = "\n".join(
            line for line in lines
            if not line.strip().startswith("import ")
            and not line.strip().startswith("from ")
        )

        unused = []
        for name in imported_names:
            # Check if name appears in non-import code (as word boundary)
            if not re.search(r'\b' + re.escape(name) + r'\b', non_import_content):
                unused.append(name)

        if unused:
            result.add(
                f"No unused imports: {py_file.name}",
                False,
                f"Unused: {', '.join(unused)}",
            )
        else:
            result.add(f"No unused imports: {py_file.name}", True)


def check_unreachable_code(app_dir, result):
    """Check for unreachable code patterns — dead code left from agent iteration."""
    for py_file in app_dir.glob("*.py"):
        if py_file.name == "__init__.py":
            continue
        content = py_file.read_text()
        lines = content.split("\n")
        issues = []

        # Build a map of (enclosing_class, func_name) to detect true duplicates.
        # Methods with the same name in DIFFERENT classes (e.g., __init__, draw)
        # are NOT duplicates. Only same name in the same scope is a duplicate.
        current_class = None
        func_scope_map = {}  # (class_name_or_None, func_name) -> [line_numbers]
        for li, l in enumerate(lines, 1):
            s = l.strip()
            ind = len(l) - len(l.lstrip())
            if s.startswith("class ") and (":" in s):
                current_class = s.split("(")[0].split(":")[0].replace("class ", "")
            elif ind == 0 and s and not s.startswith(("@", "#", "def ")):
                # Module-level non-class, non-def code resets class context
                pass
            if s.startswith("def "):
                fn = s.split("(")[0].replace("def ", "")
                # If indented, it's a method in current_class; if indent=0, module-level
                scope = current_class if ind > 0 else None
                key = (scope, fn)
                func_scope_map.setdefault(key, []).append(li)

        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            # Code after unconditional return/break/continue/sys.exit at same indent
            if i < len(lines):
                if stripped in ("return", "break", "continue", "sys.exit(0)", "sys.exit(1)"):
                    # Check next non-empty line at same or deeper indent
                    indent = len(line) - len(line.lstrip())
                    for j in range(i, min(i + 3, len(lines))):
                        next_line = lines[j]
                        if not next_line.strip():
                            continue
                        next_indent = len(next_line) - len(next_line.lstrip())
                        next_stripped = next_line.strip()
                        # Same indent, not a decorator/def/class/except/elif/else/finally
                        if (next_indent == indent
                                and next_stripped
                                and not next_stripped.startswith(("def ", "class ", "@", "except", "elif", "else", "finally", "#"))):
                            issues.append(f"line {i}: code after '{stripped}' may be unreachable")
                        break

        # Check for duplicate functions within the same scope
        for (scope, fn), line_nums in func_scope_map.items():
            if len(line_nums) > 1:
                for ln in line_nums:
                    issues.append(f"line {ln}: duplicate function definition '{fn}'")

        # Deduplicate
        issues = list(dict.fromkeys(issues))

        if issues:
            result.add(
                f"No unreachable code: {py_file.name}",
                False,
                "; ".join(issues[:5]),  # Cap at 5 to avoid noise
            )
        else:
            result.add(f"No unreachable code: {py_file.name}", True)


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


# ---------------------------------------------------------------------------
# Runtime smoke tests (--smoke-test)
# ---------------------------------------------------------------------------

def find_repo_root():
    """Walk up from CWD to find the repo root (contains hailo_apps/)."""
    current = Path.cwd()
    for parent in [current] + list(current.parents):
        if (parent / "hailo_apps").is_dir():
            return parent
    return current


def run_command(cmd, timeout=15, cwd=None):
    """Run a command and return (returncode, stdout, stderr)."""
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        return proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "Command timed out"
    except Exception as e:
        return -1, "", str(e)


def check_cli_help(app_dir, app_name, result, timeout=15):
    """Smoke test: run app with --help and check it exits cleanly.

    Gracefully skips if Hailo/GStreamer dependencies are unavailable.
    """
    main_file = app_dir / f"{app_name}.py"
    if not main_file.exists():
        result.add("Smoke: CLI --help", True, "Skipped — main file not found")
        return

    repo_root = find_repo_root()
    try:
        rel_path = app_dir.relative_to(repo_root)
    except ValueError:
        result.add("Smoke: CLI --help", True, "Skipped — app not under repo root")
        return

    module_path = str(rel_path).replace("/", ".").replace("\\", ".")
    rc, out, err = run_command(
        [sys.executable, "-m", f"{module_path}.{app_name}", "--help"],
        timeout=timeout,
        cwd=str(repo_root),
    )

    if rc == 0:
        has_usage = "usage:" in out.lower() or "usage:" in err.lower()
        has_options = "--input" in out or "--hef" in out or "--help" in out
        result.add("Smoke: CLI --help", True, f"usage={has_usage}, options={has_options}")
    elif "ModuleNotFoundError" in err or "ImportError" in err:
        result.add("Smoke: CLI --help", True, "Skipped — Hailo/GStreamer not available")
    else:
        detail = err.strip()[:300] if err else f"Exit code {rc}"
        result.add("Smoke: CLI --help", False, detail)


def check_module_import(app_dir, app_name, result, timeout=15):
    """Smoke test: verify the module can be imported.

    Gracefully skips if Hailo/GStreamer dependencies are unavailable.
    """
    repo_root = find_repo_root()
    try:
        rel_path = app_dir.relative_to(repo_root)
    except ValueError:
        result.add("Smoke: import", True, "Skipped — app not under repo root")
        return

    module_path = str(rel_path).replace("/", ".").replace("\\", ".")
    target = f"{module_path}.{app_name}"

    rc, out, err = run_command(
        [sys.executable, "-c", f"import {target}; print('OK')"],
        timeout=timeout,
        cwd=str(repo_root),
    )

    if rc == 0 and "OK" in out:
        result.add("Smoke: import", True, f"{target} imported successfully")
    elif "ModuleNotFoundError" in err and ("hailo" in err or "gi" in err):
        result.add("Smoke: import", True, "Skipped — Hailo/GStreamer not available")
    else:
        detail = err.strip()[:300] if err else f"Exit code {rc}"
        result.add("Smoke: import", False, detail)


def main():
    parser = argparse.ArgumentParser(description="Validate a scaffolded Hailo app")
    parser.add_argument("app_dir", type=str, help="Path to the app directory")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show all details")
    parser.add_argument("--smoke-test", action="store_true",
                       help="Also run runtime smoke tests (CLI --help, module import)")
    parser.add_argument("--timeout", type=int, default=15,
                       help="Timeout for smoke test commands (default: 15s)")
    args = parser.parse_args()

    app_dir = Path(args.app_dir).resolve()
    if not app_dir.is_dir():
        print(f"Error: {app_dir} is not a directory")
        sys.exit(1)

    app_name = app_dir.name

    print(f"Validating app: {app_dir}")
    print(f"App name: {app_name}")
    if args.smoke_test:
        print(f"Mode: static checks + runtime smoke tests")
    print()

    result = ValidationResult()

    # Static checks (always run)
    check_required_files(app_dir, app_name, result)
    check_python_syntax(app_dir, result)
    check_no_relative_imports(app_dir, result)
    check_logger_usage(app_dir, app_name, result)
    check_required_imports(app_dir, app_name, result)
    check_entry_point(app_dir, app_name, result)
    check_signal_handler(app_dir, app_name, result)
    check_no_hardcoded_paths(app_dir, result)
    check_unused_imports(app_dir, result)
    check_unreachable_code(app_dir, result)
    check_readme_standards(app_dir, result)

    # Runtime smoke tests (opt-in via --smoke-test)
    if args.smoke_test:
        check_cli_help(app_dir, app_name, result, timeout=args.timeout)
        check_module_import(app_dir, app_name, result, timeout=args.timeout)

    print(result.summary())
    sys.exit(0 if result.all_passed else 1)


if __name__ == "__main__":
    main()
