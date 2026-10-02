from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field
from backend.models.sop_models import PolicyEvaluationResult

class UserIntent(BaseModel):
    activity: Optional[str] = Field(default=None, description="Normalized activity name, e.g. cycling, running, picnic, travel, dog_walking")
    location: Optional[str] = Field(default=None, description="Extracted city or region name, e.g. Bhopal, Mumbai, London")
    time_reference: str = Field(default="current", description="Time window, e.g. current, today, this_afternoon, this_evening, tomorrow")
    user_group: str = Field(default="all", description="Target user group, e.g. all, children, elderly, pets")
    intent: str = Field(default="outdoor_safety", description="General intent, e.g. outdoor_safety, weather_inquiry, general_conversation")

class LocationData(BaseModel):
    city: str
    country: Optional[str] = None
    admin1: Optional[str] = None
    latitude: float
    longitude: float
    timezone: Optional[str] = "UTC"

    @property
    def display_name(self) -> str:
        parts = [self.city]
        if self.admin1 and self.admin1 != self.city:
            parts.append(self.admin1)
        if self.country:
            parts.append(self.country)
        return ", ".join(parts)

class WeatherFacts(BaseModel):
    temperature_c: float
    wind_speed_kmh: float
    precipitation_mm: float
    precipitation_probability: float
    uv_index: float
    timestamp: str
    time_context: str = "current"
    raw_data: Optional[Dict[str, Any]] = None

    def to_summary_dict(self) -> Dict[str, Any]:
        return {
            "temperature_c": round(self.temperature_c, 1),
            "wind_speed_kmh": round(self.wind_speed_kmh, 1),
            "precipitation_mm": round(self.precipitation_mm, 2),
            "precipitation_probability": round(self.precipitation_probability, 1),
            "uv_index": round(self.uv_index, 1),
            "time_context": self.time_context,
            "timestamp": self.timestamp
        }

class ChatRequest(BaseModel):
    message: str
    session_id: str = "default"

class ChatResponse(BaseModel):
    response: str
    session_id: str
    status: str # "success", "no_sop", "location_error", "weather_error"
    location: Optional[LocationData] = None
    weather: Optional[WeatherFacts] = None
    policy_result: Optional[PolicyEvaluationResult] = None
    error: Optional[str] = None
