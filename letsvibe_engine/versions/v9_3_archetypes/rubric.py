"""
Stage 3: rubric passes on the dossier. Three separate passes (value, creativity, journey), each answered with fixed
choices and 1-3 exact quotes from the dossier; Python checks each quote. The model never sees code and never picks a
number: scoring.py turns the answers into points.
"""
import re
from typing import Any, Callable, Dict, Optional, Tuple

_S = {"type": "string"}
_EV = {"type": "array", "items": _S, "maxItems": 3}


def _field(kind):
    return {"type": "object", "properties": {"answer": kind, "evidence": _EV}, "required": ["answer", "evidence"]}


def _enum(*vals):
    return {"type": "string", "enum": list(vals)}


PASSES: Dict[str, Dict[str, Any]] = {
    "value": {
        "intro": "Judge only the REAL-WORLD VALUE of this app, compared with the many similar apps people build from a single prompt.",
        "fields": {
            "identified_archetype": {"type": "object", "properties": {"answer": _S, "evidence": _EV}, "required": ["answer", "evidence"]},
            "is_default_prompt_clone": _field({"type": "boolean"}),
            "specific_twists": {"type": "array", "maxItems": 4, "items": {"type": "object", "properties": {"twist": _S, "evidence": _EV},
                                                                         "required": ["twist", "evidence"]}},
            "tier": _field(_enum("TIER_0_BROKEN_OR_SHELL", "TIER_1_GENERIC_CLONE", "TIER_2_ITERATIVE_NICHE", "TIER_3_GENUINE_GAP_OR_HOOK")),
        },
        "questions": """identified_archetype: what is this app at its core, in a few words?
is_default_prompt_clone: true if a user could get 90% of this exact app from one two-sentence prompt (like "make me a space shooter" or "make a budget tracker"); false if it clearly goes beyond that.
specific_twists: concrete features in the dossier that go beyond the basic archetype (empty list if none).
tier: TIER_0_BROKEN_OR_SHELL = placeholders or mock data, doesn't really work. TIER_1_GENERIC_CLONE = works, but a standard version of a common idea. TIER_2_ITERATIVE_NICHE = a common idea adapted for a specific niche or with a cohesive twist. TIER_3_GENUINE_GAP_OR_HOOK = solves a real problem that existing free tools overcomplicate, or has an entertainment loop that keeps a player hooked past 5 minutes.""",
    },
    "creativity": {
        "intro": "Judge only CREATIVITY. Ignore how the code is written. Judge only the human-facing design, narrative voice and interaction flow.",
        "fields": {
            "has_distinct_voice": _field({"type": "boolean"}),
            "subverts_standard_ui": _field({"type": "boolean"}),
            "depth_of_world_or_concept": _field(_enum("STERILE_DEFAULT", "LIGHTLY_THEMED", "THEMED", "RICHLY_THEMED")),
            "mechanical_synergy": _field({"type": "boolean"}),
        },
        "questions": """has_distinct_voice: true if the on-screen text, dialogue or labels show personality, humour or world-building, rather than plain default text like "Welcome to Dashboard".
subverts_standard_ui: true if people use it in an unexpected way (for example a productivity tool framed as a virtual pet, or several synchronized screens), rather than standard sidebars, forms and tables.
depth_of_world_or_concept: STERILE_DEFAULT, LIGHTLY_THEMED, THEMED or RICHLY_THEMED.
mechanical_synergy: true if the features combine into one experience; false if they are a pile of separate features.""",
    },
    "functionality": {
        "intro": "Judge only FUNCTIONALITY: does what is built actually work for the person using it? Ignore how the code is written.",
        "fields": {
            "core_flow": _field(_enum("WORKS_END_TO_END", "MOSTLY_WORKS", "PARTLY_BUILT", "SHELL_OR_PLACEHOLDER")),
            "features_connected": _field(_enum("CONNECTED", "SOME_LOOSE_ENDS", "DISCONNECTED")),
            "tells_user_about_problems": _field(_enum("CLEARLY", "SOMETIMES", "NOT_SHOWN_IN_DOSSIER")),
            "confirms_success": _field(_enum("CLEARLY", "SOMETIMES", "NOT_SHOWN_IN_DOSSIER")),
        },
        "questions": """core_flow: can a person complete the app's main task from start to finish, judging from the screens, endpoints, data and text in the dossier? WORKS_END_TO_END, MOSTLY_WORKS (small gaps), PARTLY_BUILT (key parts missing or unfinished), SHELL_OR_PLACEHOLDER (mostly mock data or empty screens).
features_connected: CONNECTED = the features feed into each other. SOME_LOOSE_ENDS = a few parts are built but not wired up (see "Proven problems", for example endpoints nothing calls). DISCONNECTED = mostly separate pieces.
tells_user_about_problems: does the app show people a message when something goes wrong? Use NOT_SHOWN_IN_DOSSIER when the dossier gives no evidence either way (a count of 0 means the scan did not find it, not that it is missing).
confirms_success: does the app confirm when an action worked? Same rule for NOT_SHOWN_IN_DOSSIER.""",
    },
    "ui_ux": {
        "intro": "Judge only UI/UX: the screens or interface themselves, for the device the app is made for. Ignore how the code is written.",
        "fields": {
            "clarity": _field(_enum("CLEAR", "MIXED", "CLUTTERED_OR_TECHNICAL")),
            "consistency": _field(_enum("CONSISTENT", "MOSTLY_CONSISTENT", "PATCHWORK")),
            "feedback_while_working": _field(_enum("CLEAR", "SOME", "NOT_SHOWN_IN_DOSSIER")),
            "fits_its_device": _field(_enum("WELL", "ADEQUATELY", "POORLY", "NOT_SHOWN_IN_DOSSIER")),
            "accessibility_labels": _field(_enum("PRESENT", "FEW", "NOT_SHOWN_IN_DOSSIER")),
        },
        "questions": """clarity: is the on-screen text and layout easy to understand for an ordinary user? CLEAR, MIXED, or CLUTTERED_OR_TECHNICAL (crowded, or full of technical terms; see the share of technical wording).
consistency: do the screens look like one product (shared theme colors and styles) or a patchwork of different styles? CONSISTENT, MOSTLY_CONSISTENT, PATCHWORK.
feedback_while_working: does the interface show loading, progress or empty states while people wait? CLEAR, SOME, or NOT_SHOWN_IN_DOSSIER (a count of 0 means the scan did not find it, not that it is missing).
fits_its_device: does the interface suit its device (phone, TV, desktop, terminal), for example adapting to screen size or using touch-friendly controls? WELL, ADEQUATELY, POORLY, or NOT_SHOWN_IN_DOSSIER.
accessibility_labels: are there labels for screen readers (aria labels, alt text, content descriptions)? PRESENT, FEW, or NOT_SHOWN_IN_DOSSIER.""",
    },
    "journey": {
        "intro": "Judge only the USER JOURNEY, from installing it to closing it.",
        "fields": {
            "launch_experience": _field(_enum("RUNS_IMMEDIATELY", "ONE_STEP_INSTALL", "MANUAL_SETUP", "BRING_YOUR_OWN_KEY")),
            "navigation_friction": _field(_enum("STRAIGHT_TO_CORE", "A_FEW_STEPS", "BURIED")),
            "setup_burden": _field(_enum("NONE", "LIGHT", "MODERATE", "HEAVY")),
            "state_and_save": _field(_enum("AUTO_SAVE", "MANUAL_SAVE", "NO_SAVE", "NOT_NEEDED")),
            "hostile_monetization": _field({"type": "boolean"}),
        },
        "questions": """launch_experience: RUNS_IMMEDIATELY = web link, standalone app or zero-config launch. ONE_STEP_INSTALL = one installer, package or launch script. MANUAL_SETUP = the user must install dependencies or configure things by hand first. BRING_YOUR_OWN_KEY = it cannot be used without the user supplying their own API key.
navigation_friction: STRAIGHT_TO_CORE = the user lands on the main thing. A_FEW_STEPS = a short setup or menu first. BURIED = the core is behind splash screens, sign-ins or nested menus.
setup_burden: how much a person must fill in or understand before they can first use it (see "Setup burden" in the dossier). NONE = nothing. LIGHT = a few plain choices. MODERATE = several fields, or some technical terms. HEAVY = many fields or mostly technical terms, required before first use.
state_and_save: AUTO_SAVE = progress or data is kept automatically. MANUAL_SAVE = the user must save. NO_SAVE = closing it loses everything that matters. NOT_NEEDED = nothing needs keeping.
hostile_monetization: true only if the dossier shows ads, a paywall or payments, or a required sign-in service in the code (see the line about ads, payments and sign-in). Words in on-screen or story text do not count.""",
    },
}

