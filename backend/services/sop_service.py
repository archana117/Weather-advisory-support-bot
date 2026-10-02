import yaml
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime

from backend.config import settings
from backend.models.schemas import UserIntent, WeatherFacts
from backend.models.sop_models import (
    SOP, 
    ConditionSpec, 
    FuzzyRuleSpec, 
    PolicyEvaluationResult, 
    SEVERITY_WEIGHTS
)
from backend.utils.logging_config import logger

# Activity synonym mapping to canonical activities
ACTIVITY_SYNONYMS: Dict[str, str] = {
    "bike": "cycling",
    "biking": "cycling",
    "bicycle": "cycling",
    "cycle": "cycling",
    "bike_ride": "cycling",
    "two_wheeler": "cycling",
    "scooter": "cycling",
    
    "run": "running",
    "jog": "running",
    "jogging": "running",
    "sprint": "running",
    "marathon": "running",
    "trail_running": "running",
    
    "walk": "walking",
    "stroll": "walking",
    
    "dog_walking": "dog_walking",
    "walking_dog": "dog_walking",
    "walk_dog": "dog_walking",
    "pet_walk": "dog_walking",
    
    "picnic": "picnic",
    "barbecue": "picnic",
    "bbq": "picnic",
    "outdoor_lunch": "picnic",
    "cookout": "picnic",
    
    "drive": "travel",
    "driving": "travel",
    "road_trip": "travel",
    "commute": "travel",
    "travel": "travel",
    "highway_travel": "travel",
    
    "playground": "park",
    "park": "park",
    "outdoor_play": "park",
    "playing": "park"
}

