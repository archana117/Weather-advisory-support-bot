from typing import Dict, Any, List

from backend.graph.state import WeatherBotState
from backend.models.schemas import UserIntent, LocationData, WeatherFacts
from backend.models.sop_models import PolicyEvaluationResult
from backend.services.geocoding_service import geocoding_service
from backend.services.weather_service import weather_service
from backend.services.sop_service import sop_service
from backend.services.llm_service import llm_service
from backend.utils.logging_config import logger

async def parse_user_query_node(state: WeatherBotState) -> Dict[str, Any]:
    """Parses user input to extract structured intent, taking session history into account."""
    user_q = state.get("user_question", "")
    history = list(state.get("messages", []))
    prev_intent = state.get("intent") or {}
    prev_loc = state.get("location") or {}
    
    logger.info(f"Node [parse_user_query] processing: '{user_q}'")
    intent = await llm_service.parse_intent(user_q, history)

    # Multi-turn Context Carryover:
    # If the user did not specify location/activity/user_group in this turn,
    # carry forward from the active session's checkpoint
    if not intent.location:
        if prev_intent.get("location"):
            intent.location = prev_intent.get("location")
        elif prev_loc.get("city"):
            intent.location = prev_loc.get("city")

    if not intent.activity and prev_intent.get("activity"):
        intent.activity = prev_intent.get("activity")

    if intent.user_group == "all" and prev_intent.get("user_group"):
        intent.user_group = prev_intent.get("user_group")

    history.append({
        "role": "user",
        "content": user_q,
        "intent": intent.model_dump()
    })
    
    return {
        "intent": intent.model_dump(),
        "messages": history
    }

async def resolve_location_node(state: WeatherBotState) -> Dict[str, Any]:
    """Resolves extracted city name into geographic coordinates via Open-Meteo Geocoding."""
    intent_data = state.get("intent") or {}
    city_name = intent_data.get("location")
    prev_loc = state.get("location")

    logger.info(f"Node [resolve_location] resolving: '{city_name}'")

    if not city_name:
        return {
            "location": None,
            "error": "No geographic location specified in query.",
            "status": "location_error"
        }

    # Reuse previously resolved location if identical to avoid redundant network call
    if prev_loc and prev_loc.get("city", "").lower() == city_name.lower() and prev_loc.get("latitude"):
        logger.info(f"Reusing cached session location: {prev_loc.get('city')}")
        return {
            "location": prev_loc,
            "error": None
        }

    location = await geocoding_service.resolve_city(city_name)
    if not location:
        return {
            "location": None,
            "error": f"Unable to resolve location '{city_name}'.",
            "status": "location_error"
        }

    return {
        "location": location.model_dump(),
        "error": None
    }

async def location_error_node(state: WeatherBotState) -> Dict[str, Any]:
    """Generates honest response when location resolution fails."""
    intent_data = state.get("intent") or {}
    city_name = intent_data.get("location")
    
    if city_name:
        msg = (
            f"I could not locate or resolve '{city_name}' via the geocoding service. "
            "Please check the spelling or specify a nearby recognized city so I can fetch live weather data."
        )
    else:
        msg = (
            "I could not determine the location for your inquiry. "
            "Please specify a city name (for example, 'in Bhopal', 'in Mumbai', or 'in London') so I can check live weather conditions."
        )

    # Append to history
    messages = list(state.get("messages", []))
    messages.append({
        "role": "assistant",
        "content": msg,
        "intent": intent_data
    })

    return {
        "response": msg,
        "status": "location_error",
        "messages": messages
    }

async def fetch_weather_node(state: WeatherBotState) -> Dict[str, Any]:
    """Fetches live weather facts from Open-Meteo using resolved coordinates."""
    loc_dict = state.get("location")
    intent_dict = state.get("intent") or {}
    time_ref = intent_dict.get("time_reference", "current")

    if not loc_dict:
        return {
            "weather": None,
            "error": "Location data missing prior to weather fetch.",
            "status": "weather_error"
        }

    lat = loc_dict.get("latitude")
    lon = loc_dict.get("longitude")

    logger.info(f"Node [fetch_weather] coords: ({lat}, {lon}), time_ref: '{time_ref}'")
    weather = await weather_service.fetch_weather(lat, lon, time_reference=time_ref)

    if not weather:
        return {
            "weather": None,
            "error": "Failed to fetch live weather data from Open-Meteo.",
            "status": "weather_error"
        }

    return {
        "weather": weather.model_dump(),
        "error": None
    }

