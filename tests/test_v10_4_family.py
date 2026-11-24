"""v10.4 rubric family from evidence (plan item 2): the family picks the checklist questions, so a wrong one makes every
factor wrong. Real benchmark repos at their pinned commits (skipped if the store isn't cloned) plus the traps found
on night 1: licence text, docs templates, a library's own examples, a method named argParser.
"""

import contextlib
import io
import json
from pathlib import Path

import pytest

from letsvibe.core.ingest import RepositoryIngestor
from letsvibe_engine.versions.v10_4_verified import profile_detect as pd
from letsvibe_engine.versions.v10_4_verified import rubric

BENCH = Path.home() / "storage/letsvibe-benchmark/repos"
MIT = "Permission is hereby granted... THE SOFTWARE IS PROVIDED \"AS IS\", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED"


def family(files, model_says=None):
    sig = pd.extract_structural_signals(files)
    key, _, how = pd.resolve_project_profile(None, sig, model_says)
    return rubric.rubric_family_for_profile(key), sig


def every_answer(files):
    """The family whatever the model suggests."""
    return {family(files, k)[0] for k in pd.CANONICAL_PROFILES}


# ---- the real repos -----------------------------------------------------------------------------

@pytest.mark.parametrize("repo,expected", [
    ("requests", "library_or_sdk"),         # night 1: a GUI app (docs theme licence said "flask"/"express")
    ("commander.js", "library_or_sdk"),     # night 1: a CLI tool (its own examples use commander)
    ("kilo", "gui_or_general"),             # night 1: a CLI tool; it is a full-screen editor
    ("glow", "cli_or_automation"),          # cobra commands + a TUI: still a command
    ("pipreqs", "cli_or_automation"),
    ("winnow-grammar", "library_or_sdk"),
    ("VibeBuilder-IDE-public", "gui_or_general"),
    ("full-stack-fastapi-template", "gui_or_general"),
])
def test_real_repos_whatever_the_model_says(repo, expected):
    if not (BENCH / repo).exists():
        pytest.skip("benchmark store not cloned")
    with contextlib.redirect_stdout(io.StringIO()):
        files = RepositoryIngestor.ingest(str(BENCH / repo), owned_code_v2=True).files
    assert every_answer(files) == {expected}


# ---- the traps ----------------------------------------------------------------------------------

def test_licence_and_docs_are_not_evidence():
    files = {"LICENSE": MIT, "docs/_themes/LICENSE": "Flask theme. " + MIT, "docs/_templates/sidebar.html": "<div></div>",
             "pyproject.toml": "[project]\nname = 'httpthing'\n", "src/httpthing/__init__.py": "def get(url):\n    return url\n"}
    fam, sig = family(files)
    assert sig["web_fw_markers"] == [] and sig["ui_template_files"] == 0
    assert fam == "library_or_sdk" and "no command" in sig["shipped_evidence"]


def test_a_library_for_building_clis_is_a_library():
    files = {"package.json": json.dumps({"name": "flagkit", "main": "./index.js", "exports": {".": "./index.js"}}),
             "lib/command.js": "class Command { argParser(fn) { this._parse = fn; } }\n",
             "examples/demo.js": "const { program } = require('commander');\nprogram.parse();\n"}
    assert every_answer(files) == {"library_or_sdk"}


def test_a_private_web_app_with_main_is_not_a_library():
    files = {"package.json": json.dumps({"name": "shop", "private": True, "main": "server.js",
                                         "dependencies": {"express": "^4", "react": "^18"}}),
             "server.js": "const express = require('express');\nexpress().listen(3000);\n",
             "src/App.jsx": "import React from 'react';\nexport default () => <main/>;\n"}
    fam, sig = family(files)
    assert sig["shipped_as"] is None and fam == "gui_or_general" and "express" in sig["web_fw_markers"]


def test_a_command_declared_in_the_manifest_is_a_cli():
    files = {"pyproject.toml": "[project]\nname = 'tidy'\n[project.scripts]\ntidy = 'tidy.cli:main'\n",
             "tidy/cli.py": "import argparse\n\ndef main():\n    argparse.ArgumentParser().parse_args()\n"}
    assert every_answer(files) == {"cli_or_automation"}


def test_full_screen_terminal_program_is_judged_as_an_app():
    files = {"Makefile": "all:\n\tcc -o ed ed.c\n",
             "ed.c": "#include <termios.h>\nint main(void){ struct termios t; t.c_lflag &= ~(ECHO|ICANON);\n"
                     "tcsetattr(0, TCSAFLUSH, &t); return 0; }\n"}
    assert every_answer(files) == {"gui_or_general"}
    # with a flag parser it is a command that happens to draw (glow)
    files["main.go"] = 'package main\nvar root = &cobra.Command{Use: "ed"}\nfunc main(){ tea.NewProgram(m).Run() }\n'
    files["go.mod"] = "module ed\n"
    assert family(files)[0] == "cli_or_automation"
