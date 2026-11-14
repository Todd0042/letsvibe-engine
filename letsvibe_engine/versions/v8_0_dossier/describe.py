"""
Stage 5: descriptions. For each category the model rewrites ONLY its own rubric answers and their evidence quotes as
plain-English sentences. "Needs work" is written only from genuine problem answers (chosen by Python); when there are
none, it says so instead of inventing advice.
"""
from typing import Any, Callable, Dict, List, Tuple

from letsvibe.evaluator.ollama import CpuSpilloverError
from .scoring import POINTS, PROBLEM_ANSWERS

SYSTEM = "You are a careful writer who explains software to people who do not write code. You never add facts."
TITLES = {"value": "Real-World Value", "creativity": "Creativity", "journey": "User Journey", "functionality": "Functionality", "ui_ux": "UI / UX"}
PLAIN = {
    "is_default_prompt_clone": {True: "could be made from a short two-sentence prompt", False: "goes beyond what a short two-sentence prompt would make"},
    "has_distinct_voice": {True: "its on-screen text has personality", False: "its on-screen text is plain and generic"},
    "subverts_standard_ui": {True: "people use it in an unusual way", False: "it uses a standard layout"},
    "mechanical_synergy": {True: "its features work together as one experience", False: "its features feel separate"},
    "hostile_monetization": {True: "the code includes ads, payments or a required sign-in service", False: "no ads, paywalls, forced sign-in or wait timers"},
    "clarity": {"CLEAR": "the screens are clear and easy to understand", "MIXED": "the screens are partly clear and partly confusing",
                "CLUTTERED_OR_TECHNICAL": "the screens are cluttered or use too many technical terms"},
    "consistency": {"CONSISTENT": "the screens share one consistent look", "MOSTLY_CONSISTENT": "the screens mostly share one look",
                    "PATCHWORK": "the screens look like a patchwork of different styles"},
    "setup_burden": {"NONE": "nothing has to be set up before first use", "LIGHT": "only a few plain choices before first use",
                     "MODERATE": "a moderate amount of setup before first use", "HEAVY": "a heavy, technical setup is required before first use"},
}
# Words that would say the opposite of a negative answer (checked in Python after writing)
CONTRADICTS = {
    ("clarity", "CLUTTERED_OR_TECHNICAL"): r"\b(clear|clean|simple|tidy) (interface|screens?|layout|design|wording|language|labels)\b"
                                           r"|\beasy to (use|understand|read)\b|\bminimal (technical|jargon)|\buncluttered\b|\bintuitive\b",
    ("setup_burden", "HEAVY"): r"\b(quick|easy|simple|effortless|minimal) (setup|set up|to set up)\b|\bno setup\b",
    ("consistency", "PATCHWORK"): r"\b(consistent|cohesive|unified) (look|style|design)\b",
    ("is_default_prompt_clone", True): r"\b(unique|one of a kind|original)\b",
}
_TEXT = {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}


def _meaning(field: str, ans: Any) -> str:
    return PLAIN.get(field, {}).get(ans, str(ans).replace("_", " ").lower())


def drop_contradictions(answers: Dict[str, Any], text: str) -> str:
    """Removes sentences that say the opposite of a negative checklist answer (plain Python; no rewriting)."""
    import re
    rules = [rx for (field, bad), rx in CONTRADICTS.items() if (answers.get(field) or {}).get("answer") == bad]
    if not rules:
        return text
    sentences = re.split(r"(?<=[.!?])\s+", text)
    kept = [s for s in sentences if not any(re.search(rx, s, re.I) for rx in rules)]
    return " ".join(kept).strip()


def facts_for(answers: Dict[str, Any]) -> List[str]:
    lines = []
    for k, v in answers.items():
        if k == "specific_twists":
            lines += [f"- Goes beyond the basic idea with: {t['twist']}" for t in v]
            continue
        quotes = "; ".join(f'"{q[:120]}"' for q in v.get("evidence", [])[:2] if q.strip())
        lines.append(f"- {k.replace('_', ' ')}: {_meaning(k, v.get('answer'))}" + (f" (evidence: {quotes})" if quotes else ""))
    return lines


