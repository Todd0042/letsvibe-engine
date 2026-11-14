# LetsVibe Evaluation Engine (`letsvibe-engine`)

Private, version-controlled repository containing all evaluation rubrics, domain archetype profiles, prompts, and scoring logic for LetsVibe.

## Structure

```text
letsvibe_engine/
├── registry.json                    # Engine version manifest & production/testing flags
├── api.py                           # Unified entry point & version router
├── profiles/
│   └── project_profiles.json        # 7 domain archetypes & evaluation lenses
└── versions/
    ├── v9_3_archetypes/             # Rubric v9.3 (Production: Archetypes & Hackathon Judge)
    ├── v9_4_experimental/           # Rubric v9.4 (Testing: Submitter Intake & Grounding)
    └── v8_consensus/                # Rubric v8.0 (Historical Dual-Model Consensus)
```

## Engine Status Flags (`registry.json`)

- `"status": "production"`: Shown to all users on `letsvibe`.
- `"status": "testing"`: Shown only to Admin on `letsvibe` (and on `letsvibe-og-bk`). Submissions using a `"testing"` engine automatically run in Admin Test Mode (`is_test = 1`).
