"""v10.4 end to end (1f): the whole engine on a realistic repo with a stand-in for the model.

The repo is a small notes app with real git history: its own code has one genuinely swallowed error next to an
expected one (missing settings file -> defaults) and an explained one, and it bundles a 40-file third-party library
(one bulk import) full of swallowed errors. The fake model answers every stage the way the real one does, including
a Functionality 100 with one weakness the code disproves and one it can't, and a false "needs work" claim.
Checks that the pieces work together: dependencies are never judged, intent-aware scanning, false claims dropped
before the grade, the 1d cap, and that the narrative is written from the same grade the report shows.
"""

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from letsvibe.core.ingest import RepositoryIngestor
from letsvibe.evaluator.classifier import Classification
from letsvibe.evaluator.pipeline import gather_metrics
from letsvibe_engine.versions import v10_4_verified as engine
from letsvibe_engine.versions.v10_4_verified import rubric

STORAGE = '''"""Saving and loading notes."""
import json
from pathlib import Path


def load_settings(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return {"theme": "dark"}  # first run: no settings file yet


def save(notes: list, path: Path) -> bool:
    if not isinstance(notes, list):
        raise ValueError("notes must be a list")
    try:
        path.write_text(json.dumps(notes))
        return True
    except OSError as exc:
        print(f"Could not save notes: {exc}")
        return False
'''

SERVER = '''"""Tiny notes server."""
from pathlib import Path

from app.storage import load_settings, save

NOTES: list = []


def add_note(text: str) -> dict:
    if not text.strip():
        return {"ok": False, "error": "A note can't be empty"}
    NOTES.append(text)
    ok = save(NOTES, Path("notes.json"))
    return {"ok": ok, "message": "Saved" if ok else "Not saved"}


def ping_analytics(event: str) -> None:
    try:
        import urllib.request
        urllib.request.urlopen("http://127.0.0.1:9/" + event, timeout=1)
    except Exception:
        pass


def close_socket(sock) -> None:
    try:
        sock.close()
    except OSError:
        pass  # already closed by the peer; nothing to clean up
'''

VENDOR = '''def helper_{i}(x):
    try:
        return int(x)
    except Exception:
        pass
'''

FALSE_CLAIM = "save() in app/storage.py has no error handling when writing the notes file"
VAGUE_CLAIM = "No offline mode for the notes list"
FALSE_NEEDS_WORK = "add_note in app/server.py doesn't validate empty input"


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@localhost", *args],
                   check=True, capture_output=True)


@pytest.fixture
def notes_app(tmp_path):
    root = tmp_path / "notes-app"
    (root / "app").mkdir(parents=True)
    (root / "README.md").write_text("# Notes app\n\nA tiny notes server: add a note, it is saved to notes.json.\n")
    (root / "app/__init__.py").write_text("")
    (root / "app/storage.py").write_text(STORAGE)
    (root / "app/server.py").write_text(SERVER)
    _git(root, "init", "-q")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "Notes app")
    lib = root / "vendor/minilib"
    lib.mkdir(parents=True)
    (lib / "LICENSE").write_text("MIT\n")
    for i in range(40):  # one bulk import of someone else's library, never touched again
        (lib / f"helpers_{i}.py").write_text(VENDOR.format(i=i))
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "Add minilib")
    return root


