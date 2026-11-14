"""
Consensus and harmonization engine for the Dual-Model Blend.
Synthesizes micro and macro evaluations into a single, cohesive VibeReport.
"""

import re
import time
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional
from letsvibe.core.models import (
    LEGACY_V5_FACTORS as CORE_FACTORS,
    DeterministicMetrics,
    DynamicWeights,
    FactorEvaluation,
    FactorType,
    ModelPerspective,
    ProjectArchetype,
    VibeReport,
)
from letsvibe.core.platforms import GENERAL_CATEGORIES, platform_context
from letsvibe.evaluator.classifier import Classification
from .weights import clamp_weights, ranges_for
from .checklist import (
    CHECKLIST_SYSTEM_PROMPT,
    build_checklist_prompt,
    checklist_schema,
    score_checklist,
)
from letsvibe.evaluator.ollama import (
    CHARS_PER_TOKEN,
    TEMPLATE_OVERHEAD_TOKENS,
    CpuSpilloverError,
    OllamaClient,
    estimate_tokens,
    get_free_vram_mb,
    max_ctx_for,
)
from .prompts import (
    SYSTEM_PROMPT_ARCHETYPE,
    SYSTEM_PROMPT_MACRO_14B,
    SYSTEM_PROMPT_MICRO_7B,
    LOCALIZED_FACTORS,
    archetype_schema,
    macro_schema,
    micro_schema,
)

_PLACEHOLDER_RE = re.compile(
    r"^\s*(none|n/?a|not applicable|nothing)\b|not applicable|none applicable|does not contain any"
    r"|no [\w/ ]{0,30}(code|considerations) (evident|detected|found|present)"
    r"|^\s*no (obvious |significant |major )?(stub\w*|issues?|problems?|defects?|incomplete|malicious)\b.*\b(found|detected|identified)\W*$",
    re.I,
)


def _real_findings(items: Any) -> List[str]:
    """Drops placeholder text ("None applicable", "N/A", ...) that small models emit instead of a finding."""
    return [str(x).strip() for x in (items or []) if str(x).strip() and not _PLACEHOLDER_RE.search(str(x))]


def _batch_relevant(findings: Dict[str, Any], factor: str) -> bool:
    """Localized factors count only where the batch says it contains relevant code (missing flag = relevant)."""
    if factor not in LOCALIZED_FACTORS:
        return True
    entry = findings.get(factor)
    return not (isinstance(entry, dict) and entry.get("relevant") is False)


MACRO_OUTPUT_TOKENS = 1200

# Fraction of micro batches that must return real scores before a report may be ranked.
MIN_MICRO_BATCH_SUCCESS = 0.5


class IncompleteEvaluationError(RuntimeError):
    """Raised when the models failed to produce real scores; such reports must never be ranked."""


def _has_all_scores(data: Any) -> bool:
    """True only if the model output carries a numeric score for every core factor."""
    if not isinstance(data, dict):
        return False
    fs = data.get("factor_scores")
    if not isinstance(fs, dict):
        return False
    for f in CORE_FACTORS:
        try:
            float(fs[f])
        except (KeyError, TypeError, ValueError):
            return False
    return True


# Letter-grade cutoffs, aligned with the prompt rubric:
#   55-68 = competent working project, 69-79 = solid, 80-89 = standout, 90+ = category-leading.
GRADE_CUTOFFS = (
    (95.0, "A+"),
    (91.0, "A"),
    (88.0, "A-"),
    (84.0, "B+"),
    (80.0, "B"),
    (76.0, "B-"),
    (72.0, "C+"),
    (65.0, "C"),
    (58.0, "C-"),
    (45.0, "D"),
)


def calculate_letter_grade(score: float) -> str:
    """Maps a 0-100 score to a letter grade (a typical working project of ~62 earns a C-, not an F)."""
    for cutoff, grade in GRADE_CUTOFFS:
        if score >= cutoff:
            return grade
    return "F"


