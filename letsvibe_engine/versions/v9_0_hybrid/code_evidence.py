"""
Stage 3 (rubric v9): per-factor code evidence from the 7B.

The code is cut into the same 5,200-token chunks as rubric v7 (evaluator/pipeline.build_batches). Each chunk is sent
only to the factors it can tell us about (routing, Python only), and every factor is asked in its OWN 7B session, one
factor at a time: functionality, UI/UX, user journey and creativity. Real-world value is never judged from code
chunks; it comes from the App Dossier as a whole.

The 7B answers the same checklist items as the dossier rubric (rubric.PASSES), with the same fixed choices plus
NOT_IN_THIS_CODE, and must quote the code lines behind each answer. Python then checks every quote against the actual
file: an answer whose quotes are not in the code is thrown out. The 7B never picks a number.

Answers from all chunks are then combined per checklist item (majority of the checked answers).
"""
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from letsvibe.evaluator.ollama import CpuSpilloverError
from letsvibe.evaluator.triage import content_role, name_role
from .rubric import PASSES

MODEL = "qwen2.5-coder:7b"
NOT_IN_CODE = "NOT_IN_THIS_CODE"
NOT_SHOWN = "NOT_SHOWN_IN_DOSSIER"

# Factors judged from code chunks, and the checklist items asked about each (same names as the dossier rubric).
# hostile_monetization stays with the Python scan; value is judged from the dossier only.
CODE_FIELDS: Dict[str, Tuple[str, ...]] = {
    "functionality": ("core_flow", "features_connected", "tells_user_about_problems", "confirms_success"),
    "ui_ux": ("clarity", "consistency", "feedback_while_working", "fits_its_device", "accessibility_labels"),
    "journey": ("launch_experience", "navigation_friction", "setup_burden", "state_and_save"),
    "creativity": ("has_distinct_voice", "subverts_standard_ui", "depth_of_world_or_concept", "mechanical_synergy"),
}
# Which file roles (evaluator/triage.py) each factor reads
FACTOR_ROLES: Dict[str, Tuple[str, ...]] = {
    "functionality": ("core", "io", "ui", "journey"),
    "ui_ux": ("ui", "journey"),
    "journey": ("journey", "ui"),
    "creativity": ("core", "ui", "content", "journey"),
}
_ENTRY = re.compile(r"(^|/)(main|app|index|__main__|server|cli|run|start|launch|tray)\.\w+$", re.I)

FACTOR_INTROS = {
    "functionality": "You are checking only FUNCTIONALITY: does the code in this chunk actually do what the app promises, "
                     "and does it tell people when something worked or went wrong?",
    "ui_ux": "You are checking only UI/UX: the screens, layouts, styles and on-screen feedback in this chunk.",
    "journey": "You are checking only the USER JOURNEY: launching or installing the app, first-run setup, navigation, "
               "settings, and whether people's work is saved.",
    "creativity": "You are checking only CREATIVITY: on-screen text with personality, unusual ways of using the app, "
                  "theming and world-building, and features that combine into one experience.",
}
SYSTEM = ("You read one chunk of a program's source code and answer a short checklist about ONE topic. You answer with "
          "fixed choices, and you copy exact lines from the code as evidence. If this chunk does not show something, "
          f"you answer {NOT_IN_CODE}. Respond with JSON only.")


# ---- routing (Python only) ------------------------------------------------------------------------

def chunk_files(chunk_text: str) -> List[str]:
    return list(dict.fromkeys(re.findall(r"--- START FILE: (.+?)(?: \[Part \d+\])? ---", chunk_text)))


def route(batches: List[Tuple[str, str]], files: Dict[str, str]) -> Dict[str, List[int]]:
    """{factor: [chunk index, ...]}. A chunk goes to a factor when one of its files has a role that factor reads.
    Files whose name says 'core' but whose contents are clearly screens, setup or I/O are counted by their contents."""
    out: Dict[str, List[int]] = {f: [] for f in CODE_FIELDS}
    for i, (_, text) in enumerate(batches):
        roles = set()
        for p in chunk_files(text):
            r = name_role(p)
            if r == "core":
                r = content_role(p, files.get(p, "")) or r
            roles.add(r)
            if _ENTRY.search(p):
                roles.add("journey")      # the program's entry point is where launch and first run happen
        for f, wanted in FACTOR_ROLES.items():
            if roles & set(wanted):
                out[f].append(i)
    return out


