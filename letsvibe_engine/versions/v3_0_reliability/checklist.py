"""
Binary evidence checklist scoring.

Small local models are unreliable at free-form 0-100 scoring but good at concrete yes/no
questions. Each core factor has a fixed list of questions; the checklist score is derived from
the fraction answered "yes" (questions answered "na" are excluded), so it is anchored,
repeatable and explainable. It is blended with the free-form model scores in consensus.py.
"""

from typing import Any, Dict, List, Optional, Tuple

# factor -> [(question_id, question)]
CHECKLIST: Dict[str, List[Tuple[str, str]]] = {
    "maintainability": [
        ("clear_names", "Are functions, variables and files named clearly and consistently?"),
        ("small_units", "Is logic split into reasonably small functions/modules (no giant god-functions)?"),
        ("low_duplication", "Is copy-pasted or duplicated logic largely absent?"),
        ("no_magic_values", "Are constants/config named instead of scattered magic numbers and hardcoded paths?"),
        ("docs_or_comments", "Do the README or code comments explain how to build, run and modify it?"),
    ],
    "functionality": [
        ("core_implemented", "Is the core feature promised by the README actually implemented (not stubs/TODOs)?"),
        ("edge_cases", "Does the code handle empty, invalid or missing input explicitly?"),
        ("error_paths", "Do failures produce handled errors or messages rather than crashes or silent failure?"),
        ("has_tests", "Are there automated tests that exercise real behavior?"),
        ("complete_flow", "Can a user complete the main workflow end to end from the code shown?"),
    ],
    "creativity": [
        ("novel_idea", "Does the project do something not already covered by a standard well-known tool?"),
        ("custom_logic", "Does it contain custom algorithms or mechanics beyond CRUD/wrapper code?"),
        ("thoughtful_design", "Do design choices show deliberate, domain-specific thinking?"),
        ("not_template", "Is it clearly more than an unmodified template or tutorial project?"),
    ],
    "ui_ux": [
        ("has_interface", "Does the project expose a user-facing interface (GUI, TUI, CLI or documented API)?"),
        ("discoverable", "Is the interface discoverable (help text, clear labels, sensible defaults)?"),
        ("feedback", "Does it give users feedback on progress, errors and results?"),
        ("ergonomics", "Are interactions efficient for the target users (shortcuts, minimal steps, good layout)?"),
    ],
    "architecture": [
        ("separation", "Are concerns separated (data/logic/presentation or transport/domain)?"),
        ("module_boundaries", "Are module boundaries clear with limited circular or tangled imports?"),
        ("not_monolith", "Is the code spread across sensible files rather than one large monolith?"),
        ("extensible", "Could a new feature be added without editing many unrelated files?"),
        ("deps_managed", "Are dependencies declared and managed (manifest/lockfile)?"),
    ],
    "operational_safety": [
        ("timeouts", "Do network, subprocess or IO calls have timeouts or bounded waits?"),
        ("resource_cleanup", "Are files, sockets, processes and similar resources released reliably?"),
        ("input_validation", "Is external or user input validated before use?"),
        ("no_silent_data_loss", "Are destructive operations (delete/overwrite) guarded against accidental data loss?"),
        ("no_swallowed_errors", "Are exceptions handled specifically rather than blindly swallowed?"),
    ],
    "resonance": [
        ("real_problem", "Does it solve a genuine problem for a identifiable group of users?"),
        ("differentiated", "Does it offer something meaningfully different from common alternatives?"),
        ("usable_now", "Could a real user get value from it today without major missing pieces?"),
        ("audience_fit", "Is the design well matched to its intended audience?"),
    ],
}

CHECKLIST_SYSTEM_PROMPT = (
    "You are a strict code auditor answering concrete yes/no questions about a repository. "
    "Answer ONLY from the evidence provided. Answer \"yes\" only if the evidence clearly supports it, "
    "\"no\" if it is absent or contradicted, and \"na\" only if the question cannot apply to this kind of project. "
    "When evidence is missing, answer \"no\". Respond with JSON only."
)

SCORE_FLOOR = 35.0
SCORE_CEIL = 95.0


def checklist_schema() -> Dict[str, Any]:
    """JSON schema forcing a yes/no/na answer for every checklist question."""
    props = {
        factor: {
            "type": "object",
            "properties": {qid: {"type": "string", "enum": ["yes", "no", "na"]} for qid, _ in questions},
            "required": [qid for qid, _ in questions],
        }
        for factor, questions in CHECKLIST.items()
    }
    return {"type": "object", "properties": props, "required": list(CHECKLIST.keys())}


def build_checklist_prompt(evidence: str) -> str:
    lines = ["Answer every question with yes, no or na.\n"]
    for factor, questions in CHECKLIST.items():
        lines.append(f"[{factor}]")
        for qid, text in questions:
            lines.append(f"  {qid}: {text}")
    return "REPOSITORY EVIDENCE:\n" + evidence + "\n\nQUESTIONS:\n" + "\n".join(lines)


def score_checklist(answers: Any) -> Tuple[Dict[str, float], Dict[str, List[str]]]:
    """
    Converts answers into per-factor scores (35 + 60 * yes_fraction) and the list of failed-check
    questions per factor. Factors with fewer than 2 answerable questions are omitted.
    """
    scores: Dict[str, float] = {}
    failures: Dict[str, List[str]] = {}
    if not isinstance(answers, dict):
        return scores, failures
    for factor, questions in CHECKLIST.items():
        block = answers.get(factor)
        if not isinstance(block, dict):
            continue
        yes = no = 0
        failed: List[str] = []
        for qid, text in questions:
            ans = str(block.get(qid, "")).strip().lower()
            if ans == "yes":
                yes += 1
            elif ans == "no":
                no += 1
                failed.append(text)
        if yes + no < 2:
            continue
        frac = yes / (yes + no)
        scores[factor] = round(SCORE_FLOOR + (SCORE_CEIL - SCORE_FLOOR) * frac, 1)
        failures[factor] = failed
    return scores, failures
