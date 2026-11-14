"""
Stage 7: descriptions. For each category the model rewrites ONLY its checked answers and their evidence as plain-English
sentences. The findings are given weakest first, and the model must open with the weakest one, stated plainly; if a
factor has a problem or a shortfall and the text never says so, Python puts the plain finding first (the score and the
words must match). "Needs work" is written by Python from every problem answer, then every answer that falls short
(scoring.PROBLEM_ANSWERS, scoring.MIDDLE_ANSWERS), with the file and line where the code shows it; when there are none,
it says so instead of inventing advice.
"""
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

from letsvibe.evaluator.ollama import CpuSpilloverError
from .scoring import POINTS, shortfall

SYSTEM = ("You are a discerning, fair hackathon reviewer evaluating software built by solo vibe-coders. "
          "You explain software clearly, highlighting the practical superpowers and real-world leverage it delivers, "
          "while candidly pointing out genuine engineering or design bottlenecks. You never invent corporate requirements, "
          "and you never soften proven bugs.")
TITLES = {"value": "Real-World Value", "creativity": "Creativity", "journey": "User Journey", "functionality": "Functionality", "ui_ux": "UI / UX"}
_NS = "not shown either way in what could be checked"
PLAIN: Dict[str, Dict[Any, str]] = {
    "is_default_prompt_clone": {True: "could be made from a short two-sentence prompt", False: "goes beyond what a short two-sentence prompt would make"},
    "tier": {"TIER_0_BROKEN_OR_SHELL": "it is mostly placeholders or does not really work yet",
             "TIER_1_GENERIC_CLONE": "it works, but it is a standard version of a common idea",
             "TIER_2_ITERATIVE_NICHE": "it adapts a common idea for a specific group of people or adds a real twist",
             "TIER_3_GENUINE_GAP_OR_HOOK": "it fills a real gap or keeps people coming back"},
    "has_distinct_voice": {True: "its on-screen text has personality", False: "its on-screen text is plain and generic"},
    "subverts_standard_ui": {True: "people use it in an unusual way", False: "it uses a standard layout"},
    "depth_of_world_or_concept": {"STERILE_DEFAULT": "it has no theme beyond the default look", "LIGHTLY_THEMED": "it is only lightly themed",
                                  "THEMED": "it has a clear theme", "RICHLY_THEMED": "it is richly themed"},
    "mechanical_synergy": {True: "its features work together as one experience", False: "its features feel separate"},
    "hostile_monetization": {True: "the code includes ads, payments or a required sign-in service", False: "no ads, paywalls, forced sign-in or wait timers"},
    "core_flow": {"WORKS_END_TO_END": "the main task can be done from start to finish", "MOSTLY_WORKS": "the main task mostly works, with small gaps",
                  "PARTLY_BUILT": "key parts of the main task are missing or unfinished", "SHELL_OR_PLACEHOLDER": "it is mostly placeholders or empty screens"},
    "features_connected": {"CONNECTED": "its features are wired together", "SOME_LOOSE_ENDS": "some parts are built but not wired up",
                           "DISCONNECTED": "its features are mostly separate pieces"},
    "tells_user_about_problems": {"CLEARLY": "it tells people clearly when something goes wrong",
                                  "SOMETIMES": "it only sometimes tells people when something goes wrong",
                                  "NOT_SHOWN_TO_USER": "when something goes wrong, people are not told (errors are only logged or ignored)",
                                  "NOT_SHOWN_IN_DOSSIER": f"whether it tells people about problems is {_NS}"},
    "confirms_success": {"CLEARLY": "it clearly confirms when an action worked", "SOMETIMES": "it only sometimes confirms that an action worked",
                         "NOT_SHOWN_TO_USER": "it does not tell people when an action worked",
                         "NOT_SHOWN_IN_DOSSIER": f"whether it confirms that actions worked is {_NS}"},
    "clarity": {"CLEAR": "the screens are clear and easy to understand", "MIXED": "the screens are partly clear and partly confusing",
                "CLUTTERED_OR_TECHNICAL": "the screens are cluttered or use too many technical terms"},
    "consistency": {"CONSISTENT": "the screens share one consistent look", "MOSTLY_CONSISTENT": "the screens mostly share one look",
                    "PATCHWORK": "the screens look like a patchwork of different styles"},
    "feedback_while_working": {"CLEAR": "it clearly shows progress or loading while people wait", "SOME": "it shows progress only some of the time",
                               "NONE": "it shows nothing while people wait for slow work",
                               "NOT_SHOWN_IN_DOSSIER": f"whether it shows progress while people wait is {_NS}"},
    "fits_its_device": {"WELL": "it suits the device it is made for", "ADEQUATELY": "it suits its device adequately",
                        "POORLY": "it does not suit the device it is made for", "NOT_SHOWN_IN_DOSSIER": f"how well it suits its device is {_NS}"},
    "accessibility_labels": {"PRESENT": "it has labels for screen readers", "FEW": "it has only a few labels for screen readers",
                             "NONE": "it has no labels for screen readers",
                             "NOT_SHOWN_IN_DOSSIER": f"whether it has labels for screen readers is {_NS}"},
    "launch_experience": {"RUNS_IMMEDIATELY": "it runs straight away", "ONE_STEP_INSTALL": "it installs in one step",
                          "MANUAL_SETUP": "people must install or configure things by hand before it runs",
                          "BRING_YOUR_OWN_KEY": "it cannot be used without the person's own API key"},
    "navigation_friction": {"STRAIGHT_TO_CORE": "people land straight on the main thing", "A_FEW_STEPS": "people go through a few steps before the main thing",
                            "BURIED": "the main thing is buried behind screens, sign-ins or menus"},
    "setup_burden": {"NONE": "nothing has to be set up before first use", "LIGHT": "only a few plain choices before first use",
                     "MODERATE": "a moderate amount of setup before first use", "HEAVY": "a heavy, technical setup is required before first use"},
    "state_and_save": {"AUTO_SAVE": "it saves people's work automatically", "MANUAL_SAVE": "people must remember to save",
                       "NO_SAVE": "closing it loses people's work", "NOT_NEEDED": "nothing needs saving"},
}
# Words that would say the opposite of a negative answer (checked in Python after writing)
CONTRADICTS = {
    ("clarity", "CLUTTERED_OR_TECHNICAL"): r"\b(clear|clean|simple|tidy) (interface|screens?|layout|design|wording|language|labels)\b"
                                           r"|\beasy to (use|understand|read)\b|\bminimal (technical|jargon)|\buncluttered\b|\bintuitive\b",
    ("setup_burden", "HEAVY"): r"\b(quick|easy|simple|effortless|minimal) (setup|set up|to set up)\b|\bno setup\b",
    ("consistency", "PATCHWORK"): r"\b(consistent|cohesive|unified) (look|style|design)\b",
    ("is_default_prompt_clone", True): r"\b(unique|one of a kind|original)\b",
    ("tells_user_about_problems", "NOT_SHOWN_TO_USER"): r"\b(clearly )?(informs?|tells?|alerts?|warns?) (users?|people|you)\b",
    ("confirms_success", "NOT_SHOWN_TO_USER"): r"\bconfirm(s|ation)?\b(?![^.]*\b(not|no|never|without)\b)",
    ("feedback_while_working", "NONE"): r"\b(clear|helpful|good) feedback\b|\bloading indicators?\b(?![^.]*\b(no|not|never)\b)",
    ("accessibility_labels", "NONE"): r"\baccessib(le|ility) (labels|features)\b(?![^.]*\b(no|not|lacks?|without)\b)",
}
# A description that names a shortfall uses at least one of these
_NEGATIVE_CUE = re.compile(r"\b(not|no|never|lacks?|lacking|missing|without|only|but|however|although|though|cluttered|"
                           r"confusing|heavy|hard|difficult|limited|unfinished|loose|separate|plain|generic|must|buried|patchwork|"
                           r"partly|few|weak|loses?)\b", re.I)
