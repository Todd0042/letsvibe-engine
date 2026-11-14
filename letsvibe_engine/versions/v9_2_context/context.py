"""
Project context (rubric v9.2): what the project says it is, read once at the start and shared by every later step.

Python gathers the project's own descriptions, cheapest first, and trims them to what a visitor actually reads:
  - the GitHub description, topics and website (one public request; private repos simply skip it)
  - the README's title, opening paragraph, table of contents (headings only) and any feature list; never the whole
    file, so a very long README costs no more than a short one
  - the last few release notes (often written by the AI assistant), and recent commit message bodies
  - the package description and window titles (already in the dossier)
Python also works out the KIND of project from its files where they are unambiguous (an Android manifest, an MCP
server, a browser-extension manifest, a command-line entry point, a Godot project...).

One small 14B call turns those excerpts into a purpose sentence, an audience, a kind and the features it says it has,
quoting the excerpts; Python keeps only quoted answers it can find, and a kind proven by the files always wins.

This is what the project SAYS it is: context for the reviewers and the summary, never evidence that a feature works
(the checklists still need the dossier and the code for that). Thin context (no README, no description) is recorded
as a fact so later wording can be hedged.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

import httpx

KINDS = ("mobile app", "desktop app", "web app", "website", "game", "command-line tool", "AI assistant plugin",
         "browser extension", "editor extension", "bot", "library", "hardware project", "other")
README_NAME = re.compile(r"^readme(\.(md|markdown|rst|txt))?$", re.I)
QUICK_START = re.compile(r"\b(install|installation|quick ?start|getting started|setup|set up|usage|how to (use|run)|run(ning)?|download)\b", re.I)
FEATURES = re.compile(r"\b(features?|what it (can )?do(es)?|highlights|capabilities)\b", re.I)
GITHUB_API = "https://api.github.com/repos"
# Kinds the files prove beyond doubt; the others (mobile, desktop, game, web) are hints the model may refine, since
# an Android project can be a game and a desktop tray tool can be the side part of a web server.
FIRM_KINDS = ("AI assistant plugin", "editor extension", "browser extension", "bot", "hardware project", "command-line tool")


# ---------------------------------------------------------------------------------------------------------------
# README: only the parts a visitor reads
# ---------------------------------------------------------------------------------------------------------------
def _inline(text: str) -> str:
    url = r"\((?:[^()]|\([^()]*\))*\)"
    text = re.sub(r"\[!\[[^\]]*\]" + url + r"\]" + url, " ", text)        # linked badges
    text = re.sub(r"!\[[^\]]*\]" + url + r"|<img[^>]*>", " ", text)         # images
    text = re.sub(r"\[([^\]]+)\]" + url, r"\1", text)                      # links -> text
    text = re.sub(r"<[^>]+>|[*_`]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def readme_parts(raw: str) -> Dict[str, Any]:
    """{"title", "opening", "toc", "features"} from a README's raw Markdown."""
    raw = re.sub(r"<!--.*?-->|```.*?```", "\n", raw or "", flags=re.S)
    lines = raw.splitlines()
    title, toc, opening, features = "", [], [], []
    in_features, seen_heading = False, 0
    for line in lines:
        h = re.match(r"^(#{1,3})\s+(.+?)\s*#*$", line)
        if h:
            text = _inline(h.group(2))
            if len(h.group(1)) == 1 and not title:
                title = text
            elif text:
                toc.append(text)
            seen_heading += 1
            in_features = bool(FEATURES.search(text)) and len(h.group(1)) >= 2
            continue
        if in_features:
            m = re.match(r"\s*(?:[-*+•]|\d+[.)])\s+(.{4,220})$", line)
            if m and len(features) < 15:
                features.append(_inline(m.group(1)))
        # opening: the first real paragraph text, before the second heading
        if seen_heading <= 1 and len(" ".join(opening)) < 700:
            t = _inline(re.sub(r"^\s*>+\s*", "", line))      # a quoted pitch line ("> Turn any TV...")
            if t and not re.match(r"^[-=|:\s]+$", t) and len(t) > 25:
                opening.append(t)
    return {"title": title, "opening": " ".join(opening)[:700], "toc": toc[:40], "features": features}


