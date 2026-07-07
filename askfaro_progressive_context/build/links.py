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

from typing import Callable

from .descriptors import Descriptor
from .distinct import descriptor_tokens, _jaccard
from .ir import SourceNode, SourceTree

# A why-phrase generator: given the source + target descriptors and their shared
# discriminating tokens, return a short human phrase explaining the relation.
WhyFn = Callable[[Descriptor, Descriptor, list[str]], str]

# Generic verbs/nouns that the descriptor style ("routes the request to the right
# approach", "finds/generates/edits ...") sprinkles across unrelated capabilities.
# They make a lexical why-phrase ("shares request, right, routing") say nothing, so
# the deterministic fallback drops them before naming the overlap.
_WHY_FILLER = {
    "request", "requests", "right", "routing", "route", "approach", "need", "needs",
    "find", "finds", "get", "gets", "provide", "provides", "return", "returns",
    "use", "used", "using", "data", "content", "information", "result", "results",
    "not", "also", "via", "into", "from", "with", "for", "the", "and",
}


def _fallback_why(shared: list[str]) -> str:
    """A deterministic why-phrase when no model is available. Names the shared
    salient terms with the generic descriptor filler removed; if nothing salient
    survives, says only that it's a related capability (honest, not noise)."""
    salient = [t for t in shared if t not in _WHY_FILLER][:3]
    if salient:
        return "related: both involve " + ", ".join(salient)
    return "related capability in another area"


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
    vectors: dict[str, list[float]] | None = None,
    why_fn: WhyFn | None = None,
) -> int:
    """Add up to `k` see-also links per node to the most-similar nodes in OTHER
    tier-1 branches (similarity >= min_sim). Mutates `SourceNode.links`. Returns
    the number of links added. Symmetric pairs are both linked.

    Similarity is **cosine over `vectors`** when a per-node embedding map is
    supplied, else **lexical Jaccard** over descriptor tokens. Embeddings capture
    semantic relatedness the lexical measure can't — and, importantly, the
    contrastive pass drives sibling *tokens* apart, so lexical cross-branch
    similarity is near-zero on good descriptors; a caller that wants real links
    should pass `vectors`. Tune `min_sim` to the measure (Jaccard ~0.3, cosine
    ~0.6-0.8). A node missing a vector falls back to lexical for its own row.

    The see-also `why` phrase names the relation. When `why_fn` is given it
    produces the phrase from the two descriptors (e.g. a model that can state the
    *semantic* reason the embedding drew the edge — which lexical overlap can't,
    since edges span branches whose salient tokens were driven apart). Without it,
    a deterministic fallback names the shared salient terms. `why_fn` is called
    once per directed edge and must not raise; any failure falls back."""
    tier1 = _tier1_of(tree)
    nodes = [n for n in tree.root.walk() if n.id != tree.root.id and n.id in descriptors]
    tokens = {n.id: descriptor_tokens(descriptors[n.id]) for n in nodes}

    def sim(a: str, b: str) -> float:
        if vectors is not None and a in vectors and b in vectors:
            return _cosine(vectors[a], vectors[b])
        return _jaccard(tokens[a], tokens[b])

    added = 0
    for node in nodes:
        scored = []
        for other in nodes:
            if other.id == node.id or tier1.get(other.id) == tier1.get(node.id):
                continue  # skip self and same-branch (that's the tree's job)
            s = sim(node.id, other.id)
            if s >= min_sim:
                shared = tokens[node.id] & tokens[other.id]
                scored.append((s, other.id, shared))
        scored.sort(key=lambda t: (-t[0], t[1]))
        existing = {link["to"] for link in node.links}
        for _s, oid, shared in scored[:k]:
            if oid in existing:
                continue
            shared_terms = sorted(shared)
            why = _fallback_why(shared_terms)
            if why_fn is not None:
                try:
                    generated = why_fn(descriptors[node.id], descriptors[oid], shared_terms)
                except Exception:
                    generated = ""
                if generated and generated.strip():
                    why = generated.strip()
            node.links.append({"to": oid, "why": why})
            added += 1
    return added


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


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
