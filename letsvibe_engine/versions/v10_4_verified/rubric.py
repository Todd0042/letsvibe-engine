"""Profile-adaptive discrete rubric and Code Health scoring for Engine v10.2 (Testing)."""

from __future__ import annotations

import math

from typing import Any, Dict, List, Optional, Tuple

WEIGHTS: Dict[str, float] = {
    "value": 25.0,
    "functionality": 20.0,
    "journey": 15.0,
    "code_health": 15.0,
    "creativity": 15.0,
    "ui_ux": 10.0,
}

FACTOR_OF: Dict[str, str] = {
    "value": "resonance",
    "creativity": "creativity",
    "journey": "user_journey",
    "functionality": "functionality",
    "code_health": "code_health",
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


# Shared core + tighter v10.2 standards
SHARED_VALUE_POINTS = {
    "tier": {
        "TIER_0_BROKEN_OR_SHELL": 0,
        "TIER_1_GENERIC_CLONE": 10,
        "TIER_2_ITERATIVE_NICHE": 25,
        "TIER_3_GENUINE_GAP_OR_HOOK": 55,
    },
    "is_default_prompt_clone": {False: 25, True: 0},
    "verified_twist_each": 5,
    "verified_twist_max": 20,
}

SHARED_FUNCTIONALITY_POINTS = {
    "core_flow": {
        "WORKS_END_TO_END": 42,
        "MOSTLY_WORKS": 26,
        "PARTLY_BUILT": 10,
        "SHELL_OR_PLACEHOLDER": 0,
    },
    "features_connected": {"CONNECTED": 25, "SOME_LOOSE_ENDS": 10, "DISCONNECTED": 0},
    "tells_user_about_problems": {"CLEARLY": 18, "SOMETIMES": 9, "NOT_SHOWN": 2, "NEVER": 0},
    "confirms_success": {"CLEARLY": 15, "SOMETIMES": 8, "NOT_SHOWN": 2, "NEVER": 0},
    "proven_problem_rate_penalty": 12,
    "proven_problem_penalty_max": 30,
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
                "RUNS_IMMEDIATELY": 20,
                "ONE_STEP_INSTALL": 16,
                "MANUAL_SETUP": 8,
                "BRING_YOUR_OWN_KEY": 0,
            },
            "invocation_friction": {"ONE_COMMAND": 25, "A_FEW_STEPS": 14, "BURIED": 0},
            "setup_burden": {"NONE": 20, "LIGHT": 20, "MODERATE": 10, "HEAVY": 0},
            "state_and_config": {"AUTO_OR_STATELESS": 20, "EXPLICIT_CONFIG": 14, "FRAGILE_OR_MANUAL": 0},
            "options_have_explanations": {"ALL_OR_MOST": 15, "NO_OPTIONS": 15, "SOME": 7, "FEW_OR_NONE": 0},
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
            "hud_and_controls_clarity": {"CLEAR": 25, "MIXED": 12, "CLUTTERED": 0},
            "visual_audio_cohesion": {"CONSISTENT": 20, "MOSTLY_CONSISTENT": 10, "PATCHWORK": 0},
            "input_and_state_feedback": {"CLEAR": 20, "SOME": 10, "NONE": 0},
            "fits_its_device": {"WELL": 15, "ADEQUATELY": 8, "POORLY": 0},
            "visual_polish": {"POLISHED": 20, "FUNCTIONAL": 10, "BAREBONES": 0},
        },
        "journey": {
            "launch_experience": {
                "RUNS_IMMEDIATELY": 20,
                "ONE_STEP_INSTALL": 16,
                "MANUAL_SETUP": 8,
                "BRING_YOUR_OWN_KEY": 0,
            },
            "navigation_friction": {"STRAIGHT_TO_CORE": 20, "A_FEW_STEPS": 10, "BURIED": 0},
            "setup_burden": {"NONE": 10, "LIGHT": 10, "MODERATE": 5, "HEAVY": 0},
            "state_and_save": {"AUTO_SAVE": 20, "MANUAL_SAVE": 14, "NOT_NEEDED": 8, "NO_SAVE": 0},
            "onboarding_and_controls_help": {"CLEAR": 30, "BASIC": 12, "NONE": 0},
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
                "RUNS_IMMEDIATELY": 25,
                "ONE_STEP_INSTALL": 18,
                "MANUAL_SETUP": 8,
                "BRING_YOUR_OWN_KEY": 0,
            },
            "navigation_friction": {"STRAIGHT_TO_CORE": 15, "A_FEW_STEPS": 8, "BURIED": 0},
            "setup_burden": {"NONE": 10, "LIGHT": 10, "MODERATE": 5, "HEAVY": 0},
            "state_and_save": {"AUTO_SAVE": 10, "NOT_NEEDED": 9, "MANUAL_SAVE": 7, "NO_SAVE": 0},
            "onboarding_and_controls_help": {"CLEAR": 15, "BASIC": 7, "NONE": 0},
            "options_have_explanations": {"ALL_OR_MOST": 15, "NO_OPTIONS": 15, "SOME": 7, "FEW_OR_NONE": 0},
            "first_time_intuitiveness": {"INTUITIVE": 10, "NEEDS_TRIAL_AND_ERROR": 4, "STEEP_LEARNING_CURVE": 0},
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
        is_clone = _coerce_bool(answers.get("is_default_prompt_clone")) is True
        if is_clone:
            # Cap tier points at TIER_1_GENERIC_CLONE if marked as a default/classic clone
            raw_tier = str(answers.get("tier") or "").strip().upper()
            tier_pts = table_map["tier"].get(raw_tier, 0)
            clone_cap = table_map["tier"]["TIER_1_GENERIC_CLONE"]
            if tier_pts > clone_cap:
                pts -= (tier_pts - clone_cap)

        maxp += table_map["verified_twist_max"]
        twists = answers.get("verified_twists")
        if isinstance(twists, list):
            twist_cnt = min(4, len([t for t in twists if str(t).strip()]))
        else:
            try:
                twist_cnt = max(0, min(4, int(answers.get("verified_twists_count") or 0)))
            except (TypeError, ValueError):
                twist_cnt = 0
        if is_clone:
            twist_cnt = min(1, twist_cnt)
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
    score = round(max(0.0, min(100.0, pts * 100.0 / maxp)), 1)
    if cat == "ui_ux" and family == "game_or_sim":
        polish = str(answers.get("visual_polish") or "").strip().upper()
        if polish == "BAREBONES":
            score = min(score, 40.0)
        elif polish == "FUNCTIONAL":
            score = min(score, 68.0)
    return score


