"""
Stages 4-5 (rubric v9): compare the code evidence (7B, code_evidence.py) with the dossier answers (14B, rubric.py),
item by item, and settle conflicts by rereading the code.

  - both agree                         -> that answer
  - the dossier could not show it        -> the code answer (this is how the code fills what the dossier could not show)
  - they disagree                       -> conflict check, whether or not the dossier's quotes matched exactly, so a
                                          code answer can never silently replace a dossier answer (rubric v9 fix):: the 14B gets the exact quoted lines from both sides, with the
                                          lines around them, and must say which claim the code supports, quoting the
                                          deciding line. Python checks that quote. If neither claim holds up, the item
                                          counts as "not shown". Every decision is kept with the report.

Answers are never averaged. The merged answers keep the dossier rubric's format, so scoring.py and describe.py work
on them unchanged.
"""
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

from letsvibe.evaluator.ollama import CpuSpilloverError
from .code_evidence import CODE_FIELDS, NOT_SHOWN
from .rubric import PASSES

SYSTEM = ("You settle a disagreement between two reviews of the same app by reading the evidence yourself. You only "
          "trust what the quoted code and text actually show. Something that works in one place does not prove it works "
          "everywhere, and a line that writes to a log, print or console is never seen by the person using the app. "
          "Respond with JSON only.")
_SCHEMA = {"type": "object", "properties": {
    "supported": {"type": "string", "enum": ["A", "B", "NEITHER"]},
    "deciding_quote": {"type": "string"},
    "reason": {"type": "string"}}, "required": ["supported", "deciding_quote", "reason"]}
CONTEXT_LINES = 6


def _norm(t: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (t or "").lower()).strip()


def code_excerpt(files: Dict[str, str], file: str, line: int, around: int = CONTEXT_LINES) -> str:
    body = (files.get(file) or "").splitlines()
    if not body:
        return ""
    lo, hi = max(1, line - around), min(len(body), line + around)
    return "\n".join(f"{n:>5}  {body[n - 1]}" for n in range(lo, hi + 1))


def dossier_excerpt(dossier_md: str, quotes: List[str], around: int = 2) -> str:
    lines = dossier_md.splitlines()
    picked = set()
    for q in quotes:
        qn = _norm(q)
        if len(qn) < 4:
            continue
        for i, l in enumerate(lines):
            if qn in _norm(l):
                picked.update(range(max(0, i - around), min(len(lines), i + around + 1)))
                break
    return "\n".join(lines[i] for i in sorted(picked))


def _question(cat: str, fld: str) -> str:
    for line in PASSES[cat]["questions"].splitlines():
        if line.startswith(fld + ":"):
            return line.partition(":")[2].strip()
    return fld.replace("_", " ")


def _quote_in(q: str, material: str) -> bool:
    qn, mn = _norm(q), _norm(material)
    if len(qn) < 4:
        return False
    if qn in mn:
        return True
    words = qn.split()
    return len(words) >= 3 and any(sum(w in set(_norm(l).split()) for w in words) / len(words) >= 0.8
                                   for l in material.splitlines())


def judge(generate: Callable[..., Dict[str, Any]], model: str, cat: str, fld: str, dossier_ans: Dict[str, Any],
          code_ans: Dict[str, Any], dossier_md: str, files: Dict[str, str]) -> Dict[str, Any]:
    """One conflict check. Returns {"winner": "dossier"|"code"|"neither"|"undecided", "quote", "reason"}."""
    a_text = dossier_excerpt(dossier_md, [q for q in dossier_ans.get("evidence", []) if isinstance(q, str)])
    b_parts = [f"{e['file']} (lines around {e['line']}):\n{code_excerpt(files, e['file'], e['line'])}"
               for e in code_ans.get("evidence", [])[:3]]
    b_text = "\n\n".join(p for p in b_parts if p.strip())
    if not b_text:
        return {"winner": "undecided", "quote": "", "reason": "no code to show"}
    user = (f"Question about the app's {cat.replace('_', ' ')}: {fld.replace('_', ' ')}\n{_question(cat, fld)}\n\n"
            f"CLAIM A: the answer is {dossier_ans.get('answer')}.\nEvidence for A (from a written summary of the app):\n"
            f"{a_text or '(no lines)'}\n\n"
            f"CLAIM B: the answer is {code_ans.get('answer')}.\nEvidence for B (from the source code):\n{b_text}\n\n"
            "Read both pieces of evidence. Which claim does the evidence actually support? Answer A, B, or NEITHER. "
            "deciding_quote: copy the one line above (word for word) that decides it. reason: one short sentence.")
    try:
        out = generate(model=model, system_prompt=SYSTEM, user_prompt=user, format_schema=_SCHEMA,
                       max_output_tokens=300, temperature=0.1)
    except CpuSpilloverError:          # includes the admin's Stop and the time limit
        raise
    except (ValueError, RuntimeError) as e:
        return {"winner": "undecided", "quote": "", "reason": f"conflict check failed: {e}"}
    sup, quote = str(out.get("supported", "")).upper(), str(out.get("deciding_quote", ""))
    reason = str(out.get("reason", ""))[:300]
    if sup == "NEITHER":
        return {"winner": "neither", "quote": quote[:200], "reason": reason}
    if sup not in ("A", "B"):
        return {"winner": "undecided", "quote": "", "reason": "no clear answer"}
    if not _quote_in(quote, a_text + "\n" + b_text):
        return {"winner": "undecided", "quote": quote[:200], "reason": "the deciding quote was not in the evidence shown"}
    return {"winner": "dossier" if sup == "A" else "code", "quote": quote[:200], "reason": reason}