class FakeModel:
    """Stands in for llama-server: answers each stage by name, records what each stage was asked."""
    calls: list = []
    model = "fake-30b-a3b"

    def __init__(self, *args, **kwargs):
        FakeModel.calls = []

    def check_health(self):
        pass

    def summary(self):
        return {"calls": len(FakeModel.calls)}

    def generate_json(self, stage, system_prompt, user_prompt, **kwargs):
        FakeModel.calls.append((stage, user_prompt))
        if stage == "context_dossier":
            return {"purpose": "Save and list short notes", "project_profile": "gui_or_general"}
        if stage.startswith("batch_"):
            return {"findings": []}
        if stage.startswith("scoring_checklist"):
            return {
                "checklist": {
                    "value": {"tier": "TIER_3_GENUINE_GAP_OR_HOOK", "is_default_prompt_clone": False,
                              "verified_twists": ["a", "b", "c", "d"]},
                    "functionality": {"core_flow": "WORKS_END_TO_END", "features_connected": "CONNECTED",
                                      "tells_user_about_problems": "CLEARLY", "confirms_success": "CLEARLY"},
                    "creativity": {"depth_of_world_or_concept": "MODERATE", "has_distinct_voice": False,
                                   "mechanical_synergy": "SOME", "subverts_standard_ui": False},
                    "journey": {"launch_experience": "MANUAL_SETUP", "navigation_friction": "A_FEW_STEPS",
                                "setup_burden": "MODERATE", "state_and_save": "AUTO_SAVE",
                                "onboarding_and_controls_help": "NONE", "options_have_explanations": "FEW_OR_NONE",
                                "first_time_intuitiveness": "NEEDS_TRIAL_AND_ERROR", "hostile_monetization": False},
                    "ui_ux": {"clarity": "SOMEWHAT_CLEAR", "consistency": "MOSTLY", "feedback_while_working": "SOME",
                              "fits_its_device": "OK", "accessibility_labels": "FEW"},
                },
                "factors": {
                    "value": {"strengths": ["Solves a real need"], "weaknesses": []},
                    "creativity": {"strengths": [], "weaknesses": []},
                    "journey": {"strengths": [], "weaknesses": []},
                    "functionality": {"strengths": ["Notes save end to end"], "weaknesses": [FALSE_CLAIM, VAGUE_CLAIM]},
                    "ui_ux": {"strengths": [], "weaknesses": []},
                },
                "top_solid_features": ["Saving notes"],
                "top_features_needing_work": [FALSE_NEEDS_WORK, "Add search"],
                "pro_next_steps": ["Add search", "Add an offline mode"],
            }
        if stage == "narrative":
            return {"verdict_title": "Small and solid", "verdict_summary": "Works.", "peer_summary": "Nice.",
                    "reasoning": {c: "ok" for c in ("value", "creativity", "journey", "functionality", "ui_ux")}}
        raise AssertionError(f"unexpected stage {stage}")


def test_full_v10_4_run_on_a_realistic_repo(notes_app, tmp_path, monkeypatch):
    log_path = tmp_path / "engine.log"
    monkeypatch.setenv("LETSVIBE_ENGINE_LOG", "1")
    monkeypatch.setenv("LETSVIBE_ENGINE_LOG_PATH", str(log_path))
    monkeypatch.setattr(engine, "LlamaMoeClient", FakeModel)

    packed = RepositoryIngestor.ingest(str(notes_app), owned_code_v2=True)
    assert not any(f.startswith("vendor/") for f in packed.files)  # someone else's code isn't graded at all
    metrics, _ = gather_metrics(packed)
    report = engine.evaluate(SimpleNamespace(), packed, str(notes_app), metrics,
                             Classification(general_category="productivity", platforms=["web"]))
    stages = [s for s, _ in FakeModel.calls]
    assert stages[0] == "context_dossier" and "scoring_checklist" in stages and stages[-1] == "narrative"

    # 1a: the claim the code disproves is gone, from the factor and from "needs work"; the vague one stays
    func = report.factor_evaluations["functionality"]
    assert FALSE_CLAIM not in func.weaknesses and VAGUE_CLAIM in func.weaknesses
    assert FALSE_NEEDS_WORK not in report.top_features_needing_work and "Add search" in report.top_features_needing_work

    # 1d: 100 with one weakness left -> 95; a factor with nothing against it keeps its 100
    assert func.score == 95.0
    assert report.factor_evaluations["resonance"].score == 100.0

    # 1b + 1c + dependencies: only the app's own genuinely swallowed error counts
    ch = report.factor_evaluations["code_health"]
    swallowed = " ".join(w for w in ch.weaknesses if "swallowed" in w)
    assert "app/server.py" in swallowed and "vendor/" not in swallowed  # ping_analytics; not the library
    assert "storage.py" not in swallowed  # FileNotFoundError -> defaults is expected, not swallowed
    assert swallowed.count("app/server.py:") == 1  # close_socket's handler is explained by its comment

    # The total follows the capped factors, and the narrative was written from that same grade
    scores = {cat: report.factor_evaluations[fname].score for cat, fname in rubric.FACTOR_OF.items()}
    assert report.final_vibe_score == rubric.overall(scores)
    narrative_prompt = dict(FakeModel.calls)["narrative"]
    assert str(report.final_vibe_score) in narrative_prompt and report.letter_grade in narrative_prompt

    # Everything that was changed is in the grading log, with the reason
    log = log_path.read_text()
    assert "dropped claims the code disproves" in log and FALSE_CLAIM in log and FALSE_NEEDS_WORK in log
    assert "scores capped" in log and json.dumps("functionality") in log


