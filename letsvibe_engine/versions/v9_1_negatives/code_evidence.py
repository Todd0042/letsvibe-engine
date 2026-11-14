"""
Stage 3 (rubric v9): per-factor code evidence from the 7B.

The code is cut into the same 5,200-token chunks as rubric v7 (evaluator/pipeline.build_batches). Each chunk is sent
only to the factors it can tell us about (routing, Python only), and every factor is asked in its OWN 7B session, one
factor at a time: functionality, UI/UX, user journey and creativity. Real-world value is never judged from code
chunks; it comes from the App Dossier as a whole.

The 7B answers the same checklist items as the dossier rubric (rubric.PASSES) with a full set of choices: the good
answers, the middle ones, a real "no" for every item (for example NOT_SHOWN_TO_USER: errors are only logged), and
NOT_IN_THIS_CODE. It is never asked to find problems or praise, and never told how many of either to give. Every
answer other than NOT_IN_THIS_CODE must quote the code behind it: for a "no", the code where the app falls short.
The 7B never picks a number. Checks, all before an answer can count:

  1. Python finds every quote in the real file (invented quotes are dropped).
  2. For things people see (messages, confirmations, loading feedback, accessibility labels), a quote that praises
     must be something a person sees: log, print and console lines are rejected by Python.
  3. Combining chunks: when checked answers disagree, the middle answer is used (never the majority of the good
     parts). Whole-app items (works end to end, features connected, one consistent look, features working together)
     need checked evidence from at least two files. "Nothing there" and "no setup / straight to the main thing" count
     only when every chunk routed to the factor was read without a failed call.
  4. The 7B checks each remaining answer against its quoted lines with a yes/no question ("does this code show
     that ...?"); evidence that does not show the claim is dropped, and an answer left without evidence is dropped.
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
# The real "no" for items whose dossier choices have none (the dossier can only say "not shown")
CODE_NEGATIVES = {"tells_user_about_problems": "NOT_SHOWN_TO_USER", "confirms_success": "NOT_SHOWN_TO_USER",
                  "feedback_while_working": "NONE", "accessibility_labels": "NONE"}
# Items about things people see: praise must quote something visible (fix for log lines counted as messages)
USER_FACING = ("tells_user_about_problems", "confirms_success", "feedback_while_working", "accessibility_labels")
# Items about the whole app: a single chunk cannot show them, so they need evidence from 2+ files
WHOLE_APP = ("core_flow", "features_connected", "consistency", "mechanical_synergy")
MIN_FILES_WHOLE_APP = 2
# Claims that something is absent: only from a complete read of the factor's chunks
ABSENCE_CLAIMS = {"setup_burden": {"NONE"}, "navigation_friction": {"STRAIGHT_TO_CORE"}}
# Choices that are not on the good-to-bad scale (left out of the middle-answer rule)
OFF_SCALE = {"state_and_save": {"NOT_NEEDED"}}

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
          "fixed choices and copy exact lines from the code as evidence. Good, middling and bad answers are all normal; "
          f"choose the one the code shows. Most chunks show nothing about some items: then answer {NOT_IN_CODE}. "
          "Respond with JSON only.")
NEGATIVE_HELP = {
    "tells_user_about_problems": "NOT_SHOWN_TO_USER = errors in this code are caught and only logged, printed or ignored, "
                                 "so the person is never told (quote that line).",
    "confirms_success": "NOT_SHOWN_TO_USER = actions in this code finish without telling the person it worked (quote the line "
                        "where the action finishes).",
    "feedback_while_working": "NONE = slow work here (loading, downloading, processing) shows nothing while people wait "
                              "(quote the line that starts the slow work).",
    "accessibility_labels": "NONE = screens or controls here have no labels for screen readers (quote a control without one).",
}

# User-facing evidence: log/print/console lines never count as something a person sees
_LOG_LINE = re.compile(r"\b(print|println|printf|eprint(ln)?|console\.(log|warn|error|info|debug)|log(ger|ging)?\.(debug|info|"
                       r"warn(ing)?|error|exception|critical)|Log\.[dviwe]|Timber\.[dviwe]|System\.(out|err)\.|NSLog|debugPrint|"
                       r"sys\.std(out|err)\.write|traceback\.print_exc)\s*\(", re.I)
_VISIBLE = {
    "tells_user_about_problems": re.compile(r"[\"'`][^\"'`]{3,}[\"'`]|toast|snackbar|alert\(|dialog|messagebox|showerror|"
                                            r"showwarning|flash\(|setError|\.error\s*=|errorText|notify|banner", re.I),
    "confirms_success": re.compile(r"[\"'`][^\"'`]{3,}[\"'`]|toast|snackbar|alert\(|dialog|messagebox|showinfo|flash\(|notify|"
                                   r"banner|success", re.I),
    "feedback_while_working": re.compile(r"spinner|progress|loading|skeleton|placeholder|empty|busy|indeterminate|"
                                         r"[\"'`][^\"'`]*(loading|please wait|working|downloading|processing)[^\"'`]*[\"'`]", re.I),
    "accessibility_labels": re.compile(r"aria-|\balt\s*=|contentDescription|accessibilityLabel|accessibilityHint|semantics|"
                                       r"\brole\s*=|setAccessibleName|AutomationProperties|tooltip", re.I),
}


def is_user_facing(fld: str, line: str) -> bool:
    if _LOG_LINE.search(line):
        return False
    rx = _VISIBLE.get(fld)
    return bool(rx.search(line)) if rx else True


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
            text = re.sub(r",? or NOT_SHOWN_IN_DOSSIER[^.]*\.?|Use NOT_SHOWN_IN_DOSSIER[^.]*\.|Same rule for NOT_SHOWN_IN_DOSSIER\.",
                          "", rest.strip())
            text = re.sub(r"\s*\(see [^)]*\)|;? see the share of technical wording", "", text)
            lines[name.strip()] = text.replace("the dossier", "this code").strip()
    return lines


def _choices(cat: str, fld: str) -> List[Any]:
    """The item's choices in scale order (as in rubric.PASSES), its real 'no' where the dossier has none, then NOT_IN_THIS_CODE."""
    spec = PASSES[cat]["fields"][fld]["properties"]["answer"]
    if spec.get("type") == "boolean":
        return [True, False, NOT_IN_CODE]
    vals = [v for v in spec["enum"] if v != NOT_SHOWN]
    if fld in CODE_NEGATIVES:
        vals.append(CODE_NEGATIVES[fld])
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
    items = "\n".join(f"{fld}: {q.get(fld, '')} {NEGATIVE_HELP.get(fld, '')} "
                      f"Choices: {', '.join(str(c) for c in _choices(cat, fld))}." for fld in CODE_FIELDS[cat])
    return (f"{chunk_text}\n\n---\n{FACTOR_INTROS[cat]}\n{platform_note}"
            "This is only part of the project. Answer only from the code above. For every answer other than "
            f"{NOT_IN_CODE}, give 1-3 pieces of evidence: the file name and ONE line copied exactly from that file "
            "(word for word, not a summary). For an answer that says something is missing or falls short, quote the line "
            "where it falls short. Messages written to a log, print or console are not seen by the person using the app.\n\n"
            + items + "\n\nJSON only.")


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


