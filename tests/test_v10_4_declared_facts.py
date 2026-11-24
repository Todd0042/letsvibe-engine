"""v10.4 1g-1j: platforms from what the repo declares, precise secret findings, a clear app-type match only.

Every check runs the old behaviour too: production engines (v10.3 and older) must get exactly what they got before.
The real case is VibeBuilder-IDE-public at the commit its report graded (benchmark store; skipped if not cloned).
"""

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from letsvibe.analyzers.security import SecurityAnalyzer
from letsvibe.core.platforms import detect_platforms
from letsvibe_engine.versions import v10_4_verified as engine

BENCH = Path.home() / "storage/letsvibe-benchmark/repos"


def make_repo(root: Path, files: dict) -> Path:
    for rel, body in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)
    return root


TAURI_PKG = json.dumps({"name": "app", "scripts": {"build": "vite build", "tauri": "tauri"},
                        "devDependencies": {"vite": "^5", "@tauri-apps/cli": "^2"}})


def tauri_conf(targets) -> str:
    return json.dumps({"productName": "App", "bundle": {"active": True, "targets": targets}})


# ---- 1g platforms ---------------------------------------------------------------------------------

def test_tauri_app_builds_only_what_it_declares(tmp_path):
    root = make_repo(tmp_path, {"desktop/package.json": TAURI_PKG, "desktop/src-tauri/tauri.conf.json": tauri_conf(["appimage", "deb", "rpm"]),
                                "desktop/src/main.ts": "console.log('hi')\n"})
    assert detect_platforms(root).platforms == ["windows", "macos", "linux", "web"]  # unchanged for old engines
    new = detect_platforms(root, declared_targets=True)
    assert new.platforms == ["linux"], new.signals
    assert "web" not in new.platforms  # the app's own UI build is not a website


def test_tauri_targets_all_or_missing_means_every_desktop(tmp_path):
    root = make_repo(tmp_path, {"package.json": TAURI_PKG, "src-tauri/tauri.conf.json": tauri_conf("all")})
    assert detect_platforms(root, declared_targets=True).platforms == ["windows", "macos", "linux"]


def test_tauri_mobile_android_sources_are_android(tmp_path):
    root = make_repo(tmp_path, {
        "desktop/package.json": TAURI_PKG, "desktop/src-tauri/tauri.conf.json": tauri_conf(["appimage"]),
        "mobile/package.json": TAURI_PKG,
        "mobile/src-tauri/android/MainActivity.kt": "package app\nimport android.os.Bundle\nclass MainActivity : TauriActivity()\n",
    })
    assert "android" not in detect_platforms(root).platforms
    assert detect_platforms(root, declared_targets=True).platforms == ["linux", "android"]


def test_a_real_website_is_still_web(tmp_path):
    root = make_repo(tmp_path, {"frontend/package.json": json.dumps({"devDependencies": {"vite": "^5"}}),
                                "backend/main.py": "from fastapi import FastAPI\napp = FastAPI()\n"})
    assert detect_platforms(root, declared_targets=True).platforms == ["web"]


def test_plain_python_cli_is_every_desktop(tmp_path):
    root = make_repo(tmp_path, {"cli.py": "import argparse\nprint(argparse.ArgumentParser().parse_args())\n"})
    assert detect_platforms(root, declared_targets=True).platforms == ["windows", "macos", "linux"]


def test_sphinx_docs_builder_is_not_a_windows_app(tmp_path):
    root = make_repo(tmp_path, {"lib/core.py": "def f():\n    return 1\n", "docs/make.bat": "@ECHO OFF\nsphinx-build\n"})
    assert detect_platforms(root).platforms == ["windows"]  # what production said for requests/pipreqs
    assert detect_platforms(root, declared_targets=True).platforms == ["windows", "macos", "linux"]


def test_code_that_handles_windows_explicitly_is_cross_platform(tmp_path):
    root = make_repo(tmp_path, {"proxy.py": "import sys\nif sys.platform == 'win32':\n    import winreg\n"})
    assert detect_platforms(root, declared_targets=True).platforms == ["windows", "macos", "linux"]


def test_posix_terminal_c_program_is_linux_and_macos(tmp_path):
    root = make_repo(tmp_path, {"kilo.c": "#include <termios.h>\n#include <unistd.h>\nint main(void){return 0;}\n"})
    assert detect_platforms(root).platforms == ["windows", "macos", "linux"]
    assert detect_platforms(root, declared_targets=True).platforms == ["macos", "linux"]


