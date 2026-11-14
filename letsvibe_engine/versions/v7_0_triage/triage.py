"""
Triage + targeted review (rubric v6 "triage" strategy).

Vibe-coded software is written by AI, and AI names files and folders very deliberately
(`routes/setup.py`, `templates/mobile.html`, `story/chapter3.json`). So instead of asking a model
about every factor for every chunk of code, we:

1. TRIAGE: the model sees only the file list (numbered paths + line counts) and assigns each file a
   role. Separately, and without AI, each file's contents are checked for role markers. Agreement
   between the two rates how well the model interprets the project's naming; when the contents
   clearly contradict the name, the contents win.
2. ROUTE: files are grouped by role, and each chunk is asked ONLY about the factors that role can
   tell us about (e.g. screens -> UI/UX and user journey). Content files (story, dialogue, levels)
   are sampled rather than read in full; tests/config/docs are not reviewed by a model.

The whole-project review and the yes/no checklist then work as before.
"""

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

ROLES = ("ui", "journey", "core", "io", "content", "tests", "config", "docs")
ROLE_LABELS = {
    "ui": "Screens / UI", "journey": "Setup, navigation & settings", "core": "Core logic", "io": "I/O, network & devices",
    "content": "Content (story, dialogue, levels, data)", "tests": "Tests", "config": "Build, packaging & config",
    "docs": "Docs",
}
# Factors each role can tell us about (the chunk is asked only these)
ROLE_FACTORS: Dict[str, Tuple[str, ...]] = {
    "ui": ("ui_ux", "user_journey", "functionality"),
    "journey": ("user_journey", "functionality", "ui_ux"),
    "core": ("functionality", "creativity", "code_health"),
    "io": ("operational_safety", "functionality", "code_health"),
    "content": ("resonance", "creativity"),
    "tests": ("code_health",),
}
REVIEWED_ROLES = tuple(ROLE_FACTORS)
# Roles whose chunks also carry the safety-check qualifier (executable logic)
SAFETY_ROLES = ("core", "io", "journey")
CONTENT_SAMPLE_FILES = 6
MAX_CHUNKS_PER_ROLE = 6       # keeps a run inside its time budget; skipped files are reported as coverage
MAX_PARTS_PER_FILE = 2        # one huge file must not use up a whole role's quota
ROUTED_BATCH_TOKENS = 7000    # larger than whole-codebase chunks: fewer calls, less repeated instruction text
_PRIORITY_NAME = re.compile(r"(^|/)(main|app|index|game|__main__|server|cli)\.\w+$|setup|onboard|wizard|settings|menu|screen|"
                            r"route|nav|player|engine|core", re.I)
CONTENT_SAMPLE_CHARS = 1500
TESTS_SAMPLE_CHARS = 6000

TRIAGE_SYSTEM_PROMPT = """You are sorting the files of a vibe-coded project (software written by AI from someone's prompts).
AI-written projects name files and folders very deliberately, so judge each file's role from its path and name.
Roles:
- ui: screens, views, pages, templates, styles, frontend scripts, widgets, rendering/drawing code
- journey: setup/first-run/onboarding, navigation, routing, menus, settings/preferences, launch or install scripts
- core: main program logic, game mechanics, algorithms, services, state, models
- io: networking, files/storage, databases, devices/hardware, audio/video pipelines, background threads
- content: story text, dialogue, scripts, quests, levels, lyrics, quiz questions, translations, large data
- tests: automated tests
- config: build files, manifests, packaging, CI, dependency lists, settings files read by the build
- docs: documentation and notes
Every listed file number must appear in exactly one role. Respond with JSON only."""

# ---- deterministic checks (no AI) ---------------------------------------------------------------
_EXT_CONFIG = (".toml", ".ini", ".cfg", ".yml", ".yaml", ".gradle", ".kts", ".properties", ".lock", ".spec", ".iss",
               ".nsi", ".desktop", ".plist", ".xcconfig", ".cmake", ".mk")
_NAME_CONFIG = re.compile(r"^setup\.py$|(^|/)(pyproject\.toml|package\.json|requirements[^/]*\.txt|cargo\.toml|makefile|cmakelists\.txt|"
                          r"dockerfile|pkgbuild|build\.gradle(\.kts)?|settings\.gradle(\.kts)?|androidmanifest\.xml|platformio\.ini|"
                          r"\.github/|\.gitlab-ci|tsconfig[^/]*\.json|vite\.config|webpack\.config)", re.I)