def _is_negative(cat: str, fld: str, ans: Any) -> bool:
    from .scoring import shortfall
    return shortfall(fld, ans) > 0


def check(answers: Dict[str, Any], cat: str, files: Dict[str, str], candidates: List[str]) -> Dict[str, Dict[str, Any]]:
    """Keeps only answers backed by at least one quote found in the code; records file and line for each quote. For
    things people see, praise must quote a visible line (never a log/print/console line)."""
    out: Dict[str, Dict[str, Any]] = {}
    for fld in CODE_FIELDS[cat]:
        v = (answers or {}).get(fld)
        if not isinstance(v, dict) or "answer" not in v:
            continue
        ans = v["answer"]
        if ans == NOT_IN_CODE or ans not in _choices(cat, fld):
            continue
        found, rejected = [], 0
        for ev in (v.get("evidence") or [])[:3]:
            if not isinstance(ev, dict):
                continue
            hit = locate(str(ev.get("quote", "")), str(ev.get("file", "")), files, candidates)
            if not hit or hit in found:
                continue
            if fld in USER_FACING and not _is_negative(cat, fld, ans) and not is_user_facing(fld, hit[2]):
                rejected += 1          # e.g. a log line offered as "tells the user"
                continue
            found.append(hit)
        out[fld] = {"answer": ans, "verified": bool(found), "not_user_facing": rejected,
                    "evidence": [{"file": f, "line": n, "quote": q[:200]} for f, n, q in found]}
    return out


