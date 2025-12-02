"""
Tool discovery module.

Handles automatic discovery and collection of tool modules.
"""

import importlib
import logging
import pkgutil
import sys
import traceback
from pathlib import Path
from types import ModuleType
from typing import Any, List, Dict, Optional

# Setup logger
logger = logging.getLogger(__name__)


def discover_tool_modules(tool_dir: Optional[Path] = None) -> List[ModuleType]:
    """
    Discover tool modules from files named 'tool_*.py' in the tools directory.

    Args:
        tool_dir: Directory to search for tools. If None, searches the current directory.

    Returns:
        List of imported tool modules
    """
    modules: List[ModuleType] = []

    if tool_dir is None:
        # Fallback to current directory if not provided (legacy behavior support)
        target_dir = Path(__file__).parent
    else:
        target_dir = tool_dir

    # Ensure target directory is in sys.path
    if str(target_dir) not in sys.path:
        sys.path.insert(0, str(target_dir))

    # Build module name: use package prefix if available, otherwise just module name
    # Note: When importing from a dynamic path added to sys.path, we might not have a package prefix
    # or we might need to rely on the file name being importable directly.
    package_prefix = ""
    # If we are scanning a directory added to sys.path, we can import modules by name directly.
    # The original code used __package__ because it was inside the package.
    # When scanning an external dir, we don't prepend the current package name.

    logger.debug("Discovering tools in %s", target_dir)

    for module_info in pkgutil.iter_modules([str(target_dir)]):
        if not module_info.name.startswith("tool_"):
            continue

        module_name = module_info.name
        try:
            logger.debug("Importing module: %s", module_name)
            modules.append(importlib.import_module(module_name))
        except Exception as e:
            # Reason: Log detailed error but don't crash app if one tool is broken
            logger.error("Failed to import tool module '%s': %s", module_name, e)
            logger.debug(traceback.format_exc())
            continue

    return modules


def collect_tools(modules: List[ModuleType]) -> List[Dict[str, Any]]:
    """
    Collect tool metadata and schemas from tool modules.

    Args:
        modules: List of tool modules to process

    Returns:
        List of dictionaries with keys:
            - name: Tool name (string)
            - display_description: User-facing description for CLI (string)
            - llm_description: Description for LLM/tool schema (string)
            - tool_def: Full tool definition dict following the TOOL_SCHEMA format
            - runner: Callable that executes the tool (usually module.run)
            - module: The originating module (for debugging/logging)
    """
    tools: List[Dict[str, Any]] = []
    seen_names: set[str] = set()

    for m in modules:
        module_filename = getattr(m, "__file__", "unknown")

        # Check for run function
        run_fn = getattr(m, "run", None)
        if not callable(run_fn):
            logger.warning("Skipping module %s: missing 'run' function", module_filename)
            continue

        # Check for template or example tools that shouldn't be loaded
        module_tool_name = getattr(m, "name", None)
        if module_tool_name == "template_tool" or module_tool_name == "mytool":
            logger.debug("Skipping template tool in %s", module_filename)
            continue

        # Get metadata attributes
        tool_schemas = getattr(m, "TOOLS_SCHEMA", None)
        display_description = getattr(m, "display_description", None)
        llm_description_attr = getattr(m, "description", None)

        # Parse TOOLS_SCHEMA
        if tool_schemas and isinstance(tool_schemas, list):
            for entry in tool_schemas:
                if not isinstance(entry, dict):
                    logger.warning("Skipping invalid schema entry in %s: expected dict, got %s", module_filename, type(entry))
                    continue

                if entry.get("type") != "function":
                    continue

                function_def = entry.get("function", {})
                name = function_def.get("name")
                description = function_def.get("description", llm_description_attr or "")

                if not name:
                    logger.warning("Skipping unnamed tool in %s", module_filename)
                    continue

                if name in seen_names:
                    logger.warning("Skipping duplicate tool name '%s' in %s", name, module_filename)
                    continue

                seen_names.add(name)
                display_desc = display_description if display_description else description or name

                tools.append(
                    {
                        "name": str(name),
                        "display_description": str(display_desc),
                        "llm_description": str(description),
                        "tool_def": entry,
                        "runner": run_fn,
                        "module": m,
                    }
                )
        else:
            logger.warning("Skipping module %s: missing or invalid 'TOOLS_SCHEMA'", module_filename)

    tools.sort(key=lambda t: t["name"])
    return tools

