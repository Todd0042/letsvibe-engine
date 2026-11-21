"""Claim checker (v10.4): AI-written weaknesses are checked against the repo's own code before they reach a report.

A claim is dropped only when the code gives specific evidence against it:
  - it cites a file that doesn't exist in the repo;
  - it cites a line past the end of the cited file;
  - it names an identifier in backticks (`gui_start`, `adb_connect()`) that appears nowhere in the code;
  - it says a named function / cited spot is missing a timeout, error handling, validation or a user
    notification, and the code right there clearly has one.
Claims that name no file and no identifier can't be checked and are kept as they are: guessing would risk
deleting true complaints. Every dropped claim is returned with the evidence, so the engine can log it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

CODE_EXT = r"py|pyi|ts|tsx|js|jsx|mjs|cjs|svelte|vue|rs|go|kt|kts|java|cpp|cc|cxx|c|h|hpp|cs|swift|rb|php|sh|lua|dart|zig"
_FILE = re.compile(rf"(?<![\w/.-])((?:[\w.-]+/)*[\w.-]+\.(?:{CODE_EXT}))\b")
_LINE = re.compile(r"\blines?\s+(\d{1,6})\b|:(\d{1,6})\b")
_IDENT = re.compile(r"`([A-Za-z_][\w.:]*?)(?:\(\))?`")
_NEGATION = re.compile(r"\b(missing|no|lacks?|lacking|without|absent|doesn't|does not|never)\b", re.I)
REGION = 40  # lines after a function's start that count as "that function" for the "missing X" checks

# "missing X" claims: what counts as evidence that X is there.
EVIDENCE: dict[str, tuple[re.Pattern, re.Pattern]] = {
    "timeout": (re.compile(r"time-?outs?\b", re.I),
                re.compile(r"timeout|Duration::from_(secs|millis)|setTimeout|wait_for\(|AbortSignal\.timeout|deadline", re.I)),
    "error handling": (re.compile(r"error[- ]handling|handle (the )?errors?|unhandled|exception handling", re.I),
                       re.compile(r"\btry\b|\bexcept\b|\bcatch\b|map_err|\.ok_or|Result<|\?;|if err != nil|"
                                  r"return Err\(|raise\b|\.error\(|ui\.error|logger?\.(error|warning)")),
    "validation": (re.compile(r"\bvalidat|\bsaniti[sz]|\bcheck(s|ed)? (the )?input", re.I),
                   re.compile(r"\.chars\(\)\.all|re\.(fullmatch|match)|\bmatch(es)?\(|isinstance\(|Field\(|"
                              r"raise \w*(Value|Validation)Error|return Err\(|is_ascii|\.test\(|startswith\(|len\(")),
    "notification": (re.compile(r"\bnotif|\bnotify|\bwarn(s|ing)? the user|\btells? the user|\buser (is )?(never )?told", re.I),
                     re.compile(r"toast|notify|alert\(|confirm\(|\.error\(|message|signed out|showMessage|snackbar", re.I)),
}


@dataclass
class Dropped:
    claim: str
    reason: str


_WORD = re.compile(r"\b([a-z][a-z0-9]*_[a-z0-9_]+|[a-z]+[A-Z][A-Za-z0-9]+)\b")  # snake_case / camelCase names


def _subjects(claim: str, idents: list[str]) -> list[str]:
    """What the claim is about: backticked identifiers plus snake_case/camelCase words."""
    out = idents + _WORD.findall(claim)  # whole names only: "`adb start-server`" mustn't match any start()/server()
    return list(dict.fromkeys(w for w in out if len(w) >= 3))


class RepoIndex:
    """The repo's code files, loaded lazily: path -> lines."""

    def __init__(self, root: Path, files: Iterable[str] | None = None, max_bytes: int = 2_000_000):
        self.root = Path(root)
        rels = list(files) if files is not None else [
            str(p.relative_to(self.root)) for p in self.root.rglob("*") if p.is_file() and ".git" not in p.parts]
        self.paths = sorted(r.replace("\\", "/") for r in rels)
        self.max_bytes = max_bytes
        self._lines: dict[str, list[str]] = {}
        self._blob: str | None = None

    def find(self, cited: str) -> list[str]:
        """Repo paths matching a cited path (exact, or the cited path is a suffix: the AI often drops folders)."""
        cited = cited.lstrip("./")
        return [p for p in self.paths if p == cited or p.endswith("/" + cited)]

    def lines(self, rel: str) -> list[str]:
        if rel not in self._lines:
            try:
                f = self.root / rel
                self._lines[rel] = f.read_text(errors="replace").splitlines() if f.stat().st_size <= self.max_bytes else []
            except OSError:
                self._lines[rel] = []
        return self._lines[rel]

    def contains_word(self, word: str) -> bool:
        if self._blob is None:
            code = [p for p in self.paths if re.search(rf"\.({CODE_EXT})$", p)]
            self._blob = "\n".join("\n".join(self.lines(p)) for p in code)
        return re.search(rf"(?<![\w]){re.escape(word)}(?![\w])", self._blob) is not None

    _DEF = re.compile(r"\b(?:async\s+)?(?:def|fn|func|function|fun)\s+([A-Za-z_]\w*)")

    def functions_matching(self, subjects: list[str], within: list[str], exact_only: bool) -> list[tuple[str, int, str, list[str]]]:
        """Function definitions whose name is a subject, or (inside the cited files only) contains one as a word part
        (`adb` -> adb_connect), as (path, line, name, the next REGION lines)."""
        subs = {s.lower() for s in subjects}
        out = []
        for rel in within:
            ls = self.lines(rel)
            for i, line in enumerate(ls):
                m = self._DEF.search(line)
                if not m:
                    continue
                name = m.group(1)
                parts = set(re.split(r"_|(?<=[a-z])(?=[A-Z])", name.lower()))
                if name.lower() in subs or (not exact_only and subs & parts):
                    body = [ls[i]]
                    for nxt in ls[i + 1:i + REGION]:  # the function's own lines: stop at the next definition
                        if self._DEF.search(nxt):
                            break
                        body.append(nxt)
                    out.append((rel, i + 1, name, body))
        return out

