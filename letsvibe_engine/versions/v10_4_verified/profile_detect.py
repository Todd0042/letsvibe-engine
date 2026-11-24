"""Hardened deterministic + LLM-arbitrated project profile & runtime-envelope detection for Engine v10.3."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from letsvibe_engine.versions.v9_4_experimental.context import load_project_profiles

CANONICAL_PROFILES = (
    "library_or_sdk",
    "developer_tool_or_mcp",
    "interactive_game_or_simulation",
    "media_or_social_lounge",
    "hardware_iot_or_mobile",
    "web_productivity_app",
    "automation_script_or_pipeline",
    "unknown_or_general",
)

PROFILE_ALIASES = {
    "library_or_sdk": "library_or_sdk",
    "library": "library_or_sdk",
    "sdk": "library_or_sdk",
    "developer_tool": "developer_tool_or_mcp",
    "cli_or_utility": "developer_tool_or_mcp",
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


# v10.4: evidence comes only from the repo's own code and manifests. Licences ("express or implied" made almost every
# repo look like an Express web app), docs (Sphinx templates made `requests` a web app), tests, examples and fixtures
# describe or exercise the project; they are not what it ships.
_NOT_OWN = re.compile(
    r"(^|/)(licen[cs]e|copying|notice|authors|contributors|changelog|changes|history)([.-][^/]*)?$"
    r"|\.(md|rst|txt|adoc)$"
    r"|(^|/)(docs?|_themes|_templates|tests?|__tests__|spec|specs|examples?|samples?|demos?|fixtures|benchmarks?|"
    r"testdata|_data\w*)/", re.I)

_WEB_FW = {  # imported or declared as a dependency, not just a word in a file
    "fastapi": r"\b(from|import)\s+fastapi\b", "flask": r"\b(from|import)\s+flask\b",
    "django": r"\b(from|import)\s+django\b",
    "express": r"(require\(\s*|from\s+)['\"]express['\"]|\"express\"\s*:",
    "react": r"(require\(\s*|from\s+)['\"]react(-dom)?['\"]|\"react\"\s*:",
    "vue": r"(require\(\s*|from\s+)['\"]vue['\"]|\"vue\"\s*:", "svelte": r"\"svelte\"\s*:|\.svelte['\"]",
    "vite": r"\"vite\"\s*:", "tailwind": r"\"tailwindcss\"\s*:", "next": r"\"next\"\s*:|from\s+['\"]next/",
}

# An interactive full-screen terminal program (an editor, a viewer, a game), as opposed to a command run with flags.
_TUI = re.compile(r"tcsetattr\([^)]*\)|\bICANON\b|\binitscr\(|[<\"](n?curses)\.h[>\"]|^\s*import curses|"
                  r"tea\.NewProgram|\bratatui\b|crossterm::terminal|\btermbox|\burwid\b|from textual\b|"
                  r"require\(['\"]blessed['\"]\)|from ['\"]ink['\"]", re.M)


def _shallowest(names, base: str):
    hits = sorted((f for f in names if Path(f).name.lower() == base and not _NOT_OWN.search(f)), key=lambda f: f.count("/"))
    return hits[0] if hits else None


def shipped_as(files: Dict[str, str]):
    """What the repo's manifests say it ships: ('library' | 'command' | None, evidence)."""
    names = list(files)
    pkg = _shallowest(names, "package.json")
    if pkg:
        try:
            import json as _json
            d = _json.loads(files[pkg])
        except Exception:
            d = {}
        deps = {**(d.get("dependencies") or {}), **(d.get("devDependencies") or {})}
        if d.get("bin"):
            return "command", f"{pkg} declares a command (bin)"
        if (d.get("main") or d.get("exports") or d.get("module")) and not d.get("private") \
                and not any(k in deps for k in ("electron", "@tauri-apps/cli", "@tauri-apps/api", "next", "react-scripts")):
            return "library", f"{pkg} publishes a package (main/exports, no command, not private)"
    py = [f for f in ("pyproject.toml", "setup.py", "setup.cfg") if _shallowest(names, f)]
    if py:
        text = "\n".join(files[_shallowest(names, f)] for f in py)
        if re.search(r"\[project\.scripts\]|\[tool\.poetry\.scripts\]|console_scripts|\[project\.gui-scripts\]", text) or \
                any(Path(f).name == "__main__.py" and not _NOT_OWN.search(f) for f in names):
            return "command", f"{py[0]} declares a command (scripts / __main__)"
        if re.search(r"\bpackages\s*=|\[project\]|\[tool\.poetry\]|py_modules|find_packages", text):
            return "library", f"{py[0]} publishes a package with no command"
    cargo = _shallowest(names, "cargo.toml")
    if cargo:
        root = cargo.rsplit("/", 1)[0] + "/" if "/" in cargo else ""
        if "[[bin]]" in files[cargo] or f"{root}src/main.rs" in files:
            return "command", f"{cargo}: a binary (src/main.rs / [[bin]])"
        if f"{root}src/lib.rs" in files or re.search(r"^\[lib\]", files[cargo], re.M):
            return "library", f"{cargo}: a library crate ([lib] / src/lib.rs, no binary)"
    gomod = _shallowest(names, "go.mod")
    if gomod:
        if any(f.endswith(".go") and re.search(r"^package main\b", t, re.M) for f, t in files.items() if not _NOT_OWN.search(f)):
            return "command", "a Go program (package main)"
        return "library", f"{gomod}: a Go module with no program (no package main)"
    return None, ""


