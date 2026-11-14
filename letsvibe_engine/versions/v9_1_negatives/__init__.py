"""
Experience grading. Rubric v9 ("v9-hybrid") grades what people experience, never how the code is written, using two
independent sources of evidence that are compared item by item.

  1. Dossier        [Python]  what it says it is, screens, multi-device use, on-screen text, mechanics, setup burden,
                              launch, saving, hostile patterns (dossier.py); proven problems (analyzers/code_scan.py)
  2. Cliché check   [Python + small embedding model]  closest common vibe-coded archetype, as a plain fact (cliche.py)
  3. Code evidence  [7B]      the code in 5,200-token chunks; each factor in its own session, one at a time, only on the
                              chunks that can tell it something; a real "no" for every item; every quote checked against the
                              real file, praise for things people see must quote something visible, and a 7B yes/no check
                              that each quote shows its claim (code_evidence.py)
  4. Rubric         [14B]     five checklists on the dossier with fixed choices and exact quotes (rubric.py)
  5. Compare        [Python + 14B]  item by item; conflicts settled by the 14B rereading both sides' quoted lines (reconcile.py)
  6. Score          [Python]  fixed points per answer; weighted overall (scoring.py)
  7. Descriptions   [14B]     the model rewrites the checked answers, weakest first; "needs work" written by Python from
                              every problem and every answer that falls short (describe.py);
                              a public, unscored code complexity description written by Python (complexity.py)

A grade that runs past the time limit (3 hours by default, LETSVIBE_TIME_LIMIT_MIN) stops and publishes nothing.
A plain-Python scan for clearly malicious code (holding the report for the owner) exists but is switched off for now.
"""
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import json

from letsvibe.analyzers.code_scan import scan as code_scan
from letsvibe.analyzers.malicious_patterns import scan as malicious_scan
from letsvibe.storage.identity import parse_repo_identity
from letsvibe.core.models import DeterministicMetrics, DynamicWeights, FactorEvaluation, FactorType, ProjectArchetype, VibeReport
from letsvibe.evaluator.ollama import CpuSpilloverError
from . import cliche, code_evidence, complexity, describe, dossier, reconcile, rubric, scoring

MODEL = "qwen2.5-coder:14b"
CHUNK_MODEL = code_evidence.MODEL
# The malicious-pattern hold is switched off for now (Todd, 2026-11-12): it will be changed and turned back on later.
# The scan code stays in analyzers/malicious_patterns.py.
MALICIOUS_HOLD_ENABLED = False
RUBRIC_ID = "v9.1-hybrid"
TIME_LIMIT_MIN = float(os.environ.get("LETSVIBE_TIME_LIMIT_MIN", "180"))


class TimeLimitExceeded(CpuSpilloverError):
    """The grade ran past the time limit. A CpuSpilloverError so every stage stops at once and nothing is published."""


class _CallLog:
    """Wraps generate_json: enforces the time limit before every model call and records seconds per call and model."""

    def __init__(self, generate, deadline: float):
        self._generate, self.deadline = generate, deadline
        self.calls: Dict[str, list] = {}

    def check_time(self) -> None:
        if time.monotonic() > self.deadline:
            raise TimeLimitExceeded(f"Grading stopped: it ran past the {TIME_LIMIT_MIN:g}-minute limit. No grade was published.")

    def __call__(self, **kwargs):
        self.check_time()
        t0 = time.perf_counter()
        try:
            return self._generate(**kwargs)
        finally:
            self.calls.setdefault(kwargs.get("model", "?"), []).append(round(time.perf_counter() - t0, 2))

    def summary(self) -> Dict[str, float]:
        out: Dict[str, float] = {}
        for model, secs in self.calls.items():
            tag = model.split(":")[-1]
            out[f"calls_{tag}"] = len(secs)
            out[f"avg_call_{tag}_sec"] = round(sum(secs) / len(secs), 2) if secs else 0.0
            out[f"max_call_{tag}_sec"] = max(secs) if secs else 0.0
        return out


def _save_maintainer_notes(repo_source: str, notes: list, lines_of_code: int) -> None:
    """Code-health findings for the project's owner only: kept in the project's own report folder (deleted with the project
    or account, never in database backups), served only to the owner or an admin, never part of the score."""
    try:
        identity = parse_repo_identity(repo_source)
        if identity.provider != "github":
            return
        folder = identity.get_report_dir()
        (folder / "maintainer_notes.json").write_text(json.dumps({"lines_of_code": lines_of_code, "notes": notes[:200]}, indent=1))
    except Exception:
        pass


def _where(v: Dict[str, Any]) -> str:
    """' (app.py line 120)' for an answer backed by code, so findings point at something a person can check."""
    ev = v.get("code_evidence") or []
    return f" ({ev[0]['file']} line {ev[0]['line']})" if ev else ""


