"""v10.4 code facts: the model's "there is no X" claims and checklist answers, checked against the code.

Real cases from the first benchmark night (kilo and pipreqs at their pinned commits; skipped if the store isn't
cloned): what must be corrected, and the true claims next to them that must stay.
"""

import copy
import io
import contextlib
from pathlib import Path

import pytest

from letsvibe.core.ingest import RepositoryIngestor
from letsvibe_engine.versions.v10_4_verified import facts, rubric, verify

BENCH = Path.home() / "storage/letsvibe-benchmark/repos"
CLI = rubric.FAMILY_POINTS["cli_or_automation"]


def index(name: str) -> verify.RepoIndex:
    with contextlib.redirect_stdout(io.StringIO()):
        packed = RepositoryIngestor.ingest(str(BENCH / name), owned_code_v2=True)
    return verify.RepoIndex(BENCH / name, files=list(packed.files))


needs = lambda name: pytest.mark.skipif(not (BENCH / name).exists(), reason="benchmark store not cloned")


@needs("kilo")
def test_kilo_false_claims_dropped_true_ones_kept():
    repo = index("kilo")
    for claim in ("No file saving or persistence features",          # editorSave(), Ctrl-S
                  "Missing error handling for file open (kilo.c line 392)",  # fopen at 806 is checked
                  "No error messages for failed operations"):          # "Can't save! I/O error: ..."
        assert verify.check_claim(claim, repo) is not None, claim
    for claim in ("No memory allocation failure checks (kilo.c line 285)",           # true: malloc isn't checked
                  "No error handling for core operations (file open, memory alloc)",  # half true: stays
                  "No unique features beyond standard editor functionality"):        # a judgement: not ours to drop
        assert verify.check_claim(claim, repo) is None, claim


@needs("kilo")
def test_kilo_checklist_raised_only_where_code_shows_it():
    checklist = {"ui_ux": {"help_and_flag_clarity": "CLUTTERED_OR_UNDOCUMENTED", "output_and_error_quality": "OPAQUE",
                           "composability_and_exit_codes": "POORLY", "defaults_and_safety": "BASIC"},
                 "functionality": {"core_flow": "MOSTLY_WORKS", "tells_user_about_problems": "NOT_SHOWN"},
                 "value": {"tier": "TIER_2_ITERATIVE_NICHE", "is_default_prompt_clone": True}}
    before = copy.deepcopy(checklist)
    fixed = {(c.category, c.field): c for c in facts.correct_checklist(checklist, CLI, index("kilo"))}
    assert checklist["ui_ux"]["help_and_flag_clarity"] == "CLEAR"  # no flags; usage + keys on screen
    assert checklist["ui_ux"]["output_and_error_quality"] == "SOME"  # error messages exist; "clear" is the model's call
    assert checklist["functionality"]["tells_user_about_problems"] == "SOMETIMES"
    assert "kilo.c:" in fixed[("ui_ux", "help_and_flag_clarity")].evidence
    # untouched: things code can't settle
    for cat, fld in (("ui_ux", "composability_and_exit_codes"), ("functionality", "core_flow"), ("value", "is_default_prompt_clone")):
        assert checklist[cat][fld] == before[cat][fld]


@needs("pipreqs")
def test_pipreqs_documented_flags():
    repo = index("pipreqs")
    checklist = {"ui_ux": {"help_and_flag_clarity": "CLUTTERED_OR_UNDOCUMENTED"},
                 "journey": {"options_have_explanations": "FEW_OR_NONE"}}
    facts.correct_checklist(checklist, CLI, repo)
    assert checklist == {"ui_ux": {"help_and_flag_clarity": "CLEAR"}, "journey": {"options_have_explanations": "ALL_OR_MOST"}}
    assert verify.check_claim("No CLI flag documentation or help strings", repo) is not None
    assert verify.check_claim("Missing error handling for file open operations", repo) is None  # 17 opens unchecked