# ---- combining chunks -----------------------------------------------------------------------------

def middle_answer(cat: str, fld: str, answers: List[str]) -> Optional[str]:
    """When checked chunk answers disagree: the answer whose points sit closest to halfway between the best and the
    worst answer given (ties go to the lower one). CLEAR + CLUTTERED -> MIXED; CLEAR + MIXED -> MIXED."""
    from .scoring import POINTS
    table = {str(k): v for k, v in (POINTS.get(cat, {}).get(fld) or {}).items()}
    scale = [c for c in (str(x) for x in _choices(cat, fld)) if c in table and c != NOT_SHOWN and c not in OFF_SCALE.get(fld, set())]
    given = [a for a in answers if a in scale]
    if not given:
        return Counter(answers).most_common(1)[0][0] if answers else None
    target = (min(table[a] for a in given) + max(table[a] for a in given)) / 2.0
    return min(scale, key=lambda c: (abs(table[c] - target), table[c]))


def combine(cat: str, chunk_answers: List[Dict[str, Dict[str, Any]]], complete: bool = True) -> Dict[str, Dict[str, Any]]:
    """Per item, from the checked chunk answers:
    - all agree -> that answer; they disagree -> the middle answer between the best and worst given (middle_answer;
      booleans: left to the dossier), so good chunks never outvote the rest;
    - whole-app items need evidence from MIN_FILES_WHOLE_APP different files;
    - no chunk showed it (a 'no' item) and every chunk was read -> the 'no' answer, with no quote (absence);
    - 'no setup' / 'straight to the main thing' only when every chunk was read."""
    out: Dict[str, Dict[str, Any]] = {}
    for fld in CODE_FIELDS[cat]:
        got = [a[fld] for a in chunk_answers if fld in a and a[fld].get("verified")]
        if not got:
            if fld in CODE_NEGATIVES and complete and chunk_answers:
                out[fld] = {"answer": CODE_NEGATIVES[fld], "evidence": [], "votes": {}, "chunks": 0, "absence": True,
                            "chunks_read": len(chunk_answers)}
            continue
        votes = Counter(str(g["answer"]) for g in got)
        if len(votes) == 1:
            best = next(iter(votes))
        elif isinstance(_choices(cat, fld)[0], bool):
            continue                  # true in one chunk, false in another: the dossier decides
        else:
            best = middle_answer(cat, fld, [str(g["answer"]) for g in got])
            if best is None:
                continue
        if best in ABSENCE_CLAIMS.get(fld, set()) and not complete:
            continue
        evidence = [e for g in got if str(g["answer"]) == best for e in g["evidence"]]
        if not evidence:              # the middle answer no chunk gave: keep the evidence of the answers around it
            evidence = [e for g in got for e in g["evidence"]]
        if fld in WHOLE_APP and len({e["file"] for e in evidence}) < MIN_FILES_WHOLE_APP:
            continue
        answer: Any = {"True": True, "False": False}.get(best, best)
        out[fld] = {"answer": answer, "evidence": evidence[:4], "votes": dict(votes), "chunks": len(got)}
    return out


# ---- relevance check (7B yes/no) ------------------------------------------------------------------

_RELEVANCE_SCHEMA = {"type": "object", "properties": {"supporting": {"type": "array", "items": {"type": "integer"}}},
                     "required": ["supporting"]}
RELEVANCE_SYSTEM = ("You check whether lines of code show a specific claim about an app. Be strict: a line that is only "
                    "related, or only logs or prints something, does not show it. Respond with JSON only.")


def claim_text(cat: str, fld: str, answer: Any) -> str:
    from .describe import _meaning
    return _meaning(fld, answer)


def excerpt(files: Dict[str, str], file: str, line: int, around: int = 3) -> str:
    body = (files.get(file) or "").splitlines()
    lo, hi = max(1, line - around), min(len(body), line + around)
    return "\n".join(f"{n:>5}  {body[n - 1]}" for n in range(lo, hi + 1))


