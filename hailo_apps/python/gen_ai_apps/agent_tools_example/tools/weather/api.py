"""
Weather API utilities for Open-Meteo.

Gets current temperature and weather data for any location worldwide.
No API key required!
"""

from __future__ import annotations

import logging
import time
from datetime import date, timedelta
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

    Args:
        location: Location string that may contain country abbreviations.

    Returns:
        Normalized location with full country names.
    """
    if "," in location:
        parts = [part.strip() for part in location.split(",")]
        if len(parts) >= 2 and parts[-1] in COUNTRY_ABBREVIATIONS:
            parts[-1] = COUNTRY_ABBREVIATIONS[parts[-1]]
            return ", ".join(parts)
    return location


def get_current_temperature(
    location: str, unit: str = "celsius", timeout: int = 5
) -> str:
    """
    Get the current temperature and time at a location using Open-Meteo API.

    Args:
        location: The location to get the temperature for.
        unit: Temperature unit ('celsius' or 'fahrenheit').
        timeout: Request timeout in seconds.

    Returns:
        Formatted string with temperature and time, or error message.
    """
    try:
        logger.debug("get_current_temperature() called: location=%s, unit=%s", location, unit)
        start_time = time.time()

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

        geo_response = requests.get(geocoding_url, params=geocoding_params, timeout=timeout)
        geo_response.raise_for_status()
        geo_data = geo_response.json()

        if not geo_data.get("results"):
            return f"Error: Location '{location}' not found. Please check the city name."

        first_result = geo_data["results"][0]
        latitude = first_result["latitude"]
        longitude = first_result["longitude"]
        location_name = first_result["name"]
        timezone = first_result.get("timezone", "GMT")

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

        weather_response = requests.get(weather_url, params=weather_params, timeout=timeout)
        weather_response.raise_for_status()
        weather_data = weather_response.json()

        current_weather = weather_data["current_weather"]
        temperature = current_weather["temperature"]
        time_str = current_weather["time"]

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


def get_weather_forecast(
    location: str,
    future_days: int = 0,
    include_rain: bool = False,
    unit: str = "celsius",
    timeout: int = 5,
) -> str:
    """
    Get weather forecast for a location with optional precipitation data.

    Args:
        location: Location name.
        future_days: Days in the future (0=today, 1=tomorrow, etc.)
        include_rain: Include precipitation data.
        unit: Temperature unit ('celsius' or 'fahrenheit').
        timeout: Request timeout in seconds.

    Returns:
        Formatted string with weather forecast.
    """
    try:
        logger.debug(
            "get_weather_forecast(): location=%s, future_days=%s, include_rain=%s",
            location, future_days, include_rain
        )
        start_time = time.time()

        normalized_location = normalize_location(location)

        # Step 1: Geocode the location
        geocoding_url = "https://geocoding-api.open-meteo.com/v1/search"
        geocoding_params: dict[str, Any] = {
            "name": normalized_location,
            "count": 1,
            "language": "en",
            "format": "json",
        }

        geo_response = requests.get(geocoding_url, params=geocoding_params, timeout=timeout)
        geo_response.raise_for_status()
        geo_data = geo_response.json()

        if not geo_data.get("results"):
            return f"Error: Location '{location}' not found."

        first_result = geo_data["results"][0]
        latitude = first_result["latitude"]
        longitude = first_result["longitude"]
        location_name = first_result["name"]
        timezone = first_result.get("timezone", "GMT")

        if "country" in first_result:
            location_name = f"{location_name}, {first_result['country']}"

        # Step 2: Calculate forecast date
        today = date.today()
        future_days = max(0, int(future_days))
        if future_days == 0:
            forecast_date = None
            is_today = True
        else:
            forecast_date_obj = today + timedelta(days=future_days)
            forecast_date = forecast_date_obj.isoformat()
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
            weather_params["current_weather"] = "true"
            if include_rain:
                weather_params["daily"] = "temperature_2m_max,temperature_2m_min,precipitation_sum,precipitation_probability_max"
                weather_params["forecast_days"] = 1
        else:
            weather_params["daily"] = "temperature_2m_max,temperature_2m_min"
            if include_rain:
                weather_params["daily"] += ",precipitation_sum,precipitation_probability_max"
            weather_params["start_date"] = forecast_date
            weather_params["end_date"] = forecast_date

        weather_response = requests.get(weather_url, params=weather_params, timeout=timeout)
        weather_response.raise_for_status()
        weather_data = weather_response.json()

        # Step 4: Format response
        result_parts: list[str] = []

        if is_today:
            if "current_weather" in weather_data:
                current = weather_data["current_weather"]
                temp = current["temperature"]
                time_str = current["time"]
                result_parts.append(
                    f"Current temperature in {location_name}: {temp:.1f}°{unit[0].upper()} "
                    f"(Local time: {time_str})"
                )

            if "daily" in weather_data and include_rain:
                daily = weather_data["daily"]
                if daily.get("time") and len(daily["time"]) > 0:
                    max_temp = daily["temperature_2m_max"][0]
                    min_temp = daily["temperature_2m_min"][0]
                    precip_sum = daily.get("precipitation_sum", [0])[0] or 0
                    precip_prob = daily.get("precipitation_probability_max", [0])[0] or 0

                    result_parts.append(
                        f"Today's forecast: High {max_temp:.1f}°{unit[0].upper()}, "
                        f"Low {min_temp:.1f}°{unit[0].upper()}"
                    )
                    if include_rain:
                        result_parts.append(
                            f"Precipitation: {precip_sum:.1f}mm expected ({precip_prob:.0f}% chance)"
                        )
        else:
            if "daily" in weather_data:
                daily = weather_data["daily"]
                if daily.get("time") and len(daily["time"]) > 0:
                    max_temp = daily["temperature_2m_max"][0]
                    min_temp = daily["temperature_2m_min"][0]

                    result_parts.append(f"Weather for {location_name} on {forecast_date}:")
                    result_parts.append(
                        f"High: {max_temp:.1f}°{unit[0].upper()}, Low: {min_temp:.1f}°{unit[0].upper()}"
                    )

                    if include_rain:
                        precip_sum = daily.get("precipitation_sum", [0])[0] or 0
                        precip_prob = daily.get("precipitation_probability_max", [0])[0] or 0

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