def test_answers_are_never_lowered(tmp_path):
    (tmp_path / "cli.py").write_text("import argparse\np = argparse.ArgumentParser()\np.add_argument('--x')\n"
                                     "p.add_argument('--y')\np.add_argument('--z', help='zed')\n")
    repo = verify.RepoIndex(tmp_path, files=["cli.py"])
    checklist = {"ui_ux": {"help_and_flag_clarity": "CLEAR"}, "journey": {"options_have_explanations": "ALL_OR_MOST"}}
    assert facts.correct_checklist(checklist, CLI, repo) == []
    assert checklist["ui_ux"]["help_and_flag_clarity"] == "CLEAR"
    # two of three flags have no help: "undocumented" is not disproved
    assert verify.check_claim("No help text for CLI flags", repo) is None


# ---- app / game families (plan 2 graded kilo as an app: different questions) ---------------------------------------

APP = rubric.FAMILY_POINTS["gui_or_general"]


@needs("kilo")
def test_kilo_as_an_app():
    repo = index("kilo")
    checklist = {"ui_ux": {"feedback_while_working": "NONE", "accessibility_labels": "NONE"},
                 "journey": {"onboarding_and_controls_help": "NONE", "state_and_save": "NOT_NEEDED"}}
    facts.correct_checklist(checklist, APP, repo)
    assert checklist["ui_ux"]["feedback_while_working"] == "SOME"            # "N bytes written", "Can't save! ..."
    assert checklist["journey"]["onboarding_and_controls_help"] == "BASIC"   # HELP: Ctrl-S = save | Ctrl-Q = quit
    assert checklist["journey"]["state_and_save"] == "NOT_NEEDED"            # never lowered (scores above MANUAL_SAVE here)
    assert checklist["ui_ux"]["accessibility_labels"] == "NONE"              # nothing in code says otherwise
    assert verify.check_claim("No visual feedback for user actions", repo) is not None
    assert verify.check_claim("No onboarding or tutorials provided", repo) is None  # true: there is no tutorial


def test_bundled_libraries_and_tooling_are_not_the_program(tmp_path):
    (tmp_path / "js").mkdir()
    (tmp_path / "js" / "engine-min.js").write_text("localStorage.setItem('k',1);fs.writeFileSync('a','b');\n")
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools" / "flash.sh").write_text('echo "Flashed! Starting monitor (Ctrl+C to exit)..."\n')
    (tmp_path / "game.js").write_text("function tick(){ draw(); }\n")
    repo = verify.RepoIndex(tmp_path, files=["js/engine-min.js", "tools/flash.sh", "game.js"])
    game = rubric.FAMILY_POINTS["game_or_sim"]
    checklist = {"journey": {"state_and_save": "NOT_NEEDED", "onboarding_and_controls_help": "NONE"}}
    assert facts.correct_checklist(checklist, game, repo) == []


@needs("letsvibe-good")
def test_missing_file_handled_at_load():
    repo = index("letsvibe-good")
    # store.py:33 `if not self.path.exists()`; the claim cites the wrong file and line
    assert verify.check_claim("No error handling for missing data file on first run (fairshare.py line 25)", repo) is not None
    assert verify.check_claim("No validation for empty chore list in setup (server.py line 102)", repo) is None  # not ours


@needs("taxonomy")
def test_loading_screens_are_feedback():
    repo = index("taxonomy")
    table = rubric.FAMILY_POINTS["gui_or_general"]
    checklist = {"ui_ux": {"feedback_while_working": "NOT_SHOWN", "clarity": "CLUTTERED_OR_TECHNICAL"}}
    facts.correct_checklist(checklist, table, repo)
    assert checklist["ui_ux"] == {"feedback_while_working": "SOME", "clarity": "CLUTTERED_OR_TECHNICAL"}
    assert verify.check_claim("Missing loading states for contentlayer data fetching", repo) is None  # names more: stays
