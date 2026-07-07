"""Core data types for the progressive-context (pcx) manifest format.

A manifest is a tree of nodes. Each node carries a navigation *descriptor*
(`what` / `when` / `keywords`) plus token costs, and is either a *branch*
(has `children`) or a *leaf* (has `payload`). Leaves are never inlined —
`payload.ref` points at verbatim content resolved by the expansion protocol.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

PCX_VERSION = "0.2"

# Self-description shipped at the top of every manifest so a cold agent that has
# never seen the format knows how to navigate it. This is part of the standard.
PROTOCOL_USAGE = (
    "This is a progressive-context (pcx) manifest: a compact, navigable index of a much larger body of "
    "content, meant to be read under a small token budget. You are seeing descriptors, NOT full content. "
    "Each node has `what` (what it is), `when` (when it is relevant), a token cost, and either `children` "
    "(a branch) or a `payload` (a leaf). To find what you need: (1) scan the descriptors under `root.children`; "
    "(2) follow the node whose `when` best matches your goal; (3) for a branch, look up its child ids in "
    "`nodes` to go deeper; (4) for a leaf, fetch the full verbatim content by resolving `payload.ref` "
    "(e.g. `node://<id>`) — a leaf's content is not in this file. A node may also carry `links` "
    "(see-also references `{to, why}` to related nodes in OTHER branches — follow them to explore "
    "laterally) and `facets` (a map of orthogonal tags like type/status — filter on these to narrow "
    "before reading descriptors). Expand only what you need and stay within `variant.budget` tokens. "
    "If your host exposes navigation tools (index / open / look / related / filter), prefer those; "
    "otherwise resolve `node://` refs yourself."
)

# A rough char->token ratio used only to *estimate* descriptor cost when a
# node omits `desc_tokens`. Real builds annotate with the target tokenizer.
_CHARS_PER_TOKEN = 4


def estimate_tokens(text: str) -> int:
    return max(1, (len(text) + _CHARS_PER_TOKEN - 1) // _CHARS_PER_TOKEN)


@dataclass
class Payload:
    """Pointer to a leaf's verbatim content (never inlined)."""

    ref: str
    format: str = "md"
    render: list[str] = field(default_factory=lambda: ["full"])

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Payload":
        return cls(ref=d["ref"], format=d.get("format", "md"), render=list(d.get("render", ["full"])))

    def to_dict(self) -> dict[str, Any]:
        return {"ref": self.ref, "format": self.format, "render": self.render}


@dataclass
class Link:
    """A lateral see-also edge to a related node in another branch."""

    to: str
    why: str = ""

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Link":
        return cls(to=d["to"], why=d.get("why", ""))

    def to_dict(self) -> dict[str, Any]:
        return {"to": self.to, "why": self.why} if self.why else {"to": self.to}


@dataclass
class Node:
    """One unit of content. Branch (children) XOR leaf (payload)."""

    id: str
    what: str
    when: str
    tier: int = 0
    title: str | None = None
    keywords: list[str] = field(default_factory=list)
    # Lateral cross-links (see-also) and orthogonal facets — pcx v0.2.
    links: list[Link] = field(default_factory=list)
    facets: dict[str, str] = field(default_factory=dict)
    # Cost to show this node's descriptor in a frontier (estimated if absent).
    desc_tokens: int | None = None
    # Cost to expand this node's direct full payload (leaf); 0 for branches.
    tokens: int = 0
    # Optional cheaper render level.
    summary_tokens: int | None = None
    # Cost to expand the whole subtree to full leaves (planning hint).
    subtree_tokens: int | None = None
    children: list[str] | None = None
    payload: Payload | None = None
    # Domain-specific node attributes the manifest carries that are not part of
    # the pcx schema (e.g. a consumer's own id). Preserved verbatim so navigation
    # can surface them; pcx itself never interprets them.
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def is_branch(self) -> bool:
        return self.children is not None

    @property
    def is_leaf(self) -> bool:
        return self.payload is not None

    def descriptor_cost(self) -> int:
        if self.desc_tokens is not None:
            return self.desc_tokens
        text = " ".join(filter(None, [self.title, self.what, self.when, " ".join(self.keywords)]))
        return estimate_tokens(text)

    def render_cost(self, level: str = "full") -> int:
        if level == "summary" and self.summary_tokens is not None:
            return self.summary_tokens
        return self.tokens

    _SCHEMA_KEYS = frozenset(
        {
            "id", "what", "when", "tier", "title", "keywords", "desc_tokens",
            "tokens", "summary_tokens", "subtree_tokens", "children", "payload",
            "links", "facets",
        }
    )

    @classmethod
    def from_dict(cls, node_id: str, d: dict[str, Any]) -> "Node":
        payload = d.get("payload")
        return cls(
            id=d.get("id", node_id),
            what=d["what"],
            when=d["when"],
            tier=d.get("tier", 0),
            title=d.get("title"),
            keywords=list(d.get("keywords", [])),
            links=[Link.from_dict(x) for x in d.get("links", [])],
            facets={str(k): str(v) for k, v in (d.get("facets") or {}).items()},
            desc_tokens=d.get("desc_tokens"),
            tokens=d.get("tokens", 0),
            summary_tokens=d.get("summary_tokens"),
            subtree_tokens=d.get("subtree_tokens"),
            children=list(d["children"]) if "children" in d else None,
            payload=Payload.from_dict(payload) if payload else None,
            meta={k: v for k, v in d.items() if k not in cls._SCHEMA_KEYS},
        )


@dataclass
class Variant:
    budget: int
    manifest_tokens: int | None = None
    siblings: list[int] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Variant":
        return cls(
            budget=d["budget"],
            manifest_tokens=d.get("manifest_tokens"),
            siblings=list(d.get("siblings", [])),
        )


@dataclass
class Manifest:
    source: dict[str, Any]
    variant: Variant
    root: Node
    nodes: dict[str, Node]
    full_tokens: int | None = None
    pcx_version: str = PCX_VERSION

    @property
    def identity(self) -> str | None:
        """A stable token identifying this manifest's *content*.

        Two manifests with the same identity are interchangeable; a changed
        identity means the content moved and a cache must refetch. Derived from
        the build's bottom-up `source.content_hash` (see `build.emit`). Returns
        ``None`` when the source omits a hash — callers that need an identity in
        that case should fall back to `loader.identity_of`, which hashes the body.
        """
        h = self.source.get("content_hash")
        return str(h) if h is not None else None

    def get(self, node_id: str) -> Node:
        if node_id == self.root.id:
            return self.root
        return self.nodes[node_id]

    def children_of(self, node: Node) -> list[Node]:
        return [self.get(cid) for cid in (node.children or [])]

    def baseline_tokens(self) -> int:
        """Always-loaded cost: root + its immediate children descriptors."""
        if self.variant.manifest_tokens is not None:
            return self.variant.manifest_tokens
        base = self.root.descriptor_cost()
        base += sum(c.descriptor_cost() for c in self.children_of(self.root))
        return base

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Manifest":
        root_raw = dict(d["root"])
        root_raw.setdefault("id", "r")
        root = Node.from_dict(root_raw["id"], root_raw)
        nodes = {nid: Node.from_dict(nid, nd) for nid, nd in d.get("nodes", {}).items()}
        return cls(
            source=d["source"],
            variant=Variant.from_dict(d["variant"]),
            root=root,
            nodes=nodes,
            full_tokens=d.get("full_tokens"),
            pcx_version=d.get("pcx_version", PCX_VERSION),
        )