def readme_facts(raw: Optional[str], files: Iterable[str]) -> Dict[str, Any]:
    """Countable facts about the documentation (Python only)."""
    names = {Path(f).name.lower() for f in files}
    top = {f.lower() for f in files if "/" not in f}
    facts: Dict[str, Any] = {
        "has_readme": bool(raw and raw.strip()),
        "license": any(n.startswith(("license", "licence", "copying")) for n in top),
        "changelog": any(n.startswith(("changelog", "changes", "history")) for n in top),
        "contributing": "contributing.md" in names,
    }
    if not facts["has_readme"]:
        return {**facts, "readme_lines": 0, "sections": 0, "quick_start_section": None, "screenshots": 0}
    parts = readme_parts(raw)
    main_sections = [_inline(h) for h in re.findall(r"(?m)^##\s+(.+?)\s*#*$", re.sub(r"```.*?```", "", raw, flags=re.S))]
    quick = next((i for i, h in enumerate(main_sections, start=1) if QUICK_START.search(h)), None)
    shots = len(re.findall(r"!\[[^\]]*\]\([^)]*\.(?:png|jpe?g|gif|webp|svg)|<img[^>]+src=", raw, re.I))
    return {**facts, "readme_lines": raw.count("\n") + 1, "sections": len(parts["toc"]), "quick_start_section": quick,
            "screenshots": shots}


def readme_note(f: Dict[str, Any]) -> str:
    """One plain sentence about how quickly a newcomer can learn what it is and how to start it."""
    if not f.get("has_readme"):
        return "No README: someone finding it on GitHub can't tell what it is or how to start it."
    good, gaps = [], []
    q = f.get("quick_start_section")
    if q and q <= 4:
        good.append("explains how to install or start it early on")
    elif q:
        gaps.append(f"how to install or start it only comes in section {q}")
    else:
        gaps.append("it doesn't say how to install or start it")
    (good if f.get("screenshots") else gaps).append("has screenshots" if f.get("screenshots") else "it has no screenshots")
    if f.get("license"):
        good.append("has a licence")

    def _and(items):
        return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]

    if not good:
        return "In the README, " + "; ".join(gaps) + "."
    return "The README " + _and(good) + ("; " + "; ".join(gaps) if gaps else "") + "."


# ---------------------------------------------------------------------------------------------------------------
# Other sources
# ---------------------------------------------------------------------------------------------------------------
def github_meta(owner: str, repo: str, get: Optional[Callable[..., Any]] = None) -> Dict[str, Any]:
    """Public GitHub description, topics, website and the last 3 release notes. Empty when unreachable or private."""
    get = get or (lambda url: httpx.get(url, timeout=6.0, headers={"Accept": "application/vnd.github+json",
                                                                   "User-Agent": "LetsVibe-grader"}))
    out: Dict[str, Any] = {"description": "", "topics": [], "homepage": "", "releases": []}
    if not owner or not repo or owner == "local":
        return out
    try:
        r = get(f"{GITHUB_API}/{owner}/{repo}")
        if r.status_code == 200:
            d = r.json()
            out.update(description=(d.get("description") or "").strip(), topics=list(d.get("topics") or [])[:15],
                       homepage=(d.get("homepage") or "").strip())
        r = get(f"{GITHUB_API}/{owner}/{repo}/releases?per_page=3")
        if r.status_code == 200:
            for rel in r.json()[:3]:
                body = _inline(re.sub(r"(?m)^#+\s*", "", rel.get("body") or ""))
                if len(body) > 40:
                    out["releases"].append(f"{rel.get('name') or rel.get('tag_name') or 'Release'}: {body[:400]}")
    except Exception:
        pass
    return out


def commit_notes(repo: Path, limit: int = 6) -> List[str]:
    """Recent commit messages that explain something (subject plus a real body), trailers removed."""
    try:
        res = subprocess.run(["git", "-C", str(repo), "log", "-n", "50", "--format=%s%n%b%x1e"],
                             capture_output=True, text=True, timeout=15)
    except Exception:
        return []
    notes = []
    for entry in res.stdout.split("\x1e"):
        lines = [l for l in entry.strip().splitlines() if l.strip() and not re.match(r"^[\w-]+:\s.*<.*@.*>$", l.strip())
                 and not l.lower().startswith(("co-authored-by", "signed-off-by", "generated with", "\U0001f916"))]
        if len(lines) >= 2 and len(" ".join(lines[1:])) >= 60:
            notes.append(_inline(lines[0] + ": " + " ".join(lines[1:]))[:300])
        if len(notes) >= limit:
            break
    return notes


