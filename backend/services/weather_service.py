import httpx
from datetime import datetime
from typing import Optional, Dict, Any, List
from backend.config import settings
from backend.models.schemas import WeatherFacts
from backend.utils.logging_config import logger

class WeatherService:
    def __init__(self, base_url: Optional[str] = None):
        self.base_url = base_url or settings.OPEN_METEO_FORECAST_URL
        self._mock_failure: bool = False
        self._mock_weather: Optional[WeatherFacts] = None

    def set_mock_failure(self, fail: bool = True):
        """Used in test suites to simulate network/API outages."""
        self._mock_failure = fail

    def set_mock_weather(self, weather: Optional[WeatherFacts]):
        """Used in test suites to test severe live weather scenarios deterministically."""
        self._mock_weather = weather

    async def fetch_weather(
        self, 
        latitude: float, 
        longitude: float, 
        time_reference: str = "current"
    ) -> Optional[WeatherFacts]:
        """
        Fetches live weather data from Open-Meteo for given coordinates.
        Supports time-window extraction (e.g. 'this_afternoon', 'this_evening', 'tomorrow').
        Returns WeatherFacts or None if API fails.
        """
        if self._mock_failure:
            logger.warning("Simulated Weather API failure activated")
            return None

        if self._mock_weather is not None:
            logger.info("Using mock weather facts for testing")
            return self._mock_weather

        params = {
            "latitude": latitude,
            "longitude": longitude,
            "current": "temperature_2m,wind_speed_10m,precipitation,precipitation_probability,uv_index",
            "hourly": "temperature_2m,wind_speed_10m,precipitation,precipitation_probability,uv_index",
            "timezone": "auto",
            "forecast_days": 2
        }

        try:
            async with httpx.AsyncClient(timeout=settings.API_TIMEOUT_SECONDS) as client:
                response = await client.get(self.base_url, params=params)

                if response.status_code != 200:
                    logger.error(f"Weather API returned HTTP {response.status_code}: {response.text}")
                    return None

                data = response.json()
                current = data.get("current")
                hourly = data.get("hourly")

                if not current:
                    logger.error("Weather API response did not contain 'current' block")
                    return None

                # Extract based on time_reference
                return self._extract_weather_facts(current, hourly, time_reference, data)

        except httpx.RequestError as exc:
            logger.error(f"Network error communicating with Weather API: {exc}")
            return None
        except Exception as exc:
            logger.error(f"Unexpected error processing weather data: {exc}", exc_info=True)
            return None

    def _extract_weather_facts(
        self, 
        current: Dict[str, Any], 
        hourly: Optional[Dict[str, Any]], 
        time_ref: str,
        raw_data: Dict[str, Any]
    ) -> WeatherFacts:
        """
        Normalizes weather numbers. When a specific time window is asked (e.g., this evening),
        examines hourly data within that window to find highest risk values.
        """
        norm_ref = time_ref.lower().strip()
        
        # If no hourly or default to current
        if not hourly or norm_ref in ["current", "now", "immediately"]:
            return WeatherFacts(
                temperature_c=float(current.get("temperature_2m", 0.0)),
                wind_speed_kmh=float(current.get("wind_speed_10m", 0.0)),
                precipitation_mm=float(current.get("precipitation", 0.0)),
                precipitation_probability=float(current.get("precipitation_probability", 0.0)),
                uv_index=float(current.get("uv_index", 0.0)),
                timestamp=str(current.get("time", datetime.utcnow().isoformat())),
                time_context="current",
                raw_data=raw_data
            )

        # Inspect hourly data for time windows
        times = hourly.get("time", [])
        temps = hourly.get("temperature_2m", [])
        winds = hourly.get("wind_speed_10m", [])
        precips = hourly.get("precipitation", [])
        precip_probs = hourly.get("precipitation_probability", [])
        uvs = hourly.get("uv_index", [])

        # Filter indices by target hour range
        target_hours: List[int] = []
        target_day_offset = 0 # 0 for today, 1 for tomorrow

        if "tomorrow" in norm_ref:
            target_day_offset = 1
            target_hours = list(range(6, 22)) # daytime tomorrow
        elif "afternoon" in norm_ref:
            target_hours = [12, 13, 14, 15, 16, 17]
        elif "evening" in norm_ref or "tonight" in norm_ref:
            target_hours = [17, 18, 19, 20, 21, 22]
        elif "morning" in norm_ref:
            target_hours = [6, 7, 8, 9, 10, 11]
        elif "today" in norm_ref:
            target_hours = list(range(8, 22))

        selected_indices = []
        for i, t_str in enumerate(times):
            try:
                dt = datetime.fromisoformat(t_str)
                # Check day and hour
                if target_hours and dt.hour in target_hours:
                    selected_indices.append(i)
            except Exception:
                continue

        if not selected_indices:
            # Fallback to current values if hourly slice not found
            return WeatherFacts(
                temperature_c=float(current.get("temperature_2m", 0.0)),
                wind_speed_kmh=float(current.get("wind_speed_10m", 0.0)),
                precipitation_mm=float(current.get("precipitation", 0.0)),
                precipitation_probability=float(current.get("precipitation_probability", 0.0)),
                uv_index=float(current.get("uv_index", 0.0)),
                timestamp=str(current.get("time", datetime.utcnow().isoformat())),
                time_context=norm_ref,
                raw_data=raw_data
            )

        # Compute representative peak-risk metrics across the requested window
        max_wind = max(float(winds[i]) for i in selected_indices if i < len(winds))
        max_precip = max(float(precips[i]) for i in selected_indices if i < len(precips))
        max_precip_prob = max(float(precip_probs[i]) for i in selected_indices if i < len(precip_probs))
        max_uv = max(float(uvs[i]) for i in selected_indices if i < len(uvs))
        avg_temp = sum(float(temps[i]) for i in selected_indices if i < len(temps)) / len(selected_indices)

        rep_time = times[selected_indices[0]] if selected_indices else current.get("time")

        return WeatherFacts(
            temperature_c=round(avg_temp, 1),
            wind_speed_kmh=round(max_wind, 1),
            precipitation_mm=round(max_precip, 2),
            precipitation_probability=round(max_precip_prob, 1),
            uv_index=round(max_uv, 1),
            timestamp=str(rep_time),
            time_context=norm_ref,
            raw_data=raw_data
        )

weather_service = WeatherService()
