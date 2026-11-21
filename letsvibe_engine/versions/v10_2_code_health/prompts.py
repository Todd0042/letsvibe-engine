"""Prompts for Engine v10.1 (Profile-Adaptive Discrete Rubric + 30B-A3B --cpu-moe)."""

from __future__ import annotations

import json
from typing import Any, Dict, List


SYSTEM_AUDITOR = (
    "You are the LetsVibe v10.1 Code & Product Auditor. "
    "You judge real software repositories strictly from observed code, routes, UI, and deterministic telemetry. "
    "Never invent files, features, or line numbers. Always cite exact file paths and line numbers when visible. "
    "Respond ONLY with a valid JSON object matching the requested schema."
)


def build_context_prompt(
    repo_name: str,
    dossier_md: str,
    context_sources_text: str,
    platform_note: str,
    cliche_fact: str,
    structural_signals: Dict[str, Any],
) -> str:
    compact_signals = {
        "ui_template_files": structural_signals.get("ui_template_files", 0),
        "cli_markers": structural_signals.get("cli_markers", []),
        "mobile_iot_markers": structural_signals.get("mobile_iot_markers", []),
        "game_markers": structural_signals.get("game_markers", []),
        "media_markers": structural_signals.get("media_markers", []),
        "automation_markers": structural_signals.get("automation_markers", []),
        "web_fw_markers": structural_signals.get("web_fw_markers", []),
        "structural_top": structural_signals.get("structural_top", "unknown_or_general"),
    }
    return f"""Analyze the project context, structural file signals, and app dossier for repository `{repo_name}`.
{platform_note}{cliche_fact}
--- DETERMINISTIC STRUCTURAL SIGNALS ---
{json.dumps(compact_signals, indent=2)}

--- PROJECT CONTEXT SOURCES ---
{context_sources_text[:6000]}

--- APP DOSSIER ---
{dossier_md[:14000]}

Choose `project_profile` as the single best fit from:
- `library_or_sdk`: Reusable libraries, parsers, grammars, SDKs, or packages imported by other code (no primary GUI or CLI app).
- `developer_tool_or_mcp`: CLI utilities, MCP servers, developer tools, editor extensions (no primary GUI app).
- `interactive_game_or_simulation`: 2D/3D games, canvas/pygame simulations, retro arcade apps.
- `media_or_social_lounge`: Audio/video players, karaoke lounges, media normalizers, multi-device party apps.
- `hardware_iot_or_mobile`: Android/iOS mobile apps, Raspberry Pi/Arduino/ESP32/OBD2 hardware controllers.
- `web_productivity_app`: Web dashboards, SaaS/CRUD apps, trackers, interactive browser workspaces.
- `automation_script_or_pipeline`: Headless scrapers, crawlers, ETL/batch automation pipelines.
- `unknown_or_general`: General software that does not clearly fit the categories above.

Return a JSON object with this exact schema:
{{
  "identified_archetype": "short 3-7 word description of what this app actually is",
  "purpose": "1-2 sentence plain-English explanation of what the app does for users",
  "audience": "who this app is built for",
  "project_profile": "one of the 7 canonical keys listed above",
  "dossier_observations": {{
    "value": ["concrete observation from README/dossier/routes"],
    "creativity": ["what feels original or derivative vs standard templates"],
    "journey": ["user onboarding, navigation, flow friction, or clarity observations"],
    "functionality": ["core capabilities, integrations, or proven problems seen in dossier"],
    "ui_ux": ["UI/CLI ergonomics, structure, responsiveness, or layout observations"]
  }}
}}"""


