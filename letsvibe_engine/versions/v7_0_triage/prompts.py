"""
Prompts for classification-aware weighting (Stage 1) and the two reviewers (7B per-chunk, 14B whole-repo).

Rubric v6 philosophy: LetsVibe grades vibe-coded software as vibe-coded software. Projects are
compared with other vibe-coded projects (software written by AI from someone's prompts), never with products built by large
professional teams over years. What users experience carries most of the weight; engineering
factors are reported as "what a pro team would do next".
  * 7 weighted factors (sum to 100%): functionality, user_journey, ui_ux, resonance, creativity
    (experience) + code_health, operational_safety (engineering)
  * malware_risk -> separate trust check (unchanged here; see legal-plan.md for its replacement)
"""

from .weights import render_ranges_text  # noqa: E402

# Shared by every prompt so all reviewers judge against the same reference class and scale.
REFERENCE_CLASS = """==================================================
WHO BUILT THIS, AND WHAT TO COMPARE IT WITH
==================================================
This project is VIBE-CODED: the program was written by AI from someone's prompts, usually by a person who is not
a programmer. That is different from developers who use AI assistance in their normal work. Compare it with OTHER
vibe-coded projects -- never with software written by professional developers or teams. Reward what users actually get. Engineering gaps
(tests, file size, tidy architecture) are real, but report them as next steps, not as reasons to call the project bad.

SCORE BANDS (0-100), relative to vibe-coded projects:
- 20-39 Broken or stub: the core feature is missing or crashes on the main path.
- 40-54 Rough prototype: the idea partly works; frequent dead ends or missing pieces.
- 55-69 Typical working vibe-coded project: does its job with rough edges. 62 is the center of this scale.
- 70-79 Strong vibe-coded project: polished and dependable for the people it is for.
- 80-89 Among the best vibe-coded projects: complete, pleasant to use, clearly above its peers.
- 90-100 Exceptional: would impress even by professional standards. Rare.
Score each factor independently; do not give every factor the same value.

THE 7 FACTORS
What users experience (most of the weight):
- functionality: does it do what the README promises? Are the features wired together, and does it handle bad
  or missing input with a message instead of crashing?
- user_journey: the user's path from start to finish. Get it running (installer, package, launch script or a
  README quick start that matches the code; code signing is never expected). First-run setup where needed (setup
  wizard, Android permission requests with an explanation). Finding their way (menus/screens/commands feel like
  one product, every screen has a way back, common settings reachable in 1-2 steps rather than menus inside menus
  inside menus). Finishing the main task without dead ends. A clear confirmation that it worked ("saved",
  "synced to your phone", level complete, a CLI summary). Clear error and empty states. Use the USER JOURNEY
  EVIDENCE block when it is provided.
- ui_ux: quality of the individual screens or output for the target device: clarity, layout, feedback, and fit
  with the input method (touch, keyboard, buttons, glanceable display, terminal).
- resonance: real-world value -- a genuine problem solved or real enjoyment for an identifiable audience, and
  difference from common alternatives. Independent of code quality.
- creativity: custom mechanics, algorithms, hardware/protocol work or inventive ideas beyond template/wrapper code.
Engineering (less weight; phrase weaknesses as what a pro team would do next):
- code_health: readable names, code organized into sensible files, not dominated by giant tangled functions,
  some tests or self-checks, declared dependencies. A few large functions are normal in vibe-coded projects.
- operational_safety: does not hang (timeouts/bounded waits), does not lose data, releases files/sockets/devices,
  validates external input, and does not silently ignore errors.

SIZE IS NEVER A QUALITY SIGNAL: do not reward or penalize a project for its total lines of code or number of
files. Many vibe-coded projects are deliberately content-heavy -- story and visual-novel apps, games with dialogue,
lyrics, level data, quizzes or translations -- and that content is the point of the project, not bloat. Judge code
health on the program logic only; a large, well-organized content file is fine.

PLATFORM-RELATIVE GRADING: if Target Platforms / a Device Profile are given, judge every factor against THAT
device. On microcontrollers, consoles or small screens, a minimal, fast, glanceable UI and tight memory use are
strengths; desktop expectations (rich menus, help pages, Docker) do not apply.
"""