def compute_deterministic_adjustments(metrics: DeterministicMetrics) -> Dict[str, float]:
    """
    Computes bounded, objective score adjustments from deterministic AST metrics
    so LLM grade inflation is anchored by real code measurements.
    """
    maint_adj = 0.0
    ops_adj = 0.0
    func_adj = 0.0

    # 1. Cyclomatic Complexity impact on Maintainability
    avg_cc = float(metrics.avg_cyclomatic_complexity or 0.0)
    max_cc = int(metrics.max_cyclomatic_complexity or 0)

    if avg_cc > 0:
        if avg_cc <= 2.8 and max_cc <= 15:
            maint_adj += 4.0  # Exceptionally clean, modular functions
        elif avg_cc <= 4.0 and max_cc <= 22:
            maint_adj += 1.5
        elif avg_cc >= 8.0 or max_cc >= 55:
            maint_adj -= 10.0  # Severe monolithic god-functions
        elif avg_cc >= 5.8 or max_cc >= 35:
            maint_adj -= 5.5

    # 2. Hardcoded secrets / security findings impact on Operational Safety
    if metrics.detected_secrets_count > 0:
        ops_adj -= min(18.0, metrics.detected_secrets_count * 6.0)

    # 3. Test suite presence provides a modest verifiable boost to Functionality & Safety
    test_ratio = float(metrics.test_to_code_ratio or 0.0)
    if test_ratio >= 0.15:
        func_adj += 3.5
        ops_adj += 2.5
    elif test_ratio >= 0.05:
        func_adj += 1.5

    return {
        "maintainability": maint_adj,
        "operational_safety": ops_adj,
        "functionality": func_adj,
    }


