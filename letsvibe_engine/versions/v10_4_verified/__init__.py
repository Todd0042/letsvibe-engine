"""Engine v10.1 (testing): Profile-Adaptive Discrete Rubric on 30B-A3B --cpu-moe.

Combines v10's fast unified llama.cpp --cpu-moe batch code audit with v9.4-style
deterministic discrete checklist scoring, adapted per detected project profile
(CLI/MCP, Game/Sim, Web/Mobile/Media/General) and deterministic seed=0 sampling.
"""

from __future__ import annotations

import inspect
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from letsvibe.analyzers.code_scan import scan as code_scan
from letsvibe.analyzers.host_headers import discover_in_repo_host_headers
from letsvibe.analyzers.malicious_patterns import scan as malicious_scan
from letsvibe.core.models import (
    DeterministicMetrics,
    DynamicWeights,
    FactorEvaluation,
    FactorType,
    ProjectArchetype,
    VibeReport,
)
from letsvibe.evaluator.consensus import calculate_letter_grade
from letsvibe.evaluator.pipeline import select_for_review
from letsvibe.storage.identity import parse_repo_identity
from letsvibe_engine.versions.v10_4_verified import verify as claim_verify
from letsvibe_engine.versions.v9_3_archetypes import (
    cliche,
    complexity,
    context,
    dossier,
    enginelog,
)

from . import profile_detect, prompts, rubric
from .llama_client import LlamaMoeClient

RUBRIC_ID = "v10.4-verified"
MALICIOUS_HOLD_ENABLED = False
MAX_BATCH_TOKENS = int(os.environ.get("LETSVIBE_V10_BATCH_TOKENS", "12000"))
MAX_BATCHES = int(os.environ.get("LETSVIBE_V10_MAX_BATCHES", "6"))
TIME_LIMIT_MIN = float(os.environ.get("LETSVIBE_TIME_LIMIT_MIN", "60"))


def _platform_note(classification: Any) -> str:
    plats = ", ".join(getattr(classification, "platforms", []) or [])
    dev = getattr(classification, "device_profile", "") or ""
    if not plats and not dev:
        return ""
    return f"The app is made for: {plats or 'unknown platforms'}{' (' + dev + ')' if dev else ''}. Judge it for that device.\n"


def _str_list(items: Any, limit: int = 6) -> List[str]:
    if not isinstance(items, list):
        return []
    out: List[str] = []
    for item in items:
        s = str(item).strip()
        if s and s not in out:
            out.append(s)
        if len(out) >= limit:
            break
    return out


def evaluate(
    client: Any,
    packed_repo: Any,
    repo_source: str,
    metrics: DeterministicMetrics,
    classification: Any,
    progress: Optional[Callable[[str, int], None]] = None,
    submission_meta: Optional[Dict[str, Any]] = None,
) -> VibeReport:
    """Grade one repository using Engine v10.1 (profile-adaptive discrete rubric)."""
    try:
        slug = parse_repo_identity(repo_source).full_slug
    except Exception:
        slug = packed_repo.repo_name
    log = enginelog.GradingLog(slug, RUBRIC_ID)
    try:
        report = _evaluate(
            client,
            packed_repo,
            repo_source,
            metrics,
            classification,
            progress,
            log,
            submission_meta=submission_meta,
        )
    except BaseException as exc:
        log.finish(f"STOPPED: {type(exc).__name__}: {exc}")
        raise
    log.step(
        "scores",
        {
            "final": report.final_vibe_score,
            "letter": report.letter_grade,
            "factors": {k: v.score for k, v in report.factor_evaluations.items()},
        },
    )
    log.step("timing", report.timing_breakdown)
    log.finish(f"graded {report.final_vibe_score} {report.letter_grade}")
    return report


