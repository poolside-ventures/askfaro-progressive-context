"""Lateral cross-links + betweenness (C9).

A pure tree expresses Global + Local navigation but not *Contextual* — the
"this also relates to that over in another branch" edges. `infer_cross_links`
adds see-also links between nodes in different branches whose descriptors are
similar, with a why-phrase naming the shared terms. The result is a graph, not
just a tree, so `betweenness` can flag the bridge nodes that sit on the most
navigation paths — the descriptors whose quality matters most.

Links are inferred from descriptor similarity (offline, no model). Similarity is
the same lexical measure the contrastive pass minimizes for siblings — here we
*maximize* it across branches to find relatives.
"""

from __future__ import annotations

from .descriptors import Descriptor
from .distinct import descriptor_tokens, _jaccard
from .ir import SourceNode, SourceTree


def _tier1_of(tree: SourceTree) -> dict[str, str]:
    """Map each node id to the tier-1 branch (direct child of root) it lives under."""
    tier1: dict[str, str] = {}

    def walk(node: SourceNode, top: str | None) -> None:
        for child in node.children:
            here = child.id if top is None else top
            tier1[child.id] = here
            walk(child, here)

    walk(tree.root, None)
    return tier1


def infer_cross_links(
    tree: SourceTree,
    descriptors: dict[str, Descriptor],
    *,
    k: int = 3,
    min_sim: float = 0.35,
) -> int:
    """Add up to `k` see-also links per node to the most-similar nodes in OTHER
    tier-1 branches (similarity >= min_sim). Mutates `SourceNode.links`. Returns
    the number of links added. Symmetric pairs are both linked."""
    tier1 = _tier1_of(tree)
    nodes = [n for n in tree.root.walk() if n.id != tree.root.id and n.id in descriptors]
    tokens = {n.id: descriptor_tokens(descriptors[n.id]) for n in nodes}

    added = 0
    for node in nodes:
        scored = []
        for other in nodes:
            if other.id == node.id or tier1.get(other.id) == tier1.get(node.id):
                continue  # skip self and same-branch (that's the tree's job)
            s = _jaccard(tokens[node.id], tokens[other.id])
            if s >= min_sim:
                shared = tokens[node.id] & tokens[other.id]
                scored.append((s, other.id, shared))
        scored.sort(key=lambda t: (-t[0], t[1]))
        existing = {link["to"] for link in node.links}
        for _s, oid, shared in scored[:k]:
            if oid in existing:
                continue
            why = "related: shares " + ", ".join(sorted(shared)[:3]) if shared else "related"
            node.links.append({"to": oid, "why": why})
            added += 1
    return added


def betweenness(tree: SourceTree) -> dict[str, float]:
    """Unweighted betweenness centrality over the tree+links graph (Brandes).

    High-betweenness nodes are structural bridges: they sit on the most shortest
    paths, so their descriptor quality disproportionately affects navigability.
    Only meaningful once cross-links exist (on a pure tree, betweenness tracks
    depth). Returns node_id -> centrality.
    """
    adj: dict[str, set[str]] = {}

    def edge(a: str, b: str) -> None:
        adj.setdefault(a, set()).add(b)
        adj.setdefault(b, set()).add(a)

    for node in tree.root.walk():
        adj.setdefault(node.id, set())
        for child in node.children:
            edge(node.id, child.id)
        for link in node.links:
            edge(node.id, link["to"])

    cb = {v: 0.0 for v in adj}
    for s in adj:  # Brandes
        stack, pred, sigma, dist = [], {v: [] for v in adj}, dict.fromkeys(adj, 0.0), dict.fromkeys(adj, -1)
        sigma[s], dist[s] = 1.0, 0
        queue = [s]
        while queue:
            v = queue.pop(0)
            stack.append(v)
            for w in adj[v]:
                if dist[w] < 0:
                    dist[w] = dist[v] + 1
                    queue.append(w)
                if dist[w] == dist[v] + 1:
                    sigma[w] += sigma[v]
                    pred[w].append(v)
        delta = dict.fromkeys(adj, 0.0)
        while stack:
            w = stack.pop()
            for v in pred[w]:
                delta[v] += (sigma[v] / sigma[w]) * (1 + delta[w])
            if w != s:
                cb[w] += delta[w]
    return {v: round(c / 2.0, 4) for v, c in cb.items()}  # undirected: halve