def build_batch_audit_prompt(
    repo_name: str,
    purpose: str,
    batch_index: int,
    total_batches: int,
    batch_label: str,
    batch_code: str,
    platform_note: str,
) -> str:
    return f"""Audit code batch {batch_index}/{total_batches} ({batch_label}) for `{repo_name}`.
App purpose: {purpose}
{platform_note}
Read the code carefully and report ONLY things directly visible in this batch. Cite `file (line N)` where possible.

--- CODE BATCH {batch_index}/{total_batches} ---
{batch_code}

Return a JSON object with this exact schema:
{{
  "batch_summary": "1-2 sentences summarizing what this batch implements",
  "strengths": [
    {{"factor": "value|creativity|journey|functionality|ui_ux", "claim": "specific verified capability or craft", "evidence": "file (line N): brief quote or symbol"}}
  ],
  "issues": [
    {{"factor": "value|creativity|journey|functionality|ui_ux", "severity": "high|medium|low", "claim": "concrete bug, gap, stub, missing error handling, or UX friction", "evidence": "file (line N): brief quote or symbol"}}
  ],
  "notable_twists": [
    "specific creative or high-value detail found in this code (only if genuinely present, else empty list)"
  ]
}}"""


_FAMILY_CHECKLIST_SCHEMA: Dict[str, str] = {
    "library_or_sdk": """    "creativity": {{
      "has_distinct_voice_or_craft": true,
      "clever_workflow_or_abstraction": false,
      "concept_depth": "STERILE_DEFAULT | LIGHTLY_CRAFTED | COHESIVE | DISTINCTIVE",
      "mechanical_synergy": true
    }},
    "ui_ux": {{
      "public_api_clarity": "CLEAR | MIXED | OPAQUE",
      "docs_and_examples": "CLEAR | BASIC | MISSING_OR_STALE",
      "error_and_diagnostic_quality": "CLEAR | SOME | OPAQUE",
      "packaging_and_composability": "WELL | ADEQUATELY | POORLY"
    }},
    "journey": {{
      "launch_experience": "RUNS_IMMEDIATELY | ONE_STEP_INSTALL | MANUAL_SETUP | BRING_YOUR_OWN_KEY",
      "integration_friction": "ONE_IMPORT_OR_CALL | A_FEW_STEPS | COMPLEX_SETUP",
      "setup_burden": "NONE | LIGHT | MODERATE | HEAVY",
      "state_and_config": "AUTO_OR_STATELESS | EXPLICIT_CONFIG | FRAGILE_OR_MANUAL",
      "options_have_explanations": "ALL_OR_MOST | NO_OPTIONS | SOME | FEW_OR_NONE",
      "hostile_monetization": false
    }}""",
    "cli_or_automation": """    "creativity": {{
      "has_distinct_voice_or_craft": true,
      "clever_workflow_or_abstraction": false,
      "concept_depth": "STERILE_DEFAULT | LIGHTLY_CRAFTED | COHESIVE | DISTINCTIVE",
      "mechanical_synergy": true
    }},
    "ui_ux": {{
      "help_and_flag_clarity": "CLEAR | MIXED | CLUTTERED_OR_UNDOCUMENTED",
      "output_and_error_quality": "CLEAR | SOME | OPAQUE",
      "composability_and_exit_codes": "WELL | ADEQUATELY | POORLY",
      "defaults_and_safety": "GOOD | BASIC | RISKY_OR_MISSING"
    }},
    "journey": {{
      "launch_experience": "RUNS_IMMEDIATELY | ONE_STEP_INSTALL | MANUAL_SETUP | BRING_YOUR_OWN_KEY",
      "invocation_friction": "ONE_COMMAND | A_FEW_STEPS | BURIED",
      "setup_burden": "NONE | LIGHT | MODERATE | HEAVY",
      "state_and_config": "AUTO_OR_STATELESS | EXPLICIT_CONFIG | FRAGILE_OR_MANUAL",
      "options_have_explanations": "ALL_OR_MOST | NO_OPTIONS | SOME | FEW_OR_NONE",
      "hostile_monetization": false
    }}""",
    "game_or_sim": """    "creativity": {{
      "has_distinct_voice": true,
      "subverts_standard_ui": false,
      "depth_of_world_or_concept": "STERILE_DEFAULT | LIGHTLY_THEMED | THEMED | RICHLY_THEMED",
      "mechanical_synergy": true
    }},
    "ui_ux": {{
      "hud_and_controls_clarity": "CLEAR | MIXED | CLUTTERED",
      "visual_audio_cohesion": "CONSISTENT | MOSTLY_CONSISTENT | PATCHWORK",
      "input_and_state_feedback": "CLEAR | SOME | NONE",
      "fits_its_device": "WELL | ADEQUATELY | POORLY",
      "visual_polish": "POLISHED | FUNCTIONAL | BAREBONES"
    }},
    "journey": {{
      "launch_experience": "RUNS_IMMEDIATELY | ONE_STEP_INSTALL | MANUAL_SETUP | BRING_YOUR_OWN_KEY",
      "navigation_friction": "STRAIGHT_TO_CORE | A_FEW_STEPS | BURIED",
      "setup_burden": "NONE | LIGHT | MODERATE | HEAVY",
      "state_and_save": "AUTO_SAVE | MANUAL_SAVE | NOT_NEEDED | NO_SAVE",
      "onboarding_and_controls_help": "CLEAR | BASIC | NONE",
      "hostile_monetization": false
    }}""",
    "gui_or_general": """    "creativity": {{
      "has_distinct_voice": true,
      "subverts_standard_ui": false,
      "depth_of_world_or_concept": "STERILE_DEFAULT | LIGHTLY_THEMED | THEMED | RICHLY_THEMED",
      "mechanical_synergy": true
    }},
    "ui_ux": {{
      "clarity": "CLEAR | MIXED | CLUTTERED_OR_TECHNICAL",
      "consistency": "CONSISTENT | MOSTLY_CONSISTENT | PATCHWORK",
      "feedback_while_working": "CLEAR | SOME | NOT_SHOWN | NONE",
      "fits_its_device": "WELL | ADEQUATELY | POORLY | NOT_SHOWN",
      "accessibility_labels": "PRESENT | FEW | NOT_SHOWN | NONE"
    }},
    "journey": {{
      "launch_experience": "RUNS_IMMEDIATELY | ONE_STEP_INSTALL | MANUAL_SETUP | BRING_YOUR_OWN_KEY",
      "navigation_friction": "STRAIGHT_TO_CORE | A_FEW_STEPS | BURIED",
      "setup_burden": "NONE | LIGHT | MODERATE | HEAVY",
      "state_and_save": "AUTO_SAVE | MANUAL_SAVE | NOT_NEEDED | NO_SAVE",
      "onboarding_and_controls_help": "CLEAR | BASIC | NONE",
      "options_have_explanations": "ALL_OR_MOST | NO_OPTIONS | SOME | FEW_OR_NONE",
      "first_time_intuitiveness": "INTUITIVE | NEEDS_TRIAL_AND_ERROR | STEEP_LEARNING_CURVE",
      "hostile_monetization": false
    }}""",
}


