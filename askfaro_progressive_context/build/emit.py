"""Emit — assemble pcx manifest variants and the llms.txt export.

The compiled tree is the same across budgets; each variant is the same node
set with its own `variant.budget` and computed `manifest_tokens` baseline.
(Per-budget frontier-depth/descriptor-verbosity shaping is a later refinement;
the format already carries everything needed for it.)
"""

from __future__ import annotations

from typing import Any

from ..types import PROTOCOL_USAGE
from .cost import Cost
from .descriptors import Descriptor
from .ir import SourceNode, SourceTree


def _node_dict(node: SourceNode, depth: int, d: Descriptor, c: Cost) -> dict[str, Any]:
    out: dict[str, Any] = {
        "tier": depth,
        "title": node.title,
        "what": d.what,
        "when": d.when,
        "tokens": c.tokens,
        "desc_tokens": c.desc_tokens,
        "subtree_tokens": c.subtree_tokens,
        "content_hash": c.content_hash,
    }
    if d.keywords:
        out["keywords"] = d.keywords
    if node.is_branch:
        out["children"] = [child.id for child in node.children]
    else:
        out["payload"] = {"ref": f"node://{node.id}", "format": node.format, "render": ["full"]}
    return out


def _baseline_tokens(tree: SourceTree, costs: dict[str, Cost]) -> int:
    base = costs[tree.root.id].desc_tokens
    base += sum(costs[c.id].desc_tokens for c in tree.root.children)
    return base


def build_manifest(
    tree: SourceTree,
    descriptors: dict[str, Descriptor],
    costs: dict[str, Cost],
    budget: int,
    *,
    siblings: list[int],
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = tree.root
    root_d, root_c = descriptors[root.id], costs[root.id]

    nodes: dict[str, Any] = {}
    depth: dict[str, int] = {root.id: 0}
    for node in root.walk():
        for child in node.children:
            depth[child.id] = depth[node.id] + 1
    for node in root.walk():
        if node.id == root.id:
            continue
        nodes[node.id] = _node_dict(node, depth[node.id], descriptors[node.id], costs[node.id])

    source = {"id": tree.source_id, "kind": tree.kind, "content_hash": root_c.content_hash}
    if generated_at:
        source["generated_at"] = generated_at

    return {
        "pcx_version": "0.1",
        "usage": PROTOCOL_USAGE,
        "source": source,
        "variant": {
            "budget": budget,
            "manifest_tokens": _baseline_tokens(tree, costs),
            "siblings": [b for b in siblings if b != budget],
        },
        "full_tokens": root_c.subtree_tokens,
        "root": {
            "id": root.id,
            "title": root.title,
            "what": root_d.what,
            "when": root_d.when,
            "children": [c.id for c in root.children],
        },
        "nodes": nodes,
    }


def to_llms_txt(tree: SourceTree, descriptors: dict[str, Descriptor]) -> str:
    root_d = descriptors[tree.root.id]
    lines = [
        f"# {tree.root.title or tree.source_id}",
        "",
        f"> {root_d.what}",
        "",
        "## How to read this index",
        "",
        "This is a progressive-disclosure index, not the full content. Each entry below is a"
        " short descriptor; the linked `node://<id>` resolves to the full verbatim content, which"
        " you fetch only for the entries you need. Scan the sections, follow the one matching your"
        " goal, then fetch that leaf's content. Expand as little as possible.",
        "",
    ]

    def render(node: SourceNode, level: int) -> None:
        for child in node.children:
            d = descriptors[child.id]
            if child.is_branch:
                lines.append("")
                lines.append(f"{'#' * min(level + 2, 6)} {child.title}")
                lines.append(d.what)
                render(child, level + 1)
            else:
                lines.append(f"- [{child.title}](node://{child.id}): {d.what}")

    render(tree.root, 0)
    return "\n".join(lines).rstrip() + "\n"