SYSTEM_PROMPT_ARCHETYPE = """You are an experienced reviewer of vibe-coded software (programs written by AI from someone's prompts).
Your job is to understand the repository's TRUE purpose and audience and allocate percentage weights across the
7 factors (summing to exactly 100) that fit this kind of project. You also give an initial malware_risk rating as
a separate trust check.

""" + REFERENCE_CLASS + """
WEIGHTS: use the row that matches the project's category (weights outside the row are clamped):
""" + render_ranges_text() + """

MALWARE RISK (separate trust check, 0-100, higher = safer; NOT one of the 7 weighted factors):
- Measures MALICIOUS INTENT ONLY: credential theft, token/cookie/wallet harvesting, spyware, data exfiltration to unrelated servers, backdoors, remote-code droppers, and hardcoded PRODUCTION secrets.
- If malicious behavior is found, score 0-10 and cite the exact files/lines. If none is found, score 90-100.

CLASSIFICATION RULES:
- NEVER output generic labels such as 'General Software Project', 'Codebase', or audience 'Developers'.
- The input's PROJECT CLASSIFICATION (category, target platforms, device profile) is already decided: do not contradict it.

Output strictly valid JSON matching this schema:
{
  "archetype": {
    "name": "<string>",
    "category": "<specific domain archetype>",
    "primary_language": "<string e.g. Python, C++, TypeScript, Kotlin, Rust>",
    "target_audience": "<true intended user base>",
    "core_purpose": "<clear 1-2 sentence explanation of what the app does for users>",
    "intended_scale": "<e.g. Desktop Application, Embedded Firmware, Mobile App, Web Service, Consumer Tool>"
  },
  "weights": {
    "functionality": <float>, "user_journey": <float>, "ui_ux": <float>, "resonance": <float>,
    "creativity": <float>, "code_health": <float>, "operational_safety": <float>,
    "justification": "<why these weights fit this kind of project>"
  },
  "qualifiers": {
    "malware_risk": <float 0-100>,
    "malware_reasoning": "<what was reviewed and whether any malicious behavior was found>"
  }
}
"""


SYSTEM_PROMPT_MICRO_7B = """You are a careful, evidence-driven code reviewer (Model: Qwen2.5-Coder-7B) reading ONE chunk of a
vibe-coded project. Evaluate the actual code shown before assigning numbers.

""" + REFERENCE_CLASS + """
CHUNK RULES:
- RELEVANCE: user_journey, ui_ux, operational_safety and resonance often live in only SOME files. For each of them
  set `relevant` to true ONLY if THIS chunk contains code that bears on it (user_journey: setup/onboarding,
  navigation, menus, settings, confirmations, error/empty states, install or launch scripts; ui_ux: screens,
  rendering, input handling, CLI output or a public API; operational_safety: I/O, network, memory, threads,
  external input; resonance: user-facing features). If false, leave strengths/weaknesses empty.
- Never list "not applicable" as a weakness.
- CONTENT CHUNKS: if this chunk is mostly content or data (story text, dialogue, lyrics, level/quest data,
  translations, quiz questions), judge code_health only on whether that content is organized and loadable, and
  never mark anything down for its length.
- malware_risk (separate qualifier): 95-100 if no malicious exfiltration/backdoors/credential theft found; 0-10 if
  malware found. If (and only if) you score it below 50, copy the exact suspicious line(s) verbatim into
  malware_risk.suspicious_code with their file path. Otherwise leave suspicious_code empty.

Fill out `detailed_findings` FIRST (citing real file/function names from the chunk; at most 2 short strengths and
2 short weaknesses per factor), and ONLY THEN assign `factor_scores` that match them.

Output strictly valid JSON matching this schema:
{
  "detailed_findings": {
    "malware_risk": {"strengths": [], "weaknesses": [], "suspicious_code": []},
    "<each of the 7 factors>": {"relevant": <bool, only for user_journey/ui_ux/operational_safety/resonance>, "strengths": ["<specific evidence>"], "weaknesses": ["<specific gap>"]}
  },
  "factor_scores": {"functionality": <float>, "user_journey": <float>, "ui_ux": <float>, "resonance": <float>, "creativity": <float>, "code_health": <float>, "operational_safety": <float>},
  "qualifier_scores": {"malware_risk": <float 0-100>},
  "micro_critique_summary": "<1-2 sentences citing specific files and concrete strengths/gaps in this chunk>"
}
"""


