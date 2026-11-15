"""Profile-adaptive discrete rubric and deterministic scoring for Engine v10.1."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

WEIGHTS: Dict[str, float] = {
    "value": 30.0,
    "journey": 20.0,
    "functionality": 20.0,
    "creativity": 15.0,
    "ui_ux": 15.0,
}

FACTOR_OF: Dict[str, str] = {
    "value": "resonance",
    "creativity": "creativity",
    "journey": "user_journey",
    "functionality": "functionality",
    "ui_ux": "ui_ux",
}


def rubric_family_for_profile(profile_key: str) -> str:
    if profile_key == "library_or_sdk":
        return "library_or_sdk"
    if profile_key in ("developer_tool_or_mcp", "automation_script_or_pipeline"):
        return "cli_or_automation"
    if profile_key == "interactive_game_or_simulation":
        return "game_or_sim"
    return "gui_or_general"


# Shared core + profile-adaptive discrete questions
SHARED_VALUE_POINTS = {
    "tier": {
        "TIER_0_BROKEN_OR_SHELL": 0,
        "TIER_1_GENERIC_CLONE": 18,
        "TIER_2_ITERATIVE_NICHE": 42,
        "TIER_3_GENUINE_GAP_OR_HOOK": 60,
    },
    "is_default_prompt_clone": {False: 20, True: 0},
    "verified_twist_each": 5,
    "verified_twist_max": 20,
}

SHARED_FUNCTIONALITY_POINTS = {
    "core_flow": {
        "WORKS_END_TO_END": 40,
        "MOSTLY_WORKS": 28,
        "PARTLY_BUILT": 12,
        "SHELL_OR_PLACEHOLDER": 0,
    },
    "features_connected": {"CONNECTED": 25, "SOME_LOOSE_ENDS": 12, "DISCONNECTED": 0},
    "tells_user_about_problems": {"CLEARLY": 20, "SOMETIMES": 12, "NOT_SHOWN": 6, "NEVER": 0},
    "confirms_success": {"CLEARLY": 15, "SOMETIMES": 9, "NOT_SHOWN": 5, "NEVER": 0},
    "proven_problem_rate_penalty": 10,
    "proven_problem_penalty_max": 20,
}

FAMILY_POINTS: Dict[str, Dict[str, Dict[str, Any]]] = {
    "library_or_sdk": {
        "value": SHARED_VALUE_POINTS,
        "functionality": SHARED_FUNCTIONALITY_POINTS,
        "creativity": {
            "has_distinct_voice_or_craft": {True: 25, False: 0},
            "clever_workflow_or_abstraction": {True: 25, False: 0},
            "concept_depth": {
                "STERILE_DEFAULT": 0,
                "LIGHTLY_CRAFTED": 10,
                "COHESIVE": 20,
                "DISTINCTIVE": 30,
            },
            "mechanical_synergy": {True: 20, False: 0},
        },
        "ui_ux": {
            "public_api_clarity": {"CLEAR": 30, "MIXED": 15, "OPAQUE": 0},
            "docs_and_examples": {"CLEAR": 25, "BASIC": 14, "MISSING_OR_STALE": 0},
            "error_and_diagnostic_quality": {"CLEAR": 25, "SOME": 13, "OPAQUE": 0},
            "packaging_and_composability": {"WELL": 20, "ADEQUATELY": 12, "POORLY": 0},
        },
        "journey": {
            "launch_experience": {
                "RUNS_IMMEDIATELY": 35,
                "ONE_STEP_INSTALL": 30,
                "MANUAL_SETUP": 14,
                "BRING_YOUR_OWN_KEY": 5,
            },
            "integration_friction": {"ONE_IMPORT_OR_CALL": 25, "A_FEW_STEPS": 14, "COMPLEX_SETUP": 0},
            "setup_burden": {"NONE": 20, "LIGHT": 20, "MODERATE": 10, "HEAVY": 0},
            "state_and_config": {"AUTO_OR_STATELESS": 20, "EXPLICIT_CONFIG": 14, "FRAGILE_OR_MANUAL": 0},
            "hostile_monetization": {False: 0, True: -50},
            "hostile_penalty": -50,
        },
    },
    "cli_or_automation": {
        "value": SHARED_VALUE_POINTS,
        "functionality": SHARED_FUNCTIONALITY_POINTS,
        "creativity": {
            "has_distinct_voice_or_craft": {True: 25, False: 0},
            "clever_workflow_or_abstraction": {True: 25, False: 0},
            "concept_depth": {
                "STERILE_DEFAULT": 0,
                "LIGHTLY_CRAFTED": 10,
                "COHESIVE": 20,
                "DISTINCTIVE": 30,
            },
            "mechanical_synergy": {True: 20, False: 0},
        },
        "ui_ux": {
            "help_and_flag_clarity": {"CLEAR": 25, "MIXED": 13, "CLUTTERED_OR_UNDOCUMENTED": 0},
            "output_and_error_quality": {"CLEAR": 25, "SOME": 13, "OPAQUE": 0},
            "composability_and_exit_codes": {"WELL": 25, "ADEQUATELY": 14, "POORLY": 0},
            "defaults_and_safety": {"GOOD": 25, "BASIC": 14, "RISKY_OR_MISSING": 0},
        },
        "journey": {
            "launch_experience": {
                "RUNS_IMMEDIATELY": 35,
                "ONE_STEP_INSTALL": 28,
                "MANUAL_SETUP": 14,
                "BRING_YOUR_OWN_KEY": 5,
            },
            "invocation_friction": {"ONE_COMMAND": 25, "A_FEW_STEPS": 14, "BURIED": 0},
            "setup_burden": {"NONE": 20, "LIGHT": 20, "MODERATE": 10, "HEAVY": 0},
            "state_and_config": {"AUTO_OR_STATELESS": 20, "EXPLICIT_CONFIG": 14, "FRAGILE_OR_MANUAL": 0},
            "hostile_monetization": {False: 0, True: -50},
            "hostile_penalty": -50,
        },
    },
    "game_or_sim": {
        "value": SHARED_VALUE_POINTS,
        "functionality": SHARED_FUNCTIONALITY_POINTS,
        "creativity": {
            "has_distinct_voice": {True: 25, False: 0},
            "subverts_standard_ui": {True: 25, False: 0},
            "depth_of_world_or_concept": {
                "STERILE_DEFAULT": 0,
                "LIGHTLY_THEMED": 10,
                "THEMED": 20,
                "RICHLY_THEMED": 30,
            },
            "mechanical_synergy": {True: 20, False: 0},
        },
        "ui_ux": {
            "hud_and_controls_clarity": {"CLEAR": 30, "MIXED": 15, "CLUTTERED": 0},
            "visual_audio_cohesion": {"CONSISTENT": 25, "MOSTLY_CONSISTENT": 15, "PATCHWORK": 0},
            "input_and_state_feedback": {"CLEAR": 25, "SOME": 13, "NONE": 0},
            "fits_its_device": {"WELL": 20, "ADEQUATELY": 12, "POORLY": 0},
        },
        "journey": {
            "launch_experience": {
                "RUNS_IMMEDIATELY": 35,
                "ONE_STEP_INSTALL": 26,
                "MANUAL_SETUP": 12,
                "BRING_YOUR_OWN_KEY": 0,
            },
            "navigation_friction": {"STRAIGHT_TO_CORE": 25, "A_FEW_STEPS": 13, "BURIED": 0},
            "setup_burden": {"NONE": 20, "LIGHT": 20, "MODERATE": 10, "HEAVY": 0},
            "state_and_save": {"AUTO_SAVE": 20, "NOT_NEEDED": 20, "MANUAL_SAVE": 14, "NO_SAVE": 0},
            "hostile_monetization": {False: 0, True: -50},
            "hostile_penalty": -50,
        },
    },
    "gui_or_general": {
        "value": SHARED_VALUE_POINTS,
        "functionality": SHARED_FUNCTIONALITY_POINTS,
        "creativity": {
            "has_distinct_voice": {True: 25, False: 0},
            "subverts_standard_ui": {True: 25, False: 0},
            "depth_of_world_or_concept": {
                "STERILE_DEFAULT": 0,
                "LIGHTLY_THEMED": 10,
                "THEMED": 20,
                "RICHLY_THEMED": 30,
            },
            "mechanical_synergy": {True: 20, False: 0},
        },
        "ui_ux": {
            "clarity": {"CLEAR": 25, "MIXED": 12, "CLUTTERED_OR_TECHNICAL": 0},
            "consistency": {"CONSISTENT": 20, "MOSTLY_CONSISTENT": 12, "PATCHWORK": 0},
            "feedback_while_working": {"CLEAR": 20, "SOME": 12, "NOT_SHOWN": 10, "NONE": 0},
            "fits_its_device": {"WELL": 25, "ADEQUATELY": 15, "POORLY": 0, "NOT_SHOWN": 12},
            "accessibility_labels": {"PRESENT": 10, "FEW": 5, "NOT_SHOWN": 5, "NONE": 0},
        },
        "journey": {
            "launch_experience": {
                "RUNS_IMMEDIATELY": 35,
                "ONE_STEP_INSTALL": 26,
                "MANUAL_SETUP": 12,
                "BRING_YOUR_OWN_KEY": 0,
            },
            "navigation_friction": {"STRAIGHT_TO_CORE": 25, "A_FEW_STEPS": 13, "BURIED": 0},
            "setup_burden": {"NONE": 20, "LIGHT": 20, "MODERATE": 10, "HEAVY": 0},
            "state_and_save": {"AUTO_SAVE": 20, "NOT_NEEDED": 18, "MANUAL_SAVE": 14, "NO_SAVE": 0},
            "hostile_monetization": {False: 0, True: -50},
            "hostile_penalty": -50,
        },
    },
}


def _coerce_bool(val: Any) -> Any:
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        low = val.strip().lower()
        if low in ("true", "yes", "1"):
            return True
        if low in ("false", "no", "0"):
            return False
    return val


def score_category(
    cat: str,
    family: str,
    answers: Dict[str, Any],
    hostile_found: List[str],
    proven_problems_count: int = 0,
    lines_of_code: int = 0,
    profile_data: Optional[Dict[str, Any]] = None,
) -> float:
    """Deterministically convert discrete checklist answers into a 0-100 factor score."""
    table_map = FAMILY_POINTS.get(family, FAMILY_POINTS["gui_or_general"])[cat]
    exemptions = (profile_data or {}).get("evaluation_lenses", {}).get(cat, {}).get("exemptions", [])
    pts = 0.0
    maxp = 0.0

    for field, choices in table_map.items():
        if not isinstance(choices, dict):
            continue
        field_max = max(choices.values())
        if field_max <= 0:
            # Penalty-only boolean like hostile_monetization
            val = _coerce_bool(answers.get(field))
            if val in choices:
                pts += choices[val]
            continue

        # Exempted checks (e.g. screen_reader_labels on hardware/mobile/general)
        if cat == "ui_ux" and field == "accessibility_labels" and "screen_reader_labels" in exemptions:
            continue

        maxp += field_max
        raw_val = answers.get(field)
        val = _coerce_bool(raw_val)
        if isinstance(val, str):
            val_norm = val.strip().upper()
            if val_norm in choices:
                pts += choices[val_norm]
                continue
        if val in choices:
            pts += choices[val]
        else:
            # Safe middle fallback if a field was omitted
            pts += round(field_max * 0.5)

    if cat == "value":
        maxp += table_map["verified_twist_max"]
        twists = answers.get("verified_twists")
        if isinstance(twists, list):
            twist_cnt = min(4, len([t for t in twists if str(t).strip()]))
        else:
            try:
                twist_cnt = max(0, min(4, int(answers.get("verified_twists_count") or 0)))
            except (TypeError, ValueError):
                twist_cnt = 0
        pts += min(table_map["verified_twist_max"], twist_cnt * table_map["verified_twist_each"])

    if cat == "functionality" and proven_problems_count > 0:
        kloc = max(1.0, lines_of_code / 1000.0)
        penalty = min(
            table_map["proven_problem_penalty_max"],
            round(proven_problems_count / kloc * table_map["proven_problem_rate_penalty"]),
        )
        pts -= penalty

    if cat == "journey" and hostile_found:
        pts += table_map["hostile_penalty"]

    if maxp <= 0:
        return 50.0
    return round(max(0.0, min(100.0, pts * 100.0 / maxp)), 1)


def compute_all_scores(
    family: str,
    checklist: Dict[str, Any],
    hostile_found: List[str],
    proven_problems_count: int = 0,
    lines_of_code: int = 0,
    profile_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for cat in WEIGHTS:
        cat_answers = checklist.get(cat) if isinstance(checklist.get(cat), dict) else {}
        out[cat] = score_category(
            cat=cat,
            family=family,
            answers=cat_answers,
            hostile_found=hostile_found,
            proven_problems_count=proven_problems_count,
            lines_of_code=lines_of_code,
            profile_data=profile_data,
        )
    return out


def overall(scores: Dict[str, float]) -> float:
    return round(sum(scores[c] * WEIGHTS[c] for c in WEIGHTS) / 100.0, 1)