def _strengths(cat: str, answers: Dict[str, Any]) -> list:
    out = []
    if cat == "value":
        out += [t["twist"] for t in answers.get("specific_twists", []) if t.get("verified")]
    for k, v in answers.items():
        if k == "specific_twists" or not isinstance(v, dict):
            continue
        bad = scoring.PROBLEM_ANSWERS.get(k, set())
        table = scoring.POINTS[cat].get(k)
        if isinstance(table, dict) and v.get("answer") not in bad and table.get(v.get("answer"), 0) == max(table.values()):
            out.append(describe._meaning(k, v.get("answer")).capitalize() + _where(v))
    return out[:5]


def _solid_features(results: Dict[str, Dict[str, Any]]) -> list:
    """Verified twists first, then the best-scoring answers that point at a line of code."""
    out = [t["twist"] for t in results["value"].get("specific_twists", []) if t.get("verified")]
    for cat in scoring.WEIGHTS:
        for s in _strengths(cat, results[cat]):
            if s.endswith(")") and " line " in s and s not in out:
                out.append(f"{describe.TITLES[cat]}: {s}")
    return out[:5]


def _platform_note(classification) -> str:
    plats = ", ".join(getattr(classification, "platforms", []) or [])
    dev = getattr(classification, "device_profile", "") or ""
    if not plats and not dev:
        return ""
    return f"The app is made for: {plats or 'unknown platforms'}{' (' + dev + ')' if dev else ''}. Judge it for that device.\n"