SYSTEM_PROMPT_MACRO_14B = """You are a senior reviewer of vibe-coded software (programs written by AI from someone's prompts).
Combine the project description, user-journey evidence, code measurements, a code sample and the chunk reviewers'
notes into a fair, un-inflated evaluation of this vibe-coded project.

""" + REFERENCE_CLASS + """
GROUNDING RULES:
- code_health must agree with the measurements: if average cyclomatic complexity is above 7, keep code_health at
  or below 70. Clean, modular, low-complexity code deserves 75-90.
- resonance: saturated clones (generic todo apps, basic chat wrappers, unedited templates) score 35-62; projects
  solving tangible problems for real people score 70-95 even when code_health is lower.
- If a project claims a user interface or journey that does not exist in the code, score it low.
- malware_risk (qualifier): 90-100 if no malicious behavior was found in the reviewed code; 0-10 if it was.

Write `findings` FIRST (one concrete sentence per factor citing specific files/modules), THEN `factor_scores` that
match them. Every string is ONE sentence.
- peer_summary: where this project stands among vibe-coded projects of its kind (encouraging but honest).
- pro_next_steps: what a professional team would do next to take it further (specific, practical).

Output strictly valid JSON matching this schema:
{
  "findings": {"<each of the 7 factors and malware_risk>": {"reasoning": "<one sentence>", "weakness": "<one specific weakness>"}},
  "factor_scores": {"functionality": <float>, "user_journey": <float>, "ui_ux": <float>, "resonance": <float>, "creativity": <float>, "code_health": <float>, "operational_safety": <float>},
  "qualifier_scores": {"malware_risk": <float 0-100>},
  "macro_critique_summary": "<2-3 sentences on what users get and how well it holds together>",
  "peer_summary": "<one or two sentences>",
  "verdict_title": "<punchy 3-5 word headline, e.g. 'Polished Native Voice RPG Engine'>",
  "top_solid_features": ["<Feature>: <why it works well>"],
  "top_features_needing_work": ["<Feature>: <specific gap>"],
  "pro_next_steps": ["<step 1>", "<step 2>", "<step 3>"]
}
"""

# ---------------------------------------------------------------------------
# JSON schemas passed to Ollama's structured-output `format` so models cannot
# omit required keys or answer with a free-form {"response": "..."} object.
# Property order matters: findings are generated before scores.
# ---------------------------------------------------------------------------
from letsvibe.core.models import CORE_FACTORS  # noqa: E402

_SCORED = list(CORE_FACTORS)
_ALL = _SCORED + ["malware_risk"]
_STR = {"type": "string"}
_STR_LIST = lambda n: {"type": "array", "items": _STR, "maxItems": n}  # noqa: E731
_SCORES = {"type": "object", "properties": {f: {"type": "number"} for f in _SCORED}, "required": _SCORED}
_QUALIFIERS = {"type": "object", "properties": {"malware_risk": {"type": "number"}}, "required": ["malware_risk"]}


# Factors that legitimately appear in only part of a codebase; batches flag whether they apply.
# Creativity is deliberately NOT here: a batch with no custom logic is evidence about creativity,
# not a sign the factor is irrelevant (treating it as irrelevant inflated creativity in testing).
LOCALIZED_FACTORS = ("user_journey", "ui_ux", "operational_safety", "resonance")


def micro_schema(factors=None, include_malware: bool = True) -> dict:
    """Full per-chunk schema, or (triage strategy) only the factors this chunk's role can inform."""
    if factors:
        return _routed_micro_schema(list(factors), include_malware)
    return _full_micro_schema()


