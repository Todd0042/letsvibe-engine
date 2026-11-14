"""
Stage 2: cliché check. Compares an app's summary with known vibe-coded archetypes (letsvibe/data/archetypes.json) using
a small local embedding model, and reports the closest one as a plain fact for the rubric.
"""
import hashlib
import json
import math
from pathlib import Path
from typing import Dict, List

import httpx

EMBED_MODEL = "mxbai-embed-large"
ARCHETYPES = Path(__file__).resolve().parents[2] / "data" / "archetypes.json"
CACHE = Path("data") / "cache" / "archetype_vectors.json"


def _embed(host: str, texts: List[str]) -> List[List[float]]:
    r = httpx.post(f"{host}/api/embed", json={"model": EMBED_MODEL, "input": texts, "keep_alive": "1m"}, timeout=300)
    r.raise_for_status()
    return r.json()["embeddings"]


def _cos(a, b) -> float:
    return sum(x * y for x, y in zip(a, b)) / math.sqrt(sum(x * x for x in a) * sum(y * y for y in b))


def _archetype_vectors(host: str):
    arch = json.loads(ARCHETYPES.read_text())["archetypes"]
    texts = [f"{a['name']}: {a['description']}" for a in arch]
    key = hashlib.md5(("\n".join(texts) + EMBED_MODEL).encode()).hexdigest()
    if CACHE.exists():
        c = json.loads(CACHE.read_text())
        if c.get("key") == key:
            return arch, c["vectors"]
    vecs: List[List[float]] = []
    for i in range(0, len(texts), 32):
        vecs += _embed(host, texts[i:i + 32])
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps({"key": key, "vectors": vecs}))
    return arch, vecs


def summary_of(d: dict) -> str:
    parts = [d.get("readme_title", ""), d.get("readme_blurb", "")[:400], "; ".join(d.get("window_titles", [])[:4]),
             "Screens: " + ", ".join(s.split(" ", 1)[-1] for s in d.get("screens", [])[:12]),
             "Features: " + ", ".join(d.get("mechanics", [])[:15]), "Text: " + " | ".join(d.get("strings", [])[:12])]
    return "\n".join(p for p in parts if p.strip(": ").strip())


def closest(host: str, dossier_data: dict, top: int = 3) -> List[Dict[str, float]]:
    """Closest archetypes with cosine similarity. Unloads the embedding model afterwards."""
    arch, vecs = _archetype_vectors(host)
    v = _embed(host, [summary_of(dossier_data)])[0]
    ranked = sorted(((_cos(v, av), a["name"]) for av, a in zip(vecs, arch)), reverse=True)[:top]
    try:
        httpx.post(f"{host}/api/embed", json={"model": EMBED_MODEL, "input": ["x"], "keep_alive": 0}, timeout=60)
    except Exception:
        pass
    return [{"archetype": n, "similarity": round(s, 3)} for s, n in ranked]