class SOPService:
    def __init__(self, sops_path: Optional[Path] = None):
        self.sops_path = sops_path or settings.SOP_FILE_PATH
        self._sops: List[SOP] = []
        self.load_sops()

    def load_sops(self) -> List[SOP]:
        """Loads and parses SOP rules from YAML file."""
        if not self.sops_path.exists():
            logger.error(f"SOP policy file not found at {self.sops_path}")
            self._sops = []
            return []

        try:
            with open(self.sops_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)

            raw_sops = data.get("sops", [])
            parsed_sops: List[SOP] = []

            for item in raw_sops:
                try:
                    sop = SOP(**item)
                    parsed_sops.append(sop)
                except Exception as exc:
                    logger.error(f"Failed to parse SOP item {item.get('id', 'unknown')}: {exc}")

            self._sops = parsed_sops
            logger.info(f"Successfully loaded {len(self._sops)} SOP policies from {self.sops_path}")
            return self._sops

        except Exception as exc:
            logger.error(f"Error reading SOP policy file {self.sops_path}: {exc}", exc_info=True)
            self._sops = []
            return []

    def get_all_sops(self) -> List[SOP]:
        return self._sops

    @staticmethod
    def normalize_activity(activity: Optional[str]) -> Optional[str]:
        if not activity:
            return None
        clean = activity.lower().strip().replace("-", "_").replace(" ", "_")
        return ACTIVITY_SYNONYMS.get(clean, clean)

    def _matches_activity(self, user_activity: Optional[str], sop_activities: List[str]) -> bool:
        if not user_activity:
            return False
        if "any" in sop_activities or "all" in sop_activities:
            return True
        norm_user_act = self.normalize_activity(user_activity)
        for sop_act in sop_activities:
            norm_sop_act = self.normalize_activity(sop_act)
            if norm_user_act == norm_sop_act:
                return True
        return False

    def _matches_user_group(self, user_group: str, sop_groups: List[str]) -> bool:
        if "all" in sop_groups or "any" in sop_groups:
            return True
        norm_group = user_group.lower().strip()
        return norm_group in [g.lower().strip() for g in sop_groups]

    def _matches_time_window(self, time_window: Optional[Dict[str, str]], weather: WeatherFacts) -> bool:
        if not time_window:
            return True
        
        start_str = time_window.get("start")
        end_str = time_window.get("end")
        if not start_str or not end_str:
            return True

        # If time_context indicates afternoon or midday
        if weather.time_context in ["this_afternoon", "afternoon", "midday"]:
            return True
        if weather.time_context in ["this_evening", "evening", "tonight", "night"]:
            # Evening usually falls outside 11:00-16:00
            start_h = int(start_str.split(":")[0])
            end_h = int(end_str.split(":")[0])
            if start_h >= 17 or end_h >= 20:
                return True
            return False

        # Check timestamp hour
        try:
            dt = datetime.fromisoformat(weather.timestamp)
            hour = dt.hour
            start_hour = int(start_str.split(":")[0])
            end_hour = int(end_str.split(":")[0])
            return start_hour <= hour <= end_hour
        except Exception:
            return True

    def _evaluate_numeric_condition(self, cond: ConditionSpec, actual_value: float) -> bool:
        op = cond.operator.strip()
        val = cond.value

        if op == ">":
            return actual_value > val
        elif op == ">=":
            return actual_value >= val
        elif op == "<":
            return actual_value < val
        elif op == "<=":
            return actual_value <= val
        elif op == "==":
            return actual_value == val
        elif op == "!=":
            return actual_value != val
        elif op == "between":
            if cond.min_value is not None and cond.max_value is not None:
                return cond.min_value <= actual_value <= cond.max_value
            return False
        return False

    def _evaluate_fuzzy_rule(self, fuzzy: FuzzyRuleSpec, weather: WeatherFacts) -> Tuple[bool, List[str]]:
        """
        Evaluates non-linear multi-variable criteria.
        Returns (is_triggered, list_of_reasons).
        """
        if fuzzy.type == "picnic_suitability":
            crit = fuzzy.unsuitable_criteria or {}
            reasons = []

            p_prob_gte = crit.get("precipitation_probability_gte", 45.0)
            if weather.precipitation_probability >= p_prob_gte:
                reasons.append(f"Precipitation probability ({weather.precipitation_probability}%) >= {p_prob_gte}%")

            p_mm_gte = crit.get("precipitation_mm_gte", 1.0)
            if weather.precipitation_mm >= p_mm_gte:
                reasons.append(f"Precipitation ({weather.precipitation_mm}mm) >= {p_mm_gte}mm")

            wind_gte = crit.get("wind_speed_kmh_gte", 25.0)
            if weather.wind_speed_kmh >= wind_gte:
                reasons.append(f"Wind speed ({weather.wind_speed_kmh} km/h) >= {wind_gte} km/h")

            temp_max = crit.get("temperature_max_c", 35.0)
            if weather.temperature_c >= temp_max:
                reasons.append(f"Temperature ({weather.temperature_c}°C) exceeds comfort ceiling {temp_max}°C")

            temp_min = crit.get("temperature_min_c", 14.0)
            if weather.temperature_c <= temp_min:
                reasons.append(f"Temperature ({weather.temperature_c}°C) below comfortable threshold {temp_min}°C")

            uv_gte = crit.get("uv_index_gte", 9.0)
            if weather.uv_index >= uv_gte:
                reasons.append(f"UV Index ({weather.uv_index}) >= {uv_gte}")

            return (len(reasons) > 0, reasons)

        return (False, [])

    def evaluate(self, intent: UserIntent, weather: WeatherFacts) -> PolicyEvaluationResult:
        """
        Deterministically evaluates all SOPs against the user intent and actual weather facts.
        Resolves conflicts using severity, priority, and specificity.
        """
        # Reload SOPs to guarantee dynamic updates without code changes
        self.load_sops()

        matched_sops: List[Tuple[SOP, List[str]]] = []
        fact_dict = weather.to_summary_dict()

        for sop in self._sops:
            # 1. Activity match
            if not self._matches_activity(intent.activity, sop.applicable_activities):
                continue

            # 2. User group match
            if not self._matches_user_group(intent.user_group, sop.applicable_user_groups):
                continue

            # 3. Time window check
            if not self._matches_time_window(sop.time_window, weather):
                continue

            # 4. Conditions check
            sop_matched = True
            reasons = []

            # Check standard numeric conditions
            for field_name, cond in sop.conditions.items():
                if not hasattr(weather, field_name):
                    sop_matched = False
                    break
                actual_val = getattr(weather, field_name)
                if not self._evaluate_numeric_condition(cond, actual_val):
                    sop_matched = False
                    break
                else:
                    reasons.append(f"{field_name} {cond.operator} {cond.value if cond.value is not None else f'[{cond.min_value}, {cond.max_value}]'} (actual: {actual_val})")

            if not sop_matched:
                continue

            # Check fuzzy rule if present
            if sop.fuzzy_rule:
                fuzzy_matched, fuzzy_reasons = self._evaluate_fuzzy_rule(sop.fuzzy_rule, weather)
                if not fuzzy_matched:
                    continue
                reasons.extend(fuzzy_reasons)

            # If all conditions passed, record match
            matched_sops.append((sop, reasons))

        if not matched_sops:
            logger.info(f"No SOP matched for activity='{intent.activity}', facts={fact_dict}")
            return PolicyEvaluationResult(
                sop_id=None,
                sop_name=None,
                severity=None,
                decision="no_sop_matched",
                matched_conditions=[],
                weather_facts=fact_dict,
                guidance=[],
                rationale="No existing Standard Operating Procedure covers this combination of activity and weather conditions.",
                conflicting_sops=[],
                audit_trail={"evaluated_sops_count": len(self._sops), "matches_found": 0}
            )

        # 5. Intentional Conflict Resolution Strategy:
        # Step A: Sort by severity weight (critical: 4, high: 3, moderate: 2, low: 1) descending
        # Step B: Sort by priority score (1-100) descending
        # Step C: Prefer activity-specific policy over generic 'any' policy
        def conflict_sort_key(item: Tuple[SOP, List[str]]):
            s, _ = item
            sev_score = SEVERITY_WEIGHTS.get(s.severity, 1)
            prio_score = s.priority
            specificity = 0 if "any" in s.applicable_activities else 1
            return (sev_score, prio_score, specificity)

        matched_sops.sort(key=conflict_sort_key, reverse=True)

        primary_sop, primary_reasons = matched_sops[0]
        other_matching_ids = [s.id for s, _ in matched_sops[1:]]

        decision = "safe_to_proceed" if primary_sop.severity == "low" else "advisory_issued"

        logger.info(
            f"Policy selected: {primary_sop.id} ({primary_sop.name}) [Severity: {primary_sop.severity}, Priority: {primary_sop.priority}]. "
            f"Secondary matches: {other_matching_ids}"
        )

        return PolicyEvaluationResult(
            sop_id=primary_sop.id,
            sop_name=primary_sop.name,
            severity=primary_sop.severity,
            decision=decision,
            matched_conditions=primary_reasons,
            weather_facts=fact_dict,
            guidance=primary_sop.guidance,
            rationale=primary_sop.rationale,
            conflicting_sops=other_matching_ids,
            audit_trail={
                "evaluated_sops_count": len(self._sops),
                "matches_found": len(matched_sops),
                "all_matched_ids": [s.id for s, _ in matched_sops]
            }
        )

sop_service = SOPService()