def build_scoring_prompt(
    repo_name: str,
    profile_key: str,
    profile_data: Dict[str, Any],
    rubric_family: str,
    context_json: Dict[str, Any],
    batch_findings: List[Dict[str, Any]],
    proven_problems: List[str],
    hostile_patterns: List[str],
    deterministic_summary: Dict[str, Any],
    submission_meta: Dict[str, Any] | None = None,
    in_repo_host_context: str = "",
) -> str:
    lenses = profile_data.get("evaluation_lenses") or {}
    family_block = _FAMILY_CHECKLIST_SCHEMA.get(rubric_family, _FAMILY_CHECKLIST_SCHEMA["gui_or_general"])
    ref_ctx = str((submission_meta or {}).get("reference_context_text") or "").strip()
    in_repo_ctx = str(in_repo_host_context or "").strip()
    combined_host_parts: List[str] = []
    if in_repo_ctx:
        combined_host_parts.append(f"IN-REPO HOST / SDK INTERFACES (parsed deterministically):\n{in_repo_ctx[:2000]}")
    if ref_ctx:
        combined_host_parts.append(ref_ctx[:9000])
    combined_host_txt = "\n\n".join(combined_host_parts)
    ref_block = (
        f"\n--- HOST / FRAMEWORK REFERENCE CONTEXT ---\n"
        f"Repo 1 is built on or integrates with these reference hosts/APIs. Do NOT penalize Repo 1 for windowing, "
        f"options registration, or lifecycle handled by the host; evaluate how cleanly Repo 1 uses these APIs:\n"
        f"{combined_host_txt}\n"
        if combined_host_txt
        else ""
    )
    return f"""Evaluate `{repo_name}` using the profile-adaptive discrete checklist below.
Detected Profile: `{profile_key}` ({profile_data.get('name', profile_key)}) — Checklist Family: `{rubric_family}`
Domain Lenses:
{json.dumps(lenses, indent=2)[:2500]}

IMPORTANT RULES:
- Do NOT output numeric scores. Python computes all 0-100 scores deterministically from your discrete enum/boolean choices.
- Pick the single exact enum string (not the pipe-separated list) or boolean for every field, grounded in the verified code and dossier evidence below.
- `verified_twists`: list up to 4 genuinely uncommon or inventive capabilities/twists (NOT standard genre staples like screen wraparound, waves/bosses, powerups, retro SFX synthesis, health bars, or basic menus). Use `[]` for standard implementations.

CALIBRATION & DISQUALIFIER RULES (follow strictly — v10.2 uses realistic software standards, not grade inflation):
- Most working solo vibe-coded apps belong in the C to B- range on Raw Rubric. Reserve `TIER_3_GENUINE_GAP_OR_HOOK`, `WORKS_END_TO_END`, and `CLEARLY` for verified, cohesive, end-to-end execution with minimal rough edges.
- `value.tier` & `is_default_prompt_clone`:
  - `TIER_0_BROKEN_OR_SHELL`: Broken, unrunnable, or mostly stub/placeholder.
  - `TIER_1_GENERIC_CLONE` + `is_default_prompt_clone: true`: MUST be used for any classic arcade/tutorial/prompt staple (e.g. Asteroids/space shooter, Snake, Pong, Tetris, Todo, basic CRUD, calculator). Even if it adds standard genre/hobby features (bosses, powerups, toroidal wraparound, procedural sine/square SFX or music scripts, particle trails, health bars), it is STILL `TIER_1_GENERIC_CLONE` with `is_default_prompt_clone: true` and `verified_twists: []`.
  - `TIER_2_ITERATIVE_NICHE`: Only for apps solving a real practical workflow/niche problem, OR games with genuinely original core mechanics and cohesive commercial-style polish.
  - `TIER_3_GENUINE_GAP_OR_HOOK`: Original, high-utility product or deeply crafted experience filling a real gap with standout execution and clean architecture.
- `functionality`:
  - Disqualify `WORKS_END_TO_END` if there are incomplete feature templates/TODOs (e.g. unfinished boss/level templates), missing error handling/swallowed errors for core asset/IO paths, or missing VFX/feedback for implemented mechanics (use `MOSTLY_WORKS` or `PARTLY_BUILT`).
  - Disqualify `CONNECTED` if incomplete/unused templates or loose ends exist (use `SOME_LOOSE_ENDS`).
- `ui_ux`:
  - Disqualify `CLEAR` / `CONSISTENT` / `WELL` if debug/developer text leaks on screen (e.g. `'Glow path:'`), hardcoded placeholder colors or resizing bugs appear, key events lack VFX, or visuals are primitive shapes/dots on a plain black background. In those cases, pick `MIXED` / `CLUTTERED`, `MOSTLY_CONSISTENT` / `PATCHWORK`, `SOME`, and `BAREBONES` for `visual_polish`.
- `journey`:
  - Disqualify `STRAIGHT_TO_CORE` if UI resizing bugs, clunky menus, or missing controls/onboarding help disrupt flow (use `A_FEW_STEPS`, and `BASIC` or `NONE` for `onboarding_and_controls_help`).
  - Surface-matched option documentation (`options_have_explanations`): Compare documentation directly against every detected user surface (`option_docs` telemetry). If the program has a GUI, it MUST have GUI tooltips/labels/docs; if CLI, it MUST have CLI flag `help=`/CLI docs; if BOTH, it MUST document BOTH. Complex studio/pro apps with dense docks or unexplained settings (like OBS) must get `STEEP_LEARNING_CURVE` and `FEW_OR_NONE` or `SOME`.
- `simplicity` ("Beauty in Simplicity"):
  - Honestly judge feature restraint vs. AI kitchen-sink bloat (`Laser-Focused` = tight, purposeful scope; `Balanced` = rich without too much clutter; `Kitchen-Sink` = sprawling bolt-on features or redundant modes that distract from the core experience).

--- PROJECT CONTEXT ---
{json.dumps(context_json, indent=2)[:4500]}
{ref_block}

--- DETERMINISTIC TELEMETRY ---
{json.dumps(deterministic_summary, indent=2)}

--- PROVEN PROBLEMS (STATIC SCAN) ---
{json.dumps(proven_problems[:15], indent=2)}

--- HOSTILE PATTERNS ---
{json.dumps(hostile_patterns, indent=2)}

--- CODE AUDIT FINDINGS ({len(batch_findings)} BATCHES) ---
{json.dumps(batch_findings, indent=2)[:18000]}

Return a JSON object with this exact schema:
{{
  "checklist": {{
    "value": {{
      "tier": "TIER_0_BROKEN_OR_SHELL | TIER_1_GENERIC_CLONE | TIER_2_ITERATIVE_NICHE | TIER_3_GENUINE_GAP_OR_HOOK",
      "is_default_prompt_clone": true,
      "verified_twists": []
    }},
    "functionality": {{
      "core_flow": "WORKS_END_TO_END | MOSTLY_WORKS | PARTLY_BUILT | SHELL_OR_PLACEHOLDER",
      "features_connected": "CONNECTED | SOME_LOOSE_ENDS | DISCONNECTED",
      "tells_user_about_problems": "CLEARLY | SOMETIMES | NOT_SHOWN | NEVER",
      "confirms_success": "CLEARLY | SOMETIMES | NOT_SHOWN | NEVER"
    }},
{family_block}
  }},
  "factors": {{
    "value": {{"strengths": ["..."], "weaknesses": ["..."]}},
    "creativity": {{"strengths": ["..."], "weaknesses": ["..."]}},
    "journey": {{"strengths": ["..."], "weaknesses": ["..."]}},
    "functionality": {{"strengths": ["..."], "weaknesses": ["..."]}},
    "ui_ux": {{"strengths": ["..."], "weaknesses": ["..."]}}
  }},
  "simplicity": {{
    "label": "Laser-Focused | Balanced | Kitchen-Sink",
    "summary": "1-2 honest sentences on feature focus vs. unnecessary bolt-on bloat"
  }},
  "top_solid_features": ["up to 5 strongest verified features with file/line where known"],
  "top_features_needing_work": ["up to 5 highest-impact bugs, gaps, or UX issues to fix"],
  "pro_next_steps": ["3-5 concrete, prioritized developer next steps"]
}}"""