def kind_from_files(files: Dict[str, str]) -> Optional[str]:
    """The kind of project when its files make it unambiguous; None otherwise."""
    names = {f.lower() for f in files}
    base = {Path(f).name.lower() for f in files}
    pkg = files.get("package.json", "")
    try:
        pkg_json = json.loads(pkg) if pkg else {}
    except ValueError:
        pkg_json = {}
    deps = " ".join(list((pkg_json.get("dependencies") or {}).keys()) + list((pkg_json.get("devDependencies") or {}).keys()))
    joined_py = " ".join(t[:4000] for f, t in files.items() if f.endswith((".py", "requirements.txt", "pyproject.toml")))
    if "androidmanifest.xml" in base or any(f.endswith(".xcodeproj") or "/ios/" in f for f in names):
        return "mobile app"
    if "@modelcontextprotocol/sdk" in deps or "mcp.json" in names or "fastmcp" in joined_py or "from mcp" in joined_py:
        return "AI assistant plugin"
    if (pkg_json.get("engines") or {}).get("vscode"):
        return "editor extension"
    if any(Path(f).name.lower() == "manifest.json" and '"manifest_version"' in t for f, t in files.items()):
        return "browser extension"
    if "project.godot" in base or any(f.endswith(".unity") for f in names) or "pygame" in joined_py:
        return "game"
    if any(f.endswith(".ino") for f in names) or "platformio.ini" in base:
        return "hardware project"
    if re.search(r"discord\.js|telegraf|grammy", deps) or re.search(r"\bdiscord\b|telegram\.ext|aiogram", joined_py):
        return "bot"
    if pkg_json.get("bin") or "[project.scripts]" in joined_py or "console_scripts" in joined_py:
        return "command-line tool"
    web_server = re.search(r"\b(express|fastify|next|koa)\b", deps) or re.search(r"\b(fastapi|flask|django|aiohttp)\b", joined_py)
    if (re.search(r"\b(electron|@tauri-apps)", deps) or re.search(r"\b(PyQt\d|PySide\d|tkinter)\b", joined_py)) and not web_server:
        return "desktop app"
    return None


# ---------------------------------------------------------------------------------------------------------------
# Putting it together
# ---------------------------------------------------------------------------------------------------------------
def gather(repo: Path, owner: str, name: str, data: Dict[str, Any], files: Dict[str, str],
           get: Optional[Callable[..., Any]] = None) -> Dict[str, Any]:
    """Every source, trimmed, plus Python's kind and README facts. No model call."""
    repo = Path(repo)
    readme_file = next((p for p in sorted(repo.iterdir()) if p.is_file() and README_NAME.match(p.name)), None) if repo.is_dir() else None
    raw = readme_file.read_text(errors="replace") if readme_file else ""
    gh = github_meta(owner, name, get)
    return {
        "github": gh, "readme": readme_parts(raw) if raw.strip() else {}, "commits": commit_notes(repo),
        "package": (data.get("package_meta") or {}).get("description", ""), "windows": (data.get("window_titles") or [])[:4],
        "kind_from_files": kind_from_files(files), "readme_facts": readme_facts(raw, files.keys()),
    }


def sources_text(s: Dict[str, Any]) -> str:
    """The excerpts the model reads (and its quotes are checked against)."""
    out = []
    gh, rd = s.get("github") or {}, s.get("readme") or {}
    if gh.get("description"):
        out.append(f"GitHub description: {gh['description']}")
    if gh.get("topics"):
        out.append("GitHub topics: " + ", ".join(gh["topics"]))
    if rd.get("title"):
        out.append(f"README title: {rd['title']}")
    if rd.get("opening"):
        out.append(f"README opening: {rd['opening']}")
    if rd.get("toc"):
        out.append("README sections: " + " | ".join(rd["toc"][:30]))
    if rd.get("features"):
        out.append("README feature list:\n" + "\n".join(f"- {f}" for f in rd["features"]))
    if s.get("package"):
        out.append(f"Package description: {s['package']}")
    if s.get("windows"):
        out.append("Window titles: " + " | ".join(s["windows"]))
    if gh.get("releases"):
        out.append("Release notes:\n" + "\n".join(f"- {r}" for r in gh["releases"]))
    if s.get("commits"):
        out.append("Commit messages that explain changes:\n" + "\n".join(f"- {c}" for c in s["commits"]))
    return "\n".join(out)


def strength(s: Dict[str, Any]) -> str:
    gh, rd = s.get("github") or {}, s.get("readme") or {}
    pitch = bool(gh.get("description") or rd.get("opening"))
    detail = bool(rd.get("toc") or rd.get("features") or gh.get("releases") or s.get("commits"))
    return "strong" if pitch and detail else "partial" if (pitch or detail or s.get("package")) else "thin"