SYSTEM = ("You are a discerning Hackathon Judge and Power-User evaluating vibe-coded software built by solo creators. "
          "You judge software by what it achieves for the person using it, not by enterprise bureaucracy. "
          "You reward clever high-leverage execution, real-world utility, and working software. "
          "You answer strictly from the written dossier with fixed choices and exact quotes.")


def schema(name: str) -> dict:
    f = PASSES[name]["fields"]
    return {"type": "object", "properties": f, "required": list(f)}


def prompt(dossier_md: str, name: str, cliche_fact: str = "", context_md: str = "",
           profile_data: Optional[Dict[str, Any]] = None) -> str:
    p = PASSES[name]
    head = f"{context_md}\n\n" if context_md else ""   # what the project says it is: context only, never evidence

    profile_lens = (profile_data or {}).get("evaluation_lenses", {}).get(name) or (
        profile_data or {}).get("evaluation_lenses", {}).get("user_journey" if name == "journey" else name)
    profile_guidance = ""
    if profile_lens:
        items = []
        if profile_lens.get("focus"):
            items.append(f"Domain Focus: {profile_lens['focus']}")
        if profile_lens.get("clarity_definition"):
            items.append(f"Clarity Criteria: {profile_lens['clarity_definition']}")
        if profile_lens.get("exemptions"):
            exempt_str = ", ".join(profile_lens["exemptions"])
            items.append(f"Profile Exemptions (do NOT penalize for lacking these): {exempt_str}")
        if items:
            profile_name = (profile_data or {}).get("name", "Archetype")
            profile_guidance = f"\n[Specific Evaluation Lenses for {profile_name}]:\n" + "\n".join(f"- {it}" for it in items) + "\n"

    return (f"{head}{dossier_md}\n\n---\n{cliche_fact}{p['intro']}\n{profile_guidance}\n"
            "Answer each item. For every answer, copy 1-3 short exact quotes from "
            "the dossier above as evidence (word for word). Use only the dossier.\n\n" + p["questions"] + "\n\nJSON only.")


