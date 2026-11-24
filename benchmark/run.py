#!/usr/bin/env python3
"""Grade the pinned benchmark repos with one or more engine versions (plan step 3c).

    <letsvibe venv>/bin/python benchmark/run.py --engines v10.3 v10.4 [--out DIR] [--only REPO ...] [--runs N]
    Quick set (plan): --engines v10.4 --only VibeBuilder-IDE-public kilo winnow-grammar --runs 1

Same path as the website's v10 grading (ingest with the engine's own file rules -> metrics -> file-based
classification -> GPU turn -> llama-server -> engine), but results go ONLY to files under the
benchmark store: nothing is written to the site's database or report folders.

- Repos marked consistency_runs > 1 are graded that many times per engine.
- Resumable: a run whose result file exists is skipped, so a stopped night can just be restarted.
- Takes GPU turns as app `letsvibe_bench` (falls back to `letsvibe` if the scheduler doesn't know it).
- Pins are verified before the night starts and again before every run; a drifted copy is never graded.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time
import traceback

HERE = Path(__file__).resolve().parent
MANIFEST = json.loads((HERE / "repos.json").read_text())
STORE = Path(MANIFEST["store"]).expanduser()


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True).stdout.strip()


def pinned_ok(repo: dict) -> bool:
    d = STORE / repo["id"]
    return (d / ".git").exists() and git(d, "rev-parse", "HEAD") == repo["commit"] and not git(d, "status", "--porcelain")


def log(msg: str) -> None:
    print(f"[{dt.datetime.now():%H:%M:%S}] {msg}", flush=True)


def scheduler_app() -> str:
    """Our own GPU-scheduler app name if registered, else share LetsVibe's queue."""
    try:
        import urllib.request
        with urllib.request.urlopen("http://127.0.0.1:11436/lock/status", timeout=3) as r:
            return "letsvibe_bench" if "letsvibe_bench" in json.loads(r.read()).get("rotation", []) else "letsvibe"
    except Exception:
        return "letsvibe"


def grade_once(engine_id: str, repo: dict, app_id: str, log_file: Path) -> dict:
    from letsvibe.core.ingest import RepositoryIngestor
    from letsvibe.evaluator.classifier import find_entry_file, merge_classification
    from letsvibe.evaluator.llama_supervisor_client import ensure_llama_awake, llm_lease, touch_engine
    from letsvibe.evaluator.ollama import OllamaClient
    from letsvibe.evaluator.pipeline import gather_metrics
    from letsvibe_engine import run_engine
    from letsvibe_engine.api import load_registry

    entry = next((e for e in load_registry() if e.get("id") == engine_id), {})
    os.environ["LETSVIBE_ENGINE_LOG"] = "1"  # the engine's own step log (dropped claims, platform changes...) per run
    os.environ["LETSVIBE_ENGINE_LOG_PATH"] = str(log_file)
    path = STORE / repo["id"]
    t0 = time.perf_counter()
    packed = RepositoryIngestor.ingest(str(path), owned_code_v2=entry.get("ingest_rules") == "owned-code-v2")
    try:
        metrics, platform_info = gather_metrics(packed)
        classification = merge_classification({}, platform_info)
        classification.entry_file = find_entry_file(packed.source_path)
        client = OllamaClient()
        steps: list = []
        with llm_lease(app_id, f"bench:{engine_id}:{repo['id']}", on_wait=lambda m: log(f"   waiting: {m}")):
            wake = ensure_llama_awake(on_progress=lambda m: None)
            if not wake.get("ok"):
                raise RuntimeError(f"llama-server could not be woken: {wake.get('error')}")
            report = run_engine(engine_id=engine_id, client=client, packed_repo=packed, repo_source=repo["url"],
                                metrics=metrics, classification=classification,
                                progress_callback=lambda m, pct: steps.append((round(time.perf_counter() - t0, 1), pct, m)))
        touch_engine()
        try:
            client.unload_all_models()
        except Exception:
            pass
        data = json.loads(report.model_dump_json()) if hasattr(report, "model_dump_json") else report.dict()
        return {"report": data, "progress": steps[-40:], "elapsed_sec": round(time.perf_counter() - t0, 1)}
    finally:
        if getattr(packed, "is_temporary", False):
            packed.cleanup()


