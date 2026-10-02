from typing import List, Dict, Optional, Any, Literal
from pydantic import BaseModel, Field

SeverityLevel = Literal["low", "moderate", "high", "critical"]

SEVERITY_WEIGHTS: Dict[str, int] = {
    "critical": 4,
    "high": 3,
    "moderate": 2,
    "low": 1
}

class ConditionSpec(BaseModel):
    operator: str
    value: Optional[float] = None
    min_value: Optional[float] = None
    max_value: Optional[float] = None

class FuzzyRuleSpec(BaseModel):
    type: str
    factors: Optional[Dict[str, Any]] = None
    levels: Optional[Dict[str, Any]] = None
    unsuitable_criteria: Optional[Dict[str, float]] = None

class SOP(BaseModel):
    id: str
    name: str
    category: str
    severity: SeverityLevel
    priority: int = 50
    applicable_activities: List[str] = Field(default_factory=lambda: ["any"])
    applicable_user_groups: List[str] = Field(default_factory=lambda: ["all"])
    conditions: Dict[str, ConditionSpec] = Field(default_factory=dict)
    time_window: Optional[Dict[str, str]] = None
    fuzzy_rule: Optional[FuzzyRuleSpec] = None
    guidance: List[str]
    rationale: str

class PolicyEvaluationResult(BaseModel):
    sop_id: Optional[str] = None
    sop_name: Optional[str] = None
    severity: Optional[SeverityLevel] = None
    decision: str = "no_sop_matched" # "advisory_issued", "safe_to_proceed", "no_sop_matched"
    suitability: Optional[str] = None # e.g. "Good", "Mixed", "Poor"
    matched_conditions: List[str] = Field(default_factory=list)
    weather_facts: Dict[str, Any] = Field(default_factory=dict)
    guidance: List[str] = Field(default_factory=list)
    rationale: Optional[str] = None
    conflicting_sops: List[str] = Field(default_factory=list)
    audit_trail: Dict[str, Any] = Field(default_factory=dict)