async def weather_error_node(state: WeatherBotState) -> Dict[str, Any]:
    """Generates honest response when live weather API is unreachable or fails."""
    loc_dict = state.get("location") or {}
    city_name = loc_dict.get("city", "the requested location")

    msg = (
        f"The live meteorological weather service is currently unavailable or returned an error for {city_name}. "
        "Because our safety guidelines strictly mandate verified live weather observations, "
        "I cannot provide a safety assessment without real meteorological facts. Please try again in a few moments."
    )

    messages = list(state.get("messages", []))
    messages.append({
        "role": "assistant",
        "content": msg,
        "intent": state.get("intent")
    })

    return {
        "response": msg,
        "status": "weather_error",
        "messages": messages
    }

async def evaluate_policies_node(state: WeatherBotState) -> Dict[str, Any]:
    """Deterministically evaluates SOP policies against verified weather data."""
    intent_dict = state.get("intent") or {}
    weather_dict = state.get("weather") or {}

    intent = UserIntent(**intent_dict)
    weather = WeatherFacts(**weather_dict)

    logger.info(f"Node [evaluate_policies] evaluating activity: '{intent.activity}' against weather facts")
    eval_result = sop_service.evaluate(intent, weather)

    matching_sops = []
    if eval_result.sop_id:
        matching_sops.append(eval_result.sop_id)
    matching_sops.extend(eval_result.conflicting_sops)

    selected_sop = None
    if eval_result.sop_id:
        selected_sop = {
            "id": eval_result.sop_id,
            "name": eval_result.sop_name,
            "severity": eval_result.severity
        }

    status = "success" if eval_result.sop_id else "no_sop"

    return {
        "policy_decision": eval_result.model_dump(),
        "matching_sops": matching_sops,
        "selected_sop": selected_sop,
        "status": status
    }

async def no_sop_node(state: WeatherBotState) -> Dict[str, Any]:
    """Generates honest fallback response when no SOP policy covers the scenario."""
    loc_dict = state.get("location") or {}
    weather_dict = state.get("weather") or {}
    intent_dict = state.get("intent") or {}

    city = loc_dict.get("city", "your location")
    temp = weather_dict.get("temperature_c", "N/A")
    wind = weather_dict.get("wind_speed_kmh", "N/A")
    precip = weather_dict.get("precipitation_mm", "N/A")
    activity = intent_dict.get("activity", "this activity")

    msg = (
        f"Based on current live weather in {city} (Temperature: {temp}°C, Wind Speed: {wind} km/h, Precipitation: {precip} mm), "
        f"I don't have an established Standard Operating Procedure (SOP) covering '{activity}'. "
        "Under our safety principles, I am prohibited from inventing safety advice without an authorized policy. "
        "Please consult local park or municipal guidelines for unlisted activities."
    )

    messages = list(state.get("messages", []))
    messages.append({
        "role": "assistant",
        "content": msg,
        "intent": intent_dict
    })

    return {
        "response": msg,
        "status": "no_sop",
        "messages": messages
    }

async def compose_response_node(state: WeatherBotState) -> Dict[str, Any]:
    """Composes grounded, traceable safety advisory citing SOP and weather values."""
    intent = UserIntent(**(state.get("intent") or {}))
    location = LocationData(**(state.get("location") or {}))
    weather = WeatherFacts(**(state.get("weather") or {}))
    policy_result = PolicyEvaluationResult(**(state.get("policy_decision") or {}))

    logger.info(f"Node [compose_response] formatting policy {policy_result.sop_id}")
    response_text = await llm_service.compose_response(intent, location, weather, policy_result)

    messages = list(state.get("messages", []))
    messages.append({
        "role": "assistant",
        "content": response_text,
        "intent": intent.model_dump(),
        "sop_id": policy_result.sop_id
    })

    return {
        "response": response_text,
        "status": "success",
        "messages": messages
    }
