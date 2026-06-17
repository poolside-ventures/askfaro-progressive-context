"""Cost annotation — tokenize leaves, roll up subtree costs, hash for caching.

`tokens` is the cost to expand a leaf's full content (0 for branches).
`desc_tokens` is the cost of showing the node's descriptor in a frontier.
`subtree_tokens` is the cost to expand everything beneath a node, rolled up
bottom-up. `content_hash` lets a later build reuse descriptors for unchanged
nodes (leaf = hash of content; branch = hash of child hashes).
"""

from __future__ import annotations

from dataclasses import dataclass

from ..tokenizer import Tokenizer
from .descriptors import Descriptor
from .ir import SourceNode, content_hashes


@dataclass
class Cost:
    tokens: int
    desc_tokens: int
    subtree_tokens: int
    content_hash: str


def annotate(root: SourceNode, descriptors: dict[str, Descriptor], tokenizer: Tokenizer) -> dict[str, Cost]:
    hashes = content_hashes(root)
    costs: dict[str, Cost] = {}

    for node in root.post_order():
        d = descriptors[node.id]
        desc_text = " ".join(filter(None, [node.title, d.what, d.when, " ".join(d.keywords)]))
        desc_tokens = tokenizer(desc_text)

        if node.is_leaf:
            tokens = tokenizer(node.content or "")
            costs[node.id] = Cost(tokens, desc_tokens, tokens, hashes[node.id])
        else:
            child_costs = [costs[c.id] for c in node.children]
            costs[node.id] = Cost(
                tokens=0,
                desc_tokens=desc_tokens,
                subtree_tokens=sum(c.subtree_tokens for c in child_costs),
                content_hash=hashes[node.id],
            )
    return costs
