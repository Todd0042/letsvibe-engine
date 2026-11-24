"""v10.4 Code Health: findings judged by density (per 1,000 lines) on a smooth curve, no hard caps."""

from types import SimpleNamespace

from letsvibe_engine.versions.v10_4_verified import rubric as r104
from letsvibe_engine.versions.v10_3_calibrated import rubric as r103


def metrics(loc):
    return SimpleNamespace(avg_cyclomatic_complexity=3.5, max_cyclomatic_complexity=18, total_loc=loc)


def swallowed(n):
    return [{"kind": "swallowed error", "file": f"app/m{i}.py", "line": 10 + i} for i in range(n)]


def test_same_habits_score_alike_at_any_size():
    mid = r104.score_code_health(metrics(10_000), swallowed(20))[0]  # 2 per 1,000 lines
    large = r104.score_code_health(metrics(40_000), swallowed(80))[0]  # 2 per 1,000 lines
    assert abs(mid - large) < 0.5
    # a small repo is judged on few findings, so it gets a little benefit of the doubt, never much
    small = r104.score_code_health(metrics(2_000), swallowed(4))[0]
    assert 0 < small - large < 2.5
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


def oversized(files, funcs):
    return [{"kind": "oversized file", "file": f"f{i}.c"} for i in range(files)] + \
           [{"kind": "oversized function", "file": "f0.c", "line": 10 * i} for i in range(funcs)]


def test_one_big_file_does_not_sink_a_small_program():
    # kilo: a 1,355-line editor in one file, 6 long functions, Avg CCN 7.8, Max CCN 36 (v10.4 night 1: 57.3; v10.3: 85.1)
    m = SimpleNamespace(avg_cyclomatic_complexity=7.8, max_cyclomatic_complexity=36, total_loc=1355)
    score, _, _, weaknesses = r104.score_code_health(m, oversized(1, 6))
    assert 70 <= score <= 80
    # all three problems are still named
    assert any("Avg CCN" in w for w in weaknesses) and any("oversized file" in w for w in weaknesses) \
        and any("oversized/complex function" in w for w in weaknesses)


def test_complex_functions_are_counted_once():
    # CCN and "oversized/complex functions" describe the same functions: together they cost the larger, not the sum
    m = SimpleNamespace(avg_cyclomatic_complexity=7.8, max_cyclomatic_complexity=36, total_loc=20_000)
    only_ccn = r104.score_code_health(m, [])[0]
    with_funcs = r104.score_code_health(m, oversized(0, 6))[0]
    many_funcs = r104.score_code_health(m, oversized(0, 200))[0]
    alone = 100 - r104.score_code_health(SimpleNamespace(avg_cyclomatic_complexity=3, max_cyclomatic_complexity=10,
                                                         total_loc=20_000), oversized(0, 6))[0]
    assert 0 < only_ccn - with_funcs < alone / 2  # the same functions aren't charged twice ...
    assert many_funcs < with_funcs  # ... but every fix still moves the score