def extract_structural_signals(
    files: Dict[str, str],
    readme_raw: str = "",
    kind_hint: str = "",
) -> Dict[str, Any]:
    """Compute structural evidence counts across UI, CLI, mobile/IoT, game, media, and automation."""
    all_files = files
    files = {f: t for f, t in files.items() if not _NOT_OWN.search(f)}
    names = [f.lower() for f in files]
    bases = {Path(f).name.lower() for f in files}
    joined = " ".join(t[:2500].lower() for t in files.values())
    shipped, shipped_why = shipped_as(all_files)
    tui_markers = sorted({m.group(0).strip()[:24] for t in files.values() for m in [_TUI.search(t)] if m})
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
            "from 'commander'",
            'from "commander"',
            "require('commander')",
            'require("commander")',
            '"commander":',
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
    # v10.4: Python's argparse only when imported (a substring match read commander's own `argParser` as argparse)
    if "argparse" in cli_markers and not re.search(r"^\s*(import|from)\s+argparse\b", joined, re.M):
        cli_markers.remove("argparse")

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

    web_fw_markers = [m for m, pat in _WEB_FW.items() if re.search(pat, joined)]

    library_markers = [
        m
        for m in ("cmakelists.txt", "pyproject.toml", "setup.py", "cargo.toml", "package.json")
        if m in bases
    ]
    if any(f.endswith((".h", ".hpp", ".d.ts")) for f in names):
        library_markers.append("public_headers")
    if re.search(r"\b(library|sdk|parser|grammar|lexer|package|module|api)\b", readme_l):
        library_markers.append("library_readme")

    native_gui_markers = [
        m
        for m in (
            "imgui::", "imgui.h", "qapplication", "pyqt", "pyside", "tkinter",
            "customtkinter", "gtk_", "wxapp", "egui", "iced::", "swiftui",
            "avalonia", "winui", "lvgl", "sdl_createwindow", "glfwcreatewindow",
            "createwindowex",
        )
        if m in joined
    ]

    desktop_widget_markers = [
        m
        for m in (
            "shell_notifyicon", "qsystemtrayicon", "pystray", "nsstatusitem",
            "ws_ex_layered", "ws_ex_transparent", "[rainmeter]", "systemtray",
            "new tray(", "hwnd_topmost",
        )
        if m in joined
    ]

    plugin_host_markers = [
        m
        for m in (
            "addondefinition", "addonapi", "obs_module_load", "registerrender",
            "optionsrender", "bepinex", "skse",
        )
        if m in joined
    ]
    if "plugin.json" in bases:
        plugin_host_markers.append("plugin.json")

    trainer_save_markers = [
        m
        for m in (
            "writeprocessmemory", "readprocessmemory", "openprocess",
            "process_vm_writev", "save editor",
        )
        if m in joined
    ]

    has_any_gui = bool(ui_templates > 0 or native_gui_markers or desktop_widget_markers)

    # Determine universal Runtime Envelope
    if plugin_host_markers:
        runtime_envelope = "host_plugin_or_mod"
    elif desktop_widget_markers:
        runtime_envelope = "desktop_widget_or_tray"
    elif trainer_save_markers:
        runtime_envelope = "singleplayer_trainer_or_save_tool"
    elif game_markers and (has_game_terms or "pygame" in game_markers or "project.godot" in game_markers):
        runtime_envelope = "interactive_game_or_simulation"
    elif native_gui_markers:
        runtime_envelope = "native_gui_app"
    elif tui_markers and not cli_markers and shipped != "library":
        runtime_envelope = "interactive_terminal_app"
    elif ui_templates >= 1 or web_fw_markers:
        runtime_envelope = "web_app"
    elif cli_markers:
        runtime_envelope = "cli_or_automation"
    elif library_markers:
        runtime_envelope = "library_or_sdk"
    else:
        runtime_envelope = "unknown_or_general"

    scores: Dict[str, int] = {k: 0 for k in CANONICAL_PROFILES if k != "unknown_or_general"}

    # Library / SDK: packaging/headers/parser signals with NO GUI, NO CLI, NO plugin host, NO trainer
    if library_markers and not has_any_gui and not cli_markers and not mobile_iot_markers and not game_markers and not plugin_host_markers and not trainer_save_markers:
        scores["library_or_sdk"] += min(7, 2 * len(library_markers))
    if re.search(r"\b(c\+\+ library|python library|rust crate|typescript library|parser generator|grammar library|sdk)\b", readme_l) and not has_any_gui and not plugin_host_markers:
        scores["library_or_sdk"] += 3
    if ui_templates >= 2 or len(mobile_iot_markers) >= 2 or native_gui_markers or desktop_widget_markers or plugin_host_markers:
        scores["library_or_sdk"] = 0

    # v10.4: what the manifests say the repo ships outweighs words found in it
    if shipped == "library" and not has_any_gui and not plugin_host_markers:
        scores["library_or_sdk"] += 5
    if shipped == "command":
        scores["developer_tool_or_mcp"] += 3
        scores["library_or_sdk"] = max(0, scores["library_or_sdk"] - 3)

    # Developer Tool / CLI / MCP: strong CLI/MCP signals AND no native/web GUI surface.
    # v10.4: a package whose manifest declares no command is a library, even one for building CLIs (commander.js).
    if cli_markers and shipped != "library":
        scores["developer_tool_or_mcp"] += min(6, 2 * len(cli_markers))
    if re.search(r"\b(cli tool|command-line|mcp server|model context protocol)\b", readme_l):
        scores["developer_tool_or_mcp"] += 3
    if kind_hint in ("AI assistant plugin", "editor extension", "command-line tool"):
        scores["developer_tool_or_mcp"] += 3
    if ui_templates >= 2 or len(mobile_iot_markers) >= 2 or (has_any_gui and not cli_markers):
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
    structural_top = top_profile if top_score >= 2 else "unknown_or_general"
    confidence = "high" if (top_score >= 4 and (top_score - runner_up_score) >= 2) else "low"
    if runtime_envelope == "interactive_terminal_app" and not game_markers and top_score < 4:
        # A full-screen terminal program with no flag parser is used interactively: judged like an app, not a CLI.
        structural_top, confidence = "unknown_or_general", "high"

    return {
        "ui_template_files": ui_templates,
        "css_files": css_files,
        "cli_markers": cli_markers,
        "mobile_iot_markers": mobile_iot_markers,
        "game_markers": game_markers,
        "media_markers": media_markers,
        "automation_markers": automation_markers,
        "web_fw_markers": web_fw_markers,
        "native_gui_markers": native_gui_markers,
        "desktop_widget_markers": desktop_widget_markers,
        "plugin_host_markers": plugin_host_markers,
        "trainer_save_markers": trainer_save_markers,
        "tui_markers": tui_markers,
        "shipped_as": shipped,
        "shipped_evidence": shipped_why,
        "runtime_envelope": runtime_envelope,
        "candidate_scores": dict(ranked),
        "structural_top": structural_top,
        "structural_margin": top_score - runner_up_score,
        "structural_confidence": confidence,
    }


