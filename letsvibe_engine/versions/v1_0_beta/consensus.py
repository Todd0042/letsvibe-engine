"""
Consensus and harmonization engine for the Dual-Model Blend.
Synthesizes micro and macro evaluations into a single, cohesive VibeReport.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional
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
from letsvibe.evaluator.ollama import OllamaClient, get_free_vram_mb
from .prompts import (
    SYSTEM_PROMPT_ARCHETYPE,
    SYSTEM_PROMPT_MACRO_14B,
    SYSTEM_PROMPT_MICRO_7B,
)


def calculate_letter_grade(score: float) -> str:
    if score >= 97.0:
        return "A+"
    elif score >= 93.0:
        return "A"
    elif score >= 90.0:
        return "A-"
    elif score >= 87.0:
        return "B+"
    elif score >= 83.0:
        return "B"
    elif score >= 80.0:
        return "B-"
    elif score >= 77.0:
        return "C+"
    elif score >= 73.0:
        return "C"
    elif score >= 70.0:
        return "C-"
    elif score >= 60.0:
        return "D"
    else:
        return "F"


class ConsensusEngine:
    """Orchestrates Stage 1 & Stage 2 evaluations and blends perspectives."""

    def __init__(
        self,
        client: OllamaClient,
        micro_model: str = "qwen2.5-coder:7b",
        macro_model: str = "qwen2.5-coder:14b",
        explicit_macro: bool = False,
    ):
        self.client = client
        self.micro_model = micro_model
        self.macro_model = macro_model
        self.explicit_macro = explicit_macro

    def evaluate_pipeline(
        self,
        repo_name: str,
        repo_source: str,
        manifest_batches: Any,
        metrics: DeterministicMetrics,
        mode: str = "blend",  # "blend", "fast" (7B only), or "deep" (14B only)
    ) -> VibeReport:
        # Check available models
        available = self.client.list_models()
        chosen_micro = self.micro_model
        chosen_macro = self.macro_model

        if isinstance(manifest_batches, str):
            manifest_batches = [("Full Codebase", manifest_batches)]

        # Track phase timing and warnings
        import time
        timing_breakdown: Dict[str, float] = {}
        issues_encountered: List[str] = []

        # Fallback if specific tags don't match exactly
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

        # Prepare summary of deterministic metrics for prompts
        readme_info = f"\nREADME Project Overview & Goals:\n{metrics.readme_excerpt[:2500]}\n" if metrics.readme_excerpt else ""
        desktop_pkg_str = "Present (Android APK/AAB / AppImage / Inno Setup / PyInstaller / Native Scripts)" if metrics.has_desktop_packaging else "None detected"
        metrics_summary = f"""
Deterministic Metrics:
- Total Lines of Code: {metrics.total_loc}
- Total Files: {metrics.total_files}
- Languages: {metrics.languages}
- Avg Cyclomatic Complexity: {metrics.avg_cyclomatic_complexity}
- Max Cyclomatic Complexity: {metrics.max_cyclomatic_complexity}
- Hardcoded Secrets/Risks Found: {metrics.detected_secrets_count}
- Security Details: {metrics.secret_findings[:5]}
- Test Files Count: {metrics.test_files_count} (Ratio: {metrics.test_to_code_ratio})
- Has CI/CD: {metrics.has_ci_cd}
- Has Docker: {metrics.has_docker}
- Native Standalone Packaging (Mobile APK/Desktop): {desktop_pkg_str}
- Has License: {metrics.has_license}
{readme_info}
"""

        if chosen_micro != self.micro_model:
            issues_encountered.append(f"Preferred micro-model {self.micro_model} not found, fell back to {chosen_micro}")
        if chosen_macro != self.macro_model and mode in ("blend", "deep"):
            issues_encountered.append(f"Preferred macro-model {self.macro_model} not found, fell back to {chosen_macro}")

        # -------------------------------------------------------------
        # STAGE 1: Archetype Detection & Dynamic Weights
        # -------------------------------------------------------------
        first_batch_text = manifest_batches[0][1]
        file_tree_snippet = first_batch_text.split("# REPOSITORY DIRECTORY LAYOUT:\n")
        tree_text = file_tree_snippet[1].split("\n--- START FILE:")[0] if len(file_tree_snippet) > 1 else first_batch_text[:4000]

        prompt_stage1 = f"""
Analyze this repository's true purpose, domain archetype, and target audience, and assign unbiased dynamic factor weights:
{metrics_summary}

