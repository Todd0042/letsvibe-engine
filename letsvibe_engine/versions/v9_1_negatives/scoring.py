"""
Stage 4: deterministic score. Every rubric answer maps to fixed points (POINTS, published with the method); each category
is scored 0-100 out of the points available. Hostile patterns found by the Python scan always count.
The overall score weights the categories (WEIGHTS, Todd's priority order). Factors not graded yet are left out and
the remaining weights are scaled to add up to 100. Code health is never part of the overall score.
"""
from typing import Any, Dict, List

POINTS: Dict[str, Dict[str, Any]] = {
    "value": {
        "tier": {"TIER_0_BROKEN_OR_SHELL": 0, "TIER_1_GENERIC_CLONE": 15, "TIER_2_ITERATIVE_NICHE": 40, "TIER_3_GENUINE_GAP_OR_HOOK": 60},
        "is_default_prompt_clone": {False: 20, True: 0},
        "verified_twist_each": 5, "verified_twist_max": 20,
    },
    "creativity": {
        "has_distinct_voice": {True: 25, False: 0},
        "subverts_standard_ui": {True: 25, False: 0},
        "depth_of_world_or_concept": {"STERILE_DEFAULT": 0, "LIGHTLY_THEMED": 10, "THEMED": 20, "RICHLY_THEMED": 30},
        "mechanical_synergy": {True: 20, False: 0},
    },
    # "Not shown in the dossier" earns the middle: absence the scan cannot prove is never a penalty. The "not shown to the
    # user" / "none" answers (rubric v9) come only from the code review: quoted code that shows the gap, or every relevant
    # chunk read without finding it (see code_evidence.py).
    "functionality": {
        "core_flow": {"WORKS_END_TO_END": 40, "MOSTLY_WORKS": 28, "PARTLY_BUILT": 12, "SHELL_OR_PLACEHOLDER": 0},
        "features_connected": {"CONNECTED": 25, "SOME_LOOSE_ENDS": 12, "DISCONNECTED": 0},
        "tells_user_about_problems": {"CLEARLY": 20, "SOMETIMES": 12, "NOT_SHOWN_IN_DOSSIER": 10, "NOT_SHOWN_TO_USER": 0},
        "confirms_success": {"CLEARLY": 15, "SOMETIMES": 9, "NOT_SHOWN_IN_DOSSIER": 7, "NOT_SHOWN_TO_USER": 0},
        "proven_problem_rate_penalty": 10, "proven_problem_penalty_max": 20,
    },
    "ui_ux": {
        "clarity": {"CLEAR": 25, "MIXED": 12, "CLUTTERED_OR_TECHNICAL": 0},
        "consistency": {"CONSISTENT": 20, "MOSTLY_CONSISTENT": 12, "PATCHWORK": 0},
        "feedback_while_working": {"CLEAR": 20, "SOME": 12, "NOT_SHOWN_IN_DOSSIER": 10, "NONE": 0},
        "fits_its_device": {"WELL": 25, "ADEQUATELY": 15, "POORLY": 0, "NOT_SHOWN_IN_DOSSIER": 12},
        "accessibility_labels": {"PRESENT": 10, "FEW": 5, "NOT_SHOWN_IN_DOSSIER": 5, "NONE": 0},
    },
    "journey": {
        "launch_experience": {"RUNS_IMMEDIATELY": 40, "ONE_STEP_INSTALL": 30, "MANUAL_SETUP": 15, "BRING_YOUR_OWN_KEY": 0},
        "navigation_friction": {"STRAIGHT_TO_CORE": 30, "A_FEW_STEPS": 15, "BURIED": 0},
        "setup_burden": {"NONE": 25, "LIGHT": 25, "MODERATE": 12, "HEAVY": 0},
        "state_and_save": {"AUTO_SAVE": 30, "MANUAL_SAVE": 20, "NOT_NEEDED": 25, "NO_SAVE": 0},
        "hostile_penalty": -50,
    },
}
# Todd's order (2026-11-12): value, creativity, journey, functionality, UI/UX. Functionality and UI/UX are not graded
# yet; until they are, overall() scales the graded factors' weights to 100.
ALL_WEIGHTS = {"value": 25.0, "creativity": 22.0, "journey": 20.0, "functionality": 18.0, "ui_ux": 15.0}
GRADED = ("value", "creativity", "journey", "functionality", "ui_ux")
WEIGHTS = {c: round(ALL_WEIGHTS[c] * 100.0 / sum(ALL_WEIGHTS[g] for g in GRADED), 1) for c in GRADED}
FACTOR_OF = {"value": "resonance", "creativity": "creativity", "journey": "user_journey", "functionality": "functionality", "ui_ux": "ui_ux"}