_TEXT = {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}


def _meaning(field: str, ans: Any) -> str:
    return PLAIN.get(field, {}).get(ans, str(ans).replace("_", " ").lower())


def _points_share(cat: str, field: str, ans: Any) -> float:
    table = POINTS.get(cat, {}).get(field)
    if not isinstance(table, dict) or ans not in table or not max(table.values()):
        return 1.0
    return table[ans] / max(table.values())


def drop_contradictions(answers: Dict[str, Any], text: str, extra_findings: List[str] = (), has_shortfall: bool = True) -> str:
    """Removes sentences that say the opposite of checklist answers or verified evidence."""
    rules = [rx for (field, bad), rx in CONTRADICTS.items() if (answers.get(field) or {}).get("answer") == bad]

    # Grounding check: if evidence explicitly says "zero app install" or "no install", drop claims requiring app install
    joined_ev = " ".join(extra_findings).lower()
    for v in answers.values():
        if isinstance(v, dict):
            for ev in v.get("evidence", []) or []:
                if isinstance(ev, str):
                    joined_ev += " " + ev.lower()
            if isinstance(v.get("specific_twists"), list):
                for tw in v["specific_twists"]:
                    if isinstance(tw, dict) and tw.get("twist"):
                        joined_ev += " " + str(tw["twist"]).lower()

    if re.search(r"\b(zero|no|without)\s+(app\s+)?install", joined_ev):
        rules.append(r"\b(requir|need|must|demand|barrier)\w*\s+.*(install|download)\w*\s+.*(app|client|software)\b")
        rules.append(r"\b(requir|need|must|barrier)\w*\s+(app\s+)?installation\b")

    sentences = re.split(r"(?<=[.!?])\s+", text)
    kept = []
    for s in sentences:
        if any(re.search(rx, s, re.I) for rx in rules):
            continue
        # If the factor has no shortfalls, drop any fabricated "falls short by..." opening
        if not has_shortfall and re.match(r"^.*?\bfalls short by\b", s, re.I):
            continue
        kept.append(s)

    out = " ".join(kept).strip()
    if not has_shortfall:
        out = re.sub(r"^(Despite this,\s*|However,\s*)", "", out)
        if out:
            out = out[0].upper() + out[1:]
    return out


