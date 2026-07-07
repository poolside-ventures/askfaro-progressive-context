"""Tree-shape lints (B7) — report-only structural warnings.

Descriptor clarity caps how deep a hierarchy can scale: an agent reads a `when`
as ground truth and commits, so an over-wide level (too many siblings to
discriminate) or an over-deep tree (many wrong-branch commitments) erodes
first-hop precision. And a branch whose `what` needs conjunctions or overflows a
one-line budget is doing too many things and should split.

These are warnings, never errors — the compiler emits them so a human can decide.
The thresholds follow the "basic level" categorization guidance (~8 items per
level, 2-3 tiers) rather than being hard limits.
"""

from __future__ import annotations

import re

from .descriptors import Descriptor
from .ir import SourceTree

_CONJUNCTIONS = re.compile(r"\b(and|or)\b|[;,/]|&")


def tree_shape_warnings(
    tree: SourceTree,
    descriptors: dict[str, Descriptor] | None = None,
    *,
    max_children: int = 8,
    max_depth: int = 3,
    max_what_chars: int = 200,
    min_tree_nodes: int = 50,
) -> list[str]:
    """Structural + describability warnings for the compiled tree."""
    warnings: list[str] = []

    # Depth: distance from root to the deepest leaf.
    depth = {tree.root.id: 0}
    deepest = 0
    for node in tree.root.walk():
        for child in node.children:
            depth[child.id] = depth[node.id] + 1
            deepest = max(deepest, depth[child.id])

    # Regime: below a threshold a deep tree is premature architecture — a flat
    # list navigated by retrieval (embedded-search) tends to win outright.
    total_nodes = sum(1 for _ in tree.root.walk())
    if total_nodes < min_tree_nodes and deepest > 1:
        warnings.append(
            f"small corpus ({total_nodes} nodes) built {deepest} tiers deep; below ~{min_tree_nodes} "
            f"nodes a flat list + embedded-search usually navigates better than a deep tree"
        )

    if deepest > max_depth:
        warnings.append(
            f"tree is {deepest} tiers deep (> {max_depth}); deep trees multiply wrong-branch "
            f"commitments — consider flatter grouping"
        )

    # Width + describability, per branch.
    for node in tree.branches():
        n = len(node.children)
        if n > max_children:
            warnings.append(
                f"{node.id!r}: {n} children exceed the ~{max_children}-item basic-level width; "
                f"sub-group so an agent can discriminate siblings"
            )
        if descriptors and node.id in descriptors:
            what = descriptors[node.id].what
            if len(what) > max_what_chars:
                warnings.append(
                    f"{node.id!r}: branch `what` is {len(what)} chars (> {max_what_chars}); "
                    f"if it can't be said in one line it likely does too much — consider splitting"
                )
            elif node.id != tree.root.id and len(_CONJUNCTIONS.findall(what)) >= 2:
                warnings.append(
                    f"{node.id!r}: branch `what` enumerates multiple concerns "
                    f"({what!r}); a branch that needs conjunctions may need splitting"
                )
    return warnings
