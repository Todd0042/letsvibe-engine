"""Unit tests for Engine v10.1 profile detection and adaptive discrete scoring."""

from letsvibe_engine.versions.v10_1_adaptive import profile_detect, rubric


def test_cli_tool_detected_accurately():
    files = {
        "pyproject.toml": "[project.scripts]\nmycli = 'mycli.main:cli'\n",
        "mycli/main.py": "import argparse\nparser = argparse.ArgumentParser()\n",
    }
    signals = profile_detect.extract_structural_signals(files, readme_raw="A fast CLI tool for devs.")
    key, _, method = profile_detect.resolve_project_profile("auto", signals, "web_productivity_app")
    assert key == "developer_tool_or_mcp"
    assert rubric.rubric_family_for_profile(key) == "cli_or_automation"
    assert method == "structural_high_conf"


def test_web_app_with_cli_script_not_misclassified_as_cli():
    files = {
        "pyproject.toml": "[project.scripts]\nwebapp = 'app.server:main'\n",
        "app/server.py": "from fastapi import FastAPI\napp = FastAPI()\n",
        "app/templates/index.html": "<html><body>Dashboard</body></html>",
        "app/templates/settings.html": "<html><body>Settings</body></html>",
        "app/static/app.css": "body { color: #fff; }",
    }
    signals = profile_detect.extract_structural_signals(files, readme_raw="A web dashboard and tracker.")
    key, _, _ = profile_detect.resolve_project_profile("auto", signals, "web_productivity_app")
    assert key == "web_productivity_app"
    assert rubric.rubric_family_for_profile(key) == "gui_or_general"


def test_mobile_android_app_detected_accurately():
    files = {
        "AndroidManifest.xml": "<manifest package='com.example.deciflux'/>",
        "app/src/main/java/MainActivity.kt": "import androidx.compose.runtime.Composable\n",
    }
    signals = profile_detect.extract_structural_signals(files, readme_raw="Android app for audio.")
    key, _, _ = profile_detect.resolve_project_profile("auto", signals, "hardware_iot_or_mobile")
    assert key == "hardware_iot_or_mobile"


def test_explicit_profile_overrides_auto():
    files = {"app.py": "print('hello')"}
    signals = profile_detect.extract_structural_signals(files)
    key, _, method = profile_detect.resolve_project_profile("cli_or_utility", signals, "web_productivity_app")
    assert key == "developer_tool_or_mcp"
    assert method == "explicit"


def test_cli_adaptive_scoring_gives_full_credit_for_strong_cli():
    checklist = {
        "value": {
            "tier": "TIER_3_GENUINE_GAP_OR_HOOK",
            "is_default_prompt_clone": False,
            "verified_twists": ["zero-config", "streaming pipe"],
        },
        "functionality": {
            "core_flow": "WORKS_END_TO_END",
            "features_connected": "CONNECTED",
            "tells_user_about_problems": "CLEARLY",
            "confirms_success": "CLEARLY",
        },
        "creativity": {
            "has_distinct_voice_or_craft": True,
            "clever_workflow_or_abstraction": True,
            "concept_depth": "DISTINCTIVE",
            "mechanical_synergy": True,
        },
        "ui_ux": {
            "help_and_flag_clarity": "CLEAR",
            "output_and_error_quality": "CLEAR",
            "composability_and_exit_codes": "WELL",
            "defaults_and_safety": "GOOD",
        },
        "journey": {
            "launch_experience": "ONE_STEP_INSTALL",
            "invocation_friction": "ONE_COMMAND",
            "setup_burden": "NONE",
            "state_and_config": "AUTO_OR_STATELESS",
            "hostile_monetization": False,
        },
    }
    scores = rubric.compute_all_scores("cli_or_automation", checklist, hostile_found=[])
    assert scores["ui_ux"] == 100.0
    assert scores["creativity"] == 100.0
    assert scores["functionality"] == 100.0
    assert scores["value"] == 90.0
    assert scores["journey"] == 93.0
    assert rubric.overall(scores) == 95.6