def summarize(out: Path, engines: list) -> None:
    rows = []
    for repo in MANIFEST["repos"]:
        row = {"repo": repo["id"], "language": repo["language"]}
        for eng in engines:
            runs = sorted((out / eng / repo["id"]).glob("run*.json"))
            scores, extra = [], {}
            for f in runs:
                d = json.loads(f.read_text())
                if "error" in d:
                    continue
                r = d["report"]
                scores.append(float(r.get("final_vibe_score") or 0))
                extra = {"platforms": (r.get("archetype") or {}).get("platforms"), "category": (r.get("archetype") or {}).get("category"),
                         "secrets": (r.get("deterministic_metrics") or {}).get("detected_secrets_count"),
                         "weaknesses": sum(len((fe or {}).get("weaknesses") or []) for fe in (r.get("factor_evaluations") or {}).values())
                         if isinstance(r.get("factor_evaluations"), dict) else None}
            row[eng] = {"scores": scores, "mean": round(statistics.mean(scores), 1) if scores else None,
                        "spread": round(max(scores) - min(scores), 1) if len(scores) > 1 else None,
                        "errors": sum(1 for f in runs if "error" in json.loads(f.read_text())), **extra}
        rows.append(row)
    (out / "summary.json").write_text(json.dumps(rows, indent=2))
    lines = [f"# Benchmark {out.name}", "", f"Engines: {', '.join(engines)}. Scores are final scores; spread = max - min over repeated runs.", "",
             "| Repo | Lang | " + " | ".join(f"{e} score | {e} spread | {e} platforms | {e} secrets" for e in engines) + " |",
             "|---|---|" + "---|" * (4 * len(engines))]
    for row in rows:
        cells = []
        for e in engines:
            v = row[e]
            cells += [str(v["mean"]) if v["mean"] is not None else ("error" if v["errors"] else "-"),
                      str(v["spread"]) if v["spread"] is not None else "", ",".join(v.get("platforms") or []), str(v.get("secrets", ""))]
        lines.append(f"| {row['repo']} | {row['language']} | " + " | ".join(cells) + " |")
    (out / "summary.md").write_text("\n".join(lines) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--engines", nargs="+", default=["v10.3", "v10.4"])
    ap.add_argument("--out", default=str(STORE.parent / "results" / dt.date.today().isoformat()))
    ap.add_argument("--only", nargs="*", default=[])
    ap.add_argument("--runs", type=int, default=0, help="grade each repo this many times (default: its consistency_runs)")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    work = STORE.parent / "work"  # some helpers cache relative to the current folder; keep that out of the repos
    work.mkdir(exist_ok=True)
    os.chdir(work)

    repos = [r for r in MANIFEST["repos"] if not a.only or r["id"] in a.only]
    bad = [r["id"] for r in repos if not pinned_ok(r)]
    if bad:
        log(f"STOP: these copies are missing or drifted from their pin: {bad}. Run benchmark/fetch_repos.py --verify.")
        return 2
    tok = Path.home() / ".config/gpu-scheduler/token"  # same token the site's containers are given
    if not os.environ.get("LETSVIBE_SUPERVISOR_TOKEN") and tok.is_file():
        os.environ["LETSVIBE_SUPERVISOR_TOKEN"] = tok.read_text().strip()
    app_id = scheduler_app()
    meta = {"started": dt.datetime.now().isoformat(), "engines": a.engines, "gpu_app": app_id,
            "letsvibe_commit": git(Path(os.environ.get("LETSVIBE_REPO", Path.home() / "Documents/GitHub/letsvibe")), "rev-parse", "HEAD"),
            "engine_commit": git(HERE.parent, "rev-parse", "HEAD"), "python": sys.executable}
    (out / "meta.json").write_text(json.dumps(meta, indent=2))
    plan = [(eng, r, n) for eng in a.engines for r in repos
            for n in range(1, (a.runs or int(r.get("consistency_runs", 1))) + 1)]
    log(f"{len(plan)} runs ({', '.join(a.engines)}) -> {out}  [GPU app: {app_id}]")
    for i, (eng, repo, n) in enumerate(plan, 1):
        dest = out / eng / repo["id"] / f"run{n}.json"
        if dest.exists():
            continue
        if not pinned_ok(repo):
            log(f"skip {repo['id']}: drifted from its pin")
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        log(f"({i}/{len(plan)}) {eng} {repo['id']} run {n}")
        started = time.time()
        try:
            res = grade_once(eng, repo, app_id, dest.with_suffix(".log"))
            res.update({"engine": eng, "repo": repo["id"], "commit": repo["commit"], "run": n, "started": started})
            log(f"   done in {res['elapsed_sec'] / 60:.1f} min: score {res['report'].get('final_vibe_score')}")
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            res = {"engine": eng, "repo": repo["id"], "run": n, "started": started, "error": str(exc)[:2000],
                   "traceback": traceback.format_exc()[-6000:]}
            log(f"   ERROR: {str(exc)[:200]}")
        dest.write_text(json.dumps(res, indent=1, default=str))
        summarize(out, a.engines)
    meta["finished"] = dt.datetime.now().isoformat()
    (out / "meta.json").write_text(json.dumps(meta, indent=2))
    summarize(out, a.engines)
    log(f"finished; summary in {out / 'summary.md'}")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(os.environ.get("LETSVIBE_REPO", Path.home() / "Documents/GitHub/letsvibe"))))
    sys.path.insert(0, str(HERE.parent))  # this engine checkout (letsvibe_engine)
    raise SystemExit(main())