SYSTEM = "You read a software project's own descriptions and say plainly what it is. You answer with fixed choices and exact quotes."


def schema() -> dict:
    return {"type": "object", "properties": {
        "purpose": {"type": "string"}, "audience": {"type": "string"},
        "kind": {"type": "string", "enum": list(KINDS)},
        "stated_features": {"type": "array", "maxItems": 10, "items": {"type": "string"}},
        "evidence": {"type": "array", "maxItems": 3, "items": {"type": "string"}},
    }, "required": ["purpose", "audience", "kind", "stated_features", "evidence"]}


def prompt(text: str, kind_hint: Optional[str]) -> str:
    hint = (f"\nThe project's files show it is a {kind_hint}.\n" if kind_hint in FIRM_KINDS else
            f"\nThe project's files suggest a {kind_hint}; pick a more specific kind if the excerpts show one (for example a game).\n"
            if kind_hint else "")
    return (f"{text}\n{hint}\n---\nFrom the excerpts above only:\n"
            "purpose: one plain sentence saying what it is and what it does for people (no hype, no marketing words).\n"
            "audience: who it is for, in a few words.\n"
            "kind: the kind of project.\n"
            "stated_features: up to 10 features the excerpts say it has, a few words each.\n"
            "evidence: 1-3 short exact quotes from the excerpts (word for word) that show the purpose.\nJSON only.")


def _norm(t: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (t or "").lower()).strip()


def understand(generate: Optional[Callable[..., Dict[str, Any]]], model: str, s: Dict[str, Any]) -> Dict[str, Any]:
    """The shared project context. With no model (or a failed call) it falls back to the project's own words."""
    text = sources_text(s)
    kind_files = s.get("kind_from_files")
    gh, rd = s.get("github") or {}, s.get("readme") or {}
    fallback_purpose = gh.get("description") or rd.get("opening", "")[:240] or s.get("package") or ""
    ctx: Dict[str, Any] = {"purpose": fallback_purpose, "audience": "", "kind": kind_files or "", "stated_features": rd.get("features", [])[:10],
                           "strength": strength(s), "readme_note": readme_note(s.get("readme_facts") or {}),
                           "readme_facts": s.get("readme_facts") or {}, "source": "own words", "verified": False}
    if not text.strip() or generate is None:
        return ctx
    from letsvibe.evaluator.ollama import CpuSpilloverError
    ans: Dict[str, Any] = {}
    for attempt in range(2):
        try:
            ans = generate(model=model, system_prompt=SYSTEM, user_prompt=prompt(text, kind_files), format_schema=schema(),
                           max_output_tokens=500 + 300 * attempt, temperature=0.1)
            if ans.get("purpose"):
                break
        except CpuSpilloverError:          # includes the admin's Stop
            raise
        except (ValueError, RuntimeError):
            continue
    src = _norm(text)
    verified = any(len(_norm(q)) >= 8 and _norm(q) in src for q in ans.get("evidence") or [])
    firm = kind_files in FIRM_KINDS
    if verified and str(ans.get("purpose", "")).strip():
        ctx.update(purpose=str(ans["purpose"]).strip()[:300], audience=str(ans.get("audience", "")).strip()[:120],
                   stated_features=[str(f).strip()[:80] for f in (ans.get("stated_features") or []) if str(f).strip()][:10]
                   or ctx["stated_features"], source="model, quotes checked", verified=True)
        if not firm and ans.get("kind") in KINDS:
            ctx["kind"] = ans["kind"]       # the files' hint (mobile, desktop...) can be refined, e.g. an Android game
    return ctx


def render(ctx: Dict[str, Any]) -> str:
    """The dossier's first section: what the project says it is (shared context for every reviewer)."""
    lines = ["## 0. What the project says it is (its own descriptions; context only, not proof that anything works)"]
    if ctx.get("purpose"):
        lines.append(f"- Purpose: {ctx['purpose']}")
    if ctx.get("kind"):
        lines.append(f"- Kind of project: {ctx['kind']}")
    if ctx.get("audience"):
        lines.append(f"- For: {ctx['audience']}")
    if ctx.get("stated_features"):
        lines.append("- Features it says it has: " + "; ".join(ctx["stated_features"]))
    lines.append(f"- How much it says about itself: {ctx.get('strength', 'thin')}. {ctx.get('readme_note', '')}".rstrip())
    return "\n".join(lines)