_PATH_TESTS = re.compile(r"(^|/)(tests?|spec|__tests__|androidtest)(/|$)|(^|/)test_[^/]+$|_test\.\w+$|\.(test|spec)\.\w+$", re.I)
_PATH_DOCS = re.compile(r"\.(md|rst|txt|adoc)$", re.I)
_PATH_CONTENT = re.compile(r"(^|/)(story|stories|chapters?|scenes?|dialog(ue)?s?|scripts?/(story|dialog)|quests?|levels?|maps?|"
                           r"lyrics|locales?|i18n|l10n|translations?|strings|content|narrative|lore|data|questions?)(/|[_.-]|$)", re.I)
_PATH_JOURNEY = re.compile(r"(setup|onboard|wizard|first[_-]?run|welcome|intro|tutorial|nav(igation)?|router?s?|routes?|menus?|"
                           r"settings?|prefs?|preferences|options|launch|install|start)", re.I)
_PATH_UI = re.compile(r"(^|/)(ui|views?|screens?|pages?|templates?|components?|widgets?|layouts?|styles?|css|static|frontend|"
                      r"res/layout|render(er|ing)?|hud|scenes?)(/|$)|\.(html|css|scss|vue|svelte|jsx|tsx|qml|xaml|ui)$|"
                      r"(screen|view|page|window|dialog|widget|activity|fragment|hud|renderer|ui)\.\w+$", re.I)
_PATH_IO = re.compile(r"(net(work)?|http|api|client|server|socket|ws|ble|bluetooth|serial|usb|obd|device|driver|hardware|"
                      r"storage|database|db|repo(sitory)?|cache|download(er)?|upload|sync|audio|video|stream|ffmpeg|io)(\W|_|$)", re.I)

_UI_MARKERS = re.compile(r"(<div|<template|className=|@Composable|setContentView|QWidget|QMainWindow|tk\.|tkinter|pygame\.(display|draw)|"
                         r"\.blit\(|canvas\.|ctx\.fill|document\.getElementById|innerHTML|lv_obj_create|tft\.|display\.draw|Text\(|Button\()")
_IO_MARKERS = re.compile(r"(requests\.|httpx\.|urllib|socket\.|aiohttp|fetch\(|XMLHttpRequest|WebSocket|subprocess\.|open\(|sqlite3|"
                         r"\.execute\(|threading\.|asyncio\.|serial\.|Bluetooth|BLE|Wire\.begin|SPI\.|File\(|FileOutputStream|Retrofit|OkHttp)")
_TEST_MARKERS = re.compile(r"(\bdef test_|\bassert\b|@Test\b|\bdescribe\(|\bit\(|\bexpect\(|unittest|pytest)")
_JOURNEY_MARKERS = re.compile(r"(first[_ ]?run|onboarding|setup wizard|@app\.(get|route)|@router\.|NavHost|navController|"
                              r"composable\(\"|<Route|Intent\(|startActivity|settings|preferences|argparse|click\.|typer)", re.I)


def content_role(path: str, text: str) -> Optional[str]:
    """Role suggested by the file's CONTENTS alone (None = no strong signal)."""
    if not text:
        return None
    sample = text[:20000]
    lines = [ln.strip() for ln in sample.splitlines() if ln.strip()]
    if not lines:
        return None
    if len(_TEST_MARKERS.findall(sample)) >= 3 and ("def test_" in sample or "@Test" in sample or "describe(" in sample):
        return "tests"
    prose = sum(1 for ln in lines if len(ln) > 60 and sum(c.isalpha() or c == " " for c in ln) / len(ln) > 0.8)
    quoted = sum(1 for ln in lines if re.search(r"[\"'][^\"']{40,}[\"']", ln))
    if (prose + quoted) / len(lines) > 0.35 and len(lines) > 20:
        return "content"
    ui, io, jr = len(_UI_MARKERS.findall(sample)), len(_IO_MARKERS.findall(sample)), len(_JOURNEY_MARKERS.findall(sample))
    best = max((ui, "ui"), (io, "io"), (jr, "journey"))
    return best[1] if best[0] >= 3 else None


