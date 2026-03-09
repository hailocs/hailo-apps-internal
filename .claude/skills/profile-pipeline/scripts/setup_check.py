#!/usr/bin/env python3
"""
Check and install dependencies for the pipeline profiler.

Usage:
    python setup_check.py              # Check all dependencies
    python setup_check.py --install    # Install missing dependencies
    python setup_check.py --json       # Output status as JSON
"""

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys


def check_command(cmd, args=None):
    """Check if a command exists and optionally run it."""
    path = shutil.which(cmd)
    if not path:
        return {"installed": False, "path": None, "version": None}
    result = {"installed": True, "path": path, "version": None}
    if args:
        try:
            out = subprocess.run(
                [cmd] + args, capture_output=True, text=True, timeout=10
            )
            result["version"] = (out.stdout + out.stderr).strip().split("\n")[0]
        except Exception:
            pass
    return result


def check_gst_shark():
    """Check if GST-Shark tracers are installed."""
    result = {"installed": False, "tracers": []}
    try:
        out = subprocess.run(
            ["gst-inspect-1.0", "sharktracers"],
            capture_output=True, text=True, timeout=10
        )
        if out.returncode == 0 and "proctime" in out.stdout.lower():
            result["installed"] = True
            # Extract tracer names
            for line in out.stdout.split("\n"):
                line = line.strip()
                if line and ":" in line and not line.startswith("Plugin") and not line.startswith("="):
                    name = line.split(":")[0].strip()
                    if name and not name.startswith(" ") and name.isalpha():
                        result["tracers"].append(name)
    except FileNotFoundError:
        result["error"] = "gst-inspect-1.0 not found — GStreamer not installed"
    except Exception as e:
        result["error"] = str(e)
    return result


def check_python_deps():
    """Check Python dependencies."""
    deps = {}
    for mod in ["yaml"]:
        try:
            __import__(mod)
            deps[mod] = True
        except ImportError:
            deps[mod] = False
    return deps


def detect_arch():
    """Detect system architecture for install commands."""
    machine = platform.machine()
    if machine == "x86_64":
        return "x86_64", "/usr/lib/x86_64-linux-gnu/gstreamer-1.0/"
    elif machine == "aarch64":
        return "aarch64", "/usr/lib/aarch64-linux-gnu/gstreamer-1.0/"
    return machine, None


def get_full_status():
    """Get full dependency status."""
    arch, libdir = detect_arch()
    gst_shark = check_gst_shark()
    gstreamer = check_command("gst-inspect-1.0", ["--version"])
    python_deps = check_python_deps()
    gst_shark_source = os.path.expanduser("~/gst-shark")

    return {
        "arch": arch,
        "gst_libdir": libdir,
        "gstreamer": gstreamer,
        "gst_shark": gst_shark,
        "gst_shark_source_dir": gst_shark_source,
        "gst_shark_source_exists": os.path.isdir(gst_shark_source),
        "python_deps": python_deps,
        "all_ready": gstreamer["installed"] and gst_shark["installed"] and all(python_deps.values()),
    }


def print_status(status):
    """Print human-readable status."""
    print("=== Pipeline Profiler — Dependency Check ===\n")
    print(f"Architecture: {status['arch']}")

    # GStreamer
    gst = status["gstreamer"]
    icon = "OK" if gst["installed"] else "MISSING"
    print(f"\n[{icon}] GStreamer")
    if gst["installed"]:
        print(f"  Version: {gst['version']}")
    else:
        print("  Install: sudo apt-get install -y libgstreamer1.0-dev libgstreamer-plugins-base1.0-dev")

    # GST-Shark
    shark = status["gst_shark"]
    icon = "OK" if shark["installed"] else "MISSING"
    print(f"\n[{icon}] GST-Shark tracers")
    if shark["installed"]:
        if shark.get("tracers"):
            print(f"  Tracers: {', '.join(shark['tracers'])}")
    else:
        print("  GST-Shark is not installed. Required for profiling.")
        if shark.get("error"):
            print(f"  Error: {shark['error']}")

    # GST-Shark source
    icon = "OK" if status["gst_shark_source_exists"] else "INFO"
    print(f"\n[{icon}] GST-Shark source (~/gst-shark)")
    if status["gst_shark_source_exists"]:
        print(f"  Path: {status['gst_shark_source_dir']}")
    else:
        print("  Not found. Needed for building GST-Shark and generating PDF reports.")

    # Python deps
    for mod, ok in status["python_deps"].items():
        icon = "OK" if ok else "MISSING"
        print(f"\n[{icon}] Python: {mod}")
        if not ok:
            print(f"  Install: pip install pyyaml")

    # Summary
    print(f"\n{'='*50}")
    if status["all_ready"]:
        print("All dependencies are installed. Ready to profile!")
    else:
        print("Some dependencies are missing. See above for install instructions.")

    return status["all_ready"]


def get_install_commands(status):
    """Generate install commands for missing dependencies."""
    commands = []
    arch, libdir = status["arch"], status["gst_libdir"]

    if not status["gstreamer"]["installed"]:
        commands.append({
            "description": "Install GStreamer development libraries",
            "command": (
                "sudo apt-get update && sudo apt-get install -y "
                "libgstreamer1.0-dev libgstreamer-plugins-base1.0-dev "
                "libgstreamer-plugins-bad1.0-dev"
            ),
            "sudo": True,
        })

    if not status["gst_shark"]["installed"]:
        # Build tools
        commands.append({
            "description": "Install GST-Shark build dependencies",
            "command": (
                "sudo apt-get install -y "
                "git autoconf automake libtool graphviz pkg-config gtk-doc-tools"
            ),
            "sudo": True,
        })

        if not status["gst_shark_source_exists"]:
            commands.append({
                "description": "Clone GST-Shark repository",
                "command": "cd ~ && git clone https://github.com/RidgeRun/gst-shark.git",
                "sudo": False,
            })

        if libdir:
            commands.append({
                "description": f"Build and install GST-Shark ({arch})",
                "command": (
                    f"cd ~/gst-shark && "
                    f"./autogen.sh --prefix=/usr/ --libdir={libdir} && "
                    f"make && sudo make install"
                ),
                "sudo": True,
            })
        else:
            commands.append({
                "description": f"Build and install GST-Shark (unknown arch: {arch})",
                "command": (
                    "cd ~/gst-shark && "
                    "./autogen.sh --prefix=/usr/ && "
                    "make && sudo make install"
                ),
                "sudo": True,
                "note": f"Unknown architecture '{arch}'. You may need to set --libdir manually.",
            })

    for mod, ok in status["python_deps"].items():
        if not ok:
            commands.append({
                "description": f"Install Python {mod}",
                "command": f"pip install pyyaml",
                "sudo": False,
            })

    return commands


def main():
    parser = argparse.ArgumentParser(description="Check pipeline profiler dependencies")
    parser.add_argument("--install", action="store_true",
                        help="Print install commands for missing dependencies")
    parser.add_argument("--json", action="store_true",
                        help="Output status as JSON")
    args = parser.parse_args()

    status = get_full_status()

    if args.json:
        print(json.dumps(status, indent=2))
        sys.exit(0 if status["all_ready"] else 1)

    ready = print_status(status)

    if args.install or not ready:
        commands = get_install_commands(status)
        if commands:
            print(f"\n=== Install Commands ===")
            for i, cmd in enumerate(commands, 1):
                print(f"\n{i}. {cmd['description']}:")
                print(f"   {cmd['command']}")
                if cmd.get("note"):
                    print(f"   Note: {cmd['note']}")

    sys.exit(0 if ready else 1)


if __name__ == "__main__":
    main()
