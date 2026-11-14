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
import subprocess  # nosec B404 - git/nvidia-smi run with fixed list arguments, never a shell
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
    """{"title", "opening", "toc", "features"} from a README's raw Markdown, robust to hero HTML banners."""
    raw = re.sub(r"<!--.*?-->|```.*?```", "\n", raw or "", flags=re.S)
    lines = raw.splitlines()
    title, toc, opening, features = "", [], [], []
    in_features = False
    
    # Pass 1: find Title and TOC headers
    for line in lines:
        h = re.match(r"^(#{1,3})\s+(.+?)\s*#*$", line)
        if h:
            text = _inline(h.group(2))
            if len(h.group(1)) == 1 and not title:
                title = text
            elif text:
                toc.append(text)
            in_features = bool(FEATURES.search(text)) and len(h.group(1)) >= 2
            continue
        if in_features:
            m = re.match(r"\s*(?:[-*+•]|\d+[.)])\s+(.{4,220})$", line)
            if m and len(features) < 15:
                features.append(_inline(m.group(1)))

    # Pass 2: semantic opening pitch (strips HTML wrappers, banner links, and badge blocks)
    no_html = re.sub(r"<[^>]+>", " ", raw)
    for l in [line.strip() for line in no_html.splitlines() if line.strip()]:
        if l.startswith("#") or l.startswith("---") or l.startswith("==="):
            continue
        # Skip badge blocks and image URLs
        if re.search(r"\[!\[|\[badge|\.svg\)|img\.shields|shields\.io|ko-fi", l, re.I):
            continue
        clean_l = re.sub(r"^\s*>\s*", "", l)
        clean_l = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", clean_l)
        clean_l = _inline(clean_l)
        if len(clean_l) > 30 and len(" ".join(opening)) < 700:
            opening.append(clean_l)
            if len(" ".join(opening)) >= 120:
                break

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
    """One plain sentence about documentation depth and visual onboarding."""
    if not f.get("has_readme"):
        return "No README: someone finding it on GitHub can't tell what it is or how to start it."
    good, gaps = [], []
    q = f.get("quick_start_section")
    if q and q <= 4:
        good.append("explains how to install or start it early on")
    elif q:
        good.append(f"details setup in section {q}")
    else:
        gaps.append("doesn't clearly explain how to install or run it")

    shots = f.get("screenshots", 0)
    if shots >= 5:
        good.append(f"provides rich visual proof with {shots} screenshots or diagrams")
    elif shots >= 1:
        good.append("has screenshots")
    else:
        gaps.append("has no screenshots or visual diagrams")

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
    except Exception:  # nosec B110 - deliberate best-effort fallback
        pass
    return out