# Answers that are genuine problems (they, and only they, become "needs work")
PROBLEM_ANSWERS = {
    "is_default_prompt_clone": {True}, "tier": {"TIER_0_BROKEN_OR_SHELL", "TIER_1_GENERIC_CLONE"},
    "has_distinct_voice": {False}, "depth_of_world_or_concept": {"STERILE_DEFAULT"}, "mechanical_synergy": {False},
    "launch_experience": {"MANUAL_SETUP", "BRING_YOUR_OWN_KEY"}, "navigation_friction": {"BURIED"}, "setup_burden": {"HEAVY"},
    "state_and_save": {"NO_SAVE"}, "hostile_monetization": {True},
    "core_flow": {"PARTLY_BUILT", "SHELL_OR_PLACEHOLDER"}, "features_connected": {"DISCONNECTED"},
    "clarity": {"CLUTTERED_OR_TECHNICAL"}, "consistency": {"PATCHWORK"}, "fits_its_device": {"POORLY"},
    "tells_user_about_problems": {"NOT_SHOWN_TO_USER"}, "confirms_success": {"NOT_SHOWN_TO_USER"},
    "feedback_while_working": {"NONE"}, "accessibility_labels": {"NONE"},
}
# Answers that are not problems but still fall short (rubric v9): listed under "needs work" after the problems, and
# named in the factor's description.
MIDDLE_ANSWERS = {
    "core_flow": {"MOSTLY_WORKS"}, "features_connected": {"SOME_LOOSE_ENDS"}, "tells_user_about_problems": {"SOMETIMES"},
    "confirms_success": {"SOMETIMES"}, "clarity": {"MIXED"}, "consistency": {"MOSTLY_CONSISTENT"},
    "feedback_while_working": {"SOME"}, "fits_its_device": {"ADEQUATELY"}, "accessibility_labels": {"FEW"},
    "navigation_friction": {"A_FEW_STEPS"}, "setup_burden": {"MODERATE"}, "state_and_save": {"MANUAL_SAVE"},
    "depth_of_world_or_concept": {"LIGHTLY_THEMED"},
}


def shortfall(field: str, answer: Any) -> int:
    """2 = a problem, 1 = falls short, 0 = fine (or not shown either way)."""
    if answer in PROBLEM_ANSWERS.get(field, ()):
        return 2
    if answer in MIDDLE_ANSWERS.get(field, ()):
        return 1
    return 0


def category(cat: str, answers: Dict[str, Any], hostile_found: List[str], proven_problems: int = 0, lines_of_code: int = 0) -> Dict[str, Any]:
    pts, maxp = 0, 0
    for field, table in POINTS[cat].items():
        if not isinstance(table, dict):
            continue
        maxp += max(table.values())
        a = answers.get(field)
        if a and "answer" in a:
            pts += table.get(a["answer"], 0)
    if cat == "value":
        twists = [t for t in answers.get("specific_twists", []) if t.get("verified")]
        pts += min(len(twists) * POINTS["value"]["verified_twist_each"], POINTS["value"]["verified_twist_max"])
        maxp += POINTS["value"]["verified_twist_max"]
    if cat == "functionality" and proven_problems:
        # proven defects (unwired endpoints, configs that don't parse, ...) per 1,000 lines, so size is never punished
        rate = proven_problems / max(lines_of_code / 1000.0, 1.0)
        pts -= min(rate * POINTS["functionality"]["proven_problem_rate_penalty"], POINTS["functionality"]["proven_problem_penalty_max"])
    hostile = list(hostile_found)
    if cat == "journey":
        llm = answers.get("hostile_monetization") or {}
        if llm.get("answer") is True and llm.get("verified"):
            hostile.append("reported in the rubric with a quote from the dossier")
        if hostile:
            pts += POINTS["journey"]["hostile_penalty"]
    return {"score": round(100.0 * max(pts, 0) / maxp, 1) if maxp else 0.0, "points": pts, "max": maxp,
            "hostile": hostile if cat == "journey" else []}


def overall(scores: Dict[str, float]) -> float:
    return round(sum(scores[c] * w for c, w in WEIGHTS.items()) / sum(WEIGHTS.values()), 1)
