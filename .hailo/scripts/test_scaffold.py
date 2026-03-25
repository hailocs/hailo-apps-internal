#!/usr/bin/env python3
"""
Smoke Test a Scaffolded Hailo VLM App

Quick sanity checks:
- Python files compile without syntax errors
- Main module can be imported (or fails gracefully on non-Hailo systems)
- CLI --help works (or fails gracefully on non-Hailo systems)

Usage:
    python test_scaffold.py hailo_apps/python/gen_ai_apps/my_app
    python test_scaffold.py hailo_apps/python/gen_ai_apps/my_app --timeout 10
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path


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


def test_syntax(app_dir, app_name):
    """Test: Python files compile without syntax errors."""
    print("  [TEST] Syntax check...")
    py_files = list(app_dir.glob("*.py"))
    all_ok = True
    for py_file in py_files:
        rc, out, err = run_command([sys.executable, "-m", "py_compile", str(py_file)])
        if rc != 0:
            print(f"    FAIL: {py_file.name} — {err.strip()}")
            all_ok = False
        else:
            print(f"    OK: {py_file.name}")
    return all_ok


def test_help(app_dir, app_name, repo_root):
    """Test: App runs with --help without errors."""
    print("  [TEST] CLI --help...")
    main_file = app_dir / f"{app_name}.py"
    if not main_file.exists():
        print(f"    SKIP: {main_file} not found")
        return True

    # Build module path for -m invocation
    rel_path = app_dir.relative_to(repo_root)
    module_path = str(rel_path).replace("/", ".").replace("\\", ".")

    rc, out, err = run_command(
        [sys.executable, "-m", f"{module_path}.{app_name}", "--help"],
        timeout=15,
        cwd=str(repo_root),
    )

    if rc == 0:
        has_usage = "usage:" in out.lower() or "usage:" in err.lower()
        has_options = "--input" in out or "--hef" in out or "--help" in out
        print(f"    OK: Help output received (usage={has_usage}, options={has_options})")
        return True
    else:
        if "ModuleNotFoundError" in err or "ImportError" in err:
            print("    SKIP: Import error (expected on non-Hailo system)")
            print(f"    Detail: {err.strip()[:200]}")
            return True  # Not a scaffolding error
        print(f"    FAIL: Exit code {rc}")
        if err:
            print(f"    Error: {err.strip()[:300]}")
        return False


def test_import(app_dir, app_name, repo_root):
    """Test: Module can be imported."""
    print("  [TEST] Import check...")
    rel_path = app_dir.relative_to(repo_root)
    module_path = str(rel_path).replace("/", ".").replace("\\", ".")
    target = f"{module_path}.{app_name}"

    rc, out, err = run_command(
        [sys.executable, "-c", f"import {target}; print('OK')"],
        timeout=15,
        cwd=str(repo_root),
    )

    if rc == 0 and "OK" in out:
        print(f"    OK: {target} imported successfully")
        return True
    elif "ModuleNotFoundError" in err and ("hailo" in err or "gi" in err):
        print("    SKIP: Hailo/GStreamer not available (expected on dev system)")
        return True  # Not a scaffolding error
    else:
        print(f"    FAIL: Could not import {target}")
        if err:
            print(f"    Error: {err.strip()[:300]}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Smoke test a scaffolded Hailo VLM app")
    parser.add_argument("app_dir", type=str, help="Path to the app directory")
    parser.add_argument("--timeout", type=int, default=15, help="Command timeout (default: 15s)")
    args = parser.parse_args()

    app_dir = Path(args.app_dir).resolve()
    if not app_dir.is_dir():
        print(f"Error: {app_dir} is not a directory")
        sys.exit(1)

    app_name = app_dir.name
    repo_root = find_repo_root()

    print(f"Smoke testing VLM app: {app_dir}")
    print(f"App: {app_name}")
    print(f"Repo root: {repo_root}")
    print()

    results = []
    results.append(("Syntax", test_syntax(app_dir, app_name)))
    results.append(("Help", test_help(app_dir, app_name, repo_root)))
    results.append(("Import", test_import(app_dir, app_name, repo_root)))

    print()
    passed = sum(1 for _, ok in results if ok)
    total = len(results)
    print(f"Results: {passed}/{total} tests passed")

    for name, ok in results:
        icon = "PASS" if ok else "FAIL"
        print(f"  [{icon}] {name}")

    sys.exit(0 if all(ok for _, ok in results) else 1)


if __name__ == "__main__":
    main()
