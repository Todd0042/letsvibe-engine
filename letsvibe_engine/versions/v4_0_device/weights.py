"""
Dynamic factor-weight ranges per project category.

Single source of truth: the Stage 1 prompt is rendered from WEIGHT_RANGE_ROWS, and the weights the
model returns are clamped into the row for the project's category (the 7B was observed ignoring
the ranges, e.g. 5.9% resonance for an embedded dash app whose row says 20-28%).
"""

from typing import Dict, List, Optional, Tuple

from letsvibe.core.models import LEGACY_V5_FACTORS as CORE_FACTORS

Range = Tuple[float, float]

# Rows exactly as calibrated in the rubric: (label, {factor: (min, max)})
WEIGHT_RANGE_ROWS: Dict[str, Tuple[str, Dict[str, Range]]] = {
    "games": ("Games / Entertainment / Media", {
        "resonance": (20, 28), "functionality": (15, 25), "ui_ux": (15, 25), "creativity": (12, 20),
        "maintainability": (8, 15), "architecture": (5, 12), "operational_safety": (4, 8),
    }),
    "consumer": ("Mobile / Touch / Consumer Desktop / Embedded Dash Apps", {
        "resonance": (20, 28), "functionality": (15, 25), "ui_ux": (15, 22), "maintainability": (8, 15),
        "architecture": (8, 14), "creativity": (8, 15), "operational_safety": (5, 10),
    }),
    "cli": ("Developer CLI & Terminal Utilities", {
        "resonance": (18, 26), "functionality": (18, 28), "maintainability": (12, 20), "ui_ux": (8, 15),
        "architecture": (8, 14), "operational_safety": (6, 12), "creativity": (4, 12),
    }),
    "web": ("Web Apps & Cloud Backends", {
        "resonance": (18, 25), "functionality": (18, 26), "architecture": (12, 20), "maintainability": (10, 18),
        "operational_safety": (8, 14), "ui_ux": (8, 15), "creativity": (4, 10),
    }),
    "sdk": ("SDKs / Libraries / Headless Utilities", {
        "resonance": (15, 24), "maintainability": (18, 26), "functionality": (18, 26), "architecture": (12, 20),
        "operational_safety": (6, 12), "ui_ux": (3, 10), "creativity": (4, 8),
    }),
    "research": ("Research Projects / Prototypes / Hackathons", {
        "resonance": (20, 28), "creativity": (18, 30), "functionality": (15, 25), "ui_ux": (8, 15),
        "maintainability": (4, 10), "architecture": (4, 10), "operational_safety": (3, 8),
    }),
}

# Category -> rubric row. Categories without a row only get the global rule below.
CATEGORY_ROW: Dict[str, str] = {
    "game": "games",
    "application": "consumer",
    "embedded": "consumer",
    "tool": "cli",
    "bot": "cli",
    "web_app": "web",
    "library": "sdk",
}

# Global rule stated in the prompt for every project: resonance 18-28, operational safety 5-12
GLOBAL_RANGES: Dict[str, Range] = {
    "resonance": (18, 28),
    "operational_safety": (5, 12),
    **{f: (3, 30) for f in CORE_FACTORS if f not in ("resonance", "operational_safety")},
}


def ranges_for(category: Optional[str]) -> Tuple[str, Dict[str, Range]]:
    row = CATEGORY_ROW.get(category or "")
    if row:
        return WEIGHT_RANGE_ROWS[row]
    return ("General (no category-specific row)", GLOBAL_RANGES)


def render_ranges_text() -> str:
    lines = ["Ranges per archetype:"]
    for label, ranges in WEIGHT_RANGE_ROWS.values():
        parts = ", ".join(f"{f} {lo:g}-{hi:g}" for f, (lo, hi) in ranges.items())
        lines.append(f"  * {label}: {parts}")
    return "\n".join(lines)


def clamp_weights(weights: Dict[str, float], category: Optional[str]) -> Tuple[Dict[str, float], List[str]]:
    """
    Fits weights into the category's ranges while summing to 100, moving each factor as little as
    possible: clamp to [min, max], then spread any surplus/deficit across factors in proportion to
    their remaining room. Returns (weights, list of factors that had to be moved).
    """
    _, ranges = ranges_for(category)
    raw = {f: float(weights.get(f, 0.0) or 0.0) for f in CORE_FACTORS}
    v = {f: min(max(raw[f], ranges[f][0]), ranges[f][1]) for f in CORE_FACTORS}
    for _ in range(10):
        diff = 100.0 - sum(v.values())
        if abs(diff) < 0.01:
            break
        if diff > 0:
            room = {f: ranges[f][1] - v[f] for f in CORE_FACTORS if v[f] < ranges[f][1] - 1e-9}
        else:
            room = {f: v[f] - ranges[f][0] for f in CORE_FACTORS if v[f] > ranges[f][0] + 1e-9}
        total = sum(room.values())
        if total <= 0:
            break
        step = max(-total, min(total, diff))
        for f, r in room.items():
            v[f] += step * r / total
    out = {f: round(v[f], 1) for f in CORE_FACTORS}
    moved = [f for f in CORE_FACTORS if abs(out[f] - raw[f]) > 0.5]
    return out, moved