def _code_as_answer(c: Dict[str, Any]) -> Dict[str, Any]:
    ev = [f"{e['file']} line {e['line']}: {e['quote'][:120]}" for e in c.get("evidence", [])]
    if c.get("absence"):
        ev = [f"not found in any of the {c.get('chunks_read', 0)} parts of the code read for this"]
    return {"answer": c["answer"], "evidence": ev, "verified": True, "source": "code: nothing found" if c.get("absence") else "code",
            "code_evidence": c.get("evidence", [])}


def merge(results: Dict[str, Dict[str, Any]], code: Dict[str, Dict[str, Dict[str, Any]]], dossier_md: str,
          files: Dict[str, str], generate: Optional[Callable[..., Dict[str, Any]]] = None, model: str = "",
          check_time: Optional[Callable[[], None]] = None) -> Tuple[Dict[str, Dict[str, Any]], List[Dict[str, Any]]]:
    """Returns (merged answers in the dossier rubric's format, list of every decision)."""
    merged = {cat: dict(ans) for cat, ans in results.items()}
    decisions: List[Dict[str, Any]] = []
    for cat, items in code.items():
        for fld in CODE_FIELDS.get(cat, ()):
            c = items.get(fld)
            d = merged.get(cat, {}).get(fld)
            if not c:
                if d:
                    merged[cat][fld] = {**d, "source": "dossier"}
                continue
            # Any dossier answer counts here, even when its quotes did not match exactly (the 14B often paraphrases):
            # otherwise a code answer would replace a dossier negative without a conflict check.
            d_has = bool(d and d.get("answer") not in (None, NOT_SHOWN))
            entry = {"factor": cat, "item": fld, "dossier": (d or {}).get("answer"), "code": c["answer"],
                     "code_evidence": c.get("evidence", [])[:3], "code_absence": bool(c.get("absence")),
                     "dossier_quotes_matched": bool(d and d.get("verified"))}
            if not d_has:
                merged[cat][fld] = _code_as_answer(c)
                decisions.append({**entry, "result": "code fills a gap" + (" (nothing found in any relevant chunk)" if c.get("absence") else ""),
                                  "answer": c["answer"]})
            elif d["answer"] == c["answer"]:
                merged[cat][fld] = {**d, "source": "both", "code_evidence": c.get("evidence", []),
                                    "evidence": list(d.get("evidence", [])) + _code_as_answer(c)["evidence"][:1]}
                decisions.append({**entry, "result": "agree", "answer": d["answer"]})
            else:
                if check_time:
                    check_time()
                verdict = judge(generate, model, cat, fld, d, c, dossier_md, files) if generate else {"winner": "undecided"}
                w = verdict["winner"]
                if w == "code":
                    merged[cat][fld] = {**_code_as_answer(c), "source": "conflict: code"}
                elif w == "neither" and NOT_SHOWN in [str(x) for x in _choices_with_not_shown(cat, fld)]:
                    merged[cat][fld] = {"answer": NOT_SHOWN, "evidence": [], "verified": False, "source": "conflict: neither"}
                else:   # the dossier side won, or the check could not decide: the dossier answer stands (as in v8)
                    merged[cat][fld] = {**d, "source": "conflict: dossier" if w == "dossier" else f"conflict: {w}"}
                decisions.append({**entry, "result": f"conflict -> {w}", "answer": merged[cat][fld]["answer"],
                                  "deciding_quote": verdict.get("quote", ""), "reason": verdict.get("reason", "")})
    return merged, decisions


def _choices_with_not_shown(cat: str, fld: str) -> List[Any]:
    spec = PASSES[cat]["fields"][fld]["properties"]["answer"]
    return list(spec.get("enum", [True, False]))

