"""
Grading rubric version and public changelog.

Every report records the rubric version it was graded with, so scores from different versions are
never silently compared. Bump RUBRIC_VERSION and add a changelog entry whenever a change can move
scores (prompts, weights, aggregation, grade curve, checklist).
"""

from typing import Dict, List

RUBRIC_VERSION = "v5"

# Newest first. Plain language: this is shown publicly on /changelog.
RUBRIC_CHANGELOG: List[Dict[str, object]] = [
    {
        "version": "v5",
        "date": "2026-11-11",
        "title": "Owner input before publishing, and corrections",
        "changes": [
            "When the review needs more context about specific code, the report is not published or scored down. "
            "Instead the owner is asked to explain those lines; the report is published after review, and requests "
            "left unanswered for 7 days are deleted.",
            "Owners can report an error in their review. Each report is checked against the code; confirmed errors "
            "are corrected and marked as corrected on the report.",
        ],
    },
    {
        "version": "v4",
        "date": "2026-11-11",
        "title": "Device-aware grading and fairer factor scoring",
        "changes": [
            "Each project is classified first (category, target platforms and hardware) and graded against "
            "the device it is built for, so a microcontroller dashboard is not judged like desktop software.",
            "Screen size, chip and memory are read from the project's own build files and source code.",
            "Parts of a codebase that contain no user interface, I/O or user-facing features no longer count "
            "for or against those factors. If no part contains them, the whole-repository review decides.",
            "Factor weights are kept inside the published range for each project category.",
            "Detected secrets are reported by type only; their location is never published.",
        ],
    },
    {
        "version": "v3",
        "date": "2026-11-11",
        "title": "Reliability fixes",
        "changes": [
            "Fixed model prompts that were too long for the local models' context window, which caused some "
            "evaluations to return generic placeholder results. Evaluations that fail now produce no ranking "
            "at all instead of a misleading one.",
            "Vendored third-party libraries are excluded so projects are graded on their own code.",
        ],
    },
    {
        "version": "v2",
        "date": "2026-11-11",
        "title": "Calibration",
        "changes": [
            "Letter-grade curve aligned with the scoring rubric (a typical working project is a C).",
            "Yes/no evidence checklist blended with model scores to anchor results in concrete facts.",
        ],
    },
    {
        "version": "v1",
        "date": "2026-11-08",
        "title": "Beta",
        "changes": ["Initial dual-model (7B + 14B) local grading pipeline."],
    },
]
