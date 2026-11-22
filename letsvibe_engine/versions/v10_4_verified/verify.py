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
# "line 12" / "lines 12" or "file.py:12" (a ":N" only counts right after a code file name: "127.0.0.1:11435" is a port).
_LINE = re.compile(rf"\blines?\s+(\d{{1,6}}(?:\s*(?:,|and|&|to|-|–)\s*\d{{1,6}})*)\b|\.(?:{CODE_EXT}):(\d{{1,6}})\b")
_IDENT = re.compile(r"`([A-Za-z_][\w.:]*?)(?:\(\))?`")
# A plain call, no backticks (`save()` is often written bare): the name before "()".
_CALL = re.compile(r"(?<![\w.:`])([A-Za-z_]\w*)\(\)")
_VS = re.compile(r"[`'\"]?\b([A-Za-z_]\w{2,})\b[`'\"]?\s+vs\.?\s+[`'\"]?\b([A-Za-z_]\w{2,})\b")
_DUP_MEMBER = re.compile(r"\bduplicat\w*\s+(?:field|member|entry|key|property|variable|attribute)\s+[`'\"]?([A-Za-z_]\w*)[`'\"]?"
                         r"\s+in\s+(?:the\s+)?[`'\"]?([A-Z]\w*)[`'\"]?", re.I)
_UNINIT = re.compile(r"\buninitiali[sz]ed\s+[`'\"]?([A-Za-z_]\w{2,})[`'\"]?", re.I)
_NEGATION = re.compile(r"\b(missing|no|lacks?|lacking|without|absent|doesn't|does not|never)\b", re.I)
REGION = 40  # lines after a function's start that count as "that function" for the "missing X" checks
NEAR = 4  # lines from a mention of the claim's subject that count as "right there"

