"""System check tool — reports CPU, memory, disk, and temperature via psutil."""

import logging
import psutil

logger = logging.getLogger("v2a_demo")

# Known CPU temperature sensor names in priority order:
CPU_TEMP_SENSORS = ("cpu_thermal", "cpu-thermal", "coretemp")

# Prime the CPU percent counter so the first real call returns instantly.
psutil.cpu_percent()

TOOL_PROMPT = (
    "You are a JSON-only output machine. The user is requesting a system check.\n"
    "\n"
    "This tool takes NO parameters. Your ONLY output must be exactly: {}\n"
    "\n"
    "NEVER describe system status. NEVER run diagnostics. NEVER output text.\n"
    "\n"
    "Examples:\n"
    '"Run a system check." -> {}\n'
    '"Check the system status." -> {}\n'
    '"Run diagnostics" -> {}\n'
    '"Is the system working?" -> {}\n'
    '"System status please" -> {}\n'
    "\n"
    "Your output must be ONLY: {}\n"
    "Nothing before it. Nothing after it. Just: {}"
)

TOOL_DESCRIPTIONS = [
    "Run system diagnostics and health checks",
    "Check overall system status and health",
    "Perform system checks with no parameters",
    "Report system health and diagnostic information",
    "Handle requests to check system condition",
    "Run performance and status checks",
    "Respond to system diagnostic requests",
    "Check system state and operational health",
    "Provide system status verification",
]


def _format_bytes(n: int) -> str:
    """Return a human-friendly size string, e.g. '3.7 gigabytes'."""
    for unit in ("bytes", "kilobytes", "megabytes", "gigabytes", "terabytes"):
        if abs(n) < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} petabytes"



def _get_cpu_temperature() -> str | None:
    """Read CPU temperature if available. Returns rounded string or None.

    Note: Not supported on Windows and may return empty on some Linux/macOS setups.
    """
    if not hasattr(psutil, "sensors_temperatures"):
        logger.debug("Temperature not available: platform not supported")
        return None

    try:
        temps = psutil.sensors_temperatures()
        if not temps:
            logger.debug("Temperature not available: no sensors found")
            return None

        for key in CPU_TEMP_SENSORS:
            if key in temps and temps[key]:
                return f"{temps[key][0].current:.0f}"

        # Fallback: Use first available sensor
        first_avail_sensor = next(iter(temps.values()))
        if first_avail_sensor:
            return f"{first_avail_sensor[0].current:.0f}"
    except OSError as e:
        logger.warning(f"Temperature not available: {e}")
        return None

    logger.debug("Temperature not available: no known sensors matched")
    return None


def system_check() -> str:
    """Perform a quick system health check and return a TTS-friendly summary."""
    try:
        cpu_percent = psutil.cpu_percent()
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        temp = _get_cpu_temperature()

        report_list = [
            f"CPU usage is at {cpu_percent:.0f}%.",
        ]

        if temp is not None:
            report_list.append(f"CPU temperature is {temp} degrees Celsius.")

        report_list.append(
            f"RAM usage is {memory.percent:.0f}%, "
            f"{_format_bytes(memory.used)} used out of {_format_bytes(memory.total)}."
        )
        report_list.append(
            f"Disk usage is {disk.percent:.0f}%, "
            f"{_format_bytes(disk.used)} used out of {_format_bytes(disk.total)}."
        )
        return " ".join(report_list)

    except Exception as e:
        logger.error(f"System check failed: {e}")
        return "I couldn't complete the system check right now."
