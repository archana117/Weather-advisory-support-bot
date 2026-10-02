from typing import TypedDict, List, Dict, Any, Optional

class WeatherBotState(TypedDict, total=False):
    messages: List[Dict[str, Any]]
    session_id: str
    user_question: str
    intent: Optional[Dict[str, Any]]
    location: Optional[Dict[str, Any]]
    weather: Optional[Dict[str, Any]]
    matching_sops: List[str]
    selected_sop: Optional[Dict[str, Any]]
    policy_decision: Optional[Dict[str, Any]]
    response: str
    error: Optional[str]
    status: str # "success", "no_sop", "location_error", "weather_error"
