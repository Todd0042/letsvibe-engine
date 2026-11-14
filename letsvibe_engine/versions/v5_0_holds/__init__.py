"""Rubric v5 — Historical Consensus Engine (commit 2f42641)."""
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
    batches = packed_repo.get_coverage_manifests(max_batch_tokens=5200, distill=True)
    engine = ConsensusEngine(client=client)
    report = engine.evaluate_pipeline(
        repo_name=packed_repo.repo_name,
        repo_source=repo_source,
        manifest_batches=batches,
        metrics=metrics,
        mode="blend",
        progress_callback=progress,
        classification=classification,
    )
    report.rubric_version = "v5"
    return report
