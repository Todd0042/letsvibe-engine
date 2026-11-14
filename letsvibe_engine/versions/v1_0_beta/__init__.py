"""Rubric v1 — Initial Beta Dual-Model Consensus Engine (commit 9d4d4df)."""
from typing import Any, Callable, Dict, Optional
from .consensus import ConsensusEngine


def evaluate(
    client,
    packed_repo,
    repo_source: str,
    metrics,
    classification,
    progress: Optional[Callable[[str, int], None]] = None,
    submission_meta: Optional[Dict[str, Any]] = None,
):
    if progress:
        progress("Running Rubric v1.0 Beta dual-model consensus...", 25)
    batches = packed_repo.get_coverage_manifests(max_batch_tokens=5200, distill=True)
    engine = ConsensusEngine(client=client)
    report = engine.evaluate_pipeline(
        repo_name=packed_repo.repo_name,
        repo_source=repo_source,
        manifest_batches=batches,
        metrics=metrics,
        mode="blend",
    )
    report.rubric_version = "v1"
    return report
