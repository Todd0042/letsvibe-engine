"""Legacy Rubric v8.0 / Consensus Evaluator."""
from typing import Any, Callable, Dict, Optional
from letsvibe.evaluator.consensus import ConsensusEvaluator
from letsvibe.evaluator.pipeline import build_batches


def evaluate(
    client,
    packed_repo,
    repo_source: str,
    metrics,
    classification,
    progress: Optional[Callable[[str, int], None]] = None,
    submission_meta: Optional[Dict[str, Any]] = None,
):
    """Runs the historical dual-model consensus evaluation."""
    batches, coverage = build_batches(packed_repo)
    evaluator = ConsensusEvaluator(client=client)
    return evaluator.evaluate_blend(
        repo_name=packed_repo.repo_name,
        repo_source=repo_source,
        metrics=metrics,
        batches=batches,
        file_tree=packed_repo.file_tree,
        readme_excerpt=metrics.readme_excerpt,
        classification=classification,
        progress_callback=progress,
    )