# "missing X" claims: what counts as evidence that X is there.
EVIDENCE: dict[str, tuple[re.Pattern, re.Pattern]] = {
    "empty or missing input": (re.compile(r"\b(empty|blank|null|nil|none|missing file|nonexistent|doesn't exist|does not exist)\b", re.I),
                               re.compile(r"isNullOrBlank|isNullOrEmpty|isBlank\(|isEmpty\(|== null|!= null|\bis None\b|"
                                          r"\?: return|\.exists\(|if\s*\(\s*!\s*\w+|if not \w+|== nil|len\(\w+\) == 0")),
    "timeout": (re.compile(r"time-?outs?\b", re.I),
                re.compile(r"timeout|Duration::from_(secs|millis)|setTimeout|wait_for\(|AbortSignal\.timeout|deadline", re.I)),
    "error handling": (re.compile(r"error[- ]handling|handle (the )?errors?|unhandled|exception handling", re.I),
                       re.compile(r"\btry\b|\bexcept\b|\bcatch\b|map_err|\.ok_or|Result<|\?;|if err != nil|"
                                  r"if\s*\(\s*!\s*[\w.:>-]+|==\s*(nullptr|NULL)\b|"
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
# Class.method() / Class::method() / Class.method (a class name and a method), and "Class's ..." (a class name).
_MEMBER = re.compile(r"\b([A-Z][A-Za-z0-9]+)(?:\.|::)([a-z_][A-Za-z0-9_]*)\b(?:\(\))?")
_POSSESSIVE = re.compile(r"\b([A-Z][a-z0-9]+(?:[A-Z][A-Za-z0-9]*)+)'s\b")
# Words that look like code but are ordinary product/tech words: never used to call a claim made up.
_NOT_CODE = {"iOS", "macOS", "iPhone", "iPad", "eBay", "iCloud", "watchOS", "tvOS", "npm", "pnpm"}


def _subjects(claim: str, idents: list[str]) -> list[str]:
    """What the claim is about: backticked identifiers plus snake_case/camelCase words."""
    out = idents + _WORD.findall(claim)  # whole names only: "`adb start-server`" mustn't match any start()/server()
    for cls, member in _MEMBER.findall(claim):
        out += [member, cls]
    out += _POSSESSIVE.findall(claim)
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

    def code_paths(self) -> list[str]:
        return [p for p in self.paths if re.search(rf"\.({CODE_EXT})$", p)]

    def contains_word(self, word: str) -> bool:
        if self._blob is None:
            code = [p for p in self.paths if re.search(rf"\.({CODE_EXT})$", p)]
            self._blob = "\n".join("\n".join(self.lines(p)) for p in code)
        return re.search(rf"(?<![\w]){re.escape(word)}(?![\w])", self._blob) is not None

    _DEF = re.compile(r"\b(?:async\s+)?(?:def|fn|func|function|fun)\s+([A-Za-z_]\w*)"
                      # C/C++/Java/C#/Kotlin-style: a return type, then [Class::]name( ... ) without a trailing ';'
                      r"|^\s*(?:[\w<>\[\],*&]+\s+)+(?:\w+::)?([A-Za-z_]\w*)\s*\([^;]*$")
    _KEYWORDS = {"if", "for", "while", "switch", "return", "catch", "else", "new", "sizeof", "delete", "throw"}

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
                name = m.group(1) or m.group(2)
                if name in self._KEYWORDS:
                    continue
                parts = set(re.split(r"_|(?<=[a-z])(?=[A-Z])", name.lower()))
                if name.lower() in subs or (not exact_only and subs & parts):
                    body = [ls[i]]
                    for nxt in ls[i + 1:i + REGION]:  # the function's own lines: stop at the next definition
                        if self._DEF.search(nxt):
                            break
                        body.append(nxt)
                    out.append((rel, i + 1, name, body))
        return out

def _body(text: str, i: int) -> str:
    """The text between the brace at i and its matching close (at most 20k characters)."""
    depth = 0
    for j in range(i, min(len(text), i + 20000)):
        if text[j] == "{":
            depth += 1
        elif text[j] == "}":
            depth -= 1
            if depth == 0:
                return text[i + 1:j]
    return text[i + 1:i + 20000]


def check_claim(claim: str, repo: RepoIndex) -> Dropped | None:
    """None when the claim stands (or can't be checked); Dropped(reason) when the code contradicts it."""
    files = [m.group(1) for m in _FILE.finditer(claim)]
    found: list[str] = []
    for cited in files:
        hits = repo.find(cited)
        if not hits:
            return Dropped(claim, f"cites `{cited}`, which isn't in the repo")
        found += hits

    nums = [int(n) for a, b in _LINE.findall(claim) for n in re.findall(r"\d+", a or b)]
    if found and nums:
        longest = max(len(repo.lines(p)) for p in found)
        bad = [n for n in nums if n > longest and longest]
        if bad:
            return Dropped(claim, f"cites line {bad[0]}, but {found[0]} has only {longest} lines")

    idents = [i.split("::")[-1].split(".")[-1] for i in _IDENT.findall(claim)] + _CALL.findall(_FILE.sub(" ", claim))
    idents = [i for i in idents if len(i) >= 3 and not re.fullmatch(r"\d+", i)]
    # A dotted word right after a file name is the file ("UserPrefs.h"), not Class.member.
    no_files = _FILE.sub(" ", claim)
    code_names = idents + [m for pair in _MEMBER.findall(no_files) for m in pair] + _POSSESSIVE.findall(no_files) \
        + [w for w in _WORD.findall(no_files) if len(w) >= 5]
    for name in dict.fromkeys(code_names):
        if name in _NOT_CODE or len(name) < 3:
            continue
        if not repo.contains_word(name):
            return Dropped(claim, f"names `{name}`, which appears nowhere in the code")

    if found and re.search(r"\bduplicat", claim, re.I):
        for name in dict.fromkeys(code_names):
            occurrences = sum(len(re.findall(rf"(?<!\w){re.escape(name)}(?!\w)", "\n".join(repo.lines(p)))) for p in found)
            if occurrences == 1:
                return Dropped(claim, f"says `{name}` is duplicated, but it occurs once in {found[0]}")

    # "Inconsistent X vs X": the same name on both sides compares a thing with itself.
    m = _VS.search(claim)
    if m and m.group(1) == m.group(2) and re.search(r"\b(inconsisten|mismatch|differ|conflict)", claim, re.I):
        return Dropped(claim, f"compares `{m.group(1)}` with itself")

    # "Duplicate field X in struct/class Y" (no file cited): count X's declarations inside Y's definition.
    m = _DUP_MEMBER.search(claim)
    if m:
        member, owner = m.group(1), m.group(2)
        for rel in repo.code_paths():
            text = "\n".join(repo.lines(rel))
            for d in re.finditer(rf"\b(struct|class|enum|record|interface|object|data\s+class)\s+{re.escape(owner)}\b[^;{{]*\{{", text):
                body = _body(text, d.end() - 1)
                decls = re.findall(rf"(?<![\w.>]){re.escape(member)}\s*(\[[^\]]*\]\s*)*(=|;|,|\{{|:)", body)
                if len(decls) == 1:
                    return Dropped(claim, f"says `{member}` is duplicated in {owner}, but it is declared once ({rel})")

    # "Uninitialized X": X's declaration gives it a value.
    m = _UNINIT.search(claim)
    if m:
        name = m.group(1)
        for rel in repo.code_paths():
            for j, line in enumerate(repo.lines(rel)):
                # a declaration (a type right before the name) that gives a value; a later `x = ...` doesn't count
                if re.search(rf"[\w>\]*&]\s+[*&]*{re.escape(name)}\s*(\[[^\]]*\]\s*)*(=(?!=)|\{{[^}}]+\}})", line) and \
                        not re.match(r"\s*(if|while|for|return|else|case)\b", line):
                    return Dropped(claim, f"says `{name}` is uninitialized, but {rel}:{j + 1} gives it a value: {line.strip()[:120]}")

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
        # A thing named in a cited file but not as a function (`SPIFFS`, `ringBuf_`): the lines around each mention.
        if found:
            things = [w for w in re.findall(r"\b[A-Z][A-Z0-9_]{2,}\b", no_files) if w not in ("API", "URL", "UI", "JSON")] \
                + code_names
            def names_thing(line: str) -> bool:
                return any(re.search(rf"(?<!\w){re.escape(t)}(?!\w)", line) for t in things)
            # Best evidence first: a line that handles the thing itself (`if (!SPIFFS.begin(true)) return;`) ...
            for rel in found:
                for j, line in enumerate(repo.lines(rel)):
                    if names_thing(line) and evidence.search(line):
                        return Dropped(claim, f"says {concept} is missing, but {rel}:{j + 1} has it: {line.strip()[:120]}")
            # ... then a line right after a mention of it.
            for rel in found:
                ls = repo.lines(rel)
                for i, line in enumerate(ls):
                    if not names_thing(line):
                        continue
                    for j in range(i, min(len(ls), i + NEAR)):
                        if evidence.search(ls[j]):
                            return Dropped(claim, f"says {concept} is missing, but {rel}:{j + 1} has it: {ls[j].strip()[:120]}")
    return None


def verify_claims(claims: list[str], repo: RepoIndex) -> tuple[list[str], list[Dropped]]:
    """Split claims into (kept, dropped)."""
    kept, dropped = [], []
    for c in claims:
        d = check_claim(c, repo)
        (dropped.append(d) if d else kept.append(c))
    return kept, dropped
