"""
Experience grading (rubric v8): grades what people experience, never how the code is written.

  1. Dossier       [Python]  what it says it is, screens, multi-device use, on-screen text, mechanics, setup burden,
                             launch, saving, hostile patterns (dossier.py)
  2. Cliché check  [Python + small embedding model]  closest common vibe-coded archetype, as a plain fact (cliche.py)
  3. Rubric        [14B]     three passes (value, creativity, journey) with fixed choices and exact quotes (rubric.py)
  4. Score         [Python]  fixed points per answer; weighted overall (scoring.py)
  5. Descriptions  [14B]     the model rewrites its own checked answers; "needs work" only from genuine problems (describe.py)

A plain-Python scan for clearly malicious code (holding the report for the owner) exists but is switched off for now.
"""
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import json

from letsvibe.analyzers.code_scan import scan as code_scan
from letsvibe.analyzers.malicious_patterns import scan as malicious_scan
from letsvibe.storage.identity import parse_repo_identity
from letsvibe.core.models import DeterministicMetrics, DynamicWeights, FactorEvaluation, FactorType, ProjectArchetype, VibeReport
from . import cliche, describe, dossier, rubric, scoring

MODEL = "qwen2.5-coder:14b"
# The malicious-pattern hold is switched off for now (Todd, 2026-11-12): it will be changed and turned back on later.
# The scan code stays in analyzers/malicious_patterns.py.
MALICIOUS_HOLD_ENABLED = False
RUBRIC_ID = "v8-experience"


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
            out.append(describe._meaning(k, v.get("answer")).capitalize())
    return out[:5]


def evaluate(client, packed_repo, repo_source: str, metrics: DeterministicMetrics, classification,
             progress: Optional[Callable[[str, int], None]] = None, submission_meta: Optional[Dict[str, Any]] = None) -> VibeReport:
    """Grades one repository. `client` is an OllamaClient (its generate_json carries the admin Stop check)."""
    emit = progress or (lambda msg, pct: None)
    timing: Dict[str, float] = {}
    issues = list(getattr(classification, "issues", []) or [])

    t0 = time.perf_counter()
    emit("Building the app dossier (what people see and do)...", 25)
    data = dossier.build(Path(packed_repo.source_path))
    data["repo"] = packed_repo.repo_name
    found = code_scan(Path(packed_repo.source_path))
    proven = [f"{f['detail']} ({f['file']}" + (f" line {f['line']}" if f.get("line") else "") + ")" for f in found["functionality"]]
    data["proven_problems"] = (["## 5c. Proven problems (found by a program; certain)"] + [f"- {p}" for p in proven[:12]]) if proven else []
    md = dossier.render(data)
    timing["dossier_sec"] = round(time.perf_counter() - t0, 2)

    t0 = time.perf_counter()
    emit("Comparing with common vibe-coded app types...", 32)
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

    emit("Answering the checklists: value, creativity, journey, functionality, UI/UX (14B)...", 40)
    results, t = rubric.run(client.generate_json, MODEL, md, cliche_fact)
    timing.update(t)

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
    texts, needs = describe.write(client.generate_json, MODEL, packed_repo.repo_name, results, proven[:5], hostile)
    summary = describe.summarize(client.generate_json, MODEL, packed_repo.repo_name, texts)
    timing["descriptions_sec"] = round(time.perf_counter() - t0, 2)
    client.unload_all_models()

    concerns = malicious_scan(packed_repo.files) if MALICIOUS_HOLD_ENABLED else []
    _save_maintainer_notes(repo_source, found["maintainer"], found["lines_of_code"])
    weights = DynamicWeights(functionality=scoring.WEIGHTS["functionality"], user_journey=scoring.WEIGHTS["journey"], ui_ux=scoring.WEIGHTS["ui_ux"],
                             resonance=scoring.WEIGHTS["value"],
                             creativity=scoring.WEIGHTS["creativity"], code_health=0, operational_safety=0,
                             justification="Fixed weights: real-world value, creativity, user journey, functionality, then UI/UX.")
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
        rubric_version="v8",
        peer_summary="", pro_next_steps=[], integrity_hold=bool(concerns),
        integrity_concerns=[{"file": c["file"], "code": c["code"]} for c in concerns],
        verdict_title=str(arch_answer)[:120], verdict_summary=summary,
        top_strengths=[s for c in scoring.WEIGHTS for s in _strengths(c, results[c])][:5], priority_improvements=needs,
        top_solid_features=[t["twist"] for t in results["value"].get("specific_twists", []) if t.get("verified")][:5],
        top_features_needing_work=needs, timing_breakdown=timing, issues_encountered=issues,
        # Kept with the report for transparency: exactly which answer produced which points
        experience={"rubric_id": RUBRIC_ID, "cliche": top, "answers": results, "points": cats, "hostile_patterns": hostile})
    return report
