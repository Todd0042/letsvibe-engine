# LetsVibe Evaluation Engine (`letsvibe-engine`)

Open-source, versioned evaluation engine containing all grading rubrics, domain archetype profiles, prompts, App Dossier generators, and scoring logic for [LetsVibe](https://letsvibe.todd0042.dev) ([Todd0042/letsvibe](https://github.com/Todd0042/letsvibe)).

## Structure

```text
letsvibe_engine/
├── registry.json                    # Engine version manifest & production/testing flags
├── api.py                           # Unified entry point & version router
├── profiles/                        # 7 domain archetypes, complexity forms & curve calibration
├── data/                            # Packaged reference JSON data
└── versions/                        # Every rubric generation from v1.0 through v9.4
    ├── v9_4_experimental/           # Rubric v9.4 (Production default: Submitter Context & Grounding)
    ├── v9_3_archetypes/             # Rubric v9.3 (Legacy: Archetypes & Domain Exemptions)
    ├── v9_2_context/                # Rubric v9.2 (Project Context & Deterministic Seed)
    ├── v9_1_negatives/              # Rubric v9.1 (Negative Evidence & Two-File Verification)
    ├── v9_0_hybrid/                 # Rubric v9.0 (Original Hybrid: Dossier + 7B Code Evidence)
    ├── v8_0_dossier/                # Rubric v8.0 (Pure App Dossier Experience Grading)
    ├── v7_0_triage/                 # Rubric v7.0 (7-Factor Consensus + Pre-Review File Triage)
    ├── v6_0_vibe/                   # Rubric v6.0 (Vibe-Coded Software Native, 33 Checks)
    ├── v5_0_holds/                  # Rubric v5.0 (7-Factor + Owner Explanation Holds)
    ├── v4_0_device/                 # Rubric v4.0 (Device-Aware & Relevant-Chunk Scoring)
    ├── v3_0_reliability/            # Rubric v3.0 (Anti-Truncation & Fail-Closed Consensus)
    ├── v2_0_checklist/              # Rubric v2.0 (50/50 Binary Evidence Checklist Calibration)
    └── v1_0_beta/                   # Rubric v1.0 (Original Beta Dual-Model Pipeline)
```

## Engine Status Flags (`registry.json`)

- `"status": "production"`: Shown to all users on [LetsVibe](https://letsvibe.todd0042.dev).
- `"status": "testing"`: Shown only to Admin on `letsvibe`. Submissions using a `"testing"` engine run in Admin Test Mode (`is_test = 1`).

## License

Licensed under the [PolyForm Shield License 1.0.0](LICENSE) — the same license as [Todd0042/letsvibe](https://github.com/Todd0042/letsvibe).
