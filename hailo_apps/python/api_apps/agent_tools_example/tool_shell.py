"""
Read-only shell tool: run a limited set of safe Linux commands inside the repo.

Security constraints:
- Only whitelisted commands are allowed.
- No shell interpretation (shell=False); redirections/pipes won't work.
- CWD must be inside the repository root.
- Path-like args must resolve under the repository root.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any


name: str = "shell_readonly"
display_description: str = (
    "Run whitelisted read-only shell commands (ls, cat, grep, etc.) inside the repository."
)
description: str = (
    "Run safe read-only Linux commands within the repository. "
    "Use ONLY when the user explicitly asks to view files, list directories, or inspect data. "
    "Allowed commands: ls, cat, grep, head, tail, find, stat, wc, pwd, uname, whoami, ifconfig (read-only flags)."
)

schema: dict[str, Any] = {
    "type": "object",
    "properties": {
        "cmd": {"type": "string", "description": "Base command (e.g., ls, cat)"},
        "args": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Command arguments array (defaults to empty array if not specified).",
        },
        "cwd": {
            "type": "string",
            "description": "Working directory (optional). If omitted or empty, uses repo root. Must be under repo root if provided. Examples: omit for repo root, use '.' for current dir, or relative paths. NEVER use placeholder paths like '/path/to/repo'.",
        },
        "timeout_sec": {
            "type": "number",
            "description": "Execution timeout in seconds (defaults to 5 if not specified)."
        },
    },
    "required": ["cmd"],
}

TOOLS_SCHEMA: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": schema,
        },
    }
]


ALLOWED_COMMANDS = {
    "ls",
    "cat",
    "grep",
    "head",
    "tail",
    "find",
    "stat",
    "wc",
    "pwd",
    "uname",
    "whoami",
    "ifconfig",
}


def _repo_root() -> Path:
    # tools/tool_shell.py -> hailo_app_python/tools -> hailo_app_python -> hailo_apps -> repo root
    return Path(__file__).resolve().parents[3]


def _is_under_root(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except Exception:
        return False


def _validate_payload(payload: dict[str, Any]) -> dict[str, Any]:
    cmd = str(payload.get("cmd", "")).strip()
    if not cmd:
        return {"ok": False, "error": "Missing 'cmd'"}
    if cmd not in ALLOWED_COMMANDS:
        return {"ok": False, "error": f"Command '{cmd}' not allowed"}

    args_raw = payload.get("args", [])
    # Coerce non-list args into empty list to be forgiving with model output
    if not isinstance(args_raw, list):
        args_raw = []
    args = [str(a) for a in args_raw]

    timeout_sec = payload.get("timeout_sec", 5)
    try:
        timeout_sec = float(timeout_sec)
        if timeout_sec <= 0:
            timeout_sec = 5
    except Exception:
        timeout_sec = 5

    root = _repo_root()
    cwd_in = payload.get("cwd")
    cwd = Path(cwd_in) if cwd_in else root
    if not _is_under_root(cwd, root):
        return {"ok": False, "error": "'cwd' must be under repository root"}

    # Special handling for ifconfig: enforce read-only usage
    if cmd == "ifconfig":
        # Allow only no-args, or '-a' / '-s'. Any other token implies mutation or unsupported listing.
        readonly_flags = {"-a", "-s"}
        nonflag_tokens = [t for t in args if not t.startswith("-")]
        bad_flags = [t for t in args if t.startswith("-") and t not in readonly_flags]
        mutating_tokens = {"up", "down", "add", "del", "mtu", "netmask", "broadcast", "address", "addr"}
        if nonflag_tokens or bad_flags or any(t in mutating_tokens for t in args):
            return {
                "ok": False,
                "error": "ifconfig is restricted to read-only. Use no args, '-a' or '-s' only.",
            }
        safe_args = [t for t in args if t in readonly_flags]
        return {"ok": True, "data": {"cmd": cmd, "args": safe_args, "cwd": str(cwd), "timeout_sec": timeout_sec}}

    # Validate path-like args (skip flags starting with '-')
    safe_args: list[str] = []
    for a in args:
        if a.startswith("-"):
            safe_args.append(a)
            continue
        # Interpret as path if it looks like a file/dir token (simple heuristic)
        p = Path(a) if os.path.isabs(a) else (cwd / a)
        if _is_under_root(p, root):
            safe_args.append(str(a))
        else:
            return {"ok": False, "error": f"Path argument escapes repo root: {a}"}

    return {"ok": True, "data": {"cmd": cmd, "args": safe_args, "cwd": str(cwd), "timeout_sec": timeout_sec}}


def run(input_data: dict[str, Any]) -> dict[str, Any]:
    """
    Execute a read-only shell command.

    Args:
        input_data: Dictionary with keys:
            - cmd: Command name (e.g., 'ls', 'cat')
            - args: Optional list of arguments
            - cwd: Optional working directory (must be under repo root)
            - timeout_sec: Optional timeout in seconds (default: 5)

    Returns:
        Dictionary with keys:
            - ok: Whether command succeeded (exit_code == 0)
            - result: Formatted command output (if ok=True)
            - error: Error message (if ok=False)
    """
    v = _validate_payload(input_data)
    if not v.get("ok"):
        return v

    data = v["data"]
    cmd = data["cmd"]
    args = data["args"]
    cwd = data["cwd"]
    timeout_sec = data["timeout_sec"]

    try:
        completed = subprocess.run(
            [cmd, *args],
            cwd=cwd,
            shell=False,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            env={"PATH": os.getenv("PATH", ""), "LC_ALL": "C"},
        )

        # Format result as a readable string
        result_parts = []
        if completed.stdout:
            result_parts.append(completed.stdout.rstrip())
        if completed.stderr:
            result_parts.append(f"[stderr]: {completed.stderr.rstrip()}")

        result = "\n".join(result_parts) if result_parts else "(no output)"

        if completed.returncode == 0:
            return {"ok": True, "result": result}
        else:
            return {"ok": False, "error": f"Command failed (exit code {completed.returncode}): {result}"}
    except subprocess.TimeoutExpired as exc:
        error_msg = f"Timeout after {timeout_sec}s"
        if exc.stdout or exc.stderr:
            output_parts = []
            if exc.stdout:
                output_parts.append(exc.stdout.rstrip())
            if exc.stderr:
                output_parts.append(f"[stderr]: {exc.stderr.rstrip()}")
            error_msg += f"\nPartial output: {chr(10).join(output_parts)}"
        return {"ok": False, "error": error_msg}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


