"""
Engine test log (opt-in, local only): every step's output and every model call of each grading, in plain text, so a
strange grade can be traced afterwards. Turned on with LETSVIBE_ENGINE_LOG=1 in .env; written to engine-test.log in
the working folder (git-ignored), rotated at 50 MB.

It holds quotes of graded projects' code, so it follows the delete-everywhere promise: each grading is one block
marked with its project, and deleting a project, an owner's projects or the whole database removes their blocks
(storage/backups.py). Never shown on the site.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

MAX_BYTES = 50 * 1024 * 1024
_LOCK = threading.Lock()
BEGIN, END = "===== BEGIN GRADING ", "===== END GRADING "


def enabled() -> bool:
    return os.environ.get("LETSVIBE_ENGINE_LOG", "").strip().lower() in ("1", "true", "yes", "on")


def log_path() -> Path:
    return Path(os.environ.get("LETSVIBE_ENGINE_LOG_PATH", "engine-test.log"))


def _text(value: Any, limit: int = 6000) -> str:
    if not isinstance(value, str):
        try:
            value = json.dumps(value, indent=1, default=str, ensure_ascii=False)
        except Exception:
            value = repr(value)
    return value if len(value) <= limit else value[:limit] + f"\n... [{len(value) - limit} more characters]"


class GradingLog:
    """Collects one grading's record in memory and appends it to the log as a single block when it ends."""

    def __init__(self, slug: str, rubric: str):
        self.on = enabled()
        self.slug, self.rubric = slug, rubric
        self.started = datetime.now()
        self.parts: list = []
        self.calls_7b = 0

    def step(self, name: str, value: Any, limit: int = 6000) -> None:
        if self.on:
            self.parts.append(f"\n--- {name} ---\n{_text(value, limit)}")

    def call(self, model: str, kwargs: Dict[str, Any], seconds: float, details: Dict[str, Any], answer: Any,
             error: Optional[str] = None) -> None:
        if not self.on:
            return
        prompt = kwargs.get("user_prompt") or ""
        task = prompt.strip().splitlines()[-1][:140] if prompt.strip() else ""
        head = (f"{model} | {seconds:.1f}s | prompt {len(prompt):,} chars, {details.get('prompt_eval_count')} tokens read of "
                f"{details.get('num_ctx')} | answer {details.get('eval_count')} tokens | stop: {details.get('done_reason')} | "
                f"trimmed: {details.get('trimmed')} | temperature {kwargs.get('temperature')}")
        if error:
            head += f" | ERROR: {error}"
        if "7b" in model:          # hundreds per grading: one line each
            self.calls_7b += 1
            self.parts.append(f"[7B call {self.calls_7b}] {head} | {_text(answer, 300).replace(chr(10), ' ')}")
        else:
            self.parts.append(f"\n[14B call] {head}\n  task: {task}\n  answer: {_text(answer, 4000)}")

    def finish(self, outcome: str) -> None:
        if not self.on:
            return
        stamp = self.started.isoformat(timespec="seconds")
        block = (f"{BEGIN}{self.slug} | {stamp} | rubric {self.rubric}\n" + "\n".join(self.parts) +
                 f"\n--- outcome ---\n{outcome}\n{END}{self.slug} | {stamp}\n\n")
        path = log_path()
        try:
            with _LOCK:
                if path.exists() and path.stat().st_size > MAX_BYTES:
                    path.replace(path.with_name(path.name + ".1"))
                with path.open("a", encoding="utf-8") as f:
                    f.write(block)
        except OSError:
            pass   # a log problem never stops a grading


def purge(match) -> None:
    """Removes every grading block whose project matches `match(slug) -> bool`, in the log and its rotated copy."""
    for path in (log_path(), log_path().with_name(log_path().name + ".1")):
        if not path.exists():
            continue
        with _LOCK:
            out, keep = [], True
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True):
                if line.startswith(BEGIN):
                    keep = not match(line[len(BEGIN):].split(" | ", 1)[0].strip())
                if keep:
                    out.append(line)
                if line.startswith(END):
                    keep = True
            path.write_text("".join(out), encoding="utf-8")


def purge_project(full_slug: str) -> None:
    purge(lambda slug: slug.lower() == full_slug.lower())


def purge_owner(owner: str) -> None:
    purge(lambda slug: slug.split("/", 1)[0].lower() == owner.lower())


def purge_all() -> None:
    for path in (log_path(), log_path().with_name(log_path().name + ".1")):
        path.unlink(missing_ok=True)
