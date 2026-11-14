"""Rubric v7 — Vibe-Native Consensus with Triage & 23-Item Checklist (commit 3dcc931)."""
from typing import Any, Callable, Dict, Optional
from .consensus import ConsensusEngine
from .triage import select_for_review


def evaluate(
    client,
    packed_repo,
    repo_source: str,
    metrics,
    classification,
    progress: Optional[Callable[[str, int], None]] = None,
    submission_meta: Optional[Dict[str, Any]] = None,
):
    keep, coverage, triage_summary = select_for_review(packed_repo.files)
    batches = packed_repo.get_coverage_manifests(max_batch_tokens=5200, distill=True, only=keep, local_tree=True)
    engine = ConsensusEngine(client=client)
    report = engine.evaluate_pipeline(
        repo_name=packed_repo.repo_name,
        repo_source=repo_source,
        manifest_batches=batches,
        metrics=metrics,
        mode="blend",
        progress_callback=progress,
        classification=classification,
        file_tree=packed_repo.file_tree,
        triage_summary=triage_summary,
    )
    report.rubric_version = "v7"
    return report
