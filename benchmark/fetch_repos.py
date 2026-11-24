#!/usr/bin/env python3
"""Clone the benchmark repos once into the store and pin each to its commit; afterwards only verify.

    python3 benchmark/fetch_repos.py           # clone anything missing, then verify all
    python3 benchmark/fetch_repos.py --verify  # only check: right commit, nothing changed

The store is kept until the whole engine plan is finished (the baseline must not move). A copy that
has drifted (other commit, edited files) is reported, never silently overwritten: fix it by hand
(`git -C <repo> checkout --force <commit> && git -C <repo> clean -fdx`) after checking why it changed.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent


def git(repo: Path, *args: str, check: bool = True) -> str:
    p = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    if check and p.returncode:
        raise SystemExit(f"git {' '.join(args)} failed in {repo}: {p.stderr.strip()}")
    return p.stdout.strip()


def main() -> int:
    manifest = json.loads((HERE / "repos.json").read_text())
    store = Path(manifest["store"]).expanduser()
    store.mkdir(parents=True, exist_ok=True)
    verify_only = "--verify" in sys.argv
    problems = 0
    for r in manifest["repos"]:
        dest = store / r["id"]
        if not (dest / ".git").exists():
            if verify_only:
                print(f"MISSING  {r['id']}")
                problems += 1
                continue
            print(f"cloning  {r['id']} ...", flush=True)
            subprocess.run(["git", "clone", "--quiet", "--no-checkout", r["url"], str(dest)], check=True)
            git(dest, "-c", "advice.detachedHead=false", "checkout", "--quiet", r["commit"])
        head = git(dest, "rev-parse", "HEAD")
        dirty = git(dest, "status", "--porcelain", "--ignored=no")
        if head != r["commit"] or dirty:
            problems += 1
            print(f"DRIFTED  {r['id']}: head {head[:10]} (want {r['commit'][:10]}){', has local changes' if dirty else ''}")
        else:
            runs = r.get("consistency_runs", 1)
            print(f"ok       {r['id']:30} {head[:10]}  {r['language']}{'  x' + str(runs) + ' runs' if runs > 1 else ''}")
    print(f"\n{len(manifest['repos'])} repos in {store}; {problems} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