Repository File Tree Structure:
{tree_text[:4000]}
"""
        t0 = time.perf_counter()
        try:
            stage1_data = self.client.generate_json(
                model=chosen_micro,
                system_prompt=SYSTEM_PROMPT_ARCHETYPE,
                user_prompt=prompt_stage1,
                num_ctx=4096,
            )
        except Exception as e:
            issues_encountered.append(f"Stage 1 JSON generation warning: {e}")
            stage1_data = {}
        timing_breakdown["stage_1_archetype_and_weights_sec"] = round(time.perf_counter() - t0, 2)

        arch_raw = stage1_data.get("archetype", {})
        archetype = ProjectArchetype(
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

        qualifiers_raw = stage1_data.get("qualifiers", stage1_data.get("qualifier_scores", {}))
        stage1_malware = float(qualifiers_raw.get("malware_risk", qualifiers_raw.get("security", 90.0)))
        stage1_ops = float(qualifiers_raw.get("operational_safety", 75.0))
        stage1_resonance = float(qualifiers_raw.get("resonance", qualifiers_raw.get("resonance_rating", 60.0)))

        # -------------------------------------------------------------
        # STAGE 2: Model Passes
        # -------------------------------------------------------------
        perspectives: List[ModelPerspective] = []
        micro_data: Dict = {"factor_scores": {}, "detailed_findings": {}}
        macro_data: Dict = {}

        if mode in ("blend", "fast"):
            t1 = time.perf_counter()
            accumulated_scores: Dict[str, List[float]] = {}
            accumulated_findings: Dict[str, Dict[str, List[str]]] = {}
            summaries: List[str] = []

            # Iterate through batches so 100% of all files are inspected
            for b_idx, (b_title, b_content) in enumerate(manifest_batches, 1):
                prompt_micro = f"""
Project: {archetype.name} ({archetype.category})
Module Batch {b_idx}/{len(manifest_batches)}: {b_title}
{metrics_summary}

Source Code:
{b_content}
"""
                b_tokens = int(len(b_content) / 3.6)
                b_ctx = min(32768, max(4096, int(b_tokens * 1.3) + 2048))
                try:
                    b_res = self.client.generate_json(
                        model=chosen_micro,
                        system_prompt=SYSTEM_PROMPT_MICRO_7B,
                        user_prompt=prompt_micro,
                        num_ctx=b_ctx,
                    )
                    # Accumulate scores
                    for k, v in b_res.get("factor_scores", {}).items():
                        accumulated_scores.setdefault(k, []).append(float(v))
                    qual_scores_b = b_res.get("qualifier_scores", b_res.get("qualifiers", {}))
                    for k, v in qual_scores_b.items():
                        accumulated_scores.setdefault(k, []).append(float(v))

                    # Accumulate findings
                    for k, v in b_res.get("detailed_findings", {}).items():
                        if k not in accumulated_findings:
                            accumulated_findings[k] = {"strengths": [], "weaknesses": [], "reasoning": ""}
                        accumulated_findings[k]["strengths"].extend(v.get("strengths", []))
                        accumulated_findings[k]["weaknesses"].extend(v.get("weaknesses", []))
                        if not accumulated_findings[k]["reasoning"] and v.get("reasoning"):
                            accumulated_findings[k]["reasoning"] = v.get("reasoning")
                    if b_res.get("micro_critique_summary"):
                        summaries.append(f"[{b_title}]: {b_res['micro_critique_summary']}")
                except Exception as e:
                    issues_encountered.append(f"Pass 1 Micro (7B) batch {b_title} warning: {e}")

            # Calculate micro scores across batches
            avg_micro_scores = {}
            for k, vals in accumulated_scores.items():
                if not vals:
                    continue
                avg_micro_scores[k] = round(sum(vals) / len(vals), 1)

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
            if mode == "blend" and chosen_micro != chosen_macro:
                try:
                    self.client.unload_model(chosen_micro)
                except Exception:
                    pass

            readme_sample = metrics.readme_excerpt[:2500] if metrics.readme_excerpt else "No README available."
            macro_input = f"""
Project Archetype: {archetype.name} ({archetype.category})
Target Audience: {archetype.target_audience}
Core Purpose: {archetype.core_purpose}

{metrics_summary}

README & Architectural Purpose:
{readme_sample}

Repository Directory Structure:
{tree_text[:4000]}

