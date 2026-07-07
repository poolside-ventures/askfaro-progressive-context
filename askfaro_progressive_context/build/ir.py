"""Intermediate representation produced by adapters.

A SourceTree is the native structure of a source before descriptors and costs
are attached. Leaves carry verbatim `content`; branches carry `children`.
`hint` is optional adapter-supplied context (e.g. a tool's existing
description) that the descriptor engine may use but never ships verbatim.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Iterator


@dataclass
class SourceNode:
    id: str
    title: str | None = None
    content: str | None = None
    format: str = "md"
    hint: str | None = None
    keywords: list[str] = field(default_factory=list)
    children: list["SourceNode"] = field(default_factory=list)
    # pcx v0.2: lateral see-also links [{"to","why"}] and orthogonal facets.
    # Adapters may set facets; cross-links are inferred at compile time.
    links: list[dict] = field(default_factory=list)
    facets: dict[str, str] = field(default_factory=dict)

    @property
    def is_branch(self) -> bool:
        return bool(self.children)

    @property
    def is_leaf(self) -> bool:
        return not self.children

    def walk(self) -> Iterator["SourceNode"]:
        yield self
        for child in self.children:
            yield from child.walk()

    def post_order(self) -> Iterator["SourceNode"]:
        for child in self.children:
            yield from child.post_order()
        yield self


@dataclass
class SourceTree:
    source_id: str
    kind: str
    root: SourceNode

    def branches(self) -> list[SourceNode]:
        return [n for n in self.root.walk() if n.is_branch]


def hash_content(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def flatten_single_child_branches(root: SourceNode) -> SourceNode:
    """Collapse branches that have exactly one child: a single-child branch is a
    navigation hop with nothing to discriminate. The child is lifted into the
    grandparent in place. The root is never removed (even with one child).

    Regime-awareness helper: keeps small trees from carrying pointless depth.
    """

    def rebuild(node: SourceNode) -> SourceNode:
        if node.is_leaf:
            return node
        new_children = []
        for child in node.children:
            child = rebuild(child)
            # lift a single-child branch's own child up in its place
            while child.is_branch and len(child.children) == 1:
                child = child.children[0]
            new_children.append(child)
        node.children = new_children
        return node

    return rebuild(root)


def content_hashes(root: SourceNode) -> dict[str, str]:
    """Per-node content hash (leaf = hash of content; branch = hash of child
    hashes). A node's hash captures its whole subtree, so any descendant change
    propagates up the ancestor path — the basis for incremental rebuilds."""
    hashes: dict[str, str] = {}
    for node in root.post_order():
        if node.is_leaf:
            hashes[node.id] = hash_content(node.content or "")
        else:
            hashes[node.id] = hash_content("".join(hashes[c.id] for c in node.children))
    return hashes
