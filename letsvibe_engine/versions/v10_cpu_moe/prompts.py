"""Prompts for Engine v10 (unified qwen3:30b-a3b via llama.cpp --cpu-moe)."""

from __future__ import annotations

import json
from typing import Any, Dict, List


SYSTEM_AUDITOR = (
    "You are the LetsVibe v10 Code & Product Auditor. "
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
) -> str:
    return f"""Analyze the project context and app dossier for repository `{repo_name}`.
{platform_note}{cliche_fact}
--- PROJECT CONTEXT SOURCES ---
{context_sources_text[:6000]}

--- APP DOSSIER ---
{dossier_md[:14000]}

Return a JSON object with this exact schema:
{{
  "identified_archetype": "short 3-7 word description of what this app actually is",
  "purpose": "1-2 sentence plain-English explanation of what the app does for users",
  "audience": "who this app is built for",
  "project_profile": "one of: consumer_web_app, developer_tool, media_or_game_app, cli_or_utility, library_or_sdk, automation_or_bot, unknown_or_general",
  "dossier_observations": {{
    "value": ["concrete observation from README/dossier/routes"],
    "creativity": ["what feels original or derivative vs standard templates"],
    "journey": ["user onboarding, navigation, flow friction, or clarity observations"],
    "functionality": ["core capabilities, integrations, or proven problems seen in dossier"],
    "ui_ux": ["UI structure, responsiveness, visual polish, or layout observations"]
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


def build_scoring_prompt(
    repo_name: str,
    context_json: Dict[str, Any],
    batch_findings: List[Dict[str, Any]],
    proven_problems: List[str],
    hostile_patterns: List[str],
    deterministic_summary: Dict[str, Any],
) -> str:
    return f"""Score `{repo_name}` across the 5 LetsVibe rubric factors using all verified evidence below.

Scoring calibration (0-100 per factor):
- 85-100: Exceptional production polish, distinctive value, complete end-to-end flows, minimal bugs.
- 70-84: Solid working app with real utility and coherent UX, some rough edges or missing polish.
- 50-69: Functional prototype/MVP with noticeable gaps, stubs, UX friction, or incomplete flows.
- 30-49: Early scaffold or heavily broken/incomplete app.
- 0-29: Non-functional, empty, or hostile/deceptive.

Weights: value=30%, creativity=15%, journey=20%, functionality=20%, ui_ux=15%.
Deduct appropriately for proven problems or hostile patterns if present.

--- PROJECT CONTEXT ---
{json.dumps(context_json, indent=2)[:5000]}

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
  "scores": {{
    "value": 0,
    "creativity": 0,
    "journey": 0,
    "functionality": 0,
    "ui_ux": 0
  }},
  "factors": {{
    "value": {{"strengths": ["..."], "weaknesses": ["..."]}},
    "creativity": {{"strengths": ["..."], "weaknesses": ["..."]}},
    "journey": {{"strengths": ["..."], "weaknesses": ["..."]}},
    "functionality": {{"strengths": ["..."], "weaknesses": ["..."]}},
    "ui_ux": {{"strengths": ["..."], "weaknesses": ["..."]}}
  }},
  "top_solid_features": ["up to 5 strongest verified features with file/line where known"],
  "top_features_needing_work": ["up to 5 highest-impact bugs, gaps, or UX issues to fix"],
  "pro_next_steps": ["3-5 concrete, prioritized developer next steps"]
}}"""


def build_narrative_prompt(
    repo_name: str,
    context_json: Dict[str, Any],
    scoring_json: Dict[str, Any],
    final_score: float,
    letter_grade: str,
) -> str:
    return f"""Write the final user-facing evaluation narrative for `{repo_name}` (Final Score: {final_score}/100, Grade: {letter_grade}).
Ground every sentence in the verified findings below. Be direct, constructive, and specific.

--- CONTEXT ---
{json.dumps(context_json, indent=2)[:3000]}

--- SCORES & FINDINGS ---
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
    "ui_ux": "2-3 sentence explanation of the UI/UX score"
  }}
}}"""