def _where(v: Dict[str, Any]) -> str:
    ev = v.get("code_evidence") or []
    return f" ({ev[0]['file']} line {ev[0]['line']})" if ev else ""


def ordered(cat: str, answers: Dict[str, Any], profile_data: Optional[Dict[str, Any]] = None) -> List[Tuple[str, Dict[str, Any]]]:
    """Checklist answers weakest first (problems, then shortfalls, then the rest by share of points)."""
    items = [(k, v) for k, v in answers.items() if k != "specific_twists" and isinstance(v, dict)]
    return sorted(items, key=lambda kv: (-shortfall(kv[0], kv[1].get("answer"), profile_data), _points_share(cat, kv[0], kv[1].get("answer"))))


def facts_for(answers: Dict[str, Any], cat: str = "", profile_data: Optional[Dict[str, Any]] = None) -> List[str]:
    lines = []
    for k, v in (ordered(cat, answers, profile_data) if cat else [(k, v) for k, v in answers.items() if k != "specific_twists"]):
        quotes = "; ".join(f'"{q[:120]}"' for q in v.get("evidence", [])[:2] if isinstance(q, str) and q.strip())
        tag = {2: "PROBLEM: ", 1: "FALLS SHORT: "}.get(shortfall(k, v.get("answer"), profile_data), "")
        lines.append(f"- {tag}{_meaning(k, v.get('answer'))}" + (f" (evidence: {quotes})" if quotes else ""))
    lines += [f"- Goes beyond the basic idea with: {t['twist']}" for t in answers.get("specific_twists", []) or []]
    return lines


def problems_ranked(cat: str, answers: Dict[str, Any], hostile: List[str] = (), profile_data: Optional[Dict[str, Any]] = None) -> List[Tuple[int, str]]:
    """[(2 = problem / 1 = falls short, plain-English line with where the code shows it)], problems first."""
    out: List[Tuple[int, str]] = [(2, f"{TITLES[cat]}: the code includes " + ", ".join(hostile))] if cat == "journey" and hostile else []
    for level in (2, 1):
        for k, v in ordered(cat, answers, profile_data):
            if k in POINTS.get(cat, {}) and shortfall(k, v.get("answer"), profile_data) == level:
                out.append((level, f"{TITLES[cat]}: {_meaning(k, v['answer'])}{_where(v)}"))
    return out


def problems(cat: str, answers: Dict[str, Any], hostile: List[str] = (), profile_data: Optional[Dict[str, Any]] = None) -> List[str]:
    """Every problem answer, then every answer that falls short, in plain English with where the code shows it."""
    return [line for _, line in problems_ranked(cat, answers, hostile, profile_data)]


def summarize(generate: Callable[..., Dict[str, Any]], model: str, repo: str, texts: Dict[str, str], about: str = "") -> str:
    """2-3 sentences written only from the factor descriptions (no new facts), keeping their problems. `about` is what
    the project says it is (rubric v9.2 project context), so the summary opens with what it really is."""
    sections = "\n\n".join(f"{TITLES[c]}: {t}" for c, t in texts.items() if t)
    if not sections:
        return ""
    what = (f"What the project is, in its own words: {about}\n\n" if about else "")
    prompt = (f"{what}Below are the sections of a review of a project called {repo}.\n\n{sections}\n\nWrite 2-3 plain-English sentences that "
              "summarize the whole review for someone who does not write code: " +
              ("start by saying what the project is (from its own words above), then " if about else "") +
              "its main strength and its main problems, both "
              "stated plainly. Use only these sections; do not add anything, do not repeat any sentence word for word, and do "
              "not give scores.")
    try:
        return str(generate(model=model, system_prompt=SYSTEM, user_prompt=prompt, format_schema=_TEXT,
                            max_output_tokens=220, temperature=0.3).get("text", "")).strip()
    except CpuSpilloverError:          # includes the admin's Stop
        raise
    except (ValueError, RuntimeError):
        return ""