_NAME_DOCS = re.compile(r"(^|/)(license|licence|copying|notice|authors|contributors|changelog|readme|third_party[^/]*)(\.\w+)?$", re.I)


def name_role(path: str) -> str:
    """Role suggested by the path and name alone (the deterministic baseline for naming clarity)."""
    p = path.lower()
    if _NAME_DOCS.search(p):
        return "docs"
    if p.endswith((".sh", ".bat", ".ps1", ".command")):
        return "journey"   # install/launch scripts: part of "get it running"
    if _PATH_DOCS.search(p) and not _PATH_CONTENT.search(p):
        return "docs"
    if _PATH_TESTS.search(p):
        return "tests"
    if _NAME_CONFIG.search(p) or p.endswith(_EXT_CONFIG):
        return "config"
    if _PATH_CONTENT.search(p) and not p.endswith((".py", ".js", ".ts", ".kt", ".java", ".cpp", ".c", ".rs", ".go")):
        return "content"
    base = p.rsplit("/", 1)[-1]
    if _PATH_JOURNEY.search(base):
        return "journey"
    if _PATH_UI.search(p):
        return "ui"
    if _PATH_IO.search(base):
        return "io"
    return "core"


def compatible(role: str, c_role: Optional[str]) -> bool:
    """Does a name-based role agree with what the contents show? (journey and ui overlap heavily.)"""
    if c_role is None or role == c_role:
        return True
    # Logic that also draws itself (game entities) or touches files is normal; only clear contradictions count
    overlaps = {("journey", "ui"), ("ui", "journey"), ("core", "io"), ("io", "core"), ("journey", "core"), ("core", "journey"),
                ("journey", "io"), ("core", "ui"), ("ui", "core"), ("io", "ui")}
    return (role, c_role) in overlaps


# ---- the triage result ---------------------------------------------------------------------------

@dataclass
class TriageResult:
    roles: Dict[str, str] = field(default_factory=dict)          # final role per file
    model_roles: Dict[str, str] = field(default_factory=dict)    # what the model said from names
    name_roles: Dict[str, str] = field(default_factory=dict)     # deterministic name-only baseline
    content_roles: Dict[str, Optional[str]] = field(default_factory=dict)
    disagreements: List[Tuple[str, str, str]] = field(default_factory=list)  # (path, model role, content role)
    model_ok: bool = False
    seconds: float = 0.0

    def counts(self) -> Dict[str, int]:
        out: Dict[str, int] = {}
        for r in self.roles.values():
            out[r] = out.get(r, 0) + 1
        return out

    def stats(self) -> Dict[str, Any]:
        """How well file names were interpreted: model vs contents, and name rules vs contents."""
        checkable = [p for p, c in self.content_roles.items() if c is not None]
        def agree(src: Dict[str, str]) -> Optional[float]:
            if not checkable:
                return None
            return round(sum(1 for p in checkable if compatible(src.get(p, "core"), self.content_roles[p])) / len(checkable), 3)
        model_vs_rules = (round(sum(1 for p in self.roles if self.model_roles.get(p) == self.name_roles.get(p)) / len(self.roles), 3)
                          if self.roles and self.model_roles else None)
        return {
            "files": len(self.roles), "content_checkable": len(checkable),
            "model_vs_contents": agree(self.model_roles) if self.model_roles else None,
            "name_rules_vs_contents": agree(self.name_roles),
            "model_vs_name_rules": model_vs_rules,
            "overridden_by_contents": len(self.disagreements),
            "model_answered": self.model_ok,
        }

    def summary_text(self) -> str:
        c = self.counts()
        return "; ".join(f"{ROLE_LABELS[r]}: {c[r]}" for r in ROLES if c.get(r))


def triage_schema(n_files: int) -> Dict[str, Any]:
    ids = {"type": "array", "items": {"type": "integer"}}
    return {"type": "object", "properties": {r: ids for r in ROLES}, "required": list(ROLES)}


def build_triage_prompt(paths: List[str], files: Dict[str, str], media_summary: str) -> str:
    lines = [f"{i}. {p} ({files[p].count(chr(10)) + 1} lines)" for i, p in enumerate(paths, 1)]
    return ("FILES (number. path (lines)):\n" + "\n".join(lines)
            + f"\n\nMedia files (names only, not listed above): {media_summary}\n"
            + "\nReturn, for each role, the list of file numbers that belong to it.")


