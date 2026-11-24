"""v10.4 plan 3: checklist answers that break a pairing the prompt states are made consistent (and logged)."""

import copy

from letsvibe_engine.versions.v10_4_verified import rubric


def value(tier, clone, twists=("a", "b")):
    return {"value": {"tier": tier, "is_default_prompt_clone": clone, "verified_twists": list(twists)}}


def test_clone_with_tier_2_becomes_tier_1_and_scores_the_same():
    # kilo / sunflower / the fastapi template on the 2026-11 benchmark
    cl = value("TIER_2_ITERATIVE_NICHE", True)
    before = rubric.score_category("value", "gui_or_general", copy.deepcopy(cl["value"]), [])
    changes = rubric.resolve_contradictions(cl)
    assert cl["value"]["tier"] == "TIER_1_GENERIC_CLONE"
    assert changes and "TIER_1_GENERIC_CLONE only" in changes[0]["rule"]
    assert rubric.score_category("value", "gui_or_general", cl["value"], []) == before  # the report stops contradicting itself


def test_consistent_answers_are_left_alone():
    for tier, clone in (("TIER_1_GENERIC_CLONE", True), ("TIER_2_ITERATIVE_NICHE", False),
                        ("TIER_3_GENUINE_GAP_OR_HOOK", False), ("TIER_0_BROKEN_OR_SHELL", True), ("TIER_1_GENERIC_CLONE", False)):
        cl = value(tier, clone)
        assert rubric.resolve_contradictions(cl) == [] and cl == value(tier, clone)
