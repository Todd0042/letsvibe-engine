"""v10.4 Code Health: findings judged by density (per 1,000 lines) on a smooth curve, no hard caps."""

from types import SimpleNamespace

from letsvibe_engine.versions.v10_4_verified import rubric as r104
from letsvibe_engine.versions.v10_3_calibrated import rubric as r103


def metrics(loc):
    return SimpleNamespace(avg_cyclomatic_complexity=3.5, max_cyclomatic_complexity=18, total_loc=loc)


def swallowed(n):
    return [{"kind": "swallowed error", "file": f"app/m{i}.py", "line": 10 + i} for i in range(n)]


def test_same_habits_score_alike_at_any_size():
    small = r104.score_code_health(metrics(2_000), swallowed(4))[0]  # 2 per 1,000 lines
    large = r104.score_code_health(metrics(40_000), swallowed(80))[0]  # 2 per 1,000 lines
    assert abs(small - large) < 0.5
    # v10.3 capped counts: 80 swallowed errors in 40k lines cost the same as 6 anywhere.
    assert r103.score_code_health(metrics(40_000), swallowed(80))[0] == r103.score_code_health(metrics(600), swallowed(6))[0]


def test_every_fix_moves_the_score():
    scores = [r104.score_code_health(metrics(8_000), swallowed(n))[0] for n in (40, 30, 20, 10, 0)]
    assert scores == sorted(scores) and len(set(scores)) == len(scores), scores  # strictly better with each fix
    # In v10.3 the first fixes past the cap changed nothing.
    assert r103.score_code_health(metrics(8_000), swallowed(40))[0] == r103.score_code_health(metrics(8_000), swallowed(10))[0]


def test_weaknesses_say_where_to_fix():
    weaknesses = r104.score_code_health(metrics(5_000), swallowed(7))[3]
    line = next(w for w in weaknesses if "swallowed" in w)
    assert "1.4 per 1,000 lines" in line and "app/m0.py:10" in line and "(+4 more)" in line