def problems(cat: str, answers: Dict[str, Any], hostile: List[str] = ()) -> List[str]:
    out = []
    for k in POINTS[cat]:
        bad = PROBLEM_ANSWERS.get(k)
        if not bad or k not in answers or answers[k].get("answer") not in bad:
            continue
        ev = "; ".join(f'"{q[:100]}"' for q in answers[k].get("evidence", [])[:1] if q.strip())
        out.append(f"{TITLES[cat]}: {k.replace('_', ' ')} is '{_meaning(k, answers[k]['answer'])}'" + (f" (evidence: {ev})" if ev else ""))
    if cat == "journey" and hostile:
        out.append(f"{TITLES[cat]}: the code includes " + ", ".join(hostile))
    return out


def summarize(generate: Callable[..., Dict[str, Any]], model: str, repo: str, texts: Dict[str, str]) -> str:
    """2-3 sentences written only from the factor descriptions (no new facts)."""
    sections = "\n\n".join(f"{TITLES[c]}: {t}" for c, t in texts.items() if t)
    if not sections:
        return ""
    prompt = (f"Below are the sections of a review of a project called {repo}.\n\n{sections}\n\nWrite 2-3 plain-English sentences that "
              "summarize the whole review for someone who does not write code. Use only these sections; do not add anything, do not "
              "repeat any sentence word for word, and do not give scores.")
    try:
        return str(generate(model=model, system_prompt=SYSTEM, user_prompt=prompt, format_schema=_TEXT,
                            max_output_tokens=220, temperature=0.3).get("text", "")).strip()
    except CpuSpilloverError:          # includes the admin's Stop
        raise
    except (ValueError, RuntimeError):
        return ""


def write(generate: Callable[..., Dict[str, Any]], model: str, repo: str, results: Dict[str, Dict[str, Any]],
          proven: List[str] = (), hostile: List[str] = ()) -> Tuple[Dict[str, str], List[str]]:
    """`proven` are problems found by the code scan (certain), added to the functionality findings and to "needs work"."""
    texts: Dict[str, str] = {}
    needs: List[str] = [f"Functionality: {p}" for p in proven]
    for cat, answers in results.items():
        extra = [f"- Found by an automatic scan (certain): {p}" for p in proven] if cat == "functionality" else []
        if cat == "journey":
            answers = {k: v for k, v in answers.items() if k != "hostile_monetization"}   # stated exactly below instead
            extra = ([f"- The code includes {', '.join(hostile)} (found by an automatic scan)"] if hostile
                     else ["- No ads, payments, required sign-in or review prompts were found in the code"])
        prompt = (f"These are checked findings about the {TITLES[cat]} of a project called {repo}:\n" + "\n".join(facts_for(answers) + extra) +
                  f"\n\nWrite 2-3 plain-English sentences about its {TITLES[cat]} for someone who does not write code. Every finding above "
                  "is true: your sentences must agree with each one and never say the opposite. Use only these findings and their "
                  "evidence; do not add anything else or give reasons they do not state, and do not give scores or tier names. Avoid technical jargon.")
        try:
            texts[cat] = drop_contradictions(answers, str(generate(model=model, system_prompt=SYSTEM, user_prompt=prompt, format_schema=_TEXT,
                                                                       max_output_tokens=260, temperature=0.3).get("text", "")).strip())
        except CpuSpilloverError:          # includes the admin's Stop
            raise
        except (ValueError, RuntimeError):
            texts[cat] = ""
        needs += problems(cat, answers, hostile)
    bullets: List[str] = []
    if needs:
        prompt = ("These checked findings about a project are problems:\n" + "\n".join(f"- {n}" for n in needs) +
                  "\n\nWrite at most 3 bullet points of one sentence each about what could be improved, most important first, in plain "
                  "English for someone who does not write code. Use only these findings. Put each bullet on its own line starting with '- '.")
        try:
            raw = str(generate(model=model, system_prompt=SYSTEM, user_prompt=prompt, format_schema=_TEXT,
                               max_output_tokens=260, temperature=0.3).get("text", ""))
            bullets = [b.strip(" -*•\t") for b in raw.splitlines() if b.strip(" -*•\t")][:3]
        except CpuSpilloverError:          # includes the admin's Stop
            raise
        except (ValueError, RuntimeError):
            bullets = []
    return texts, bullets