def ensure_weakness_named(cat: str, answers: Dict[str, Any], text: str, profile_data: Optional[Dict[str, Any]] = None) -> str:
    """If the factor has a problem or shortfall and the text never sounds a negative note, put the plain finding first."""
    weak = [(k, v) for k, v in ordered(cat, answers, profile_data) if shortfall(k, v.get("answer"), profile_data)]
    if not weak or _NEGATIVE_CUE.search(text or ""):
        return text
    k, v = weak[0]
    first = _meaning(k, v.get("answer"))
    return (first[0].upper() + first[1:] + ". " + (text or "")).strip()


def write(generate: Callable[..., Dict[str, Any]], model: str, repo: str, results: Dict[str, Dict[str, Any]],
          proven: List[str] = (), hostile: List[str] = (), profile_data: Optional[Dict[str, Any]] = None,
          submission_meta: Optional[Dict[str, Any]] = None) -> Tuple[Dict[str, str], List[str]]:
    """`proven` are problems found by the code scan (certain): first in the functionality findings and in "needs work".
    Returns ({factor: description}, needs work)."""
    texts: Dict[str, str] = {}
    ranked: List[Tuple[int, str]] = []
    meta = submission_meta or {}
    zero_install_note = ["- Zero app install required for guests or users (browser / web URL)"] if meta.get("guest_access") == "zero_install" else []
    for cat, answers in results.items():
        extra = [f"- PROBLEM (found by an automatic scan, certain): {p}" for p in proven] if cat == "functionality" else []
        if cat == "journey":
            answers = {k: v for k, v in answers.items() if k != "hostile_monetization"}   # stated exactly below instead
            extra = ([f"- PROBLEM: the code includes {', '.join(hostile)} (found by an automatic scan)"] if hostile
                     else ["- No ads, payments, required sign-in or review prompts were found in the code"])
        findings_lines = extra + facts_for(answers, cat, profile_data) + zero_install_note
        has_shortfall = any("PROBLEM" in line or "FALLS SHORT" in line for line in findings_lines)
        if has_shortfall:
            rule_instruction = (
                "If any finding is marked PROBLEM or FALLS SHORT, your first sentence must state the weakest one plainly, "
                "without softening it; then cover the rest. Every finding above is true: never say the opposite of one."
            )
        else:
            rule_instruction = (
                "All findings above are positive; NONE are marked PROBLEM or FALLS SHORT. "
                "Start with the project's main strength, superpower, or real-world leverage. "
                "Do NOT invent, assume, or fabricate any problems, shortfalls, or barriers (such as falsely claiming it requires an app install or external service)."
            )

        prompt = (f"These are checked findings about the {TITLES[cat]} of a project called {repo}, weakest first:\n"
                  + "\n".join(findings_lines) +
                  f"\n\nWrite 2-3 plain-English sentences about its {TITLES[cat]} only, for someone who does not write code. "
                  f"{rule_instruction} "
                  "Use only these findings and their evidence; do not add anything else, do not write about other topics, and do "
                  "not give scores or tier names. Avoid technical jargon.")
        try:
            raw = str(generate(model=model, system_prompt=SYSTEM, user_prompt=prompt, format_schema=_TEXT,
                               max_output_tokens=260, temperature=0.3).get("text", "")).strip()
            cleaned = drop_contradictions(answers, raw, findings_lines, has_shortfall)
            texts[cat] = ensure_weakness_named(cat, answers, cleaned, profile_data)
        except CpuSpilloverError:          # includes the admin's Stop
            raise
        except (ValueError, RuntimeError):
            texts[cat] = ensure_weakness_named(cat, answers, "", profile_data)
        ranked += problems_ranked(cat, answers, hostile if cat == "journey" else (), profile_data)
    # Proven problems first, then every problem, then every shortfall (Python only: nothing softened or dropped)
    needs = [f"Functionality: {p}" for p in proven] + [line for lvl, line in ranked if lvl == 2] + [line for lvl, line in ranked if lvl == 1]
    return texts, needs