def _norm(t: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (t or "").lower()).strip()


def check(answers: Dict[str, Any], dossier_md: str) -> Dict[str, Any]:
    """Marks each answer verified when at least one of its quotes is found in the dossier (exact, or 80% of its words in one line)."""
    dn = _norm(dossier_md)
    lines = [set(_norm(l).split()) for l in dossier_md.splitlines() if l.strip()]

    def ok(q: str) -> bool:
        qn = _norm(q)
        if len(qn) < 4:
            return False
        if qn in dn:
            return True
        words = qn.split()
        return len(words) >= 3 and any(sum(w in ls for w in words) / len(words) >= 0.8 for ls in lines)

    out: Dict[str, Any] = {}
    for k, v in (answers or {}).items():
        if k == "specific_twists":
            out[k] = [{**t, "verified": any(ok(q) for q in t.get("evidence", []))} for t in (v or []) if t.get("twist")]
        elif isinstance(v, dict):
            out[k] = {**v, "verified": any(ok(q) for q in v.get("evidence", []))}
    return out


def run(generate: Callable[..., Dict[str, Any]], model: str, dossier_md: str, cliche_fact: str,
        context_md: str = "", profile_data: Optional[Dict[str, Any]] = None) -> Tuple[Dict[str, Any], Dict[str, float]]:
    """Runs the passes. `generate` is OllamaClient.generate_json (so the admin Stop button applies). `context_md` (what
    the project says it is, rubric v9.2) is shown before the dossier, but quotes are checked against the dossier only,
    so a README claim can never count as evidence."""
    import time
    from letsvibe.evaluator.ollama import CpuSpilloverError
    results, timing = {}, {}
    for name in PASSES:
        t0 = time.perf_counter()
        ans = {}
        for attempt in range(3):          # a cut-off or malformed answer is retried with more room
            try:
                ans = generate(model=model, system_prompt=SYSTEM,
                               user_prompt=prompt(dossier_md, name, cliche_fact if name == "value" else "", context_md, profile_data),
                               format_schema=schema(name), max_output_tokens=900 + 600 * attempt, temperature=0.1)
                if all(k in ans for k in PASSES[name]["fields"]):
                    break
            except CpuSpilloverError:          # includes the admin's Stop: never swallow it
                raise
            except (ValueError, RuntimeError):  # malformed or cut-off answer: retry with more room
                continue
        results[name] = check(ans, dossier_md)
        timing[f"rubric_{name}_sec"] = round(time.perf_counter() - t0, 2)
    return results, timing
