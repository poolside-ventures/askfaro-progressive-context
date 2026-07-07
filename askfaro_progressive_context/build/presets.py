"""Named build presets (config-paralysis fix).

The compiler exposes many knobs (budgets, contrastive rounds, synthesis,
flatten, fidelity, collision gate). Surfacing all of them invites analysis
paralysis. A preset fixes a coherent set for a use case and ships a one-line
*justification* per setting, so the config is a starting point a user can
override — resolving a few intent choices instead of twenty independent knobs.

A preset only fills a setting the caller left at its default; an explicit flag
always wins.
"""

from __future__ import annotations

PRESETS: dict[str, dict] = {
    "docs-heavy": {
        "description": "Large prose corpus (docs/wikis) navigated by an agent.",
        "settings": {"budgets": "4k,32k", "synthesis": True, "flatten": True, "fidelity": "lexical"},
        "why": {
            "synthesis": "prose branches need relational synthesis, not a list of child titles",
            "flatten": "doc trees accrue single-child section chains — pointless hops",
            "fidelity": "long descriptions drift from content; catch it offline",
        },
    },
    "tool-routing": {
        "description": "A tool/capability catalog an agent picks from under budget.",
        "settings": {"budgets": "4k,32k", "collision_threshold": 0.4, "max_collision": 0.6},
        "why": {
            "collision_threshold": "tools collide on shared verbs; push discrimination harder",
            "max_collision": "gate the build — colliding tool descriptors misroute calls",
        },
    },
    "low-budget": {
        "description": "Tight on-device window; keep the always-loaded index lean.",
        "settings": {"budgets": "4k", "flatten": True},
        "why": {
            "budgets": "a single small tier; no headroom for a 32k variant",
            "flatten": "every wasted navigation hop costs scarce context",
        },
    },
}


def apply_preset(name: str, args, defaults: dict) -> list[str]:
    """Fill `args` attributes from preset `name` where the caller left the
    default. Returns human-readable justification lines. Raises KeyError on an
    unknown preset name (with the valid options)."""
    if name not in PRESETS:
        raise KeyError(f"unknown preset {name!r}; choose one of {sorted(PRESETS)}")
    preset = PRESETS[name]
    notes: list[str] = []
    for key, value in preset["settings"].items():
        if getattr(args, key, None) == defaults.get(key):  # caller didn't override
            setattr(args, key, value)
            why = preset["why"].get(key)
            notes.append(f"{key}={value}" + (f"  ({why})" if why else ""))
    return notes
