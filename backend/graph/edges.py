from typing import Literal
from backend.graph.state import WeatherBotState

def route_after_location(state: WeatherBotState) -> Literal["fetch_weather", "location_error"]:
    """Routes to fetch_weather if location was successfully resolved, else location_error."""
    if state.get("location") is not None and not state.get("error"):
        return "fetch_weather"
    return "location_error"

def route_after_weather(state: WeatherBotState) -> Literal["evaluate_policies", "weather_error"]:
    """Routes to evaluate_policies if weather was successfully retrieved, else weather_error."""
    if state.get("weather") is not None and not state.get("error"):
        return "evaluate_policies"
    return "weather_error"

def route_after_policy(state: WeatherBotState) -> Literal["compose_response", "no_sop"]:
    """Routes to compose_response if an SOP matched, else no_sop."""
    selected_sop = state.get("selected_sop")
    if selected_sop is not None and selected_sop.get("id"):
        return "compose_response"
    return "no_sop"