def verify_and_cap(scores: Dict[str, float], factors_block: Dict[str, Any], repo_index: "claim_verify.RepoIndex"):
    """v10.4 1a + 1d on the model's per-factor answers: drop weaknesses the repo's code disproves, then cap each
    factor that still lists weaknesses (scores is updated in place). Returns (verified weaknesses per category,
    dropped claims, caps applied). Code Health is computed from the scan, not written by the model: not checked."""
    verified: Dict[str, List[str]] = {}
    dropped_claims: List[Dict[str, str]] = []
    capped: List[Dict[str, Any]] = []
    for cat, fname in rubric.FACTOR_OF.items():
        if cat == "code_health":
            continue
        raw = _str_list((factors_block.get(cat) or {}).get("weaknesses"), limit=5)
        kept, dropped = claim_verify.verify_claims(raw, repo_index)
        verified[cat] = kept
        dropped_claims += [{"factor": fname, "claim": d.claim, "reason": d.reason} for d in dropped]
        cap = rubric.cap_for_weaknesses(len(kept))
        if scores.get(cat, 0) > cap:
            capped.append({"factor": fname, "from": scores[cat], "to": cap, "weaknesses": len(kept)})
            scores[cat] = cap
    return verified, dropped_claims, capped


def _evaluate(
    client: Any,
    packed_repo: Any,
    repo_source: str,
    metrics: DeterministicMetrics,
    classification: Any,
    progress: Optional[Callable[[str, int], None]],
    log: "enginelog.GradingLog",
    submission_meta: Optional[Dict[str, Any]] = None,
) -> VibeReport:
    emit = progress or (lambda msg, pct: None)
    started = time.perf_counter()
    timing: Dict[str, float] = {}
    issues = list(getattr(classification, "issues", []) or [])

    unload = getattr(client, "unload_all_models", None)
    if callable(unload):
        try:
            unload()
        except Exception:
            pass

    llama = LlamaMoeClient(
        cancel_check_client=client,
        deadline_monotonic=time.monotonic() + TIME_LIMIT_MIN * 60,
    )
    llama.check_health()

    # 1. Deterministic dossier + static scan + structural profile signals
    t0 = time.perf_counter()
    emit("Building app dossier and scanning code...", 18)
    data = dossier.build(Path(packed_repo.source_path))
    data["repo"] = packed_repo.repo_name
    # v10.4: intent-aware swallowed-error rules (expected exceptions, explained or visibly logged handling don't count;
    # Rust and Go are scanned). An older letsvibe analyzer without them falls back to the original rules, said in the log.
    if "intent_aware" in inspect.signature(code_scan).parameters:
        found = code_scan(Path(packed_repo.source_path), intent_aware=True)
    else:
        found = code_scan(Path(packed_repo.source_path))
        log.step("note", "letsvibe's code_scan has no intent-aware rules yet (deploy letsvibe engine-v10.4): original rules used")
    in_repo_host_ctx = discover_in_repo_host_headers(Path(packed_repo.source_path), packed_repo.files)
    proven = [
        f"{f['detail']} ({f['file']}" + (f" line {f['line']}" if f.get("line") else "") + ")"
        for f in found["functionality"]
    ]
    data["proven_problems"] = (
        (["## 5c. Proven problems (found by a program; certain)"] + [f"- {p}" for p in proven[:12]])
        if proven
        else []
    )
    md = dossier.render(data)
    timing["dossier_sec"] = round(time.perf_counter() - t0, 2)

    t0 = time.perf_counter()
    try:
        ident = parse_repo_identity(repo_source)
        ctx_sources = context.gather(
            Path(packed_repo.source_path),
            ident.owner,
            ident.repo_name,
            data,
            dossier.files_of(Path(packed_repo.source_path)),
            submission_meta=submission_meta,
        )
    except Exception as exc:
        issues.append(f"Project context skipped: {exc}")
        ctx_sources = {}
    ctx_sources_text = context.sources_text(ctx_sources) if ctx_sources else "(none)"

    structural_signals = profile_detect.extract_structural_signals(
        packed_repo.files,
        readme_raw=str(getattr(metrics, "readme_excerpt", "") or data.get("readme_blurb") or ""),
        kind_hint=str(getattr(classification, "general_category", "") or ""),
    )
    timing["context_gather_sec"] = round(time.perf_counter() - t0, 2)

    cliche_fact = ""
    top: List[Dict[str, Any]] = []
    if getattr(client, "host", None):
        try:
            top = cliche.closest(client.host, data)
            if top:
                cliche_fact = (
                    f"Closest common app type: '{top[0]['archetype']}' "
                    f"({round(top[0]['similarity'] * 100)}% similar).\n"
                )
        except Exception:
            top = []

    platform_note = _platform_note(classification)

    # 2. Stage 1: Context + Dossier + Profile Arbitration (1 call)
    t0 = time.perf_counter()
    emit("v10.1 (30B-A3B): classifying project profile & context...", 28)
    ctx_json = llama.generate_json(
        stage="context_dossier",
        system_prompt=prompts.SYSTEM_AUDITOR,
        user_prompt=prompts.build_context_prompt(
            packed_repo.repo_name,
            md,
            ctx_sources_text,
            platform_note,
            cliche_fact,
            structural_signals,
        ),
        max_tokens=1200,
        temperature=0.0,
        seed=0,
    )
    timing["context_llm_sec"] = round(time.perf_counter() - t0, 2)

    explicit_profile = (submission_meta or {}).get("project_profile")
    profile_key, profile_data, detection_method = profile_detect.resolve_project_profile(
        explicit_profile,
        structural_signals,
        ctx_json.get("project_profile"),
    )
    rubric_family = rubric.rubric_family_for_profile(profile_key)
    log.step(
        "v10.1 profile",
        {
            "profile_key": profile_key,
            "rubric_family": rubric_family,
            "method": detection_method,
            "signals": structural_signals,
        },
        limit=8000,
    )

    # 3. Stage 2: Deep code audit in large 12k-token batches
    t0 = time.perf_counter()
    keep, coverage, _ = select_for_review(packed_repo.files)
    batches = packed_repo.get_coverage_manifests(
        max_batch_tokens=MAX_BATCH_TOKENS, distill=True, only=keep, local_tree=True
    )
    if len(batches) > MAX_BATCHES:
        batches = batches[:MAX_BATCHES]

    batch_findings: List[Dict[str, Any]] = []
    total_batches = max(1, len(batches))
    purpose = str(ctx_json.get("purpose") or data.get("readme_blurb") or packed_repo.repo_name)
    runtime_envelope = str(structural_signals.get("runtime_envelope") or "unknown_or_general")
    for idx, (label, batch_code) in enumerate(batches, start=1):
        pct = 35 + int(35 * (idx - 1) / total_batches)
        emit(f"v10.4 (30B-A3B): auditing code batch {idx}/{total_batches}...", pct)
        finding = llama.generate_json(
            stage=f"batch_{idx}",
            system_prompt=prompts.SYSTEM_AUDITOR,
            user_prompt=prompts.build_batch_audit_prompt(
                packed_repo.repo_name,
                purpose,
                idx,
                total_batches,
                label,
                batch_code,
                platform_note,
                runtime_envelope=runtime_envelope,
            ),
            max_tokens=1500,
            temperature=0.0,
            seed=0,
        )
        finding["batch_label"] = label
        batch_findings.append(finding)
    timing["code_audit_sec"] = round(time.perf_counter() - t0, 2)
    log.step("v10.4 batch findings", batch_findings, limit=20000)

    # 4. Stage 3A: Profile-adaptive discrete checklist (LLM never picks raw 0-100 numbers)
    t0 = time.perf_counter()
    emit(f"v10.4 ({rubric_family}): evaluating adaptive discrete checklist...", 78)
    hostile = list((data.get("journey") or {}).get("hostile_patterns", {}).keys())
    det_summary = {
        "total_files": metrics.total_files,
        "lines_of_code": found["lines_of_code"],
        "languages": metrics.languages,
        "has_tests": metrics.test_files_count > 0,
        "test_files_count": metrics.test_files_count,
        "platforms": list(getattr(classification, "platforms", []) or []),
        "general_category": getattr(classification, "general_category", "Unknown"),
        "project_profile": profile_key,
        "rubric_family": rubric_family,
        "runtime_envelope": runtime_envelope,
        "option_docs": found.get("option_docs") or {},
    }
    scoring_prompt = prompts.build_scoring_prompt(
        packed_repo.repo_name,
        profile_key,
        profile_data,
        rubric_family,
        ctx_json,
        batch_findings,
        proven,
        hostile,
        det_summary,
        submission_meta=submission_meta,
        in_repo_host_context=in_repo_host_ctx,
        runtime_envelope=runtime_envelope,
    )
    scoring_json = llama.generate_json(
        stage="scoring_checklist",
        system_prompt=prompts.SYSTEM_AUDITOR,
        user_prompt=scoring_prompt,
        max_tokens=1800,
        temperature=0.0,
        seed=0,
    )
    checklist = scoring_json.get("checklist") if isinstance(scoring_json.get("checklist"), dict) else {}
    required_cats = set(rubric.WEIGHTS.keys()) - {"code_health"}
    missing_cats = [c for c in required_cats if not isinstance(checklist.get(c), dict)]
    if missing_cats:
        retry_prompt = (
            scoring_prompt
            + f"\n\nCRITICAL: Your previous response omitted required checklist sections: {missing_cats}. "
            + "You MUST include ALL 5 sections under `checklist`: value, functionality, creativity, ui_ux, journey."
        )
        scoring_json = llama.generate_json(
            stage="scoring_checklist_retry",
            system_prompt=prompts.SYSTEM_AUDITOR,
            user_prompt=retry_prompt,
            max_tokens=2000,
            temperature=0.0,
            seed=1,
        )
        checklist = scoring_json.get("checklist") if isinstance(scoring_json.get("checklist"), dict) else {}
    timing["scoring_llm_sec"] = round(time.perf_counter() - t0, 2)
    ch_score, ch_summary, ch_strengths, ch_weaknesses = rubric.score_code_health(
        metrics, found.get("maintainer") or []
    )
    scores = rubric.compute_all_scores(
        family=rubric_family,
        checklist=checklist,
        hostile_found=hostile,
        proven_problems_count=len(proven),
        lines_of_code=found["lines_of_code"],
        profile_data=profile_data,
        code_health_score=ch_score,
    )
    # v10.4 1a + 1d, before the final grade (the narrative is written from it): drop the weaknesses the repo's own code
    # disproves (verify.py), then a factor that still lists weaknesses can't be perfect (rubric.cap_for_weaknesses).
    factors_block = scoring_json.get("factors") or {}
    repo_index = claim_verify.RepoIndex(Path(packed_repo.source_path), files=list(packed_repo.files))
    verified_weaknesses, dropped_claims, capped = verify_and_cap(scores, factors_block, repo_index)
    if capped:
        log.step("v10.4 scores capped: a factor that still lists weaknesses can't be perfect", capped)
    final = rubric.overall(scores)
    letter = calculate_letter_grade(final)

    # 5. Stage 3B: Narrative descriptions + verdict summary
    t0 = time.perf_counter()
    emit("v10.2 (30B-A3B): writing final report narrative...", 90)
    narrative_json = llama.generate_json(
        stage="narrative",
        system_prompt=prompts.SYSTEM_AUDITOR,
        user_prompt=prompts.build_narrative_prompt(
            packed_repo.repo_name, ctx_json, scoring_json, scores, final, letter
        ),
        max_tokens=1200,
        temperature=0.0,
        seed=0,
    )
    timing["narrative_llm_sec"] = round(time.perf_counter() - t0, 2)

    complexity_text = complexity.describe(metrics, found["maintainer"], found["lines_of_code"])
    timing.update({k: float(v) for k, v in llama.summary().items() if isinstance(v, (int, float))})
    timing["total_sec"] = round(time.perf_counter() - started, 2)

    concerns = malicious_scan(packed_repo.files) if MALICIOUS_HOLD_ENABLED else []
    weights = DynamicWeights(
        functionality=rubric.WEIGHTS["functionality"],
        user_journey=rubric.WEIGHTS["journey"],
        ui_ux=rubric.WEIGHTS["ui_ux"],
        resonance=rubric.WEIGHTS["value"],
        creativity=rubric.WEIGHTS["creativity"],
        code_health=rubric.WEIGHTS["code_health"],
        operational_safety=0,
        justification=(
            f"Engine v10.2 ({rubric_family} adaptive checklist + Code Health, seed=0): "
            "real-world value 25%, functionality 20%, user journey 15%, code health 15%, creativity 15%, UI/UX 10%."
        ),
    )

    reasoning_block = narrative_json.get("reasoning") or {}
    factor_evals: Dict[str, FactorEvaluation] = {}
    for cat, fname in rubric.FACTOR_OF.items():
        w = rubric.WEIGHTS[cat]
        if cat == "code_health":
            factor_evals[fname] = FactorEvaluation(
                factor=FactorType(fname),
                score=scores[cat],
                weight=w,
                weighted_score=round(scores[cat] * w / 100.0, 2),
                strengths=ch_strengths,
                weaknesses=ch_weaknesses,
                reasoning=ch_summary,
            )
            continue
        f_detail = factors_block.get(cat) or {}
        factor_evals[fname] = FactorEvaluation(
            factor=FactorType(fname),
            score=scores[cat],
            weight=w,
            weighted_score=round(scores[cat] * w / 100.0, 2),
            strengths=_str_list(f_detail.get("strengths"), limit=5),
            weaknesses=verified_weaknesses.get(cat, []),
            reasoning=str(reasoning_block.get(cat) or "").strip(),
        )

    langs = metrics.languages or {}
    primary = max(langs, key=langs.get) if langs else "Multi-language"
    arch_name = str(ctx_json.get("identified_archetype") or packed_repo.repo_name)[:120]
    archetype = ProjectArchetype(
        name=arch_name,
        category=(top[0]["archetype"] if top else "General Software Project"),
        primary_language=primary,
        target_audience=str(ctx_json.get("audience") or "People who use this kind of app")[:240],
        core_purpose=str(ctx_json.get("purpose") or data.get("readme_blurb") or arch_name)[:300],
        intended_scale="Vibe-coded project",
        general_category=classification.general_category,
        platforms=list(classification.platforms),
        device_profile=classification.device_profile,
    )

    solid_features = _str_list(scoring_json.get("top_solid_features"), limit=5)
    needs_work = _str_list(scoring_json.get("top_features_needing_work"), limit=5)

    # v10.4: "top features needing work" are claims too (the factor weaknesses were checked before scoring).
    needs_work, dropped = claim_verify.verify_claims(needs_work, repo_index)
    dropped_claims += [{"factor": "top_features_needing_work", "claim": d.claim, "reason": d.reason} for d in dropped]
    log.step("v10.4 claim check: dropped claims the code disproves", dropped_claims, limit=20000)
    next_steps = _str_list(scoring_json.get("pro_next_steps"), limit=5)
    top_strengths = [
        s
        for c in rubric.WEIGHTS
        for s in _str_list((factors_block.get(c) or {}).get("strengths"), limit=2)
    ][:5]

    return VibeReport(
        repo_name=packed_repo.repo_name,
        repo_source=repo_source,
        timestamp=datetime.now().isoformat(),
        archetype=archetype,
        weights=weights,
        deterministic_metrics=metrics,
        factor_evaluations=factor_evals,
        final_vibe_score=final,
        malware_risk_score=0.0 if concerns else 100.0,
        resonance_score=scores["value"],
        letter_grade=letter,
        rubric_version="v10.4",
        peer_summary=str(narrative_json.get("peer_summary") or "").strip(),
        pro_next_steps=next_steps,
        integrity_hold=bool(concerns),
        integrity_concerns=[{"file": c["file"], "code": c["code"]} for c in concerns],
        verdict_title=str(narrative_json.get("verdict_title") or arch_name)[:120],
        verdict_summary=str(narrative_json.get("verdict_summary") or "").strip(),
        top_strengths=top_strengths,
        priority_improvements=needs_work,
        top_solid_features=solid_features,
        top_features_needing_work=needs_work,
        timing_breakdown=timing,
        issues_encountered=issues,
        complexity=complexity_text,
        experience={
            "rubric_id": RUBRIC_ID,
            "engine": "v10.4-verified",
            "model": llama.model,
            "project_profile": profile_key,
            "rubric_family": rubric_family,
            "runtime_envelope": runtime_envelope,
            "profile_detection_method": detection_method,
            "structural_signals": structural_signals,
            "checklist": checklist,
            "simplicity": scoring_json.get("simplicity") if isinstance(scoring_json.get("simplicity"), dict) else {},
            "submission_meta": submission_meta or {},
            "context": ctx_json,
            "batch_count": len(batches),
            "coverage": {k: list(v) for k, v in coverage.items()},
            "batch_findings": batch_findings,
            "proven_problems": proven,
            "hostile_patterns": hostile,
            "llama_summary": llama.summary(),
        },
    )
