"""
Grading rubric version and public changelog.

Every report records the rubric version it was graded with, so scores from different versions are
never silently compared. Bump RUBRIC_VERSION and add a changelog entry whenever a change can move
scores (prompts, weights, aggregation, grade curve, checklist).
"""

from typing import Dict, List

RUBRIC_VERSION = "v7"

# Newest first. Plain language: this is shown publicly on /changelog.
RUBRIC_CHANGELOG: List[Dict[str, object]] = [
    {
        "version": "v7",
        "date": "2026-11-11",
        "title": "Graded on a curve, with a leaner review",
        "changes": [
            "Letter grades now come from a curve (a bell curve). AI reviewers hedge toward the middle, so a raw score "
            "says little on its own. Your letter depends on how far your score sits from the average, in standard deviations; "
            "two published reference projects set the bell at first, and your category's own scores take over as it grows. Everything behind the "
            "curve, every run included, is on the Grading curve page.",
            "Before review, files are sorted by name and folder (no AI): docs, licenses, build/config files and tests "
            "are skipped (they reach the reviewers as measurements), and story, dialogue or level content is sampled. "
            "Each chunk lists only its own files, which cut the reading by about a fifth.",
            "The yes/no checklist went from 33 to 23 questions: duplicates were removed, and code-health questions "
            "that measurements already answer (tests, complexity, dependencies) or that AI-written code almost always "
            "passes (clear names) are no longer asked.",
            "Safety is always reviewed for code that makes network calls, runs other programs, uses threads or files, "
            "loops forever or silently ignores errors, and setup wizards built inside a page are now recognized.",
        ],
    },
    {
        "version": "v6",
        "date": "2026-11-11",
        "title": "Vibe-coded software, graded as vibe-coded software",
        "changes": [
            "Projects are compared with other vibe-coded projects (programs written by AI from someone's prompts), "
            "never with software written by professional developers. Score bands were rewritten accordingly: 62 is a typical working vibe-coded project.",
            "New factor: User Journey, the user's path from install and first-run setup, through finding their way "
            "(including how deep settings are buried), to finishing the main task and being told it worked.",
            "Maintainability and Architecture were merged into Code Health. Engineering factors now carry roughly "
            "10-25% of the weight in most categories and are framed as 'what a pro team would do next'.",
            "Letter grades reflect standing among similar projects once a category has 30 or more; until then the "
            "rubric curve is used (62 = C). Reports show their rank within their category.",
            "The checklist was rephrased for vibe-coded projects, and complexity now counts mainly when it is widespread "
            "rather than for a few large functions.",
        ],
    },
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