def _routed_micro_schema(factors, include_malware: bool) -> dict:
    finding = {
        "type": "object",
        "properties": {"strengths": _STR_LIST(2), "weaknesses": _STR_LIST(2), "reasoning": _STR},
        "required": ["strengths", "weaknesses", "reasoning"],
    }
    names = list(factors) + (["malware_risk"] if include_malware else [])
    findings = {f: finding for f in names}
    if include_malware:
        findings["malware_risk"] = {
            "type": "object",
            "properties": {**finding["properties"], "suspicious_code": {
                "type": "array", "maxItems": 3,
                "items": {"type": "object", "properties": {"file": _STR, "code": _STR}, "required": ["file", "code"]}}},
            "required": finding["required"] + ["suspicious_code"],
        }
    props = {
        "detailed_findings": {"type": "object", "properties": findings, "required": names},
        "factor_scores": {"type": "object", "properties": {f: {"type": "number"} for f in factors}, "required": list(factors)},
    }
    required = ["detailed_findings", "factor_scores"]
    if include_malware:
        props["qualifier_scores"] = _QUALIFIERS
        required.append("qualifier_scores")
    props["micro_critique_summary"] = _STR
    required.append("micro_critique_summary")
    return {"type": "object", "properties": props, "required": required}


def _full_micro_schema() -> dict:
    finding = {
        "type": "object",
        "properties": {"strengths": _STR_LIST(2), "weaknesses": _STR_LIST(2)},
        "required": ["strengths", "weaknesses"],
    }
    # Only for the malware check: exact quotes of code that looks malicious (empty when clean),
    # used to ask the owner about those specific lines. Never published.
    suspicious = {
        "type": "array",
        "maxItems": 3,
        "items": {"type": "object", "properties": {"file": _STR, "code": _STR}, "required": ["file", "code"]},
    }
    malware_finding = {
        "type": "object",
        "properties": {**finding["properties"], "suspicious_code": suspicious},
        "required": finding["required"] + ["suspicious_code"],
    }
    localized = {
        "type": "object",
        "properties": {"relevant": {"type": "boolean"}, **finding["properties"]},
        "required": ["relevant"] + finding["required"],
    }
    findings = {f: (localized if f in LOCALIZED_FACTORS else finding) for f in _ALL}
    findings["malware_risk"] = malware_finding
    return {
        "type": "object",
        "properties": {
            "detailed_findings": {"type": "object", "properties": findings, "required": _ALL},
            "factor_scores": _SCORES,
            "qualifier_scores": _QUALIFIERS,
            "micro_critique_summary": _STR,
        },
        "required": ["detailed_findings", "factor_scores", "qualifier_scores", "micro_critique_summary"],
    }


def macro_schema() -> dict:
    finding = {"type": "object", "properties": {"reasoning": _STR, "weakness": _STR}, "required": ["reasoning", "weakness"]}
    return {
        "type": "object",
        "properties": {
            "findings": {"type": "object", "properties": {f: finding for f in _ALL}, "required": _ALL},
            "factor_scores": _SCORES,
            "qualifier_scores": _QUALIFIERS,
            "macro_critique_summary": _STR,
            "peer_summary": _STR,
            "verdict_title": _STR,
            "top_solid_features": _STR_LIST(3),
            "top_features_needing_work": _STR_LIST(3),
            "pro_next_steps": _STR_LIST(3),
        },
        "required": [
            "findings", "factor_scores", "qualifier_scores", "macro_critique_summary", "peer_summary", "verdict_title",
            "top_solid_features", "top_features_needing_work", "pro_next_steps",
        ],
    }



def archetype_schema() -> dict:
    archetype = {
        "type": "object",
        "properties": {
            "name": _STR, "category": _STR, "primary_language": _STR, "target_audience": _STR,
            "core_purpose": _STR, "intended_scale": _STR,
        },
        "required": ["name", "category", "primary_language", "target_audience", "core_purpose", "intended_scale"],
    }
    weights = {
        "type": "object",
        "properties": {**{f: {"type": "number"} for f in _SCORED}, "justification": _STR},
        "required": _SCORED + ["justification"],
    }
    qualifiers = {
        "type": "object",
        "properties": {"malware_risk": {"type": "number"}, "malware_reasoning": _STR},
        "required": ["malware_risk", "malware_reasoning"],
    }
    return {
        "type": "object",
        "properties": {"archetype": archetype, "weights": weights, "qualifiers": qualifiers},
        "required": ["archetype", "weights", "qualifiers"],
    }
