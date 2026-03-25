"""Weather tool — forecasts via OpenWeatherMap API.

Requires the OPENWEATHER_API_KEY environment variable.
"""

import logging
import requests
from datetime import datetime, timedelta, timezone
from typing import Optional
import os

logger = logging.getLogger("v2a_demo")

def _log_warn_yellow(msg: str):
    """Log a warning highlighted in yellow."""
    logger.warning(f"\033[33m{msg}\033[0m")

API_KEY = os.getenv("OPENWEATHER_API_KEY")
if not API_KEY:
    _log_warn_yellow("OPENWEATHER_API_KEY is not set — weather tool will be unavailable")

TOOL_PROMPT = (
    "Extract parameters from the user's weather request as a JSON object.\n"
    "You MUST output ALL 2 fields in every response.\n"
    "\n"
    "Parameters:\n"
    '- "location" (required): The city name. Preserve exact spelling from user input.\n'
    '- "date" (required): MUST be ONLY one of: "today", "tomorrow", or "YYYY-MM-DD". No other values allowed.\n'
    "\n"
    "DATE NORMALIZATION - CRITICAL:\n"
    'ALL of these map to "today":\n'
    '- "this morning" -> "today"\n'
    '- "this afternoon" -> "today"\n'
    '- "this evening" -> "today"\n'
    '- "tonight" -> "today"\n'
    '- "later today" -> "today"\n'
    '- "next few hours" -> "today"\n'
    '- "right now" -> "today"\n'
    '- "currently" -> "today"\n'
    '- "at the moment" -> "today"\n'
    '- no date mentioned -> "today"\n'
    "\n"
    'NEVER output "this morning", "this afternoon", "tonight", "next few hours", or any other date value.\n'
    'ONLY output: "today", "tomorrow", or "YYYY-MM-DD".\n'
    "\n"
    "Examples:\n"
    '"What\'s the weather in London today?" -> {"location": "London", "date": "today"}\n'
    '"Will it rain tomorrow in Paris?" -> {"location": "Paris", "date": "tomorrow"}\n'
    '"If the sky looks strange over Eilat this morning, what does the forecast say?" -> {"location": "Eilat", "date": "today"}\n'
    '"Weather in Prague this morning" -> {"location": "Prague", "date": "today"}\n'
    '"For someone walking around Tokyo in the next few hours, what is the weather like?" -> {"location": "Tokyo", "date": "today"}\n'
    '"How\'s the weather in Berlin this afternoon?" -> {"location": "Berlin", "date": "today"}\n'
    '"Is it sunny in Tel Aviv right now?" -> {"location": "Tel Aviv", "date": "today"}\n'
    '"Do I need an umbrella in New York?" -> {"location": "New York", "date": "today"}\n'
    "\n"
    "Output ONLY the JSON object, nothing else."
)

TOOL_DESCRIPTIONS = [
    "Ask about the weather in a city",
    "Check current weather conditions for a location",
    "Weather forecast for today or tomorrow",
    "Ask about temperature in a city",
    "Ask if it will rain or be sunny in a place",
    "Umbrella or rain related questions for a city",
    "Questions about hot or cold weather",
    "Ask about wind, humidity, or clouds in a city",
    "General weather conditions for a location",
]


_ORDINALS = [
    "", "first", "second", "third", "fourth", "fifth", "sixth", "seventh",
    "eighth", "ninth", "tenth", "eleventh", "twelfth", "thirteenth",
    "fourteenth", "fifteenth", "sixteenth", "seventeenth", "eighteenth",
    "nineteenth", "twentieth", "twenty first", "twenty second", "twenty third",
    "twenty fourth", "twenty fifth", "twenty sixth", "twenty seventh",
    "twenty eighth", "twenty ninth", "thirtieth", "thirty first",
]


def _format_date_for_tts(d: datetime.date) -> str:
    """Format a date for natural TTS output, e.g. 'Thursday, February the twelfth'."""
    return d.strftime(f"%A, %B the {_ORDINALS[d.day]}")


def _resolve_date(date_str: Optional[str]) -> datetime.date:
    """Resolve 'today', 'tomorrow', or YYYY-MM-DD to a date object."""
    today = datetime.now(timezone.utc).date()
    if not date_str or date_str.lower() == "today":
        return today
    elif date_str.lower() == "tomorrow":
        return today + timedelta(days=1)
    else:
        try:
            return datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            raise ValueError("Invalid date format. Use 'today', 'tomorrow', or YYYY-MM-DD.")


def get_weather(location: str, date: Optional[str] = None) -> str:
    """
    Get accurate weather for today, tomorrow, or a specific date.

    Args:
        location: Name of the city
        date: 'today', 'tomorrow', or 'YYYY-MM-DD'. Defaults to 'today'

    Returns:
        Human-readable weather string.
    """
    if not API_KEY:
        _log_warn_yellow("Weather requested but OPENWEATHER_API_KEY is not set")
        return "Weather service is not configured."

    try:
        target_date = _resolve_date(date)
    except ValueError:
        return "I didn't understand that date. You can say today, tomorrow, or a specific date."

    date_str = _format_date_for_tts(target_date)

    url = "http://api.openweathermap.org/data/2.5/forecast"
    params = {
        "q": location,
        "appid": API_KEY,
        "units": "metric"
    }

    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        if data.get("cod") != "200":
            return f"I couldn't find the weather for {location} on {date_str}."

        forecasts = data["list"]
        target_forecasts = [
            f for f in forecasts
            if datetime.strptime(f["dt_txt"], "%Y-%m-%d %H:%M:%S").date() == target_date
        ]

        if not target_forecasts:
            return f"No forecast available for {location} on {date_str}."

        temps = [f["main"]["temp"] for f in target_forecasts]
        temp_min = round(min(temps))
        temp_max = round(max(temps))

        descriptions = [f["weather"][0]["description"] for f in target_forecasts]
        description = max(set(descriptions), key=descriptions.count).title()

        return (
            f"Weather in {location.title()} on {date_str}: {description}, "
            f"temperature from {temp_min} to {temp_max} degrees Celsius."
        )

    except Exception as e:
        logger.error(f"Weather API error for {location}: {e}")
        return f"I couldn't get the weather for {location} on {date_str}."
