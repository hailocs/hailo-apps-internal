"""
Shared utilities for weather API operations.

This module contains common functions used by both tool_usage_example.py
and test_weather_api.py to avoid code duplication.
"""

from __future__ import annotations

import logging
import time
from datetime import date, datetime, timedelta
from typing import Any

import requests

logger = logging.getLogger(__name__)

# Country abbreviation mapping for geocoding API
COUNTRY_ABBREVIATIONS = {
    "UK": "United Kingdom",
    "USA": "United States",
    "US": "United States",
    "UAE": "United Arab Emirates",
}


def normalize_location(location: str) -> str:
    """
    Normalize location name by replacing country abbreviations with full names.

    The Open-Meteo geocoding API requires full country names, not abbreviations.
    This function maps common abbreviations to their full names.

    Args:
        location: Location string that may contain country abbreviations.

    Returns:
        Normalized location with full country names.

    Examples:
        >>> normalize_location("London, UK")
        "London, United Kingdom"
        >>> normalize_location("New York, US")
        "New York, United States"
    """
    if "," in location:
        parts = [part.strip() for part in location.split(",")]
        if len(parts) >= 2 and parts[-1] in COUNTRY_ABBREVIATIONS:
            parts[-1] = COUNTRY_ABBREVIATIONS[parts[-1]]
            return ", ".join(parts)
    return location


def get_current_temperature(location: str, unit: str = "celsius", timeout: int = 5) -> str:
    """
    Get the current temperature and time at a location using Open-Meteo API.

    Fetches real-time weather data from the Open-Meteo API, a free weather API
    that requires NO API KEY. This makes it perfect for demos and examples.

    The function uses a geocoding service to convert location names to coordinates,
    then retrieves the current weather data including temperature and local time.

    Args:
        location: The location to get the temperature for (e.g., 'New York', 'London, UK').
        unit: The unit to return the temperature in ('celsius' or 'fahrenheit').
            Defaults to "celsius".
        timeout: Request timeout in seconds. Defaults to 5.

    Returns:
        A formatted string containing temperature and time information, or an error
        message if the API call fails.
    """
    try:
        logger.debug("get_current_temperature() called for location: %s, unit: %s", location, unit)
        start_time = time.time()

        # Normalize location name (replace abbreviations with full country names)
        normalized_location = normalize_location(location)
        logger.debug("Normalized location: %s", normalized_location)

        # Step 1: Geocode the location to get coordinates
        geocoding_url = "https://geocoding-api.open-meteo.com/v1/search"
        geocoding_params: dict[str, Any] = {
            "name": normalized_location,
            "count": 1,
            "language": "en",
            "format": "json",
        }

        logger.debug("Sending geocoding API request...")
        geo_start = time.time()
        geo_response = requests.get(geocoding_url, params=geocoding_params, timeout=timeout)
        logger.debug("Geocoding API response received in %.2fs", time.time() - geo_start)
        geo_response.raise_for_status()
        geo_data = geo_response.json()

        if not geo_data.get("results"):
            return f"Error: Location '{location}' not found. Please check the city name."

        # Get coordinates and timezone from first result
        first_result = geo_data["results"][0]
        latitude = first_result["latitude"]
        longitude = first_result["longitude"]
        location_name = first_result["name"]
        timezone = first_result.get("timezone", "GMT")

        # Add country if available
        if "country" in first_result:
            location_name = f"{location_name}, {first_result['country']}"

        # Step 2: Get current weather data
        weather_url = "https://api.open-meteo.com/v1/forecast"
        temp_unit = "celsius" if unit.lower() == "celsius" else "fahrenheit"

        weather_params: dict[str, Any] = {
            "latitude": latitude,
            "longitude": longitude,
            "current_weather": "true",
            "temperature_unit": temp_unit,
            "timezone": timezone,
        }

        logger.debug("Sending weather API request...")
        weather_start = time.time()
        weather_response = requests.get(weather_url, params=weather_params, timeout=timeout)
        logger.debug("Weather API response received in %.2fs", time.time() - weather_start)
        weather_response.raise_for_status()
        weather_data = weather_response.json()

        # Extract temperature and time
        current_weather = weather_data["current_weather"]
        temperature = current_weather["temperature"]
        time_str = current_weather["time"]  # ISO8601 format: "2025-10-16T15:45"

        result = (
            f"The current temperature in {location_name} is {temperature:.1f} degrees {unit}. "
            f"Local time: {time_str}"
        )

        logger.debug("get_current_temperature() completed in %.2fs", time.time() - start_time)
        return result

    except requests.exceptions.Timeout:
        return f"Error: Request timeout while fetching weather data for {location}"
    except requests.exceptions.RequestException as e:
        return f"Error fetching weather data: {str(e)}"
    except (KeyError, ValueError, IndexError) as e:
        return f"Error parsing weather data: {str(e)}"