# ---- prompts --------------------------------------------------------------------------------------

def _question_lines(cat: str) -> Dict[str, str]:
    lines = {}
    for line in PASSES[cat]["questions"].splitlines():
        name, _, rest = line.partition(":")
        if name.strip() in CODE_FIELDS.get(cat, ()):
            lines[name.strip()] = rest.strip().replace(NOT_SHOWN, NOT_IN_CODE).replace("the dossier", "this code")
    return lines


def _choices(cat: str, fld: str) -> List[Any]:
    spec = PASSES[cat]["fields"][fld]["properties"]["answer"]
    if spec.get("type") == "boolean":
        return [True, False, NOT_IN_CODE]
    vals = [v for v in spec["enum"] if v != NOT_SHOWN]
    return vals + [NOT_IN_CODE]


def schema(cat: str) -> dict:
    props = {}
    for fld in CODE_FIELDS[cat]:
        choices = _choices(cat, fld)
        answer = {"enum": choices} if isinstance(choices[0], bool) else {"type": "string", "enum": choices}
        props[fld] = {"type": "object", "properties": {
            "answer": answer,
            "evidence": {"type": "array", "maxItems": 3, "items": {
                "type": "object", "properties": {"file": {"type": "string"}, "quote": {"type": "string"}},
                "required": ["file", "quote"]}}},
            "required": ["answer", "evidence"]}
    return {"type": "object", "properties": props, "required": list(props)}


def prompt(cat: str, chunk_text: str, platform_note: str = "") -> str:
    q = _question_lines(cat)
    items = "\n".join(f"{fld}: {q.get(fld, '')} Choices: {', '.join(str(c) for c in _choices(cat, fld))}."
                      for fld in CODE_FIELDS[cat])
    return (f"{chunk_text}\n\n---\n{FACTOR_INTROS[cat]}\n{platform_note}"
            "This is only part of the project. Answer only from the code above. For every answer other than "
            f"{NOT_IN_CODE}, give 1-3 pieces of evidence: the file name and ONE line copied exactly from that file "
            "(word for word, not a summary).\n\n" + items + "\n\nJSON only.")


# ---- quote checks (Python only) -------------------------------------------------------------------