def commit_notes(repo: Path, limit: int = 6) -> List[str]:
    """Recent commit messages that explain something (subject plus a real body), trailers removed."""
    try:
        res = subprocess.run(["git", "-C", str(repo), "log", "-n", "50", "--format=%s%n%b%x1e"],  # nosec B603 B607 - fixed command, list arguments, no shell
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
def load_project_profiles() -> Dict[str, Any]:
    """Loads the archetype profiles map from project_profiles.json (works in both letsvibe-engine and letsvibe)."""
    here = Path(__file__).resolve().parent
    candidates = [
        here.parent / "profiles" / "project_profiles.json",
        here.parent.parent / "profiles" / "project_profiles.json",
        here.parent.parent / "data" / "project_profiles.json",
    ]
    for profiles_path in candidates:
        if profiles_path.exists():
            try:
                return json.loads(profiles_path.read_text(encoding="utf-8")).get("profiles", {})
            except Exception:
                pass
    return {}


def detect_project_profile(
    files: Dict[str, str],
    kind_hint: Optional[str] = None,
    readme_raw: Optional[str] = None,
    explicit_profile: Optional[str] = None,
) -> Tuple[str, Dict[str, Any]]:
    """Assigns the project to one of the archetypes in project_profiles.json, falling back to unknown_or_general."""
    profiles_map = load_project_profiles()

    if explicit_profile and explicit_profile != "auto" and explicit_profile in profiles_map:
        return explicit_profile, profiles_map[explicit_profile]

    names = {f.lower() for f in files}
    base = {Path(f).name.lower() for f in files}
    joined_text = " ".join(t[:2000].lower() for t in files.values())
    readme_l = (readme_raw or "").lower()

    # 1. Developer Tool / MCP Server
    if (kind_hint in ("AI assistant plugin", "editor extension", "command-line tool") or
        "mcp.json" in base or "@modelcontextprotocol/sdk" in joined_text or "fastmcp" in joined_text or
        "plugin.json" in base or "[project.scripts]" in joined_text or
        re.search(r"\b(mcp server|model context protocol|cli tool|command-line utility)\b", readme_l)):
        key = "developer_tool_or_mcp"
        return key, profiles_map.get(key, {})

    # 2. Media / Audio / Social Lounge (checked before generic animation loops so audio visualizers are not tagged as games)
    if ("karaoke" in joined_text or ("websockets" in joined_text and ("audio" in joined_text or "singer" in joined_text or "player" in joined_text)) or
        re.search(r"\b(karaoke|social lounge|party lounge|jukebox|audio visualizer|vocal training|music player)\b", readme_l)):
        key = "media_or_social_lounge"
        return key, profiles_map.get(key, {})

    # 3. Hardware / IoT / Mobile
    if (kind_hint in ("hardware project", "mobile app") or "androidmanifest.xml" in base or
        "platformio.ini" in base or "gpio" in joined_text or "obd2" in joined_text or
        re.search(r"\b(arduino|raspberry pi|esp32|sensor|microcontroller|android app|ios app)\b", readme_l)):
        key = "hardware_iot_or_mobile"
        return key, profiles_map.get(key, {})

    # 4. Game / Interactive Simulation
    game_keywords = re.search(r"\b(arcade game|retro game|gameplay loop|space shooter|roguelike|shmup|platformer)\b", readme_l)
    anim_game = (("canvas.getcontext" in joined_text or "requestanimationframe" in joined_text) and
                 bool(re.search(r"\b(game|score|lives|enemy|bullet|asteroid|spawn|sprite)\b", joined_text + " " + readme_l)))
    if kind_hint == "game" or "project.godot" in base or "pygame" in joined_text or game_keywords or anim_game:
        key = "interactive_game_or_simulation"
        return key, profiles_map.get(key, {})

    # 5. Automation Script / Pipeline
    if ("playwright" in joined_text or "beautifulsoup" in joined_text or "scrapy" in joined_text or
        re.search(r"\b(web scraper|crawler|etl pipeline|batch automation)\b", readme_l)):
        key = "automation_script_or_pipeline"
        return key, profiles_map.get(key, {})

    # 6. Web Productivity / Dashboard
    has_web = (kind_hint in ("web app", "desktop app") or
               any(f.endswith((".html", ".jsx", ".tsx", ".vue", ".svelte", ".css")) for f in names) or
               re.search(r"\b(react|vue|svelte|next|vite|tailwind|express|fastapi|flask)\b", joined_text) or
               re.search(r"\b(dashboard|productivity app|kanban|todo app|workflow app)\b", readme_l))
    if has_web:
        key = "web_productivity_app"
        return key, profiles_map.get(key, {})

    # 7. Fallback: Unknown / General Software (e.g. no README, bare scripts, unusual utility)
    key = "unknown_or_general"
    return key, profiles_map.get(key, {})


def gather(repo: Path, owner: str, name: str, data: Dict[str, Any], files: Dict[str, str],
           get: Optional[Callable[..., Any]] = None,
           submission_meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Every source, trimmed, plus Python's kind, detected profile, and README facts. No model call."""
    repo = Path(repo)
    readme_file = next((p for p in sorted(repo.iterdir()) if p.is_file() and README_NAME.match(p.name)), None) if repo.is_dir() else None
    raw = readme_file.read_text(errors="replace") if readme_file else ""
    gh = github_meta(owner, name, get)
    kind = kind_from_files(files)
    meta = submission_meta or {}
    explicit_profile = meta.get("project_profile")
    profile_key, profile_data = detect_project_profile(files, kind, raw, explicit_profile=explicit_profile)
    return {
        "github": gh, "readme": readme_parts(raw) if raw.strip() else {}, "commits": commit_notes(repo),
        "package": (data.get("package_meta") or {}).get("description", ""), "windows": (data.get("window_titles") or [])[:4],
        "kind_from_files": kind, "project_profile": profile_key, "profile_data": profile_data,
        "readme_facts": readme_facts(raw, files.keys()),
        "submission_meta": meta,
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
    meta = s.get("submission_meta") or {}
    fallback_purpose = str(meta.get("user_hook") or "").strip() or gh.get("description") or rd.get("opening", "")[:240] or s.get("package") or ""
    ctx: Dict[str, Any] = {"purpose": fallback_purpose, "audience": "", "kind": kind_files or "",
                           "project_profile": s.get("project_profile", "unknown_or_general"),
                           "profile_data": s.get("profile_data") or {},
                           "submission_meta": meta,
                           "stated_features": rd.get("features", [])[:10],
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
    if meta.get("user_hook"):
        hook = str(meta["user_hook"]).strip()
        if hook and hook not in ctx.get("purpose", ""):
            ctx["purpose"] = f"{ctx['purpose']} ({hook})".strip(" ()") if ctx.get("purpose") else hook
    return ctx


def render(ctx: Dict[str, Any]) -> str:
    """The dossier's first section: what the project says it is (shared context for every reviewer)."""
    lines = ["## 0. What the project says it is (its own descriptions; context only, not proof that anything works)"]
    if ctx.get("purpose"):
        lines.append(f"- Purpose: {ctx['purpose']}")
    if ctx.get("kind"):
        lines.append(f"- Kind of project: {ctx['kind']}")
    profile_data = ctx.get("profile_data") or {}
    if profile_data.get("name"):
        lines.append(f"- Archetype profile: {profile_data['name']}")
    meta = ctx.get("submission_meta") or {}
    if meta.get("provenance"):
        prov_labels = {
            "vibe_coded": "Vibe-Coded (Prompt-driven / AI-built)",
            "ai_assisted": "AI-Assisted (Human-architected with AI Copilots)",
            "human_made": "Human-Made (Hand-crafted code)",
        }
        lines.append(f"- Creation provenance: {prov_labels.get(meta['provenance'], meta['provenance'])}")
    if meta.get("guest_access") == "zero_install":
        lines.append("- Guest / User Access: Zero app installation required (runs in browser / QR code / web URL)")
    elif meta.get("guest_access") == "install_required":
        lines.append("- Guest / User Access: Requires native app, binary, or package installation")
    elif meta.get("guest_access") == "cli_or_sdk":
        lines.append("- Guest / User Access: Terminal CLI or developer library / plugin")
    if ctx.get("audience"):
        lines.append(f"- For: {ctx['audience']}")
    if ctx.get("stated_features"):
        lines.append("- Features it says it has: " + "; ".join(ctx["stated_features"]))
    lines.append(f"- How much it says about itself: {ctx.get('strength', 'thin')}. {ctx.get('readme_note', '')}".rstrip())
    return "\n".join(lines)