def build_narrative_prompt(
    repo_name: str,
    context_json: Dict[str, Any],
    scoring_json: Dict[str, Any],
    computed_scores: Dict[str, float],
    final_score: float,
    letter_grade: str,
) -> str:
    return f"""Write the final user-facing evaluation narrative for `{repo_name}` (Final Score: {final_score}/100, Grade: {letter_grade}).
Factor Scores (computed deterministically): {json.dumps(computed_scores)}
Ground every sentence in the verified findings below. Be direct, constructive, and specific.

--- CONTEXT ---
{json.dumps(context_json, indent=2)[:3000]}

--- CHECKLIST & FINDINGS ---
{json.dumps(scoring_json, indent=2)[:12000]}

Return a JSON object with this exact schema:
{{
  "verdict_title": "punchy 4-9 word verdict title",
  "verdict_summary": "3-4 sentence executive summary of what the app does well, where it falls short, and who it's ready for",
  "peer_summary": "1-2 sentence candid developer-to-developer takeaway",
  "reasoning": {{
    "value": "2-3 sentence explanation of the Real-World Value score",
    "creativity": "2-3 sentence explanation of the Creativity score",
    "journey": "2-3 sentence explanation of the User Journey score",
    "functionality": "2-3 sentence explanation of the Functionality score",
    "ui_ux": "2-3 sentence explanation of the UI/UX or Ergonomics score"
  }}
}}"""
