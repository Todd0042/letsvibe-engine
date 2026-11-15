"""Hardened deterministic + LLM-arbitrated project profile detection for Engine v10.1."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from letsvibe_engine.versions.v9_4_experimental.context import load_project_profiles

CANONICAL_PROFILES = (
    "developer_tool_or_mcp",
    "interactive_game_or_simulation",
    "media_or_social_lounge",
    "hardware_iot_or_mobile",
    "web_productivity_app",
    "automation_script_or_pipeline",
    "unknown_or_general",
)

PROFILE_ALIASES = {
    "developer_tool": "developer_tool_or_mcp",
    "cli_or_utility": "developer_tool_or_mcp",
    "library_or_sdk": "developer_tool_or_mcp",
    "mcp_server": "developer_tool_or_mcp",
    "consumer_web_app": "web_productivity_app",
    "web_app": "web_productivity_app",
    "media_or_game_app": "interactive_game_or_simulation",
    "game": "interactive_game_or_simulation",
    "automation_or_bot": "automation_script_or_pipeline",
    "mobile_or_iot": "hardware_iot_or_mobile",
}


def normalize_profile_key(raw: Optional[str]) -> Optional[str]:
    val = str(raw or "").strip().lower()
    if not val or val == "auto":
        return None
    if val in CANONICAL_PROFILES:
        return val
    return PROFILE_ALIASES.get(val)


def extract_structural_signals(
    files: Dict[str, str],
    readme_raw: str = "",
    kind_hint: str = "",
) -> Dict[str, Any]:
    """Compute structural evidence counts across UI, CLI, mobile/IoT, game, media, and automation."""
    names = [f.lower() for f in files]
    bases = {Path(f).name.lower() for f in files}
    joined = " ".join(t[:2500].lower() for t in files.values())
    readme_l = (readme_raw or "").lower()

    ui_templates = sum(
        1
        for f in names
        if f.endswith((".html", ".jsx", ".tsx", ".vue", ".svelte"))
        and "/test" not in f
        and "tests/" not in f
    )
    css_files = sum(1 for f in names if f.endswith((".css", ".scss")))

    cli_markers = [
        m
        for m in (
            "argparse",
            "import click",
            "from click",
            "import typer",
            "from typer",
            "commander",
            "yargs",
            "clap::",
            "cobra.command",
            "fastmcp",
            "@modelcontextprotocol/sdk",
            "[project.scripts]",
            "console_scripts",
        )
        if m in joined
    ]
    if "mcp.json" in bases or "plugin.json" in bases:
        cli_markers.append("mcp_manifest")

    mobile_iot_markers = [
        m
        for m in (
            "androidmanifest.xml",
            "platformio.ini",
        )
        if m in bases
    ] + [
        m
        for m in ("gpio", "obd2", "serial.serial", "bluetooth", "androidx", "jetpack compose", "kivy", "flutter")
        if m in joined
    ]

    game_markers = [
        m
        for m in ("pygame", "phaser", "three.js", "pixi", "delta_time", "requestanimationframe", "canvas.getcontext")
        if m in joined
    ]
    if "project.godot" in bases:
        game_markers.append("project.godot")
    has_game_terms = bool(re.search(r"\b(sprite|collision|enemy|bullet|asteroid|high_score|gameplay|roguelike|shmup|platformer)\b", joined + " " + readme_l))

    media_markers = [
        m
        for m in ("karaoke", "ffmpeg", "howler", "sounddevice", "lyrics", "now_playing", "audio_stream")
        if m in joined
    ]
    if "websockets" in joined and any(w in joined for w in ("audio", "singer", "player", "video")):
        media_markers.append("ws_media")

    automation_markers = [
        m
        for m in ("playwright", "beautifulsoup", "scrapy", "selenium")
        if m in joined
    ]

    web_fw_markers = [
        m
        for m in ("fastapi", "flask", "django", "express", "react", "vue", "svelte", "next", "vite", "tailwind")
        if re.search(rf"\b{re.escape(m)}\b", joined)
    ]

    scores: Dict[str, int] = {k: 0 for k in CANONICAL_PROFILES if k != "unknown_or_general"}

    # Developer Tool / CLI / MCP: strong CLI/MCP signals AND minimal/no GUI surface
    if cli_markers:
        scores["developer_tool_or_mcp"] += min(6, 2 * len(cli_markers))
    if re.search(r"\b(cli tool|command-line|mcp server|model context protocol|sdk|python library|npm package)\b", readme_l):
        scores["developer_tool_or_mcp"] += 3
    if kind_hint in ("AI assistant plugin", "editor extension", "command-line tool"):
        scores["developer_tool_or_mcp"] += 3
    # Anti-misclassification: a real web/mobile app that happens to have a [project.scripts] launcher isn't a CLI
    if ui_templates >= 2 or len(mobile_iot_markers) >= 2:
        scores["developer_tool_or_mcp"] = max(0, scores["developer_tool_or_mcp"] - 4)

    # Hardware / IoT / Mobile
    if mobile_iot_markers:
        scores["hardware_iot_or_mobile"] += min(7, 2 * len(mobile_iot_markers))
    if kind_hint in ("hardware project", "mobile app"):
        scores["hardware_iot_or_mobile"] += 3
    if re.search(r"\b(android app|ios app|raspberry pi|arduino|esp32|obd|microcontroller)\b", readme_l):
        scores["hardware_iot_or_mobile"] += 2

    # Media / Social Lounge
    if media_markers:
        scores["media_or_social_lounge"] += min(7, 2 * len(media_markers))
    if re.search(r"\b(karaoke|media player|video player|music player|audio normalizer|social lounge)\b", readme_l):
        scores["media_or_social_lounge"] += 3

    # Game / Interactive Simulation
    if game_markers and (has_game_terms or "pygame" in game_markers or "project.godot" in game_markers):
        scores["interactive_game_or_simulation"] += min(7, 2 * len(game_markers) + (2 if has_game_terms else 0))
    if kind_hint == "game" or re.search(r"\b(arcade game|retro game|space shooter|roguelike|shmup|platformer)\b", readme_l):
        scores["interactive_game_or_simulation"] += 3

    # Automation Script / Pipeline
    if automation_markers:
        scores["automation_script_or_pipeline"] += min(6, 2 * len(automation_markers))
    if re.search(r"\b(web scraper|crawler|etl pipeline|batch automation)\b", readme_l):
        scores["automation_script_or_pipeline"] += 3
    if ui_templates >= 2:
        scores["automation_script_or_pipeline"] = max(0, scores["automation_script_or_pipeline"] - 3)

    # Web Productivity / Dashboard
    if ui_templates >= 1:
        scores["web_productivity_app"] += min(5, 1 + ui_templates)
    if web_fw_markers:
        scores["web_productivity_app"] += min(4, len(web_fw_markers))
    if kind_hint in ("web app", "desktop app"):
        scores["web_productivity_app"] += 2
    if re.search(r"\b(dashboard|web app|kanban|budget|tracker|workspace)\b", readme_l):
        scores["web_productivity_app"] += 2

    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    top_profile, top_score = ranked[0]
    runner_up_score = ranked[1][1] if len(ranked) > 1 else 0

    return {
        "ui_template_files": ui_templates,
        "css_files": css_files,
        "cli_markers": cli_markers,
        "mobile_iot_markers": mobile_iot_markers,
        "game_markers": game_markers,
        "media_markers": media_markers,
        "automation_markers": automation_markers,
        "web_fw_markers": web_fw_markers,
        "candidate_scores": dict(ranked),
        "structural_top": top_profile if top_score >= 2 else "unknown_or_general",
        "structural_margin": top_score - runner_up_score,
        "structural_confidence": "high" if (top_score >= 4 and (top_score - runner_up_score) >= 2) else "low",
    }


def resolve_project_profile(
    explicit_profile: Optional[str],
    signals: Dict[str, Any],
    llm_profile: Optional[str],
) -> Tuple[str, Dict[str, Any], str]:
    """Return (profile_key, profile_data, detection_method)."""
    profiles_map = load_project_profiles()

    explicit_key = normalize_profile_key(explicit_profile)
    if explicit_key and explicit_key in profiles_map:
        return explicit_key, profiles_map[explicit_key], "explicit"

    llm_key = normalize_profile_key(llm_profile)
    top_key = str(signals.get("structural_top") or "unknown_or_general")
    confidence = signals.get("structural_confidence")

    if confidence == "high" and top_key in profiles_map:
        # Only let LLM override if LLM picked a closely competing structural candidate (>= 3)
        cand_scores = signals.get("candidate_scores") or {}
        if llm_key and llm_key in profiles_map and cand_scores.get(llm_key, 0) >= max(3, cand_scores.get(top_key, 0) - 1):
            return llm_key, profiles_map[llm_key], "structural+llm_tiebreak"
        return top_key, profiles_map[top_key], "structural_high_conf"

    if llm_key and llm_key in profiles_map and llm_key != "unknown_or_general":
        return llm_key, profiles_map[llm_key], "llm_arbitrated"

    if top_key in profiles_map:
        return top_key, profiles_map[top_key], "structural_fallback"

    return "unknown_or_general", profiles_map.get("unknown_or_general", {}), "fallback"
