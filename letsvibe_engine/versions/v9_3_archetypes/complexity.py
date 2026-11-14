"""
Code complexity description (rubric v9): public, plain English, NEVER part of the score.

Written by Python from measurements only (no AI, so nothing can be invented): average and peak cyclomatic complexity
(how many paths through a function), the most complex functions, and counts of oversized files, oversized functions and
duplicated blocks from the code scan. Exact locations of other code-health notes stay owner-only (maintainer notes).
"""
from typing import Any, Dict, List

# Average cyclomatic complexity bands (per function)
_BANDS = [(3.0, "low: most functions follow one or two simple paths"),
          (6.0, "moderate: typical for a working app"),
          (10.0, "high: many functions branch in several directions"),
          (float("inf"), "very high: functions are hard to follow on average")]


def describe(metrics: Any, maintainer_findings: List[Dict[str, Any]], lines_of_code: int) -> Dict[str, Any]:
    """Returns {"summary": str, "details": [str], "graded": False}."""
    avg = float(getattr(metrics, "avg_cyclomatic_complexity", 0) or 0)
    peak = int(getattr(metrics, "max_cyclomatic_complexity", 0) or 0)
    top = list(getattr(metrics, "top_complex_functions", []) or [])
    counts: Dict[str, int] = {}
    for f in maintainer_findings or []:
        counts[f.get("kind", "")] = counts.get(f.get("kind", ""), 0) + 1
    if not avg and not top:
        return {"summary": "No functions could be measured, so there is no complexity description for this project.",
                "details": [], "graded": False}
    band = next(text for limit, text in _BANDS if avg < limit)
    summary = (f"Average complexity is {avg:.1f} paths per function ({band}). "
               f"The most complex function has {peak} path{'s' if peak != 1 else ''}.")
    details = []
    for fn in top[:3]:
        name, file = getattr(fn, "name", ""), getattr(fn, "filename", "")
        cc, nloc = getattr(fn, "cyclomatic_complexity", 0), getattr(fn, "nloc", 0)
        details.append(f"{name} in {file}: {cc} path{'s' if cc != 1 else ''} over {nloc} line{'s' if nloc != 1 else ''}")
    for kind, one, many in (("oversized file", "very large file", "very large files"),
                            ("oversized function", "very long function", "very long functions"),
                            ("duplicated code", "repeated block of code", "repeated blocks of code")):
        n = counts.get(kind, 0)
        if n:
            details.append(f"{n} {one if n == 1 else many}" + (f" in {lines_of_code:,} lines of code" if lines_of_code else ""))
    if peak >= 30 and avg < 6:
        summary += " Most of the code is simple; the complexity sits in a few large functions."
    return {"summary": summary, "details": details, "graded": False}