_KIND_OF_LABEL = {"oversized file(s)": ("oversized file",), "oversized/complex function(s)": ("oversized function",),
                  "repeated 10-line": ("duplicated code",), "swallowed error(s)": ("swallowed error",),
                  "unused file(s)": ("unused file", "unused route")}


def _where(findings: List[Dict[str, Any]], label: str, limit: int = 3) -> str:
    """'a.py:12, b.ts:40 (+5 more)': where to start fixing."""
    kinds = next((k for prefix, k in _KIND_OF_LABEL.items() if label.startswith(prefix)), ())
    hits = [f for f in findings if f.get("kind") in kinds and f.get("file")]
    spots = [f"{f['file']}:{f['line']}" if f.get("line") else str(f["file"]) for f in hits[:limit]]
    more = f" (+{len(hits) - limit} more)" if len(hits) > limit else ""
    return ", ".join(spots) + more


def score_code_health(
    metrics: Any,
    maintainer_findings: List[Dict[str, Any]],
) -> Tuple[float, str, List[str], List[str]]:
    """
    Deterministic 0-100 Code Health score combining cyclomatic complexity,
    oversized files/functions, 10-line duplicated code blocks, dead code,
    and swallowed errors.
    """
    avg_ccn = float(getattr(metrics, "avg_cyclomatic_complexity", 0.0) or 0.0)
    max_ccn = int(getattr(metrics, "max_cyclomatic_complexity", 0) or 0)
    findings = maintainer_findings or []

    oversized_files = sum(1 for f in findings if f.get("kind") == "oversized file")
    oversized_funcs = sum(1 for f in findings if f.get("kind") == "oversized function")
    duplicated_blocks = sum(1 for f in findings if f.get("kind") == "duplicated code")
    swallowed_errors = sum(1 for f in findings if f.get("kind") == "swallowed error")
    dead_code = sum(1 for f in findings if f.get("kind") in ("unused file", "unused route"))

    score = 100.0
    strengths: List[str] = []
    weaknesses: List[str] = []

    # Function complexity is measured twice: CCN (average and peak) and "oversized/complex functions". They mostly describe
    # the same functions, so together they cost the larger penalty plus a quarter of the smaller: the overlap counts once,
    # and fixing either still moves the score (both stay listed as weaknesses).
    ccn_penalty = 0.0
    if avg_ccn > 5.0:
        ccn_penalty += min(20.0, (avg_ccn - 5.0) * 2.5)
        weaknesses.append(f"High average function complexity (Avg CCN {avg_ccn:.1f})")
    elif avg_ccn > 0:
        strengths.append(f"Clean average function branching (Avg CCN {avg_ccn:.1f})")

    if max_ccn > 20:
        ccn_penalty += min(15.0, (max_ccn - 20) * 0.5)
        weaknesses.append(f"Deeply nested peak function (Max CCN {max_ccn})")

    # v10.4: findings are judged by density (per 1,000 lines of code), on a smooth curve towards the same maximum
    # penalty v10.3 capped at: a few findings in a big codebase cost little, every fix moves the score a little,
    # and a small and a large repo with the same habits score alike. (v10.3 capped counts: 6 swallowed errors in
    # 600 lines and in 36,000 cost the same 18 points, and fixes past the cap changed nothing.)
    kloc = max(0.5, float(getattr(metrics, "total_loc", 0) or 0) / 1000.0)
    # Small samples: in a 1,300-line program one oversized file is "0.7 per 1,000 lines", as if a large repo had one
    # every 1,400 lines. The penalty density is taken over the code plus 2,000 lines of assumed-clean code, which barely
    # changes a large repo and stops one or two findings from deciding a small one. (The shown density is the real one.)
    SMALL_SAMPLE_KLOC = 2.0

    def density_penalty(n: int, cap: float, scale: float) -> tuple[float, float]:
        # d / (d + scale): rises quickly for the first findings, keeps rising (never flat) as they pile up, so even a
        # messy repo sees every fix; never reaches the cap.
        d = n / (kloc + SMALL_SAMPLE_KLOC)
        return cap * d / (d + scale), n / kloc

    for n, cap, scale, label, good in (
        (oversized_files, 16.0, 0.13, "oversized file(s) mixing responsibilities", "No oversized monolith files flagged"),
        (oversized_funcs, 15.0, 0.25, "oversized/complex function(s)", None),
        (duplicated_blocks, 16.0, 0.13, "repeated 10-line code block(s)", "No 10-line duplicated logic blocks detected"),
        (swallowed_errors, 18.0, 0.25, "swallowed error(s) hiding failures silently", "No silent swallowed-error blocks flagged"),
        (dead_code, 12.0, 0.08, "unused file(s) or unwired route(s)", None),
    ):
        if n > 0:
            pen, d = density_penalty(n, cap, scale)
            if label == "oversized/complex function(s)":
                # combined with CCN: max(a, b) + min(a, b) / 4, minus the CCN part already taken below
                pen = max(pen, ccn_penalty) + min(pen, ccn_penalty) / 4 - ccn_penalty
            score -= pen
            where = _where(findings, label)
            weaknesses.append(f"{n} {label} ({d:.1f} per 1,000 lines){': ' + where if where else ''}")
        elif good:
            strengths.append(good)

    score -= ccn_penalty
    final = round(max(0.0, min(100.0, score)), 1)
    parts = [
        f"Avg CCN {avg_ccn:.1f}",
        f"Max CCN {max_ccn}",
        f"{oversized_files} oversized file(s)",
        f"{duplicated_blocks} duplicated block(s)",
        f"{swallowed_errors} swallowed error(s)",
    ]
    summary = (
        f"Code Health scored {final:.1f}/100 from static code telemetry ({', '.join(parts)})."
    )
    return final, summary, strengths[:5], weaknesses[:5]