def evaluate(client, packed_repo, repo_source: str, metrics: DeterministicMetrics, classification,
             progress: Optional[Callable[[str, int], None]] = None, submission_meta: Optional[Dict[str, Any]] = None) -> VibeReport:
    """Grades one repository. `client` is an OllamaClient (its generate_json carries the admin Stop check)."""
    emit = progress or (lambda msg, pct: None)
    timing: Dict[str, float] = {}
    issues = list(getattr(classification, "issues", []) or [])
    started = time.perf_counter()
    gen = _CallLog(client.generate_json, time.monotonic() + TIME_LIMIT_MIN * 60)

    t0 = time.perf_counter()
    emit("Building the app dossier (what people see and do)...", 22)
    data = dossier.build(Path(packed_repo.source_path))
    data["repo"] = packed_repo.repo_name
    found = code_scan(Path(packed_repo.source_path))
    proven = [f"{f['detail']} ({f['file']}" + (f" line {f['line']}" if f.get("line") else "") + ")" for f in found["functionality"]]
    data["proven_problems"] = (["## 5c. Proven problems (found by a program; certain)"] + [f"- {p}" for p in proven[:12]]) if proven else []
    md = dossier.render(data)
    timing["dossier_sec"] = round(time.perf_counter() - t0, 2)

    t0 = time.perf_counter()
    emit("Comparing with common vibe-coded app types...", 26)
    cliche_fact = ""
    try:
        top = cliche.closest(client.host, data)
        if top:
            cliche_fact = (f"Fact: the closest common app type is '{top[0]['archetype']}' "
                           f"({round(top[0]['similarity'] * 100)}% similar).\n")
    except Exception as e:  # the check is optional; grading continues without it
        issues.append(f"Archetype comparison skipped: {e}")
        top = []
    timing["cliche_sec"] = round(time.perf_counter() - t0, 2)

    # 3. Code evidence: every factor in its own 7B session, chunk by chunk (all 7B work first, so the GPU never swaps
    #    between models mid-stage)
    t0 = time.perf_counter()
    from letsvibe.evaluator.pipeline import build_batches
    batches, coverage = build_batches(packed_repo)
    emit(f"Reading the code one factor at a time (7B, {len(batches)} chunks)...", 30)
    code = code_evidence.run(gen, batches, packed_repo.files, _platform_note(classification),
                             progress=lambda m: emit(m, 30 + min(28, int(28 * len(gen.calls.get(CHUNK_MODEL, [])) /
                                                                         max(1, len(batches) * 4)))),
                             check_time=gen.check_time)
    timing["code_evidence_sec"] = round(time.perf_counter() - t0, 2)
    client.unload_all_models()

    t0 = time.perf_counter()
    emit("Answering the checklists from the dossier: value, creativity, journey, functionality, UI/UX (14B)...", 60)
    results, t = rubric.run(gen, MODEL, md, cliche_fact)
    timing.update(t)

    t0 = time.perf_counter()
    emit("Comparing the code evidence with the dossier; rereading the code where they disagree (14B)...", 74)
    results, decisions = reconcile.merge(results, code.answers, md, packed_repo.files, generate=gen, model=MODEL,
                                         check_time=gen.check_time)
    timing["compare_sec"] = round(time.perf_counter() - t0, 2)

    hostile = list(data["journey"].get("hostile_patterns", {}).keys())
    # The model's own hostile answer only counts with evidence from elsewhere in the dossier, never the scan's line
    hm = results["journey"].get("hostile_monetization") or {}
    scan_line = next((l for l in md.splitlines() if l.startswith("- Ads, payments, required sign-in")), "")
    if hm.get("answer") is True and all((q or "").strip() and (q.strip() in scan_line) for q in hm.get("evidence", [])):
        hm["verified"] = False
    cats = {c: scoring.category(c, results[c], hostile, len(found["functionality"]), found["lines_of_code"]) for c in scoring.WEIGHTS}
    scores = {c: v["score"] for c, v in cats.items()}
    final = scoring.overall(scores)

    t0 = time.perf_counter()
    emit("Writing the descriptions (14B)...", 85)
    texts, needs = describe.write(gen, MODEL, packed_repo.repo_name, results, proven[:5], hostile)
    summary = describe.summarize(gen, MODEL, packed_repo.repo_name, texts)
    timing["descriptions_sec"] = round(time.perf_counter() - t0, 2)
    client.unload_all_models()
    complexity_text = complexity.describe(metrics, found["maintainer"], found["lines_of_code"])

    timing.update(gen.summary())
    timing["total_sec"] = round(time.perf_counter() - started, 2)
    unsupported_dossier = sum(1 for cat in results.values() for v in cat.values()
                              if isinstance(v, dict) and v.get("answer") not in (None, reconcile.NOT_SHOWN)
                              and not v.get("verified") and not str(v.get("source", "")).startswith("conflict: neither"))

    concerns = malicious_scan(packed_repo.files) if MALICIOUS_HOLD_ENABLED else []
    _save_maintainer_notes(repo_source, found["maintainer"], found["lines_of_code"])
    weights = DynamicWeights(functionality=scoring.WEIGHTS["functionality"], user_journey=scoring.WEIGHTS["journey"], ui_ux=scoring.WEIGHTS["ui_ux"],
                             resonance=scoring.WEIGHTS["value"],
                             creativity=scoring.WEIGHTS["creativity"], code_health=0, operational_safety=0,
                             justification="Fixed weights: real-world value, creativity, user journey, functionality, then UI/UX. "
                                           "Code complexity is described but never scored.")
    factor_evals = {}
    for cat, fname in scoring.FACTOR_OF.items():
        w = scoring.WEIGHTS[cat]
        factor_evals[fname] = FactorEvaluation(
            factor=FactorType(fname), score=scores[cat], weight=w, weighted_score=round(scores[cat] * w / 100, 2),
            strengths=_strengths(cat, results[cat]), weaknesses=describe.problems(cat, results[cat], hostile if cat == "journey" else ()),
            reasoning=texts.get(cat, ""))

    from letsvibe.evaluator.consensus import calculate_letter_grade
    langs = metrics.languages or {}
    primary = max(langs, key=langs.get) if langs else "Multi-language"
    arch_answer = (results["value"].get("identified_archetype") or {}).get("answer") or packed_repo.repo_name
    archetype = ProjectArchetype(
        name=str(arch_answer)[:120], category=(top[0]["archetype"] if top else "General Software Project"), primary_language=primary,
        target_audience="People who use this kind of app", core_purpose=(data.get("readme_blurb") or "")[:300] or str(arch_answer),
        intended_scale="Vibe-coded project", general_category=classification.general_category, platforms=list(classification.platforms),
        device_profile=classification.device_profile)
    report = VibeReport(
        repo_name=packed_repo.repo_name, repo_source=repo_source, timestamp=datetime.now().isoformat(), archetype=archetype,
        weights=weights, deterministic_metrics=metrics, factor_evaluations=factor_evals, final_vibe_score=final,
        malware_risk_score=0.0 if concerns else 100.0, resonance_score=scores["value"], letter_grade=calculate_letter_grade(final),
        rubric_version="v9.1",
        peer_summary="", pro_next_steps=[], integrity_hold=bool(concerns),
        integrity_concerns=[{"file": c["file"], "code": c["code"]} for c in concerns],
        verdict_title=str(arch_answer)[:120], verdict_summary=summary,
        top_strengths=[s for c in scoring.WEIGHTS for s in _strengths(c, results[c])][:5], priority_improvements=needs,
        top_solid_features=_solid_features(results),
        top_features_needing_work=needs, timing_breakdown=timing, issues_encountered=issues,
        complexity=complexity_text,
        # Kept with the report for transparency: exactly which answer produced which points, and where each came from
        experience={"rubric_id": RUBRIC_ID, "cliche": top, "answers": results, "points": cats, "hostile_patterns": hostile,
                    "decisions": decisions,
                    "code_evidence": {"chunks": len(batches), "coverage": {k: list(v) for k, v in coverage.items()},
                                      "routed": code.routed, "calls": code.calls, "failed_calls": code.failed_calls,
                                      "seconds": code.seconds, "unsupported_answers_dropped": code.unsupported,
                                      "not_user_facing_quotes_rejected": code.not_user_facing,
                                      "answers_failing_relevance_check": code.irrelevant},
                    "unsupported_answers": {"code_dropped": code.unsupported, "dossier_unverified": unsupported_dossier}})
    return report
