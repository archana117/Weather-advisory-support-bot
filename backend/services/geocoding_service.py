import httpx
from typing import Optional
from backend.config import settings
from backend.models.schemas import LocationData
from backend.utils.logging_config import logger

class GeocodingService:
    def __init__(self, base_url: Optional[str] = None):
        self.base_url = base_url or settings.OPEN_METEO_GEOCODING_URL
        # In-memory cache: populated ONLY after successful Open-Meteo API resolution
        self._cache: dict = {}

    async def resolve_city(self, city_name: Optional[str]) -> Optional[LocationData]:
        """
        Resolves a city name to geographic coordinates using Open-Meteo Geocoding API.
        Takes the first returned result's latitude and longitude.
        Caches successful API results only AFTER the API resolution.
        Returns LocationData on success, or None if unresolvable / API failure.
        """
        if not city_name or not city_name.strip():
            logger.warning("Empty city name provided to geocoding service")
            return None

        clean_name = city_name.strip()
        cache_key = clean_name.lower()

        # Cache is checked, but contains only entries previously returned by the API
        if cache_key in self._cache:
            logger.info(f"Using cached API geocoding result for '{clean_name}'")
            return self._cache[cache_key]

        params = {
            "name": clean_name,
            "count": 5,
            "language": "en",
            "format": "json"
        }

        try:
            async with httpx.AsyncClient(timeout=settings.API_TIMEOUT_SECONDS) as client:
                response = await client.get(self.base_url, params=params)
                
                if response.status_code != 200:
                    logger.error(f"Geocoding API returned status code {response.status_code} for query '{clean_name}'")
                    return None

                data = response.json()
                results = data.get("results")
                if not results or len(results) == 0:
                    logger.warning(f"No geocoding results found for city '{clean_name}'")
                    return None

                # Select primary candidate
                best_match = results[0]
                location = LocationData(
                    city=best_match.get("name", clean_name),
                    country=best_match.get("country"),
                    admin1=best_match.get("admin1"),
                    latitude=float(best_match.get("latitude")),
                    longitude=float(best_match.get("longitude")),
                    timezone=best_match.get("timezone", "UTC")
                )
                self._cache[cache_key] = location
                logger.info(f"Resolved '{clean_name}' to {location.display_name} ({location.latitude}, {location.longitude})")
                return location

        except httpx.RequestError as exc:
            logger.error(f"Network error communicating with Geocoding API for '{clean_name}': {exc}")
            return None
        except Exception as exc:
            logger.error(f"Unexpected error in geocoding resolution for '{clean_name}': {exc}", exc_info=True)
            return None

geocoding_service = GeocodingService()