def _ws(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def locate(quote: str, file_hint: str, files: Dict[str, str], candidates: List[str]) -> Optional[Tuple[str, int, str]]:
    """Finds a quoted line in the real file contents. Returns (file, line number, exact line) or None.
    The quote must be at least 8 non-space characters and appear in one line (whitespace-insensitive)."""
    q = _ws(quote).strip("`'\" ")
    if len(q.replace(" ", "")) < 8:
        return None
    order = [p for p in candidates if p == file_hint or p.endswith("/" + file_hint) or file_hint.endswith(p)]
    order += [p for p in candidates if p not in order]
    for p in order:
        body = files.get(p)
        if not body:
            continue
        for n, line in enumerate(body.splitlines(), 1):
            if q in _ws(line):
                return p, n, line.strip()
    return None


def check(answers: Dict[str, Any], cat: str, files: Dict[str, str], candidates: List[str]) -> Dict[str, Dict[str, Any]]:
    """Keeps only answers backed by at least one quote found in the code; records file and line for each quote."""
    out: Dict[str, Dict[str, Any]] = {}
    for fld in CODE_FIELDS[cat]:
        v = (answers or {}).get(fld)
        if not isinstance(v, dict) or "answer" not in v:
            continue
        ans = v["answer"]
        if ans == NOT_IN_CODE or ans not in _choices(cat, fld):
            continue
        found = []
        for ev in (v.get("evidence") or [])[:3]:
            if not isinstance(ev, dict):
                continue
            hit = locate(str(ev.get("quote", "")), str(ev.get("file", "")), files, candidates)
            if hit and hit not in found:
                found.append(hit)
        out[fld] = {"answer": ans, "verified": bool(found),
                    "evidence": [{"file": f, "line": n, "quote": q[:200]} for f, n, q in found]}
    return out


# ---- running and combining ------------------------------------------------------------------------

@dataclass
class CodeEvidence:
    answers: Dict[str, Dict[str, Dict[str, Any]]] = field(default_factory=dict)  # {factor: {item: combined answer}}
    per_chunk: List[Dict[str, Any]] = field(default_factory=list)               # every call, for the record
    calls: int = 0
    seconds: float = 0.0
    unsupported: int = 0          # answers thrown out because their quotes were not in the code
    routed: Dict[str, int] = field(default_factory=dict)
    failed_calls: int = 0


def combine(cat: str, chunk_answers: List[Dict[str, Dict[str, Any]]]) -> Dict[str, Dict[str, Any]]:
    """Per item: the answer most checked chunks gave. Ties go to the answer with more checked quotes, then to the one
    nearest the middle of the choices (never the most extreme on thin evidence)."""
    out: Dict[str, Dict[str, Any]] = {}
    for fld in CODE_FIELDS[cat]:
        got = [a[fld] for a in chunk_answers if fld in a and a[fld].get("verified")]
        if not got:
            continue
        votes = Counter(str(g["answer"]) for g in got)
        quotes = Counter()
        for g in got:
            quotes[str(g["answer"])] += len(g["evidence"])
        choices = [str(c) for c in _choices(cat, fld) if c != NOT_IN_CODE]
        mid = (len(choices) - 1) / 2.0
        best = max(votes, key=lambda a: (votes[a], quotes[a], -abs(choices.index(a) - mid) if a in choices else -99))
        evidence = [e for g in got if str(g["answer"]) == best for e in g["evidence"]]
        answer: Any = {"True": True, "False": False}.get(best, best)
        out[fld] = {"answer": answer, "evidence": evidence[:4], "votes": dict(votes), "chunks": len(got)}
    return out


def run(generate: Callable[..., Dict[str, Any]], batches: List[Tuple[str, str]], files: Dict[str, str],
        platform_note: str = "", progress: Optional[Callable[[str], None]] = None,
        check_time: Optional[Callable[[], None]] = None) -> CodeEvidence:
    """One 7B session per factor per routed chunk. `generate` is OllamaClient.generate_json (admin Stop applies)."""
    res = CodeEvidence()
    routes = route(batches, files)
    res.routed = {f: len(ix) for f, ix in routes.items()}
    total = sum(res.routed.values())
    done = 0
    for cat, indexes in routes.items():
        chunk_answers = []
        for i in indexes:
            if check_time:
                check_time()
            done += 1
            if progress:
                progress(f"Reading the code for {cat.replace('_', ' ')} only (7B, chunk {done} of {total})...")
            title, text = batches[i]
            t0 = time.perf_counter()
            raw: Dict[str, Any] = {}
            for attempt in range(2):
                try:
                    raw = generate(model=MODEL, system_prompt=SYSTEM, user_prompt=prompt(cat, text, platform_note),
                                   format_schema=schema(cat), max_output_tokens=700 + 500 * attempt, temperature=0.1)
                    break
                except CpuSpilloverError:      # includes the admin's Stop and the time limit
                    raise
                except (ValueError, RuntimeError):
                    raw = {}
                    continue
            secs = time.perf_counter() - t0
            res.calls += 1
            res.seconds += secs
            if not raw:
                res.failed_calls += 1
            checked = check(raw, cat, files, chunk_files(text))
            res.unsupported += sum(1 for v in checked.values() if not v["verified"])
            chunk_answers.append(checked)
            res.per_chunk.append({"factor": cat, "chunk": title, "seconds": round(secs, 1),
                                  "answers": {k: {"answer": v["answer"], "verified": v["verified"], "evidence": v["evidence"]}
                                              for k, v in checked.items()}})
        res.answers[cat] = combine(cat, chunk_answers)
    res.seconds = round(res.seconds, 1)
    return res
