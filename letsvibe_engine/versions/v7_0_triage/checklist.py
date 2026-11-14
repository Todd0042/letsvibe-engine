"""
Binary evidence checklist scoring.

Small local models are unreliable at free-form 0-100 scoring but good at concrete yes/no
questions. Each core factor has a fixed list of questions; the checklist score is derived from
the fraction answered "yes" (questions answered "na" are excluded), so it is anchored,
repeatable and explainable. It is blended with the free-form model scores in consensus.py.
"""

from typing import Any, Dict, List, Optional, Tuple

# factor -> [(question_id, question)]
# Rubric v6: phrased for vibe-coded projects (written by AI from prompts). Only questions that tell
# vibe-coded projects apart are asked: AI-written code is almost always clearly named, and complexity,
# tests and declared dependencies are measured directly, so code_health has no checklist questions
# (it comes from the reviewers plus measurements). Duplicates across factors were removed. Team-process habits (lockfiles, test suites,
# small functions) live under code_health, which carries little weight; the experience factors ask
# what a user of the project would notice.
CHECKLIST: Dict[str, List[Tuple[str, str]]] = {
    "functionality": [
        ("core_implemented", "Is the core feature promised by the README actually implemented (not stubs/TODOs)?"),
        ("features_connected", "Do the main features work together (no half-wired buttons, dead menu items or unused screens)?"),
        ("input_handled", "Does the program cope with empty, invalid or missing input instead of crashing?"),
    ],
    "user_journey": [
        ("easy_to_start", "Is there a clear way to install or launch it (installer, package, launch script, or README quick start that matches the code)?"),
        ("first_run", "Is first-time setup guided where the project needs it (setup wizard, onboarding, permission requests with an explanation)? Answer na if no setup is needed."),
        ("cohesive_navigation", "Do the menus/screens/commands feel like one coherent product, with a way to get back from every screen?"),
        ("shallow_settings", "Can common settings be reached in one or two steps, rather than menus inside menus inside menus?"),
        ("main_flow_complete", "Can a user get from starting the program to finishing its main task without dead ends?"),
        ("confirms_outcome", "Does the program clearly confirm when something worked (saved, synced, exported, level complete, summary printed)?"),
        ("recovers", "Are there clear empty and error states that tell the user what to do next?"),
    ],
    "ui_ux": [
        ("discoverable", "Are controls and options understandable without reading the code (labels, help text, sensible defaults)?"),
        ("feedback", "Does the interface show progress or status while things happen?"),
        ("fits_device", "Is the interface designed for its target device (screen size, touch/keyboard/buttons, glanceability)?"),
    ],
    "resonance": [
        ("real_problem", "Does it solve a genuine problem or provide real enjoyment for an identifiable group of people?"),
        ("differentiated", "Does it offer something meaningfully different from common alternatives?"),
        ("audience_fit", "Is the design well matched to its intended audience?"),
    ],
    "creativity": [
        ("novel_idea", "Does the project do something not already covered by a standard well-known tool?"),
        ("custom_logic", "Does it contain custom algorithms or mechanics beyond CRUD/wrapper code?"),
        ("thoughtful_design", "Do design choices show deliberate, domain-specific thinking?"),
    ],
    "operational_safety": [
        ("timeouts", "Do network, subprocess or device calls avoid hanging forever (timeouts or bounded waits)?"),
        ("resource_cleanup", "Are files, sockets, processes and similar resources released reliably?"),
        ("no_silent_data_loss", "Are destructive operations (delete/overwrite) guarded against accidental data loss?"),
        ("errors_not_swallowed", "Are most errors handled or reported rather than silently ignored?"),
    ],
}

CHECKLIST_SYSTEM_PROMPT = (
    "You are a fair code reviewer answering concrete yes/no questions about a VIBE-CODED project: the program was "
    "written by AI from someone's prompts, usually by a person who is not a programmer. Judge it as such a project, "
    "never against software written by professional developers. "
    "Answer ONLY from the evidence provided. Answer \"yes\" only if the evidence clearly supports it, "
    "\"no\" if it is absent or contradicted, and \"na\" only if the question cannot apply to this kind of project "
    "or its target hardware (e.g. a setup wizard for a tool with nothing to configure, or rich help text on a microcontroller display). "
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