Pass 1 Micro-Auditor Insights (Across All Module Batches):
{micro_data.get('micro_critique_summary', 'N/A')}
Pass 1 Micro Factor Scores: {micro_data.get('factor_scores', {})}
"""
            t2 = time.perf_counter()
            try:
                macro_data = self.client.generate_json(
                    model=chosen_macro,
                    system_prompt=SYSTEM_PROMPT_MACRO_14B,
                    user_prompt=macro_input,
                    num_ctx=8192,
                )
            except Exception as e:
                issues_encountered.append(f"Pass 2 Macro warning: {e}")
                macro_data = {}
            timing_breakdown["pass_2_macro_architect_sec"] = round(time.perf_counter() - t2, 2)

            perspectives.append(
                ModelPerspective(
                    model_name=chosen_macro,
                    role="Macro Architecture & Resonance Auditor (Pass 2)",
                    factor_scores=macro_data.get("factor_scores", {}),
                    critique_summary=macro_data.get("macro_critique_summary", ""),
                )
            )

        # -------------------------------------------------------------
        # HARMONIZATION: Blending factor scores & insights
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

        def get_valid_score(source: dict, key: str, fallback: float) -> float:
            val = source.get(key)
            if val is not None:
                try:
                    fval = float(val)
                    if fval > 5.0:  # Ignore unmeasured 0.0 hallucinations
                        return fval
                except (ValueError, TypeError):
                    pass
            return fallback

        def get_gate_score(source: dict, key: str, fallback: float) -> float:
            """Like get_valid_score, but a genuine 0-5 is honored (malware verdict must be able to fail a repo)."""
            val = source.get(key)
            try:
                if val is not None:
                    return max(0.0, min(100.0, float(val)))
            except (ValueError, TypeError):
                pass
            return fallback

        # 1. Malware Risk (separate trust check, not a weighted factor)
        s_malware_micro = get_gate_score(micro_scores, "malware_risk", get_valid_score(micro_scores, "security", stage1_malware))
        if metrics.detected_secrets_count == 0 and "malware_risk" not in micro_scores and "security" not in micro_scores:
            s_malware_micro = max(s_malware_micro, 92.0)
        s_malware_macro = get_gate_score(macro_scores, "malware_risk", get_valid_score(macro_scores, "security", s_malware_micro))
        malware_risk_score = round(s_malware_micro * 0.40 + s_malware_macro * 0.60, 1)

        # 2. Evaluate the 7 weighted factors (Summing to 100% weight)
        for fname in core_factors:
            s_micro = get_valid_score(micro_scores, fname, 80.0)
            s_macro = get_valid_score(macro_scores, fname, s_micro)

            if mode == "fast":
                blended_score = s_micro
            elif mode == "deep":
                blended_score = s_macro
            else:
                if fname in ("maintainability", "functionality", "operational_safety"):
                    blended_score = round(s_micro * 0.40 + s_macro * 0.60, 1)
                else:
                    blended_score = round(get_valid_score(macro_scores, fname, s_micro), 1)

            w = weight_dict.get(fname, 20.0)
            weighted_val = round(blended_score * (w / 100.0), 2)
            core_weighted_sum += weighted_val

            strengths = []
            weaknesses = []
            if fname in micro_findings:
                strengths.extend(micro_findings[fname].get("strengths", []))
                weaknesses.extend(micro_findings[fname].get("weaknesses", []))
            if fname in macro_findings:
                strengths.extend(macro_findings[fname].get("strengths", []))
                weaknesses.extend(macro_findings[fname].get("weaknesses", []))

            reasoning = macro_findings.get(fname, {}).get("reasoning") or micro_findings.get(fname, {}).get("reasoning", "")

            factor_evaluations[fname] = FactorEvaluation(
                factor=FactorType(fname),
                score=blended_score,
                weight=w,
                weighted_score=weighted_val,
                strengths=list(dict.fromkeys(strengths))[:4],
                weaknesses=list(dict.fromkeys(weaknesses))[:4],
                reasoning=reasoning,
            )

        # 3. Store the malware trust check in factor_evaluations with weight=0.0 (not part of the weighted pool)
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
                or qualifiers_raw.get(f"{qname}_reasoning", "")
            )
            factor_evaluations[qname] = FactorEvaluation(
                factor=FactorType(qname),
                score=qscore,
                weight=0.0,
                weighted_score=0.0,
                strengths=list(dict.fromkeys(q_strengths))[:4],
                weaknesses=list(dict.fromkeys(q_weaknesses))[:4],
                reasoning=q_reasoning,
            )

        operational_safety_score = factor_evaluations["operational_safety"].score
        resonance_score = factor_evaluations["resonance"].score

        # Final score: weighted 7-factor sum, then the malware trust check.
        # >= 85: none found, no effect. 10-85: scaled down heavily. <= 10: malicious behavior found -> fails (0).
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

        # Compile top strengths from all factors
        top_strengths: List[str] = []
        for fe in factor_evaluations.values():
            if fe.score >= 80.0:
                top_strengths.extend(fe.strengths)
        top_strengths = list(dict.fromkeys(top_strengths))[:5]

        # Extract Top 5 Solid Features and Top 5 Needing Work
        top_solid_features = macro_data.get("top_solid_features", [])
        if not top_solid_features:
            top_solid_features = top_strengths[:5]

        top_features_needing_work = macro_data.get("top_features_needing_work", [])
        if not top_features_needing_work:
            combined_weaknesses = []
            for fe in factor_evaluations.values():
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

        # Release all LLM models from GPU VRAM immediately upon completion
        try:
            self.client.unload_all_models()
        except Exception:
            pass

        return report