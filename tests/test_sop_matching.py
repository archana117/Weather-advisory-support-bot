import pytest
from pathlib import Path
from backend.models.schemas import UserIntent, WeatherFacts
from backend.services.sop_service import SOPService, sop_service
from backend.models.sop_models import SOP, ConditionSpec

def test_sop_loading():
    sops = sop_service.load_sops()
    assert len(sops) >= 10, f"Expected at least 10 SOPs, found {len(sops)}"
    categories = {s.category for s in sops}
    assert len(categories) >= 3, f"Expected at least 3 categories, found {categories}"

def test_numeric_condition_evaluation():
    # Test greater than or equal
    cond_gte = ConditionSpec(operator=">=", value=40.0)
    assert sop_service._evaluate_numeric_condition(cond_gte, 40.0) is True
    assert sop_service._evaluate_numeric_condition(cond_gte, 45.0) is True
    assert sop_service._evaluate_numeric_condition(cond_gte, 39.9) is False

    # Test less than or equal
    cond_lte = ConditionSpec(operator="<=", value=5.0)
    assert sop_service._evaluate_numeric_condition(cond_lte, 2.0) is True
    assert sop_service._evaluate_numeric_condition(cond_lte, 5.0) is True
    assert sop_service._evaluate_numeric_condition(cond_lte, 5.1) is False

    # Test between
    cond_btwn = ConditionSpec(operator="between", min_value=18.0, max_value=28.0)
    assert sop_service._evaluate_numeric_condition(cond_btwn, 22.0) is True
    assert sop_service._evaluate_numeric_condition(cond_btwn, 18.0) is True
    assert sop_service._evaluate_numeric_condition(cond_btwn, 28.0) is True
    assert sop_service._evaluate_numeric_condition(cond_btwn, 17.9) is False
    assert sop_service._evaluate_numeric_condition(cond_btwn, 28.1) is False

def test_activity_synonym_normalization():
    assert sop_service.normalize_activity("bike") == "cycling"
    assert sop_service.normalize_activity("biking") == "cycling"
    assert sop_service.normalize_activity("two_wheeler") == "cycling"
    assert sop_service.normalize_activity("jogging") == "running"
    assert sop_service.normalize_activity("drive") == "travel"
    assert sop_service.normalize_activity("walking_dog") == "dog_walking"

def test_conflict_resolution_severity_and_priority():
    # Given high wind (45 km/h) and high UV (8.5), for cycling
    # SOP-001 (wind >= 40, priority 85) vs SOP-002 (uv >= 8, priority 80)
    intent = UserIntent(activity="cycling", user_group="all", time_reference="this_afternoon")
    weather = WeatherFacts(
        temperature_c=32.0,
        wind_speed_kmh=45.0,
        precipitation_mm=0.0,
        precipitation_probability=0.0,
        uv_index=8.5,
        timestamp="2026-10-01T13:00",
        time_context="this_afternoon"
    )
    result = sop_service.evaluate(intent, weather)
    assert result.sop_id == "SOP-001"
    assert "SOP-002" in result.conflicting_sops

def test_fuzzy_picnic_suitability():
    intent = UserIntent(activity="picnic", user_group="all", time_reference="today")
    # Windy picnic condition
    weather = WeatherFacts(
        temperature_c=25.0,
        wind_speed_kmh=27.0, # >= 25 triggers picnic advisory
        precipitation_mm=0.0,
        precipitation_probability=10.0,
        uv_index=3.0,
        timestamp="2026-10-01T12:00",
        time_context="today"
    )
    result = sop_service.evaluate(intent, weather)
    assert result.sop_id == "SOP-011"
    assert result.severity == "moderate"

def test_dynamic_sop_addition(tmp_path):
    """
    Validates that a new SOP (e.g. SOP-999) can be added to the YAML
    and evaluated immediately without touching Python control-flow code.
    """
    yaml_content = """
sops:
  - id: "SOP-999"
    name: "Severe Sandstorm & Dust Inhalation Warning"
    category: "general_outdoor"
    severity: "critical"
    priority: 99
    applicable_activities: ["any"]
    applicable_user_groups: ["all"]
    conditions:
      wind_speed_kmh:
        operator: ">="
        value: 65.0
    guidance:
      - "Seek sealed shelter immediately."
    rationale: "Severe airborne particulate hazards."
"""
    test_yaml = tmp_path / "custom_sops.yaml"
    test_yaml.write_text(yaml_content, encoding="utf-8")

    custom_service = SOPService(sops_path=test_yaml)
    assert len(custom_service.get_all_sops()) == 1

    intent = UserIntent(activity="running", user_group="all")
    weather = WeatherFacts(
        temperature_c=30.0,
        wind_speed_kmh=70.0,
        precipitation_mm=0.0,
        precipitation_probability=0.0,
        uv_index=2.0,
        timestamp="2026-10-01T12:00"
    )
    result = custom_service.evaluate(intent, weather)
    assert result.sop_id == "SOP-999"
    assert result.severity == "critical"
    assert "Seek sealed shelter immediately." in result.guidance