def parse_date_query(date_query: str | None) -> str | None:
    """
    Parse a date query into an ISO format date string.

    Supports:
    - "today", "now" -> None (current date, handled separately)
    - "tomorrow" -> date string for tomorrow
    - "in X days" -> date string for X days from now
    - ISO format dates: "2025-01-15"
    - Relative days: "1" (tomorrow), "2" (day after tomorrow), etc.

    Args:
        date_query: Date query string or None for current/today

    Returns:
        ISO format date string (YYYY-MM-DD) or None for today/current
    """
    if not date_query or date_query.lower() in ("today", "now", "current"):
        return None

    date_query = date_query.strip().lower()
    today = date.today()

    # Handle "tomorrow"
    if date_query == "tomorrow":
        tomorrow = today + timedelta(days=1)
        return tomorrow.isoformat()

    # Handle "in X days" format
    if date_query.startswith("in ") and date_query.endswith(" days"):
        try:
            days = int(date_query.replace("in ", "").replace(" days", "").strip())
            target_date = today + timedelta(days=days)
            return target_date.isoformat()
        except ValueError:
            pass

    # Handle numeric days: "1" = tomorrow, "2" = day after, etc.
    try:
        days = int(date_query)
        if days >= 0:
            target_date = today + timedelta(days=days)
            return target_date.isoformat()
    except ValueError:
        pass

    # Handle ISO format dates (YYYY-MM-DD)
    try:
        parsed_date = datetime.strptime(date_query, "%Y-%m-%d").date()
        # Ensure date is not in the past (for forecast, only future dates)
        if parsed_date < today:
            return None
        return parsed_date.isoformat()
    except ValueError:
        pass

    # Try other common date formats
    date_formats = ["%Y/%m/%d", "%d/%m/%Y", "%m/%d/%Y"]
    for fmt in date_formats:
        try:
            parsed_date = datetime.strptime(date_query, fmt).date()
            if parsed_date < today:
                return None
            return parsed_date.isoformat()
        except ValueError:
            continue

    return None