def run_triage(client: Any, model: str, files: Dict[str, str], media_summary: str = "none") -> TriageResult:
    import time

    paths = sorted(files)
    res = TriageResult()
    res.name_roles = {p: name_role(p) for p in paths}
    res.content_roles = {p: content_role(p, files[p]) for p in paths}
    t0 = time.time()
    model_map: Dict[str, str] = {}
    try:
        raw = client.generate_json(model=model, system_prompt=TRIAGE_SYSTEM_PROMPT,
                                   user_prompt=build_triage_prompt(paths, files, media_summary),
                                   temperature=0.0, format_schema=triage_schema(len(paths)),
                                   max_output_tokens=min(4000, 300 + 6 * len(paths)))
        for role in ROLES:
            for idx in (raw.get(role) or []):
                try:
                    i = int(idx)
                except (TypeError, ValueError):
                    continue
                if 1 <= i <= len(paths) and paths[i - 1] not in model_map:
                    model_map[paths[i - 1]] = role
        res.model_ok = len(model_map) >= 0.8 * len(paths)
    except Exception as e:  # noqa: BLE001 - triage must never sink the evaluation
        if "Time limit" in str(e) or type(e).__name__ in ("CpuSpilloverError", "BudgetExceeded"):
            raise
    res.seconds = round(time.time() - t0, 1)
    res.model_roles = model_map
    for p in paths:
        proposed = model_map.get(p) or res.name_roles[p]
        c = res.content_roles[p]
        # Docs, licenses, build/config files and tests are identified reliably by name; prose in them is not story content
        if res.name_roles[p] in ("docs", "config", "tests") or p.lower().endswith((".sh", ".bat", ".ps1", ".command")):
            res.roles[p] = res.name_roles[p]
            continue
        if not compatible(proposed, c):
            res.disagreements.append((p, proposed, c or "-"))
            proposed = c
        res.roles[p] = proposed
    return res


def _priority(path: str, size: int) -> Tuple[int, int]:
    """Entry points and files named for setup/screens/menus first, then the largest files."""
    return (0 if _PRIORITY_NAME.search(path) else 1, -size)


