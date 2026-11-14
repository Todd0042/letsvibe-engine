"""
Unified Engine Registry & Evaluation Router for LetsVibe (`letsvibe-engine`).
Manages production and testing engine versions and dispatches evaluations to the selected engine folder.
"""
import importlib
import json
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

REGISTRY_PATH = Path(__file__).resolve().parent / "registry.json"
PROFILES_PATH = Path(__file__).resolve().parent / "profiles" / "project_profiles.json"


def rubric_version_rank(version: Optional[str]) -> int:
    """
    Converts a rubric version string (e.g. 'v9.3', 'v9', 'v8', 'v1') into an integer rank
    so SQLite and Python can sort reports newest-engine-first (v9.3 -> 903, v9.0/v9 -> 900, v8 -> 800, v1 -> 100).
    """
    if not version:
        return 0
    s = str(version).strip().lower()
    m = re.match(r"^v?(\d+)(?:\.(\d+))?", s)
    if not m:
        return 0
    major = int(m.group(1))
    minor = int(m.group(2) or 0)
    return major * 100 + minor


def load_registry() -> List[Dict[str, Any]]:
    """Loads all registered engine versions from registry.json."""
    try:
        data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        return list(data.get("engines") or [])
    except Exception:
        return [
            {
                "id": "blend",
                "engine_version": "v9.4",
                "rubric_version": "v9.4",
                "rubric_rank": 904,
                "module": "v9_4_experimental",
                "name": "✨ Rubric v9.4 — Submitter Context & Grounding (Production)",
                "short_name": "Rubric v9.4",
                "status": "production",
                "is_default": True,
                "description": "7 domain archetype lenses, submitter context weighting, grounding, and Hackathon Judge",
            }
        ]


def get_available_engines(include_testing: bool = False) -> List[Dict[str, Any]]:
    """Returns engines filtered by visibility (`production` for standard users, plus `testing` for admins/test environments)."""
    engines = load_registry()
    if include_testing:
        return engines
    return [e for e in engines if e.get("status") == "production"]


def get_engine_info(engine_id: str) -> Optional[Dict[str, Any]]:
    """Looks up an engine by its id, engine_version, or rubric_version."""
    key = (engine_id or "blend").strip()
    alias_map = {
        "v8.0-test": "v8.0",
        "v9.0-test": "v9.0",
        "v9.4-test": "v9.4",
    }
    key = alias_map.get(key, key)
    for eng in load_registry():
        if key in (eng.get("id"), eng.get("engine_version"), eng.get("rubric_version")):
            return eng
    # Legacy aliases ("fast", "deep", "blend") map to default production engine
    if key in ("fast", "deep", "blend"):
        for eng in load_registry():
            if eng.get("is_default"):
                return eng
    return None


def load_project_profiles() -> Dict[str, Any]:
    """Returns the domain archetype profiles map from profiles/project_profiles.json."""
    try:
        return json.loads(PROFILES_PATH.read_text(encoding="utf-8")).get("profiles", {})
    except Exception:
        return {}


def run_engine(
    engine_id: str,
    client,
    packed_repo,
    repo_source: str,
    metrics,
    classification,
    progress_callback: Optional[Callable[[str, int], None]] = None,
    submission_meta: Optional[Dict[str, Any]] = None,
):
    """Dispatches evaluation to the requested engine version module."""
    info = get_engine_info(engine_id)
    module_name = (info or {}).get("module") or "v9_3_archetypes"
    mod = importlib.import_module(f"letsvibe_engine.versions.{module_name}")
    report = mod.evaluate(
        client,
        packed_repo,
        repo_source,
        metrics,
        classification,
        progress=progress_callback,
        submission_meta=submission_meta,
    )
    if info and info.get("rubric_version"):
        report.rubric_version = str(info["rubric_version"])
    return report
