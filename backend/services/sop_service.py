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

    def _evaluate_fuzzy_rule(self, fuzzy: FuzzyRuleSpec, weather: WeatherFacts) -> Tuple[bool, List[str], Optional[str], Optional[str], Optional[List[str]], Optional[str]]:
        """
        Evaluates non-linear multi-variable criteria defined in the external SOP YAML.
        Returns (is_matched, reasons, suitability, level_severity, level_guidance, level_decision).
        Produces deterministic outcomes: 'Good', 'Mixed', or 'Poor'.
        """
        if fuzzy.type == "picnic_suitability":
            factors = fuzzy.factors or {}
            levels = fuzzy.levels or {}
            factor_scores = {}
            reasons = []

            # 1. Precipitation Probability Factor
            p_prob_cfg = factors.get("precipitation_probability", {})
            p_prob_val = weather.precipitation_probability
            if p_prob_val >= p_prob_cfg.get("poor_threshold", 60.0):
                factor_scores["precipitation_probability"] = "poor"
                reasons.append(f"Precipitation probability ({p_prob_val}%) >= poor threshold ({p_prob_cfg.get('poor_threshold', 60.0)}%)")
            elif p_prob_val >= p_prob_cfg.get("mixed_threshold", 30.0):
                factor_scores["precipitation_probability"] = "mixed"
                reasons.append(f"Precipitation probability ({p_prob_val}%) >= marginal threshold ({p_prob_cfg.get('mixed_threshold', 30.0)}%)")
            else:
                factor_scores["precipitation_probability"] = "good"

            # 2. Precipitation Volume Factor (mm)
            p_mm_cfg = factors.get("precipitation_mm", {})
            p_mm_val = weather.precipitation_mm
            if p_mm_val >= p_mm_cfg.get("poor_threshold", 2.0):
                factor_scores["precipitation_mm"] = "poor"
                reasons.append(f"Precipitation ({p_mm_val}mm) >= poor threshold ({p_mm_cfg.get('poor_threshold', 2.0)}mm)")
            elif p_mm_val >= p_mm_cfg.get("mixed_threshold", 0.5):
                factor_scores["precipitation_mm"] = "mixed"
                reasons.append(f"Precipitation ({p_mm_val}mm) >= marginal threshold ({p_mm_cfg.get('mixed_threshold', 0.5)}mm)")
            else:
                factor_scores["precipitation_mm"] = "good"

            # 3. Wind Speed Factor (km/h)
            wind_cfg = factors.get("wind_speed_kmh", {})
            wind_val = weather.wind_speed_kmh
            if wind_val >= wind_cfg.get("poor_threshold", 30.0):
                factor_scores["wind_speed_kmh"] = "poor"
                reasons.append(f"Wind speed ({wind_val} km/h) >= poor threshold ({wind_cfg.get('poor_threshold', 30.0)} km/h)")
            elif wind_val >= wind_cfg.get("mixed_threshold", 20.0):
                factor_scores["wind_speed_kmh"] = "mixed"
                reasons.append(f"Wind speed ({wind_val} km/h) >= marginal threshold ({wind_cfg.get('mixed_threshold', 20.0)} km/h)")
            else:
                factor_scores["wind_speed_kmh"] = "good"

            # 4. Temperature Comfort Factor (°C)
            temp_cfg = factors.get("temperature_c", {})
            temp_val = weather.temperature_c
            acc_min = temp_cfg.get("acceptable_min", 14.0)
            acc_max = temp_cfg.get("acceptable_max", 34.0)
            ideal_min = temp_cfg.get("ideal_min", 18.0)
            ideal_max = temp_cfg.get("ideal_max", 28.0)

            if temp_val < acc_min or temp_val > acc_max:
                factor_scores["temperature_c"] = "poor"
                reasons.append(f"Temperature ({temp_val}°C) outside acceptable bounds [{acc_min}°C, {acc_max}°C]")
            elif temp_val < ideal_min or temp_val > ideal_max:
                factor_scores["temperature_c"] = "mixed"
                reasons.append(f"Temperature ({temp_val}°C) outside ideal comfort [{ideal_min}°C, {ideal_max}°C]")
            else:
                factor_scores["temperature_c"] = "good"

            # 5. UV Index Factor
            uv_cfg = factors.get("uv_index", {})
            uv_val = weather.uv_index
            if uv_val >= uv_cfg.get("poor_threshold", 8.0):
                factor_scores["uv_index"] = "poor"
                reasons.append(f"UV Index ({uv_val}) >= poor threshold ({uv_cfg.get('poor_threshold', 8.0)})")
            elif uv_val >= uv_cfg.get("mixed_threshold", 6.0):
                factor_scores["uv_index"] = "mixed"
                reasons.append(f"UV Index ({uv_val}) >= marginal threshold ({uv_cfg.get('mixed_threshold', 6.0)})")
            else:
                factor_scores["uv_index"] = "good"

            # Composite Suitability Determination: Good / Mixed / Poor
            poor_count = sum(1 for s in factor_scores.values() if s == "poor")
            mixed_count = sum(1 for s in factor_scores.values() if s == "mixed")

            if poor_count > 0 or mixed_count >= 2:
                suitability = "Poor"
            elif mixed_count > 0:
                suitability = "Mixed"
            else:
                suitability = "Good"

            reasons.insert(0, f"Composite Multi-Factor Picnic Suitability: {suitability.upper()}")

            lvl_info = levels.get(suitability.lower(), {})
            level_sev = lvl_info.get("severity", "moderate")
            level_guidance = lvl_info.get("guidance", [])
            level_dec = lvl_info.get("decision", "advisory_issued")

            return (True, reasons, suitability, level_sev, level_guidance, level_dec)

        return (False, [], None, None, None, None)

    def evaluate(self, intent: UserIntent, weather: WeatherFacts) -> PolicyEvaluationResult:
        """
        Deterministically evaluates all SOPs against the user intent and actual weather facts.
        Resolves conflicts using severity, priority, and specificity.
        """
        # Reload SOPs to guarantee dynamic updates without code changes
        self.load_sops()

        matched_sops: List[Tuple[SOP, List[str], Optional[str], Optional[str], Optional[List[str]], Optional[str]]] = []
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
            suitability = None
            custom_sev = None
            custom_guidance = None
            custom_dec = None

            if sop.fuzzy_rule:
                f_matched, f_reasons, suitability, custom_sev, custom_guidance, custom_dec = self._evaluate_fuzzy_rule(sop.fuzzy_rule, weather)
                if not f_matched:
                    continue
                reasons.extend(f_reasons)

            # If all conditions passed, record match
            matched_sops.append((sop, reasons, suitability, custom_sev, custom_guidance, custom_dec))

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
        def conflict_sort_key(item):
            s, _, _, custom_sev, _, _ = item
            effective_sev = custom_sev or s.severity
            sev_score = SEVERITY_WEIGHTS.get(effective_sev, 1)
            prio_score = s.priority
            specificity = 0 if "any" in s.applicable_activities else 1
            return (sev_score, prio_score, specificity)

        matched_sops.sort(key=conflict_sort_key, reverse=True)

        primary_sop, primary_reasons, primary_suitability, primary_custom_sev, primary_custom_guidance, primary_custom_dec = matched_sops[0]
        other_matching_ids = [s.id for s, _, _, _, _, _ in matched_sops[1:]]

        final_severity = primary_custom_sev or primary_sop.severity
        final_guidance = primary_custom_guidance or primary_sop.guidance
        final_decision = primary_custom_dec or ("safe_to_proceed" if final_severity == "low" else "advisory_issued")

        logger.info(
            f"Policy selected: {primary_sop.id} ({primary_sop.name}) [Severity: {final_severity}, Priority: {primary_sop.priority}, Suitability: {primary_suitability}]. "
            f"Secondary matches: {other_matching_ids}"
        )

        return PolicyEvaluationResult(
            sop_id=primary_sop.id,
            sop_name=primary_sop.name,
            severity=final_severity,
            decision=final_decision,
            suitability=primary_suitability,
            matched_conditions=primary_reasons,
            weather_facts=fact_dict,
            guidance=final_guidance,
            rationale=primary_sop.rationale,
            conflicting_sops=other_matching_ids,
            audit_trail={
                "evaluated_sops_count": len(self._sops),
                "matches_found": len(matched_sops),
                "all_matched_ids": [s.id for s, _, _, _, _, _ in matched_sops],
                "fuzzy_suitability": primary_suitability
            }
        )

sop_service = SOPService()
