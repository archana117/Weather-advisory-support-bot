import asyncio
import sys
import yaml
from pathlib import Path
from typing import Dict, Any, List

# Ensure project root is in sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from backend.graph.workflow import run_weather_bot
from backend.models.schemas import WeatherFacts
from backend.services.weather_service import weather_service
from backend.utils.logging_config import logger

# Ensure UTF-8 stdout on Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

async def run_evaluation_suite() -> bool:
    test_cases_file = ROOT_DIR / "evals" / "test_cases.yaml"
    if not test_cases_file.exists():
        print(f"Test cases file not found: {test_cases_file}")
        return False

    with open(test_cases_file, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    cases = data.get("cases", [])
    print("\n" + "="*80)
    print(" [EVAL] RUNNING WEATHER-ADVISORY SUPPORT BOT EVALUATION SUITE")
    print(f" Loaded {len(cases)} comprehensive test cases from evals/test_cases.yaml")
    print("="*80 + "\n")

    results = []
    all_passed = True

    for case in cases:
        case_id = case["id"]
        name = case["name"]
        category = case["category"]
        user_input = case.get("input", "")
        mock_w = case.get("mock_weather")
        sim_fail = case.get("simulate_weather_failure", False)
        multi_turn = case.get("multi_turn")

        # Setup mocks
        if sim_fail:
            weather_service.set_mock_failure(True)
        elif mock_w:
            weather_service.set_mock_weather(WeatherFacts(**mock_w))
        else:
            weather_service.set_mock_failure(False)
            weather_service.set_mock_weather(None)

        passed = True
        notes = []

        try:
            if multi_turn:
                # Handle multi-turn session test
                session_id = f"eval_{case_id}"
                turn1 = multi_turn[0]["input"]
                turn2 = multi_turn[1]["input"]

                res1 = await run_weather_bot(turn1, session_id=session_id)
                res2 = await run_weather_bot(turn2, session_id=session_id)

                loc2 = res2.get("location", {}) or {}
                intent2 = res2.get("intent", {}) or {}

                if loc2.get("city", "").lower() != "bhopal":
                    passed = False
                    notes.append(f"Turn 2 location '{loc2.get('city')}' != 'Bhopal'")
                if intent2.get("activity") != "cycling":
                    passed = False
                    notes.append(f"Turn 2 activity '{intent2.get('activity')}' != 'cycling'")
                if intent2.get("time_reference") != "this_evening":
                    passed = False
                    notes.append(f"Turn 2 time_reference '{intent2.get('time_reference')}' != 'this_evening'")

                if passed:
                    notes.append("Context retained (Location: Bhopal, Activity: cycling, Time: this_evening)")

            else:
                session_id = f"eval_{case_id}"
                state = await run_weather_bot(user_input, session_id=session_id)
                status = state.get("status")
                policy_dec = state.get("policy_decision") or {}
                selected_sop = state.get("selected_sop") or {}
                response = state.get("response", "")

                # Specific case checks
                if case_id == "EVAL-001":
                    if selected_sop.get("id") != "SOP-001":
                        passed = False
                        notes.append(f"Selected SOP '{selected_sop.get('id')}' != 'SOP-001'")
                    if selected_sop.get("severity") != "high":
                        passed = False
                        notes.append(f"Severity '{selected_sop.get('severity')}' != 'high'")
                    if "46.2" not in response:
                        passed = False
                        notes.append("Response failed to cite exact wind speed 46.2 km/h")

                elif case_id == "EVAL-002":
                    if selected_sop.get("id") != "SOP-008":
                        passed = False
                        notes.append(f"Selected SOP '{selected_sop.get('id')}' != 'SOP-008'")
                    if selected_sop.get("severity") != "high":
                        passed = False
                        notes.append(f"Severity '{selected_sop.get('severity')}' != 'high'")

                elif case_id == "EVAL-003":
                    intent = state.get("intent") or {}
                    if intent.get("activity") != "cycling":
                        passed = False
                        notes.append(f"Paraphrased activity '{intent.get('activity')}' != 'cycling'")
                    if selected_sop.get("id") != "SOP-001":
                        passed = False
                        notes.append(f"Selected SOP '{selected_sop.get('id')}' != 'SOP-001'")

                elif case_id == "EVAL-004":
                    intent = state.get("intent") or {}
                    if intent.get("activity") != "travel":
                        passed = False
                        notes.append(f"Activity '{intent.get('activity')}' != 'travel'")
                    if selected_sop.get("id") != "SOP-005":
                        passed = False
                        notes.append(f"Selected SOP '{selected_sop.get('id')}' != 'SOP-005'")

                elif case_id == "EVAL-005":
                    # Live weather check
                    if status not in ["success", "advisory_issued"]:
                        passed = False
                        notes.append(f"Live query status '{status}' not success")
                    loc = state.get("location") or {}
                    if "bhopal" not in loc.get("city", "").lower():
                        passed = False
                        notes.append("Live geocoding did not resolve Bhopal")
                    weather = state.get("weather") or {}
                    if not weather or weather.get("temperature_c") is None:
                        passed = False
                        notes.append("Live weather data was empty")
                    else:
                        notes.append(f"Live Weather: {weather.get('temperature_c')}°C, {weather.get('wind_speed_kmh')} km/h, {weather.get('precipitation_mm')}mm rain")

                elif case_id == "EVAL-006":
                    if selected_sop.get("id") != "SOP-003":
                        passed = False
                        notes.append(f"Selected SOP '{selected_sop.get('id')}' != 'SOP-003'")
                    if selected_sop.get("severity") != "critical":
                        passed = False
                        notes.append(f"Severity '{selected_sop.get('severity')}' != 'critical'")

                elif case_id == "EVAL-007":
                    if status != "no_sop":
                        passed = False
                        notes.append(f"Expected status 'no_sop', got '{status}'")
                    if selected_sop.get("id") is not None:
                        passed = False
                        notes.append(f"Invented SOP '{selected_sop.get('id')}' for non-covered query")

                elif case_id == "EVAL-008":
                    if status != "location_error":
                        passed = False
                        notes.append(f"Expected status 'location_error', got '{status}'")
                    if state.get("weather") is not None:
                        passed = False
                        notes.append("Fabricated weather data despite location error")

                elif case_id == "EVAL-009":
                    if status != "weather_error":
                        passed = False
                        notes.append(f"Expected status 'weather_error', got '{status}'")
                    if "unavailable" not in response.lower() and "error" not in response.lower():
                        passed = False
                        notes.append("Response lacked honest outage notification")

                elif case_id == "EVAL-010":
                    # SOP-001 (priority 85) vs SOP-002 (priority 80)
                    if selected_sop.get("id") != "SOP-001":
                        passed = False
                        notes.append(f"Conflict resolution failed: selected '{selected_sop.get('id')}' instead of 'SOP-001'")
                    matching = state.get("matching_sops") or []
                    if "SOP-002" not in matching:
                        passed = False
                        notes.append(f"Secondary matching SOP-002 missing from audit trail: {matching}")

                elif case_id == "EVAL-011":
                    # Adversarial injection
                    if selected_sop.get("id") != "SOP-001":
                        passed = False
                        notes.append(f"Adversarial test bypassed SOP-001; got '{selected_sop.get('id')}'")
                    if selected_sop.get("severity") != "high":
                        passed = False
                        notes.append(f"Adversarial attack altered severity to '{selected_sop.get('severity')}'")

                elif case_id == "EVAL-013":
                    # Fuzzy picnic rule
                    if selected_sop.get("id") != "SOP-011":
                        passed = False
                        notes.append(f"Fuzzy rule failed: expected SOP-011, got '{selected_sop.get('id')}'")
                    if selected_sop.get("severity") != "moderate":
                        passed = False
                        notes.append(f"Fuzzy rule severity '{selected_sop.get('severity')}' != 'moderate'")

        except Exception as exc:
            passed = False
            notes.append(f"Exception during test execution: {str(exc)}")

        finally:
            # Clean up mocks
            weather_service.set_mock_failure(False)
            weather_service.set_mock_weather(None)

        if not passed:
            all_passed = False

        status_icon = "PASS" if passed else "FAIL"
        detail_msg = "; ".join(notes) if notes else "All validation checks satisfied."
        print(f"[{status_icon}] {case_id}: {name} ({category})")
        if notes:
            print(f"       Details: {detail_msg}")
        results.append((case_id, name, status_icon, detail_msg))

    print("\n" + "="*80)
    print(" [REPORT] EVALUATION SUITE SUMMARY REPORT")
    print("="*80)
    passed_count = sum(1 for _, _, icon, _ in results if "PASS" in icon)
    print(f" Total Cases Evaluated : {len(results)}")
    print(f" Passed                : {passed_count}")
    print(f" Failed                : {len(results) - passed_count}")
    print("="*80)
    
    return all_passed

if __name__ == "__main__":
    success = asyncio.run(run_evaluation_suite())
    sys.exit(0 if success else 1)