def get_weather_forecast(
    location: str,
    future_days: int = 0,
    include_rain: bool = False,
    unit: str = "celsius",
    timeout: int = 5,
) -> str:
    """
    Get weather forecast for a location, optionally for a specific number of days in the future with precipitation data.

    Args:
        location: Location name (e.g., 'Tel Aviv', 'London, UK')
        future_days: Number of days in the future for forecast (0=today, 1=tomorrow, 2=in 2 days, etc.)
        include_rain: If True, include precipitation and rain probability data
        unit: Temperature unit ('celsius' or 'fahrenheit'). Defaults to "celsius"
        timeout: Request timeout in seconds. Defaults to 5

    Returns:
        Formatted string with weather forecast information
    """
    try:
        logger.debug(
            "get_weather_forecast() called: location=%s, future_days=%s, include_rain=%s, unit=%s",
            location,
            future_days,
            include_rain,
            unit,
        )
        start_time = time.time()

        # Normalize location
        normalized_location = normalize_location(location)
        logger.debug("Normalized location: %s", normalized_location)

        # Step 1: Geocode the location
        geocoding_url = "https://geocoding-api.open-meteo.com/v1/search"
        geocoding_params: dict[str, Any] = {
            "name": normalized_location,
            "count": 1,
            "language": "en",
            "format": "json",
        }

        logger.debug("Sending geocoding API request...")
        geo_start = time.time()
        geo_response = requests.get(geocoding_url, params=geocoding_params, timeout=timeout)
        logger.debug("Geocoding API response received in %.2fs", time.time() - geo_start)
        geo_response.raise_for_status()
        geo_data = geo_response.json()

        if not geo_data.get("results"):
            return f"Error: Location '{location}' not found. Please check the city name."

        # Get coordinates and timezone
        first_result = geo_data["results"][0]
        latitude = first_result["latitude"]
        longitude = first_result["longitude"]
        location_name = first_result["name"]
        timezone = first_result.get("timezone", "GMT")

        if "country" in first_result:
            location_name = f"{location_name}, {first_result['country']}"

        # Step 2: Calculate forecast date from future_days
        today = date.today()
        future_days = max(0, int(future_days))  # Ensure non-negative
        if future_days == 0:
            forecast_date = None  # Today - use current weather
            is_today = True
        else:
            forecast_date_obj = today + timedelta(days=future_days)
            forecast_date = forecast_date_obj.isoformat()  # Convert to YYYY-MM-DD
            is_today = False

        # Step 3: Get weather forecast
        weather_url = "https://api.open-meteo.com/v1/forecast"
        temp_unit = "celsius" if unit.lower() == "celsius" else "fahrenheit"

        weather_params: dict[str, Any] = {
            "latitude": latitude,
            "longitude": longitude,
            "temperature_unit": temp_unit,
            "timezone": timezone,
        }

        if is_today:
            # For today, get current weather + forecast
            weather_params["current_weather"] = "true"
            if include_rain:
                # Get daily forecast for precipitation
                weather_params["daily"] = "temperature_2m_max,temperature_2m_min,precipitation_sum,precipitation_probability_max"
                weather_params["forecast_days"] = 1
        else:
            # For future dates, use daily forecast
            weather_params["daily"] = "temperature_2m_max,temperature_2m_min"
            if include_rain:
                weather_params["daily"] += ",precipitation_sum,precipitation_probability_max"
            # forecast_date is already in ISO format (YYYY-MM-DD)
            # Note: When using start_date/end_date, do NOT set forecast_days (they conflict)
            weather_params["start_date"] = forecast_date
            weather_params["end_date"] = forecast_date

        logger.debug("Sending weather API request...")
        weather_start = time.time()
        weather_response = requests.get(weather_url, params=weather_params, timeout=timeout)
        logger.debug("Weather API response received in %.2fs", time.time() - weather_start)
        weather_response.raise_for_status()
        weather_data = weather_response.json()

        # Step 4: Format response
        result_parts: list[str] = []

        if is_today:
            # Current weather for today
            if "current_weather" in weather_data:
                current = weather_data["current_weather"]
                temp = current["temperature"]
                time_str = current["time"]
                result_parts.append(f"Current temperature in {location_name}: {temp:.1f}°{unit[0].upper()} (Local time: {time_str})")

            # Daily forecast for today
            if "daily" in weather_data and include_rain:
                daily = weather_data["daily"]
                if daily.get("time") and len(daily["time"]) > 0:
                    max_temp = daily["temperature_2m_max"][0]
                    min_temp = daily["temperature_2m_min"][0]
                    precip_sum = daily.get("precipitation_sum", [0])[0] if daily.get("precipitation_sum") else 0
                    precip_prob = daily.get("precipitation_probability_max", [0])[0] if daily.get("precipitation_probability_max") else 0

                    result_parts.append(f"Today's forecast: High {max_temp:.1f}°{unit[0].upper()}, Low {min_temp:.1f}°{unit[0].upper()}")
                    if include_rain:
                        result_parts.append(f"Precipitation: {precip_sum:.1f}mm expected ({precip_prob:.0f}% chance)")
        else:
            # Forecast for future date
            if "daily" in weather_data:
                daily = weather_data["daily"]
                date_display = forecast_date  # Could format this better

                if daily.get("time") and len(daily["time"]) > 0:
                    max_temp = daily["temperature_2m_max"][0]
                    min_temp = daily["temperature_2m_min"][0]

                    result_parts.append(f"Weather for {location_name} on {date_display}:")
                    result_parts.append(f"High: {max_temp:.1f}°{unit[0].upper()}, Low: {min_temp:.1f}°{unit[0].upper()}")

                    if include_rain:
                        precip_sum = daily.get("precipitation_sum", [0])[0] if daily.get("precipitation_sum") else 0
                        precip_prob = daily.get("precipitation_probability_max", [0])[0] if daily.get("precipitation_probability_max") else 0

                        if precip_sum > 0 or precip_prob > 0:
                            result_parts.append(f"Rain expected: {precip_sum:.1f}mm ({precip_prob:.0f}% chance)")
                        else:
                            result_parts.append("No rain expected")

        result = " ".join(result_parts)
        logger.debug("get_weather_forecast() completed in %.2fs", time.time() - start_time)
        return result

    except requests.exceptions.Timeout:
        return f"Error: Request timeout while fetching weather data for {location}"
    except requests.exceptions.RequestException as e:
        return f"Error fetching weather data: {str(e)}"
    except (KeyError, ValueError, IndexError) as e:
        return f"Error parsing weather data: {str(e)}"