def check_claim(claim: str, repo: RepoIndex) -> Dropped | None:
    """None when the claim stands (or can't be checked); Dropped(reason) when the code contradicts it."""
    files = [m.group(1) for m in _FILE.finditer(claim)]
    found: list[str] = []
    for cited in files:
        hits = repo.find(cited)
        if not hits:
            return Dropped(claim, f"cites `{cited}`, which isn't in the repo")
        found += hits

    nums = [int(a or b) for a, b in _LINE.findall(claim)]
    if found and nums:
        longest = max(len(repo.lines(p)) for p in found)
        bad = [n for n in nums if n > longest and longest]
        if bad:
            return Dropped(claim, f"cites line {bad[0]}, but {found[0]} has only {longest} lines")

    idents = [i.split("::")[-1].split(".")[-1] for i in _IDENT.findall(claim)]
    idents = [i for i in idents if len(i) >= 3 and not re.fullmatch(r"\d+", i)]
    for ident in idents:
        if not repo.contains_word(ident):
            return Dropped(claim, f"names `{ident}`, which appears nowhere in the code")

    if not _NEGATION.search(claim):
        return None
    subjects = _subjects(claim, idents)
    for concept, (asks, evidence) in EVIDENCE.items():
        if not asks.search(claim):
            continue
        # Only inside a function that matches the claim's subject (`adb` -> adb_connect, gui_start -> gui_start):
        # line numbers from the AI are unreliable, and evidence anywhere else proves nothing about the claim.
        scope = found or repo.paths
        for rel, start, name, body in repo.functions_matching(subjects, scope, exact_only=not found):
            for off, line in enumerate(body[1:], start=1):  # the body: a signature saying "can fail" isn't handling
                if evidence.search(line):
                    return Dropped(claim, f"says {concept} is missing, but {name}() in {rel}:{start + off} has it: "
                                          f"{line.strip()[:120]}")
    return None


def verify_claims(claims: list[str], repo: RepoIndex) -> tuple[list[str], list[Dropped]]:
    """Split claims into (kept, dropped)."""
    kept, dropped = [], []
    for c in claims:
        d = check_claim(c, repo)
        (dropped.append(d) if d else kept.append(c))
    return kept, dropped
