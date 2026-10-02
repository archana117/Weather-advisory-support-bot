import pytest
from backend.services.geocoding_service import geocoding_service
from backend.services.weather_service import weather_service
from backend.models.schemas import WeatherFacts

@pytest.mark.asyncio
async def test_geocoding_valid_city():
    loc = await geocoding_service.resolve_city("Bhopal")
    assert loc is not None
    assert "bhopal" in loc.city.lower()
    assert loc.latitude is not None
    assert loc.longitude is not None

@pytest.mark.asyncio
async def test_geocoding_empty_or_invalid():
    loc1 = await geocoding_service.resolve_city("")
    assert loc1 is None

    loc2 = await geocoding_service.resolve_city("FakeNonExistentCityXYZ9999")
    assert loc2 is None

@pytest.mark.asyncio
async def test_live_weather_fetch():
    # Coords for Bhopal
    weather = await weather_service.fetch_weather(23.25, 77.40, time_reference="current")
    assert weather is not None
    assert weather.temperature_c is not None
    assert weather.wind_speed_kmh is not None
    assert weather.precipitation_mm is not None
    assert weather.uv_index is not None

@pytest.mark.asyncio
async def test_weather_service_failure_simulation():
    weather_service.set_mock_failure(True)
    try:
        weather = await weather_service.fetch_weather(23.25, 77.40)
        assert weather is None
    finally:
        weather_service.set_mock_failure(False)

@pytest.mark.asyncio
async def test_weather_hourly_slice_evening():
    weather = await weather_service.fetch_weather(23.25, 77.40, time_reference="this_evening")
    assert weather is not None
    assert weather.time_context == "this_evening"