def resolve_project_profile(
    explicit_profile: Optional[str],
    signals: Dict[str, Any],
    llm_profile: Optional[str],
) -> Tuple[str, Dict[str, Any], str]:
    """Return (profile_key, profile_data, detection_method)."""
    profiles_map = load_project_profiles()

    explicit_key = normalize_profile_key(explicit_profile)
    if explicit_key:
        prof = profiles_map.get(explicit_key) or profiles_map.get("developer_tool_or_mcp", {})
        return explicit_key, prof, "explicit"

    llm_key = normalize_profile_key(llm_profile)
    top_key = str(signals.get("structural_top") or "unknown_or_general")
    confidence = signals.get("structural_confidence")

    # Guardrail: native GUI / desktop widget / host plugin UI apps with zero CLI markers must NEVER
    # be misrouted to cli_or_automation (developer_tool_or_mcp).
    has_non_cli_ui = bool(
        signals.get("native_gui_markers")
        or signals.get("desktop_widget_markers")
        or signals.get("plugin_host_markers")
    ) and not signals.get("cli_markers")
    if has_non_cli_ui and llm_key == "developer_tool_or_mcp":
        llm_key = (
            "interactive_game_or_simulation"
            if signals.get("game_markers")
            else "unknown_or_general"
        )

    def _profile_data_for(k: str) -> Dict[str, Any]:
        if k in profiles_map:
            return profiles_map[k]
        if k == "library_or_sdk":
            return profiles_map.get("developer_tool_or_mcp", {})
        return profiles_map.get("unknown_or_general", {})

    if confidence == "high" and (top_key in profiles_map or top_key == "library_or_sdk"):
        cand_scores = signals.get("candidate_scores") or {}
        if top_key == "unknown_or_general" and llm_key and cand_scores.get(llm_key, 0) < 3:
            return top_key, _profile_data_for(top_key), "structural_high_conf"
        if llm_key and (llm_key in profiles_map or llm_key == "library_or_sdk") and cand_scores.get(llm_key, 0) >= max(3, cand_scores.get(top_key, 0) - 1):
            return llm_key, _profile_data_for(llm_key), "structural+llm_tiebreak"
        return top_key, _profile_data_for(top_key), "structural_high_conf"

    if llm_key and (llm_key in profiles_map or llm_key == "library_or_sdk") and llm_key != "unknown_or_general":
        return llm_key, _profile_data_for(llm_key), "llm_arbitrated"

    if top_key in profiles_map or top_key == "library_or_sdk":
        return top_key, _profile_data_for(top_key), "structural_fallback"

    return "unknown_or_general", profiles_map.get("unknown_or_general", {}), "fallback"