def compute_all_scores(
    family: str,
    checklist: Dict[str, Any],
    hostile_found: List[str],
    proven_problems_count: int = 0,
    lines_of_code: int = 0,
    profile_data: Optional[Dict[str, Any]] = None,
    code_health_score: float = 70.0,
) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for cat in WEIGHTS:
        if cat == "code_health":
            out[cat] = round(max(0.0, min(100.0, float(code_health_score))), 1)
            continue
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
    jrn = checklist.get("journey") if isinstance(checklist.get("journey"), dict) else {}
    if (
        str(jrn.get("first_time_intuitiveness") or "").strip().upper() == "STEEP_LEARNING_CURVE"
        or str(jrn.get("options_have_explanations") or "").strip().upper() == "FEW_OR_NONE"
    ):
        out["journey"] = min(out["journey"], 65.0)
    if family == "game_or_sim":
        func = checklist.get("functionality") if isinstance(checklist.get("functionality"), dict) else {}
        core_flow = str(func.get("core_flow") or "").strip().upper()
        if core_flow in ("MOSTLY_WORKS", "PARTLY_BUILT", "SHELL_OR_PLACEHOLDER"):
            out["journey"] = min(out["journey"], 65.0)
    return out


def cap_for_weaknesses(n: int) -> float:
    """v10.4 1d: the most a factor can score while n (verified) weaknesses are still listed against it: 100 with none,
    95 with one, a point less for each more, never below 90. A report can't call something perfect and then list
    what's wrong with it; the cap stays small because the rubric's checklist already scored the substance."""
    return 100.0 if n <= 0 else max(90.0, 96.0 - n)


def overall(scores: Dict[str, float]) -> float:
    return round(sum(scores[c] * WEIGHTS[c] for c in WEIGHTS) / 100.0, 1)