class ConsensusEngine:
    """Orchestrates Stage 1 & Stage 2 evaluations and blends perspectives."""

    def __init__(
        self,
        client: OllamaClient,
        micro_model: str = "qwen2.5-coder:7b",
        macro_model: str = "qwen2.5-coder:14b",
        explicit_macro: bool = False,
        max_pipeline_seconds: Optional[float] = None,
    ):
        self.client = client
        self.micro_model = micro_model
        self.macro_model = macro_model
        self.explicit_macro = explicit_macro
        self.max_pipeline_seconds = max_pipeline_seconds

    def evaluate_pipeline(
        self,
        repo_name: str,
        repo_source: str,
        manifest_batches: Any,
        metrics: DeterministicMetrics,
        mode: str = "blend",  # "blend", "fast" (7B only), or "deep" (14B only)
        progress_callback: Optional[Callable[[str, int], None]] = None,
        classification: Optional[Classification] = None,
    ) -> VibeReport:
        pipeline_start = time.perf_counter()
        if isinstance(manifest_batches, str):
            manifest_batches = [("Full Codebase", manifest_batches)]
        # Real 7B audits take ~30s per batch and the CPU-offloaded 14B ~3-4 minutes in total,
        # so the hard stop scales with the work instead of being a fixed 8 minutes.
        deadline_seconds = self.max_pipeline_seconds or min(3600.0, 420.0 + 45.0 * len(manifest_batches))

        def emit_progress(msg: str, pct: int) -> None:
            if progress_callback:
                progress_callback(msg, max(0, min(100, pct)))

        def check_deadline(stage_label: str) -> None:
            elapsed = time.perf_counter() - pipeline_start
            if elapsed > deadline_seconds:
                self.client.unload_all_models()
                raise CpuSpilloverError(
                    f"Hard Stop Triggered: Evaluation exceeded maximum allowed wall-clock time "
                    f"({int(elapsed)}s > {int(deadline_seconds)}s) during '{stage_label}'."
                )

        available = self.client.list_models()
        chosen_micro = self.micro_model
        chosen_macro = self.macro_model

        timing_breakdown: Dict[str, float] = {}
        issues_encountered: List[str] = []

        if available:
            if chosen_micro not in available:
                matches = [m for m in available if "qwen" in m or "7b" in m or "llama" in m]
                if matches:
                    chosen_micro = matches[0]
            if chosen_macro not in available:
                matches = [m for m in available if "14b" in m or "coder" in m or "qwen" in m]
                if matches:
                    chosen_macro = matches[0]
                else:
                    chosen_macro = chosen_micro

        readme_info = f"\nREADME Project Overview & Goals:\n{metrics.readme_excerpt[:2500]}\n" if metrics.readme_excerpt else ""
        desktop_pkg_str = "Present (Android APK/AAB / AppImage / Inno Setup / PyInstaller / Native Scripts)" if metrics.has_desktop_packaging else "None detected"
        top_cc_str = (
            ", ".join(
                f"{getattr(f, 'name', getattr(f, 'function_name', str(f)))} (CC={getattr(f, 'complexity', '?')})"
                if not isinstance(f, str) else f
                for f in metrics.top_complex_functions[:5]
            )
            if metrics.top_complex_functions
            else "None flagged"
        )
        metrics_summary = f"""
Deterministic Static AST Metrics:
- Total Lines of Code: {metrics.total_loc}
- Total Files: {metrics.total_files}
- Languages: {metrics.languages}
- Avg Cyclomatic Complexity: {metrics.avg_cyclomatic_complexity} (<=3.0 is very clean; >=6.0 is complex)
- Max Cyclomatic Complexity: {metrics.max_cyclomatic_complexity} (Top complex functions: {top_cc_str})
- Hardcoded Secrets/Risks Found: {metrics.detected_secrets_count} ({metrics.secret_findings[:3]})
- Test Files Count: {metrics.test_files_count} (Test-to-Code Ratio: {metrics.test_to_code_ratio})
- Native Standalone Packaging (Mobile APK/Desktop): {desktop_pkg_str}
- Has License: {metrics.has_license}
"""
        # Classification runs before grading (see evaluator/classifier.py); without one, fall back to build-file detection
        if classification is None:
            classification = Classification(platforms=list(metrics.detected_platforms), device_profile=metrics.device_profile)
        issues_encountered.extend(classification.issues)
        platform_block = platform_context(classification.platforms, classification.device_profile)
        classification_block = (
            "PROJECT CLASSIFICATION (already decided):\n"
            f"Category: {GENERAL_CATEGORIES.get(classification.general_category, 'Other')}\n"
            + (platform_block + "\n" if platform_block else "")
        )
        metrics_with_readme = metrics_summary + classification_block + readme_info

        if chosen_micro != self.micro_model:
            issues_encountered.append(f"Preferred micro-model {self.micro_model} not found, fell back to {chosen_micro}")
        if chosen_macro != self.macro_model and mode in ("blend", "deep"):
            issues_encountered.append(f"Preferred macro-model {self.macro_model} not found, fell back to {chosen_macro}")

        # -------------------------------------------------------------
        # STAGE 1: Archetype Detection & Dynamic Weights
        # -------------------------------------------------------------
        emit_progress(f"Stage 1/3: Detecting project archetype & dynamic weights ({chosen_micro})...", 22)
        first_batch_text = manifest_batches[0][1]
        file_tree_snippet = first_batch_text.split("# REPOSITORY DIRECTORY LAYOUT:\n")
        tree_text = file_tree_snippet[1].split("\n--- START FILE:")[0] if len(file_tree_snippet) > 1 else first_batch_text[:4000]

        prompt_stage1 = f"""
Analyze this repository's true purpose, domain archetype, and target audience, and assign unbiased dynamic factor weights:
{metrics_with_readme}

Repository File Tree Structure:
{tree_text[:4000]}
"""
        t0 = time.perf_counter()
        try:
            stage1_data = self.client.generate_json(
                model=chosen_micro,
                system_prompt=SYSTEM_PROMPT_ARCHETYPE,
                user_prompt=prompt_stage1,
                format_schema=archetype_schema(),
                max_output_tokens=900,
            )
        except CpuSpilloverError:
            raise
        except Exception as e:
            issues_encountered.append(f"Stage 1 JSON generation warning: {e}")
            stage1_data = {}
        timing_breakdown["stage_1_archetype_and_weights_sec"] = round(time.perf_counter() - t0, 2)

        arch_raw = stage1_data.get("archetype", {})
        archetype = ProjectArchetype(
            general_category=classification.general_category,
            platforms=list(classification.platforms),
            device_profile=classification.device_profile,
            name=arch_raw.get("name", repo_name),
            category=arch_raw.get("category", "General Software Project"),
            primary_language=arch_raw.get("primary_language", "Multi-language"),
            target_audience=arch_raw.get("target_audience", "Developers"),
            core_purpose=arch_raw.get("core_purpose", "Software application or utility"),
            intended_scale=arch_raw.get("intended_scale", "Production"),
        )

        weights_raw = stage1_data.get("weights", {})
        weights_defaults = DynamicWeights()
        weights = DynamicWeights(
            maintainability=float(weights_raw.get("maintainability", weights_raw.get("complexity", weights_defaults.maintainability))),
            functionality=float(weights_raw.get("functionality", weights_defaults.functionality)),
            creativity=float(weights_raw.get("creativity", weights_defaults.creativity)),
            ui_ux=float(weights_raw.get("ui_ux", weights_defaults.ui_ux)),
            architecture=float(weights_raw.get("architecture", weights_raw.get("project_flow", weights_defaults.architecture))),
            operational_safety=float(weights_raw.get("operational_safety", weights_defaults.operational_safety)),
            resonance=float(weights_raw.get("resonance", weights_defaults.resonance)),
            justification=weights_raw.get("justification", weights_defaults.justification),
        ).normalize()
        # Enforce the rubric's range row for this category (the model often ignores it)
        clamped, moved = clamp_weights({f: getattr(weights, f) for f in CORE_FACTORS}, classification.general_category)
        if moved:
            row_label = ranges_for(classification.general_category)[0]
            issues_encountered.append(f"Weights for {', '.join(moved)} were outside the '{row_label}' ranges and were clamped.")
            note = f" (Weights adjusted to the rubric's '{row_label}' ranges.)"
            weights = DynamicWeights(**clamped, justification=(weights.justification or "").strip() + note).normalize()

        # Every later grading prompt is told which hardware to judge against
        if platform_block:
            metrics_summary += platform_block + "\n"

        qualifiers_raw = stage1_data.get("qualifiers", stage1_data.get("qualifier_scores", {}))
        stage1_malware = float(qualifiers_raw.get("malware_risk", qualifiers_raw.get("security", 92.0)))

        # -------------------------------------------------------------
        # STAGE 2: Model Passes
        # -------------------------------------------------------------
        perspectives: List[ModelPerspective] = []
        micro_data: Dict = {"factor_scores": {}, "detailed_findings": {}}
        macro_data: Dict = {}
        checklist_scores: Dict[str, float] = {}
        checklist_failures: Dict[str, List[str]] = {}
        no_relevant_code: set = set()

        total_batches = len(manifest_batches)

        if mode in ("blend", "fast"):
            t1 = time.perf_counter()
            accumulated_scores: Dict[str, List[float]] = {}
            irrelevant_scores: Dict[str, List[float]] = {}  # scores from batches with no code for that factor
            accumulated_findings: Dict[str, Dict[str, List[str]]] = {}
            summaries: List[str] = []
            failed_batches: List[str] = []

            for b_idx, (b_title, b_content) in enumerate(manifest_batches, 1):
                check_deadline(f"Pass 1 Micro Batch {b_idx}/{total_batches} ({b_title})")

                batch_pct = 28 + int(((b_idx - 1) / max(1, total_batches)) * 48)
                emit_progress(
                    f"Stage 2/3 [7B Micro]: Auditing batch {b_idx} of {total_batches} — {b_title}...",
                    batch_pct,
                )

                prompt_micro = f"""
Project: {archetype.name} ({archetype.category})
Intended Audience: {archetype.target_audience}
Core Purpose: {archetype.core_purpose}
Module Batch {b_idx}/{total_batches}: {b_title}
{metrics_summary}

Source Code:
{b_content}
"""
                try:
                    b_res = self.client.generate_json(
                        model=chosen_micro,
                        system_prompt=SYSTEM_PROMPT_MICRO_7B,
                        user_prompt=prompt_micro,
                        format_schema=micro_schema(),
                        max_output_tokens=1400,
                    )
                    if getattr(self.client, "last_call", {}).get("trimmed"):
                        issues_encountered.append(f"Pass 1 batch {b_title}: input trimmed to fit the context window.")
                    if not _has_all_scores(b_res):
                        keys = sorted(b_res.keys()) if isinstance(b_res, dict) else type(b_res).__name__
                        failed_batches.append(b_title)
                        issues_encountered.append(f"Pass 1 Micro batch {b_title} returned no usable scores (keys: {keys}).")
                        continue
                    b_findings = b_res.get("detailed_findings", {}) or {}
                    for k, v in b_res.get("factor_scores", {}).items():
                        try:
                            target = accumulated_scores if _batch_relevant(b_findings, k) else irrelevant_scores
                            target.setdefault(k, []).append(float(v))
                        except (ValueError, TypeError):
                            pass
                    qual_scores_b = b_res.get("qualifier_scores", b_res.get("qualifiers", {}))
                    for k, v in qual_scores_b.items():
                        try:
                            accumulated_scores.setdefault(k, []).append(float(v))
                        except (ValueError, TypeError):
                            pass

                    for k, v in b_findings.items():
                        if not isinstance(v, dict) or not _batch_relevant(b_findings, k):
                            continue
                        if k not in accumulated_findings:
                            accumulated_findings[k] = {"strengths": [], "weaknesses": [], "reasoning": ""}
                        accumulated_findings[k]["strengths"].extend(_real_findings(v.get("strengths")))
                        accumulated_findings[k]["weaknesses"].extend(_real_findings(v.get("weaknesses")))
                        if v.get("reasoning"):
                            if accumulated_findings[k]["reasoning"]:
                                accumulated_findings[k]["reasoning"] += f" | {v.get('reasoning')}"
                            else:
                                accumulated_findings[k]["reasoning"] = v.get("reasoning")
                    if b_res.get("micro_critique_summary"):
                        summaries.append(f"[{b_title}]: {b_res['micro_critique_summary']}")
                except CpuSpilloverError:
                    raise
                except Exception as e:
                    failed_batches.append(b_title)
                    issues_encountered.append(f"Pass 1 Micro (7B) batch {b_title} failed: {e}")

            ok_batches = total_batches - len(failed_batches)
            if ok_batches < max(1, total_batches * MIN_MICRO_BATCH_SUCCESS):
                raise IncompleteEvaluationError(
                    f"Evaluation incomplete: only {ok_batches}/{total_batches} code batches were audited "
                    f"successfully by {chosen_micro}. No ranking was produced. "
                    f"Details: {' | '.join(issues_encountered)[-400:]}"
                )

            # Failsafe for factors no batch found relevant code for: in blend/deep the whole-repo 14B review
            # and the checklist decide (a claimed-but-missing UI still scores low there). In fast mode
            # there is no 14B, so fall back to the batch scores rather than dropping the factor.
            for f in LOCALIZED_FACTORS:
                if f in accumulated_scores or f not in irrelevant_scores:
                    continue
                if mode == "fast":
                    accumulated_scores[f] = irrelevant_scores[f]
                    issues_encountered.append(f"{f}: no batch contained relevant code; fast mode used all batch scores.")
                else:
                    no_relevant_code.add(f)

            # Weakest-link batch aggregation: prevents trivial config batches from masking messy core batches
            avg_micro_scores = {}
            for k, vals in accumulated_scores.items():
                if not vals:
                    continue
                mean_val = sum(vals) / len(vals)
                if len(vals) > 1 and k in ("maintainability", "functionality", "operational_safety"):
                    min_val = min(vals)
                    avg_micro_scores[k] = round(mean_val * 0.65 + min_val * 0.35, 1)
                elif len(vals) > 1 and k in ("creativity", "resonance"):
                    max_val = max(vals)
                    avg_micro_scores[k] = round(mean_val * 0.60 + max_val * 0.40, 1)
                else:
                    avg_micro_scores[k] = round(mean_val, 1)

            micro_data = {
                "factor_scores": avg_micro_scores,
                "detailed_findings": accumulated_findings,
                "micro_critique_summary": " | ".join(summaries),
            }
            timing_breakdown["pass_1_micro_analyst_sec"] = round(time.perf_counter() - t1, 2)

            perspectives.append(
                ModelPerspective(
                    model_name=chosen_micro,
                    role="Micro Syntax & Code Hygiene Analyst (Pass 1)",
                    factor_scores=avg_micro_scores,
                    critique_summary=micro_data["micro_critique_summary"],
                )
            )

        if mode in ("blend", "deep"):
            check_deadline("Stage 3 Macro 14B Preparation")
            emit_progress(f"Stage 3/3 [14B Macro]: Freeing 7B VRAM & running architectural synthesis ({chosen_macro})...", 82)

            try:
                self.client.unload_all_models()
                time.sleep(0.75)
            except Exception:
                pass

            readme_sample = metrics.readme_excerpt[:1500] if metrics.readme_excerpt else "No README available."
            micro_summary_trimmed = (micro_data.get("micro_critique_summary") or "N/A")[:1800]

            # Extract concrete strengths & weaknesses discovered in Pass 1 (WITHOUT feeding numerical scores, to prevent anchoring!)
            qualitative_digest_lines = []
            for fk, fv in micro_data.get("detailed_findings", {}).items():
                w_list = fv.get("weaknesses", [])[:3]
                s_list = fv.get("strengths", [])[:2]
                if w_list or s_list:
                    qualitative_digest_lines.append(f"- {fk.upper()}: Strengths={s_list} | Weaknesses={w_list}")
            qualitative_digest = "\n".join(qualitative_digest_lines)[:1800]

            # Include a representative slice of actual source code from the batches so 14B is never blind to the code
            code_excerpt_parts = []
            for b_title, b_text in manifest_batches[:2]:
                if "--- START FILE:" in b_text:
                    code_slice = "--- START FILE:" + b_text.split("--- START FILE:", 1)[1]
                    code_excerpt_parts.append(code_slice[:1200])
            representative_code = "\n".join(code_excerpt_parts)[:2000]

            # Size every section to the 14B's context budget up front (instead of the client cutting the
            # tail), shrinking the least important first: tree -> code sample -> README -> Pass 1 notes.
            budget_chars = int(
                (max_ctx_for(chosen_macro) - estimate_tokens(SYSTEM_PROMPT_MACRO_14B) - MACRO_OUTPUT_TOKENS
                 - TEMPLATE_OVERHEAD_TOKENS - 32) * CHARS_PER_TOKEN
            )
            sections = {
                "notes": f"{micro_summary_trimmed}\n{qualitative_digest}",
                "readme": readme_sample,
                "code": representative_code,
                "tree": tree_text[:1500],
            }

            def render_macro_input() -> str:
                return f"""
Project Archetype: {archetype.name} ({archetype.category})
Target Audience: {archetype.target_audience}
Core Purpose: {archetype.core_purpose}

{metrics_summary}

Pass 1 Module-Level Qualitative Audit Notes (Do NOT inflate; penalize the weaknesses listed below):
{sections["notes"]}

README & Architectural Purpose:
{sections["readme"]}

Representative Distilled Code Sample:
{sections["code"]}

Repository Directory Structure:
{sections["tree"]}
"""

            macro_input = render_macro_input()
            for key in ("tree", "code", "readme", "notes"):
                over = len(macro_input) - budget_chars
                if over <= 0:
                    break
                sections[key] = sections[key][: max(0, len(sections[key]) - over)]
                macro_input = render_macro_input()
            shrunk = [k for k, full in (("tree", tree_text[:1500]), ("code", representative_code), ("readme", readme_sample)) if len(sections[k]) < len(full)]
            if shrunk:
                issues_encountered.append(f"Pass 2 Macro: shortened {', '.join(shrunk)} to fit the 14B context window.")
            t2 = time.perf_counter()
            macro_data = {}
            for attempt in (1, 2):
                try:
                    candidate = self.client.generate_json(
                        model=chosen_macro,
                        system_prompt=SYSTEM_PROMPT_MACRO_14B,
                        user_prompt=macro_input,
                        temperature=0.2 if attempt == 1 else 0.0,
                        keep_alive=0,
                        format_schema=macro_schema(),
                        max_output_tokens=MACRO_OUTPUT_TOKENS,
                    )
                    if getattr(self.client, "last_call", {}).get("trimmed"):
                        issues_encountered.append("Pass 2 Macro: input trimmed to fit the context window.")
                except CpuSpilloverError:
                    raise
                except Exception as e:
                    issues_encountered.append(f"Pass 2 Macro attempt {attempt} failed: {e}")
                    continue
                if _has_all_scores(candidate) and str(candidate.get("macro_critique_summary") or "").strip():
                    macro_data = candidate
                    break
                keys = sorted(candidate.keys()) if isinstance(candidate, dict) else type(candidate).__name__
                issues_encountered.append(f"Pass 2 Macro attempt {attempt} returned incomplete output (keys: {keys}).")

            if mode in ("blend", "deep") and not macro_data:
                raise IncompleteEvaluationError(
                    f"Evaluation incomplete: {chosen_macro} did not return a complete architectural review. "
                    f"No ranking was produced. Details: {' | '.join(issues_encountered)[-400:]}"
                )

            # Normalize the compact macro findings into the shared strengths/weaknesses/reasoning shape
            macro_data["detailed_findings"] = {
                k: {
                    "strengths": [],
                    "weaknesses": _real_findings([v.get("weakness")]),
                    "reasoning": str(v.get("reasoning") or "").strip(),
                }
                for k, v in (macro_data.get("findings") or {}).items()
                if isinstance(v, dict)
            }

            # Binary evidence checklist: anchors scores in concrete yes/no answers (non-fatal if it fails)
            try:
                checklist_answers = self.client.generate_json(
                    model=chosen_macro,
                    system_prompt=CHECKLIST_SYSTEM_PROMPT,
                    # Evidence is trimmed here, not by the client, so the questions are never cut off
                    user_prompt=build_checklist_prompt(macro_input[:9000]),
                    temperature=0.0,
                    keep_alive=0,
                    format_schema=checklist_schema(),
                    max_output_tokens=700,
                )
                checklist_scores, checklist_failures = score_checklist(checklist_answers)
                if not checklist_scores:
                    issues_encountered.append("Checklist pass returned no usable answers; using model scores only.")
            except CpuSpilloverError:
                raise
            except Exception as e:
                issues_encountered.append(f"Checklist pass warning: {e}")
            timing_breakdown["pass_2_macro_architect_sec"] = round(time.perf_counter() - t2, 2)

            perspectives.append(
                ModelPerspective(
                    model_name=chosen_macro,
                    role="Macro Architecture & Resonance Auditor (Pass 2)",
                    factor_scores=macro_data.get("factor_scores", {}),
                    critique_summary=macro_data.get("macro_critique_summary", ""),
                )
            )

        emit_progress("Harmonizing dual-model scores & compiling final VibeReport...", 94)

        # FAIL CLOSED: never publish a ranking built from placeholder numbers.
        _micro_fs = micro_data.get("factor_scores", {}) or {}
        _macro_fs = (macro_data.get("factor_scores", {}) if isinstance(macro_data, dict) else {}) or {}
        _missing = [f for f in CORE_FACTORS if f not in _micro_fs and f not in _macro_fs]
        if _missing:
            raise IncompleteEvaluationError(
                "Evaluation incomplete: the models returned no usable scores for "
                f"{', '.join(_missing)}. No ranking was produced. Details: {' | '.join(issues_encountered)[:300]}"
            )

        # -------------------------------------------------------------
        # HARMONIZATION: Blending factor scores, AST telemetry & insights
        # -------------------------------------------------------------
        factor_evaluations: Dict[str, FactorEvaluation] = {}
        core_weighted_sum = 0.0

        core_factors = list(CORE_FACTORS)
        weight_dict = {f: getattr(weights, f) for f in core_factors}

        micro_scores = micro_data.get("factor_scores", {})
        macro_data_scores = macro_data.get("factor_scores", {})
        macro_qualifiers = macro_data.get("qualifier_scores", macro_data.get("qualifiers", {}))
        macro_scores = {**macro_data_scores, **macro_qualifiers}

        micro_findings = micro_data.get("detailed_findings", {})
        macro_findings = macro_data.get("detailed_findings", {})

        ast_adjustments = compute_deterministic_adjustments(metrics)

        def get_valid_score(source: dict, key: str, fallback: float) -> float:
            val = source.get(key)
            if val is not None:
                try:
                    return max(0.0, min(100.0, float(val)))
                except (ValueError, TypeError):
                    pass
            return fallback

        def get_gate_score(source: dict, key: str, fallback: float) -> float:
            val = source.get(key)
            try:
                if val is not None:
                    return max(0.0, min(100.0, float(val)))
            except (ValueError, TypeError):
                pass
            return fallback

        # 1. Malware Risk
        s_malware_micro = get_gate_score(micro_scores, "malware_risk", get_valid_score(micro_scores, "security", stage1_malware))
        if metrics.detected_secrets_count == 0 and "malware_risk" not in micro_scores and "security" not in micro_scores:
            s_malware_micro = max(s_malware_micro, 92.0)
        s_malware_macro = get_gate_score(macro_scores, "malware_risk", get_valid_score(macro_scores, "security", s_malware_micro))
        malware_risk_score = round(s_malware_micro * 0.40 + s_malware_macro * 0.60, 1)

        # 2. Evaluate the 7 weighted factors
        for fname in core_factors:
            # Gate above guarantees at least one model supplied this factor.
            if fname in micro_scores:
                s_micro = get_valid_score(micro_scores, fname, 0.0)
                s_macro = get_valid_score(macro_scores, fname, s_micro)
            else:
                s_macro = get_valid_score(macro_scores, fname, 0.0)
                s_micro = s_macro
                if fname in no_relevant_code:
                    issues_encountered.append(
                        f"{fname}: no code batch contained relevant code; scored from the whole-repo review and checklist only."
                    )
                else:
                    issues_encountered.append(f"{fname}: scored by 14B only (7B returned no score).")

            if mode == "fast":
                raw_blended = s_micro
            elif mode == "deep":
                raw_blended = s_macro
            else:
                if fname in ("maintainability", "functionality", "operational_safety"):
                    # 7B inspected 100% of batches line-by-line, so give it 55% weight on code hygiene
                    raw_blended = s_micro * 0.55 + s_macro * 0.45
                else:
                    # 14B leads on macro architecture, UI/UX, creativity, and resonance (70% macro / 30% micro)
                    raw_blended = s_micro * 0.30 + s_macro * 0.70

            # Anchor with the binary evidence checklist (50/50) when available
            if fname in checklist_scores:
                raw_blended = raw_blended * 0.5 + checklist_scores[fname] * 0.5

            # Apply deterministic AST / security adjustments
            raw_blended += ast_adjustments.get(fname, 0.0)

            # Apply gentle contrast stretch around 72.0 so individual factor scores don't clump in 80-85
            stretched = 72.0 + (raw_blended - 72.0) * 1.25
            blended_score = round(max(0.0, min(100.0, stretched)), 1)

            w = weight_dict.get(fname, 14.28)
            weighted_val = round(blended_score * (w / 100.0), 2)
            core_weighted_sum += weighted_val

            strengths = []
            weaknesses = []
            if fname in macro_findings:
                strengths.extend(macro_findings[fname].get("strengths", []))
                weaknesses.extend(macro_findings[fname].get("weaknesses", []))
            if fname in micro_findings:
                strengths.extend(micro_findings[fname].get("strengths", []))
                weaknesses.extend(micro_findings[fname].get("weaknesses", []))

            weaknesses.extend(f"Failed check: {q}" for q in checklist_failures.get(fname, [])[:2])

            reasoning = macro_findings.get(fname, {}).get("reasoning") or micro_findings.get(fname, {}).get("reasoning", "")
            if len(reasoning) > 450:
                reasoning = reasoning[:447] + "..."

            factor_evaluations[fname] = FactorEvaluation(
                factor=FactorType(fname),
                score=blended_score,
                weight=w,
                weighted_score=weighted_val,
                strengths=list(dict.fromkeys(strengths))[:4],
                weaknesses=list(dict.fromkeys(weaknesses))[:4],
                reasoning=reasoning,
            )

        # 3. Store malware trust check
        for qname, qscore in [("malware_risk", malware_risk_score)]:
            q_strengths = []
            q_weaknesses = []
            if qname in micro_findings:
                q_strengths.extend(micro_findings[qname].get("strengths", []))
                q_weaknesses.extend(micro_findings[qname].get("weaknesses", []))
            if qname in macro_findings:
                q_strengths.extend(macro_findings[qname].get("strengths", []))
                q_weaknesses.extend(macro_findings[qname].get("weaknesses", []))
            q_reasoning = (
                macro_findings.get(qname, {}).get("reasoning")
                or micro_findings.get(qname, {}).get("reasoning")
                or qualifiers_raw.get("malware_reasoning", "")
                or qualifiers_raw.get(f"{qname}_reasoning", "")
            )
            factor_evaluations[qname] = FactorEvaluation(
                factor=FactorType(qname),
                score=qscore,
                weight=0.0,
                weighted_score=0.0,
                strengths=list(dict.fromkeys(q_strengths))[:4],
                weaknesses=list(dict.fromkeys(q_weaknesses))[:4],
                reasoning=q_reasoning[:450] if q_reasoning else "No malicious behavior was found in the reviewed code.",
            )

        operational_safety_score = factor_evaluations["operational_safety"].score
        resonance_score = factor_evaluations["resonance"].score

        if malware_risk_score <= 10.0:
            malware_multiplier = 0.0
        elif malware_risk_score >= 85.0:
            malware_multiplier = 1.0
        else:
            malware_multiplier = (malware_risk_score - 10.0) / 75.0

        final_vibe_score = min(100.0, max(0.0, round(core_weighted_sum * malware_multiplier, 1)))
        letter_grade = calculate_letter_grade(final_vibe_score)

        verdict_title = macro_data.get("verdict_title") or f"{archetype.category} — Grade {letter_grade}"
        verdict_summary = macro_data.get("macro_critique_summary") or micro_data.get("micro_critique_summary", "Evaluation complete.")
        priority_improvements = macro_data.get("priority_improvements", [])

        top_strengths: List[str] = []
        for fe in sorted(factor_evaluations.values(), key=lambda x: x.score, reverse=True):
            if fe.factor != FactorType.MALWARE_RISK and fe.score >= 70.0:
                top_strengths.extend(fe.strengths)
        top_strengths = list(dict.fromkeys(top_strengths))[:5]

        top_solid_features = macro_data.get("top_solid_features", [])
        if not top_solid_features:
            top_solid_features = top_strengths[:5]

        top_features_needing_work = macro_data.get("top_features_needing_work", [])
        if not top_features_needing_work:
            combined_weaknesses = []
            for fe in sorted(factor_evaluations.values(), key=lambda x: x.score):
                if fe.factor != FactorType.MALWARE_RISK:
                    combined_weaknesses.extend(fe.weaknesses)
            top_features_needing_work = list(dict.fromkeys(combined_weaknesses))[:5]

        report = VibeReport(
            repo_name=repo_name,
            repo_source=repo_source,
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            archetype=archetype,
            weights=weights,
            deterministic_metrics=metrics,
            perspectives=perspectives,
            factor_evaluations=factor_evaluations,
            final_vibe_score=final_vibe_score,
            malware_risk_score=malware_risk_score,
            operational_safety_score=operational_safety_score,
            resonance_score=resonance_score,
            letter_grade=letter_grade,
            verdict_title=verdict_title,
            verdict_summary=verdict_summary,
            top_strengths=top_strengths,
            priority_improvements=priority_improvements[:5],
            top_solid_features=top_solid_features[:5],
            top_features_needing_work=top_features_needing_work[:5],
            timing_breakdown=timing_breakdown,
            issues_encountered=issues_encountered,
        )

        try:
            self.client.unload_all_models()
        except Exception:
            pass

        return report