def test_linux_service_code_is_linux(tmp_path):
    root = make_repo(tmp_path, {"daemon.py": "import subprocess\nsubprocess.run(['systemctl', '--user', 'restart', 'x'])\n"})
    assert detect_platforms(root, declared_targets=True).platforms == ["linux"]


# ---- 1i secrets ------------------------------------------------------------------------------------

SECRET_FILES = {
    "client-state/editors.svelte.ts": "export interface Handle {\n  exec(cmd: EditorCommand): void;\n}\n",
    "server/problems.py": 'def hide(m):\n    return m.group(0) + "…"  # keep "password=", hide the value\n\nNAME = "x"\n',
    "emails/new_account.tsx": 'export const Email = ({\n  password = "{{ password }}",\n}) => null\n',
    "js/engine-min.js": "var a=1;eval(a);\n",
}


def test_old_rules_unchanged():
    n, _ = SecurityAnalyzer.scan(SECRET_FILES)
    assert n == 4  # exec declaration, comment spanning lines, template placeholder, vendored eval


def test_precise_rules_drop_the_false_alarms():
    assert SecurityAnalyzer.scan(SECRET_FILES, precise=True) == (0, [])


def test_precise_rules_still_catch_real_problems():
    files = {**SECRET_FILES,
             "app/config.py": 'DB_USER = "admin"\npassword = "hunter2-correct-horse"\n',
             "app/calc.py": "def run(user_input):\n    return eval(user_input)\n"}
    n, findings = SecurityAnalyzer.scan(files, precise=True)
    assert n == 2
    assert any("Hardcoded Password" in f for f in findings) and any("eval()" in f for f in findings)


# ---- 1h app type -----------------------------------------------------------------------------------

@pytest.mark.parametrize("top,clear", [
    ([{"archetype": "Flappy Bird clone", "similarity": 0.704}, {"archetype": "Idle game", "similarity": 0.548}], True),
    ([{"archetype": "Translator", "similarity": 0.596}, {"archetype": "Web scraper", "similarity": 0.572}], False),
    ([{"archetype": "AI image generator front end", "similarity": 0.63}, {"archetype": "Code editor", "similarity": 0.62}], False),
    ([], False),
])
def test_app_type_used_only_for_a_clear_match(top, clear):
    assert engine.cliche_is_clear(top) is clear


# ---- wiring + the real repo ----------------------------------------------------------------------

class Log:
    def __init__(self):
        self.steps = []

    def step(self, name, value):
        self.steps.append((name, str(value)))


def test_engine_applies_declared_facts_and_logs_why(tmp_path):
    root = make_repo(tmp_path, {"package.json": TAURI_PKG, "src-tauri/tauri.conf.json": tauri_conf(["deb"]),
                                **SECRET_FILES})
    files = {k: (root / k).read_text() for k in SECRET_FILES}
    cls = SimpleNamespace(platforms=["windows", "macos", "linux", "web"], device_profile="")
    metrics = SimpleNamespace(detected_secrets_count=4, secret_findings=["x"])
    log = Log()
    engine.apply_declared_facts(SimpleNamespace(source_path=str(root), files=files), metrics, cls, log)
    assert cls.platforms == ["linux"] and metrics.detected_secrets_count == 0
    assert any(n == "platforms" and "declared targets: linux" in v for n, v in log.steps)
    assert any(n == "secrets" and "4 -> 0" in v for n, v in log.steps)


@pytest.mark.skipif(not (BENCH / "VibeBuilder-IDE-public").exists(), reason="benchmark store not cloned")
def test_vibebuilder_at_its_graded_commit():
    root = BENCH / "VibeBuilder-IDE-public"
    assert subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip() \
        == "e2fa52ad6e9b30e49e4ee6a8281d5f641b0fb1ad"
    files = {}
    for f in subprocess.run(["git", "-C", str(root), "ls-files"], capture_output=True, text=True).stdout.split():
        if (root / f).is_file():
            files[f] = (root / f).read_text(errors="ignore")
    # production: what the published report says
    assert detect_platforms(root).platforms == ["windows", "macos", "linux", "web"]
    assert SecurityAnalyzer.scan(files)[0] == 2
    # v10.4: what the project really is
    assert detect_platforms(root, declared_targets=True).platforms == ["linux", "android"]
    assert SecurityAnalyzer.scan(files, precise=True) == (0, [])