def relevance(generate: Callable[..., Dict[str, Any]], cat: str, fld: str, item: Dict[str, Any],
              files: Dict[str, str]) -> List[Dict[str, Any]]:
    """Returns the evidence the 7B confirms shows the claim (an empty list drops the answer)."""
    ev = item.get("evidence", [])[:4]
    if not ev:
        return []
    blocks = "\n\n".join(f"[{i}] {e['file']} line {e['line']}:\n{excerpt(files, e['file'], e['line'])}" for i, e in enumerate(ev, 1))
    user = (f"Claim about the app's {cat.replace('_', ' ')}: {claim_text(cat, fld, item['answer'])}.\n\n{blocks}\n\n"
            "Which numbered pieces of code, on their own, show this claim is true? List their numbers in 'supporting' "
            "(an empty list if none do).")
    try:
        out = generate(model=MODEL, system_prompt=RELEVANCE_SYSTEM, user_prompt=user, format_schema=_RELEVANCE_SCHEMA,
                       max_output_tokens=120, temperature=0.0)
    except CpuSpilloverError:          # includes the admin's Stop and the time limit
        raise
    except (ValueError, RuntimeError):
        return []
    keep = {int(n) for n in (out.get("supporting") or []) if isinstance(n, (int, float)) or str(n).isdigit()}
    return [e for i, e in enumerate(ev, 1) if i in keep]


# ---- running --------------------------------------------------------------------------------------

@dataclass
class CodeEvidence:
    answers: Dict[str, Dict[str, Dict[str, Any]]] = field(default_factory=dict)  # {factor: {item: combined answer}}
    per_chunk: List[Dict[str, Any]] = field(default_factory=list)               # every call, for the record
    calls: int = 0
    seconds: float = 0.0
    unsupported: int = 0          # answers thrown out because their quotes were not in the code
    not_user_facing: int = 0      # quotes rejected because people never see them (log/print/console lines)
    irrelevant: int = 0           # answers dropped by the relevance check
    routed: Dict[str, int] = field(default_factory=dict)
    failed_calls: int = 0


def run(generate: Callable[..., Dict[str, Any]], batches: List[Tuple[str, str]], files: Dict[str, str],
        platform_note: str = "", progress: Optional[Callable[[str], None]] = None,
        check_time: Optional[Callable[[], None]] = None) -> CodeEvidence:
    """One 7B session per factor per routed chunk, then one relevance check per combined answer.
    `generate` is OllamaClient.generate_json (admin Stop and the time limit apply)."""
    res = CodeEvidence()
    routes = route(batches, files)
    res.routed = {f: len(ix) for f, ix in routes.items()}
    total = sum(res.routed.values())
    done = 0
    for cat, indexes in routes.items():
        chunk_answers, failed = [], 0
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
                failed += 1
            checked = check(raw, cat, files, chunk_files(text))
            res.unsupported += sum(1 for v in checked.values() if not v["verified"])
            res.not_user_facing += sum(v.get("not_user_facing", 0) for v in checked.values())
            chunk_answers.append(checked)
            res.per_chunk.append({"factor": cat, "chunk": title, "seconds": round(secs, 1),
                                  "answers": {k: {"answer": v["answer"], "verified": v["verified"], "evidence": v["evidence"]}
                                              for k, v in checked.items()}})
        combined = combine(cat, chunk_answers, complete=bool(indexes) and failed == 0)
        if progress:
            progress(f"Checking that the quoted code really shows each {cat.replace('_', ' ')} answer (7B)...")
        for fld, item in list(combined.items()):
            if item.get("absence"):
                continue              # nothing quoted: decided by a complete read, not by a quote
            if check_time:
                check_time()
            kept = relevance(generate, cat, fld, item, files)
            if not kept or (fld in WHOLE_APP and len({e["file"] for e in kept}) < MIN_FILES_WHOLE_APP):
                res.irrelevant += 1
                del combined[fld]
            else:
                item["evidence"] = kept
        res.answers[cat] = combined
    res.seconds = round(res.seconds, 1)
    return res
