"""
Real weather tool using Open-Meteo API.
Gets current temperature and weather data for any location worldwide.
No API key required!
"""

from __future__ import annotations

from typing import Any

# Temperature unit configuration
# Default to Celsius. Note: Can be changed to "fahrenheit" if needed.
TEMPERATURE_UNIT: str = "celsius"

name: str = "weather"

# User-facing description (shown in CLI tool list)
display_description: str = (
    "Get current weather and rain forecasts (supports future days) using the Open-Meteo API."
)

# LLM instruction description (includes warnings for model)
description: str = (
    "CRITICAL: Use this tool ONLY when the user explicitly asks about weather, temperature, or rain. "
    "If you don't know the location of the query, do not call this tool. Ask the user for the location."
    "Supported requests: current temperature, forecasts for future days, rain/precipitation queries. "
    "For dates: use the 'future_days' parameter (e.g., 'tomorrow' -> future_days=1, 'in 3 days' -> future_days=3, 'today' -> future_days=0). "
    "Set include_rain=true when the user asks about rain or precipitation."
)

schema: dict[str, Any] = {
    "type": "object",
    "properties": {
        "location": {
            "type": "string",
            "description": "Location in 'City' or 'City, Country' format."
        },
        "future_days": {
            "type": "integer",
            "description": (
                "Number of days in the future for forecast (0=today, 1=tomorrow, 2=in 2 days, etc.). "
                "Defaults to 0 if not specified."
            ),
        },
        "include_rain": {
            "type": "boolean",
            "description": (
                "If true, include precipitation (rain) totals and probability. "
                "Defaults to false if not specified."
            ),
        },
    },
    "required": ["location"],
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


def _validate_input(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate input parameters."""
    try:
        from pydantic import BaseModel, Field

        class WeatherInput(BaseModel):
            location: str = Field(description="Location name")
            future_days: int = Field(default=0, description="Days in future for forecast (0=today, 1=tomorrow, 2=in 2 days)", ge=0)
            include_rain: bool = Field(default=False, description="Include precipitation data")

        data = WeatherInput(**payload).model_dump()
        # Ensure future_days is valid
        future_days = int(data.get("future_days", 0))
        if future_days < 0:
            future_days = 0
        data["future_days"] = future_days
        return {"ok": True, "data": data}
    except Exception:
        # Fallback validation without pydantic
        location = str(payload.get("location", "")).strip()
        future_days = payload.get("future_days", 0)
        try:
            future_days = int(future_days)
            if future_days < 0:
                future_days = 0
        except (ValueError, TypeError):
            future_days = 0
        include_rain = bool(payload.get("include_rain", False))
        if not location:
            return {"ok": False, "error": "Missing required 'location'"}
        return {"ok": True, "data": {"location": location, "future_days": future_days, "include_rain": include_rain}}


def run(input_data: dict[str, Any]) -> dict[str, Any]:
    """
    Get weather data for a location, optionally with forecast and precipitation.

    Args:
        input_data: Dictionary with keys:
            - location: Location name (required) - e.g., "New York", "London, UK", "Tel Aviv"
            - future_days: Optional number of days in future for forecast (0=today, 1=tomorrow, 2=in 2 days, default: 0)
            - include_rain: If True, include precipitation and rain probability data (default: False)

    Returns:
        Dictionary with 'ok' and weather data (if successful) or 'error' (if failed).
    """
    # Validate input
    validated = _validate_input(input_data)
    if not validated.get("ok"):
        return validated

    data = validated["data"]
    location = data["location"]
    future_days = data.get("future_days", 0)
    include_rain = data.get("include_rain", False)

    # Import weather API utility
    try:
        from .weather_api_utils import get_current_temperature, get_weather_forecast
    except ImportError:
        return {
            "ok": False,
            "error": "Weather API utilities not available. Ensure weather_api_utils.py is present."
        }

    # Call the weather API
    try:
        # Use forecast function if future_days > 0 or if include_rain is True
        if future_days > 0 or include_rain:
            result = get_weather_forecast(
                location=location,
                future_days=future_days,
                include_rain=include_rain,
                unit=TEMPERATURE_UNIT,
            )
        else:
            # Use simple current temperature for basic queries (today, no rain)
            result = get_current_temperature(location, TEMPERATURE_UNIT)

        # Check if result indicates an error
        if result.startswith("Error:"):
            return {"ok": False, "error": result}

        # Success - return the formatted weather data
        return {
            "ok": True,
            "result": result
        }
    except Exception as e:
        return {
            "ok": False,
            "error": f"Failed to fetch weather data: {str(e)}"
        }