class ForgetfulModel(FakeModel):
    """Leaves User Journey and UI/UX out of the scoring answer, as the real model did on VibeBuilder-IDE-public
    (and on tiki-karaoke and deciflux in production v10.3), and only gives them when asked for them alone."""
    answers_when_asked = True

    def generate_json(self, stage, system_prompt, user_prompt, **kwargs):
        if stage.startswith("scoring_checklist"):
            out = super().generate_json(stage, system_prompt, user_prompt, **kwargs)
            for c in ("journey", "ui_ux"):
                out["checklist"].pop(c)
                out["factors"].pop(c)
            return out
        if stage == "scoring_missing_sections":
            FakeModel.calls.append((stage, user_prompt))
            assert "journey" in user_prompt and "ui_ux" in user_prompt and "value," not in user_prompt.split("ONLY")[1]
            if not self.answers_when_asked:
                return {"checklist": {}, "factors": {}}
            return {"checklist": {"journey": {"launch_experience": "RUNS_IMMEDIATELY", "navigation_friction": "STRAIGHT_TO_CORE",
                                              "setup_burden": "NONE", "state_and_save": "AUTO_SAVE"},
                                  "ui_ux": {"clarity": "CLEAR", "consistency": "CONSISTENT"}},
                    "factors": {"journey": {"strengths": ["Starts at once"], "weaknesses": []},
                                "ui_ux": {"strengths": ["Clear"], "weaknesses": ["No dark mode"]}}}
        return super().generate_json(stage, system_prompt, user_prompt, **kwargs)


def _grade(notes_app, monkeypatch, model):
    monkeypatch.setattr(engine, "LlamaMoeClient", model)
    packed = RepositoryIngestor.ingest(str(notes_app), owned_code_v2=True)
    metrics, _ = gather_metrics(packed)
    return engine.evaluate(SimpleNamespace(), packed, str(notes_app), metrics,
                           Classification(general_category="productivity", platforms=["web"]))


def test_missing_sections_are_asked_for_not_graded_as_worst(notes_app, monkeypatch):
    report = _grade(notes_app, monkeypatch, ForgetfulModel)
    stages = [s for s, _ in FakeModel.calls]
    assert stages.count("scoring_missing_sections") == 1 and stages.index("scoring_missing_sections") < stages.index("narrative")
    journey, ui = report.factor_evaluations["user_journey"], report.factor_evaluations["ui_ux"]
    # scored from the answers given when asked (v10.3 would have scored them as if every answer were the worst)
    worst = _grade_worst(notes_app, monkeypatch)
    assert journey.score > worst["journey"] and ui.score > worst["ui_ux"]
    assert ui.weaknesses == ["No dark mode"] and journey.strengths == ["Starts at once"]


def _grade_worst(notes_app, monkeypatch):
    return {c: rubric.compute_all_scores(family="gui_or_general", checklist={}, hostile_found=[])[c] for c in ("journey", "ui_ux")}


def test_a_section_never_answered_stops_the_grading(notes_app, monkeypatch):
    class NeverAnswers(ForgetfulModel):
        answers_when_asked = False

    with pytest.raises(engine.IncompleteScoring, match="journey, ui_ux"):
        _grade(notes_app, monkeypatch, NeverAnswers)