def build_routed_batches(files: Dict[str, str], distilled: Dict[str, str], triage: TriageResult,
                         max_batch_tokens: int = ROUTED_BATCH_TOKENS, max_chunks_per_role: int = MAX_CHUNKS_PER_ROLE,
                         coverage: Optional[Dict[str, Tuple[int, int]]] = None) -> List[Tuple[str, str, Tuple[str, ...], str]]:
    """
    (title, content, factors to ask, role) per chunk. Content is sampled; tests get one sample chunk; each
    other role gets at most `max_chunks_per_role` chunks, filled by priority. `coverage`, if given, receives
    {role: (files reviewed, files in role)}.
    """
    max_chars = int(max_batch_tokens * 3.6)
    coverage = coverage if coverage is not None else {}
    groups: Dict[str, List[str]] = {}
    for p, r in triage.roles.items():
        groups.setdefault(r, []).append(p)
    batches: List[Tuple[str, str, Tuple[str, ...], str]] = []
    for role in REVIEWED_ROLES:
        paths = sorted(groups.get(role, []))
        if not paths:
            continue
        factors = ROLE_FACTORS[role]
        if role == "content":
            # Sample: the largest content files say most about the story/world; never read everything
            sample = sorted(paths, key=lambda p: -len(files[p]))[:CONTENT_SAMPLE_FILES]
            blocks = [f"\n--- START FILE: {p} (sample) ---\n{files[p][:CONTENT_SAMPLE_CHARS]}\n--- END FILE ---\n" for p in sample]
            note = f"# {len(paths)} content files in total; showing samples from {len(sample)}.\n"
            batches.append((f"Content sample ({len(paths)} files)", note + "".join(blocks), factors, role))
            coverage[role] = (len(sample), len(paths))
            continue
        if role == "tests":
            text, used = "", []
            for p in paths:
                if len(text) > TESTS_SAMPLE_CHARS:
                    break
                text += f"\n--- START FILE: {p} ---\n{distilled.get(p, files[p])[:3000]}\n--- END FILE ---\n"
                used.append(p)
            batches.append((f"Tests sample ({len(paths)} files)", f"# {len(paths)} test files in total.\n" + text, factors, role))
            coverage[role] = (len(used), len(paths))
            continue
        role_batches: List[Tuple[str, str, Tuple[str, ...], str]] = []
        reviewed: List[str] = []
        current, size, part = [], 0, 1
        for p in sorted(paths, key=lambda x: _priority(x, len(distilled.get(x, files[x])))):
            if len(role_batches) >= max_chunks_per_role:
                break
            reviewed.append(p)
            body = distilled.get(p, files[p])
            if len(body) > max_chars:  # very large file: split by lines
                lines = body.splitlines(keepends=True)
                chunk, csize, k = [], 0, 1
                used_lines = 0
                for ln in lines:
                    if chunk and csize + len(ln) > max_chars - 500:
                        role_batches.append((f"{ROLE_LABELS[role]} - {p} part {k}",
                                        f"\n--- START FILE: {p} [part {k}] ---\n{''.join(chunk)}\n--- END FILE ---\n", factors, role))
                        chunk, csize, k = [], 0, k + 1
                        if k > MAX_PARTS_PER_FILE:
                            break
                    chunk.append(ln)
                    csize += len(ln)
                    used_lines += 1
                if k > MAX_PARTS_PER_FILE:
                    role_batches[-1] = (role_batches[-1][0], role_batches[-1][1]
                                        + f"\n[... {len(lines) - used_lines} more lines of {p} not reviewed ...]\n", factors, role)
                    continue
                if chunk:
                    role_batches.append((f"{ROLE_LABELS[role]} - {p} part {k}",
                                    f"\n--- START FILE: {p} [part {k}] ---\n{''.join(chunk)}\n--- END FILE ---\n", factors, role))
                continue
            block = f"\n--- START FILE: {p} ---\n{body}\n--- END FILE ---\n"
            if current and size + len(block) > max_chars:
                role_batches.append((f"{ROLE_LABELS[role]} {part}", "".join(current), factors, role))
                current, size, part = [], 0, part + 1
            current.append(block)
            size += len(block)
        if current and len(role_batches) < max_chunks_per_role:
            role_batches.append((f"{ROLE_LABELS[role]} {part}", "".join(current), factors, role))
        elif current:
            reviewed = reviewed[: len(reviewed) - len(current)]
        batches.extend(role_batches[:max_chunks_per_role])
        coverage[role] = (len(reviewed), len(paths))
    return batches


# ---- name-based file filter for the classic 7B + 14B pipeline -------------------------------------
SKIPPED_ROLES = ("docs", "config", "tests")   # covered by measurements, README handling and the file tree


def select_for_review(files: Dict[str, str]) -> Tuple[Dict[str, str], Dict[str, Tuple[int, int]], Dict[str, str]]:
    """
    Decides from file names and folders alone (no AI) which files the models read:
    - docs, licenses, build/config files and tests are skipped (the README, packaging, test counts and the
      file tree already reach the reviewers through measurements);
    - content (story, dialogue, levels, lyrics, data) is sampled: the largest few files, first part only;
    - everything else (program logic, screens, setup, I/O) is read in full, exactly as before.
    Returns (files to review, {role: (files kept, files in role)}, {path: role}).
    """
    roles = {p: name_role(p) for p in files}
    keep: Dict[str, str] = {}
    by_role: Dict[str, List[str]] = {}
    for p, r in roles.items():
        by_role.setdefault(r, []).append(p)
    coverage: Dict[str, Tuple[int, int]] = {}
    for role, paths in by_role.items():
        if role in SKIPPED_ROLES:
            coverage[role] = (0, len(paths))
        elif role == "content":
            sample = sorted(paths, key=lambda x: -len(files[x]))[:CONTENT_SAMPLE_FILES]
            for p in sample:
                body = files[p]
                keep[p] = body if len(body) <= CONTENT_SAMPLE_CHARS else (
                    body[:CONTENT_SAMPLE_CHARS] + f"\n[... sample only: {len(body) - CONTENT_SAMPLE_CHARS} more characters of content ...]")
            coverage[role] = (len(sample), len(paths))
        else:
            for p in paths:
                keep[p] = files[p]
            coverage[role] = (len(paths), len(paths))
    if not keep:          # never send nothing: fall back to every file
        keep = dict(files)
    return keep, coverage, roles
