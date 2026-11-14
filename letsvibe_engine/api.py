"""
Unified Engine Registry & Evaluation Router for LetsVibe (`letsvibe-engine`).
Manages production and testing engine versions and dispatches evaluations to the selected engine folder.
"""
import importlib
import json
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

REGISTRY_PATH = Path(__file__).resolve().parent / "registry.json"
PROFILES_PATH = Path(__file__).resolve().parent / "profiles" / "project_profiles.json"


def load_registry() -> List[Dict[str, Any]]:
    """Loads all registered engine versions from registry.json."""
    try:
        data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        return list(data.get("engines") or [])
    except Exception:
        return [
            {
                "id": "blend",
                "engine_version": "v9.3",
                "module": "v9_3_archetypes",
                "name": "✨ Rubric v9.3 — Archetypes & Domain Exemptions (Production)",
                "short_name": "Rubric v9.3",
                "status": "production",
                "is_default": True,
                "description": "7 domain archetype lenses, domain-specific exemptions, and Hackathon Judge",
            }
        ]


def get_available_engines(include_testing: bool = False) -> List[Dict[str, Any]]:
    """Returns engines filtered by visibility (`production` for standard users, plus `testing` for admins/test environments)."""
    engines = load_registry()
    if include_testing:
        return engines
    return [e for e in engines if e.get("status") == "production"]


def get_engine_info(engine_id: str) -> Optional[Dict[str, Any]]:
    """Looks up an engine by its id or engine_version."""
    key = (engine_id or "blend").strip()
    for eng in load_registry():
        if eng.get("id") == key or eng.get("engine_version") == key:
            return eng
    # Legacy aliases ("fast", "deep") map to default production engine
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
    return mod.evaluate(
        client,
        packed_repo,
        repo_source,
        metrics,
        classification,
        progress=progress_callback,
        submission_meta=submission_meta,
    )
