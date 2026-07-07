"""Descriptor distinctiveness — the measurable core of the contrastive pass.

The contrastive pass exists to make sibling `when` lines mutually discriminating.
"Discriminating" is measurable, not a vibe: two descriptors collide when their
word bags overlap heavily. This module owns that measure (zero-dependency,
lexical) and the two things built on it:

- **clustering** — when a level has more children than one contrast call can
  hold, group the siblings that most need discrimination *together* (near-
  duplicates in the same group), instead of slicing by position.
- **collision reporting** — the max sibling similarity across the tree, surfaced
  as a build stat and a CI gate. A rebuild that raises the worst collision is a
  regression in the one thing the engine is supposed to optimize.

Similarity is Jaccard over the token bags of `what` + `when` + `keywords`, in
`[0, 1]`. It is deliberately not embedding-based: the compiler must run offline
and in CI with no model, and lexical overlap is exactly what dilutes keyword
retrieval anyway (see the retrieval-channel grade).
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # avoid a circular import with descriptors.py
    from .descriptors import Descriptor

_WORD = re.compile(r"[A-Za-z0-9]+")
_STOP = {
    "the", "a", "an", "to", "of", "for", "and", "or", "is", "in", "on", "with",
    "this", "that", "use", "when", "task", "involves", "anything", "about",
}


def tokenize(text: str) -> set[str]:
    """Content words of `text`, lowercased, minus stopwords and short tokens."""
    return {w for w in _WORD.findall((text or "").lower()) if len(w) > 2 and w not in _STOP}


def descriptor_tokens(d: Descriptor) -> set[str]:
    """The discriminating token bag of a descriptor: `what` + `when` + keywords."""
    toks = tokenize(f"{d.what} {d.when}")
    toks.update(w for kw in d.keywords for w in tokenize(kw))
    return toks


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 0.0
    inter = len(a & b)
    return inter / (len(a) + len(b) - inter)


def similarity(a: Descriptor, b: Descriptor) -> float:
    """Lexical similarity of two descriptors in `[0, 1]` (1.0 == identical bag)."""
    return _jaccard(descriptor_tokens(a), descriptor_tokens(b))


def worst_pair(descriptors: list[Descriptor]) -> tuple[int, int, float]:
    """The most-similar (i, j, similarity) pair; (-1, -1, 0.0) for < 2 inputs."""
    worst = (-1, -1, 0.0)
    bags = [descriptor_tokens(d) for d in descriptors]
    for i in range(len(bags)):
        for j in range(i + 1, len(bags)):
            s = _jaccard(bags[i], bags[j])
            if s > worst[2]:
                worst = (i, j, s)
    return worst


def max_pairwise(descriptors: list[Descriptor]) -> float:
    """Max similarity between any two descriptors in the group (0.0 for < 2)."""
    return worst_pair(descriptors)[2]


def cluster_by_similarity(items: list, tokens: list[set[str]], max_size: int) -> list[list]:
    """Partition `items` into clusters of at most `max_size`, greedily merging the
    most-similar pairs first so near-duplicates land in the same contrast group.

    `tokens[i]` is the pre-computed token bag for `items[i]`. Deterministic:
    pairs are processed in descending-similarity order, ties broken by index.
    """
    n = len(items)
    if n <= max_size:
        return [list(items)]

    parent = list(range(n))
    size = [1] * n

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    pairs = sorted(
        ((_jaccard(tokens[i], tokens[j]), i, j) for i in range(n) for j in range(i + 1, n)),
        key=lambda t: (-t[0], t[1], t[2]),
    )
    for _sim, i, j in pairs:
        ri, rj = find(i), find(j)
        if ri != rj and size[ri] + size[rj] <= max_size:
            parent[ri] = rj
            size[rj] += size[ri]

    groups: dict[int, list] = {}
    for idx in range(n):
        groups.setdefault(find(idx), []).append(items[idx])
    return list(groups.values())


# --- vacuity / paraphrase detection (the retrieval channel) ----------------

# Non-falsifiable filler: a `when` built from these predicts nothing about content.
_VACUOUS = {
    "various", "general", "generic", "miscellaneous", "misc", "stuff", "things",
    "everything", "anything", "several", "related", "etc",
}


def vacuity_flags(title: str | None, d: Descriptor) -> list[str]:
    """Deterministic descriptor-quality flags for the retrieval channel.

    A descriptor is a *filter*, not a summary: it must add discriminating,
    searchable terms over the title. These catch the two failures the LLM grade
    misses because they read fine as prose:

    - **paraphrase** — `what` just restates the title, adding no new term. A
      descriptor that echoes the title is zero filtering information.
    - **vacuous `when`** — `when` carries no content term beyond connective
      filler, so it can't discriminate this node from any other in search.
    """
    flags: list[str] = []
    title_toks = tokenize(title or "")
    what_toks = tokenize(d.what)
    if title_toks and title_toks <= what_toks and len(what_toks - title_toks) <= 1:
        flags.append("`what` restates the title without adding a distinguishing term")

    when_toks = tokenize(d.when)
    if len(when_toks) < 2:
        flags.append("`when` has no distinctive searchable terms (mostly filler)")
    elif when_toks & _VACUOUS and len(when_toks - _VACUOUS) < 2:
        flags.append("`when` is non-specific (generic filler words)")
    return flags


def sibling_collision_report(sibling_groups: list[list[Descriptor]], threshold: float = 0.5) -> dict:
    """Summarize collisions across every sibling group.

    `sibling_groups` is one list of descriptors per branch (children of a node).
    Returns `{"max_similarity": float, "colliding_groups": int, "pairs": [...]}`:
    `colliding_groups` counts branches whose worst sibling pair is at/above
    `threshold`; `pairs` lists the worst offenders (index within their group).
    """
    max_sim = 0.0
    colliding = 0
    pairs: list[dict] = []
    for group in sibling_groups:
        i, j, s = worst_pair(group)
        if i < 0:
            continue
        max_sim = max(max_sim, s)
        if s >= threshold:
            colliding += 1
        if s > 0.0:
            pairs.append({"a": i, "b": j, "similarity": round(s, 3)})
    pairs.sort(key=lambda p: -p["similarity"])
    return {"max_similarity": round(max_sim, 3), "colliding_groups": colliding, "pairs": pairs[:10]}
