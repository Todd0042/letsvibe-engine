"""v10.4 1d: a factor can't be perfect while weaknesses are still listed against it, and the total follows.

Uses LetsVibe v10.3's real third report on VibeBuilder-IDE-public (Functionality 100 next to three weaknesses), and
v10.3's first report's false claims on a repo laid out like VibeBuilder (disproved weaknesses don't cost anything).
"""

from letsvibe_engine.versions.v10_4_verified import rubric, verify_and_cap
from test_v10_4_verify import REAL_FALSE, make_repo

# Third v10.3 report on VibeBuilder-IDE-public (27deb8c): scores and the model's weaknesses, as stored.
SCORES = {"value": 100.0, "creativity": 65.0, "journey": 92.0, "functionality": 100.0, "code_health": 60.5, "ui_ux": 95.0}
FACTORS = {
    "value": {"weaknesses": []},
    "creativity": {"weaknesses": []},
    "journey": {"weaknesses": []},
    "functionality": {"weaknesses": [
        "Missing error handling for WebSocket connection failures in PTY socket",
        "Missing error handling for file operations when server is unreachable during rename/delete",
        "Hardcoded 10-minute session timeout without user notification",
    ]},
    "ui_ux": {"weaknesses": [
        "Missing accessibility labels for interactive elements in UI components",
        "Inconsistent port forwarding error messages for busy ports",
    ]},
}


def test_perfect_score_with_weaknesses_is_capped_and_the_total_follows(tmp_path):
    repo = make_repo(tmp_path)
    scores = dict(SCORES)
    assert rubric.overall(scores) == 87.1  # what v10.3 reported
    verified, dropped, capped = verify_and_cap(scores, FACTORS, repo)
    assert dropped == []  # these are vague: nothing to disprove, all kept
    assert scores["functionality"] == 93.0  # 100 with 3 weaknesses -> 93
    assert scores["ui_ux"] == 94.0  # 95 with 2 weaknesses -> 94
    assert scores["value"] == 100.0  # nothing listed against it: stays perfect
    assert {c["factor"] for c in capped} == {"functionality", "ui_ux"}
    assert rubric.overall(scores) == 85.6
    assert verified["functionality"] == FACTORS["functionality"]["weaknesses"]


def test_disproved_weaknesses_cost_nothing(tmp_path):
    repo = make_repo(tmp_path)
    scores = dict(SCORES)
    factors = dict(FACTORS, functionality={"weaknesses": list(REAL_FALSE)}, ui_ux={"weaknesses": []})
    verified, dropped, capped = verify_and_cap(scores, factors, repo)
    assert len(dropped) == 2 and verified["functionality"] == []
    assert scores["functionality"] == 100.0 and capped == []  # both claims were false: the 100 stands


def test_caps(tmp_path):
    assert [rubric.cap_for_weaknesses(n) for n in range(8)] == [100, 95, 94, 93, 92, 91, 90, 90]
    scores = dict(SCORES, functionality=84.0)
    verify_and_cap(scores, FACTORS, make_repo(tmp_path))
    assert scores["functionality"] == 84.0  # already below the cap: unchanged
