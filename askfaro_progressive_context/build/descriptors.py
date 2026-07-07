"""Descriptor generation — the quality engine.

`what`/`when` lines are the navigation index, and their quality is the moat.
The engine runs three passes:

1. **Bottom-up generation** — leaves from their full content, branches from
   their children's descriptors (cheaper and more accurate than re-reading
   every leaf).
2. **Contrastive sibling pass** — rewrite each sibling's `when` to be mutually
   discriminating. This is the single biggest quality lever: the agent's real
   choice is between siblings, so the `when` lines must separate them.
3. **Self-grade + repair** — grade each descriptor; regenerate the ones below
   threshold with the failure reason. Bounded retries.

`DescriptorModel` abstracts the actual model so the engine is testable offline
with `FakeDescriptorModel`. `LLMDescriptorModel` drives a real (Flash-class)
model via an `LLMClient`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..llm import LLMClient, parse_json_object
from .distinct import (
    cluster_by_similarity,
    descriptor_tokens,
    max_pairwise,
    sibling_collision_report,
    vacuity_flags,
)
from .ir import SourceNode, SourceTree, content_hashes

_MAX_CONTENT_CHARS = 6000
_WORD = re.compile(r"[A-Za-z0-9]+")


@dataclass
class Descriptor:
    what: str
    when: str
    keywords: list[str] = field(default_factory=list)


@dataclass
class Grade:
    score: float
    reason: str = ""


# --- model interface -------------------------------------------------------


class DescriptorModel:
    """Override these four methods. Defaults raise so partial impls are loud."""

    def describe_leaf(self, node: SourceNode, *, feedback: str | None = None) -> Descriptor:
        raise NotImplementedError

    def describe_branch(self, node: SourceNode, children: list[Descriptor], *, feedback: str | None = None) -> Descriptor:
        raise NotImplementedError

    def contrast(self, parent_title: str | None, siblings: list[tuple[SourceNode, Descriptor]]) -> list[Descriptor]:
        return [d for _, d in siblings]  # default: no-op

    def grade(self, node: SourceNode, descriptor: Descriptor, siblings: list[Descriptor]) -> Grade:
        return Grade(1.0)  # default: accept


# --- the engine ------------------------------------------------------------


def _run(items, fn, max_workers):
    """Map fn over items, optionally in a thread pool (calls are I/O-bound)."""
    if max_workers and max_workers > 1 and len(items) > 1:
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            return list(ex.map(fn, items))
    return [fn(x) for x in items]


def cache_from_manifest(manifest: dict) -> dict[str, tuple[str, Descriptor]]:
    """Build a content_hash-keyed descriptor cache from a prior manifest, so a
    rebuild can reuse descriptors for unchanged nodes."""
    cache: dict[str, tuple[str, Descriptor]] = {}
    root = manifest.get("root", {})
    root_hash = manifest.get("source", {}).get("content_hash")
    if root.get("id") and root_hash:
        cache[root["id"]] = (root_hash, Descriptor(root.get("what", ""), root.get("when", ""), root.get("keywords", [])))
    for nid, n in manifest.get("nodes", {}).items():
        if "content_hash" in n:
            cache[nid] = (n["content_hash"], Descriptor(n.get("what", ""), n.get("when", ""), n.get("keywords", [])))
    return cache


def generate_descriptors(
    tree: SourceTree,
    model: DescriptorModel,
    *,
    contrastive: bool = True,
    contrast_chunk: int = 8,
    collision_threshold: float = 0.5,
    max_contrast_rounds: int = 2,
    grade_threshold: float = 0.7,
    max_repairs: int = 1,
    max_workers: int = 1,
    cache: dict[str, tuple[str, Descriptor]] | None = None,
    _stats: dict | None = None,
) -> dict[str, Descriptor]:
    descriptors: dict[str, Descriptor] = {}
    hashes = content_hashes(tree.root)
    cache = cache or {}
    incremental = bool(cache)
    fresh: set[str] = set()  # nodes (re)generated this run

    depth = {tree.root.id: 0}
    by_depth: dict[int, list[SourceNode]] = {}
    for node in tree.root.walk():
        for child in node.children:
            depth[child.id] = depth[node.id] + 1
    for node in tree.root.walk():
        by_depth.setdefault(depth[node.id], []).append(node)

    # 1. bottom-up generation — reuse a cached descriptor when the node's
    #    content_hash is unchanged; otherwise describe fresh. Deepest level
    #    first so a fresh branch's children are ready.
    def _gen(node: SourceNode) -> tuple[str, Descriptor, bool]:
        cached = cache.get(node.id)
        if cached and cached[0] == hashes[node.id]:
            return node.id, cached[1], False
        if node.is_leaf:
            return node.id, model.describe_leaf(node), True
        return node.id, model.describe_branch(node, [descriptors[c.id] for c in node.children]), True

    for d in sorted(by_depth, reverse=True):
        for nid, desc, is_fresh in _run(by_depth[d], _gen, max_workers):
            descriptors[nid] = desc
            if is_fresh:
                fresh.add(nid)

    # 2. contrastive sibling pass — only for groups whose parent changed (a
    #    parent's hash rolls up its subtree, so an unchanged parent ⇒ unchanged
    #    group, whose cached descriptors were already contrasted). When a level
    #    has more children than one contrast call can hold, the group is split by
    #    *similarity* (near-duplicates together), never by position — a node must
    #    be contrasted against the siblings it actually collides with. Each group
    #    is rewritten until its worst pair drops below `collision_threshold` or a
    #    round makes no progress (bounded by `max_contrast_rounds`).
    if contrastive:
        jobs: list[tuple[str | None, list[SourceNode]]] = []
        for branch in tree.branches():  # includes the root; do not prepend it (double-contrasts)
            if incremental and branch.id not in fresh:
                continue
            sibs = branch.children
            if len(sibs) < 2:
                continue
            tokens = [descriptor_tokens(descriptors[c.id]) for c in sibs]
            for chunk in cluster_by_similarity(sibs, tokens, contrast_chunk):
                if len(chunk) >= 2:
                    jobs.append((branch.title, chunk))

        def _contrast(job):
            title, chunk = job
            current = [descriptors[c.id] for c in chunk]
            # Round 1 always runs; extra rounds only while the group still
            # collides and each round keeps improving (so a no-op model stops).
            for _ in range(max(1, max_contrast_rounds)):
                before = max_pairwise(current)
                refined = model.contrast(title, list(zip(chunk, current)))
                after = max_pairwise(refined)
                current = refined
                if after < collision_threshold or after >= before:
                    break
            return chunk, current

        for chunk, refined in _run(jobs, _contrast, max_workers):
            for child, rd in zip(chunk, refined):
                descriptors[child.id] = rd
                fresh.add(child.id)  # `when` rewritten → must be re-graded

    # 3. self-grade + repair — only nodes (re)generated this run.
    parent_of = {c.id: n for n in tree.root.walk() for c in n.children}

    def _grade_repair(node: SourceNode) -> tuple[str, Descriptor]:
        desc = descriptors[node.id]
        siblings = [descriptors[c.id] for c in parent_of[node.id].children if c.id != node.id]
        for _ in range(max_repairs):
            grade = model.grade(node, desc, siblings)
            # Deterministic retrieval-channel check the model grade misses: a
            # vacuous/paraphrase descriptor forces a repair even if it reads well.
            flags = vacuity_flags(node.title, desc)
            if grade.score >= grade_threshold and not flags:
                break
            reason = "; ".join(filter(None, [grade.reason, *flags]))
            if node.is_leaf:
                desc = model.describe_leaf(node, feedback=reason)
            else:
                desc = model.describe_branch(node, [descriptors[c.id] for c in node.children], feedback=reason)
        return node.id, desc

    targets = [n for n in tree.root.walk() if n.id != tree.root.id and (not incremental or n.id in fresh)]
    for nid, desc in _run(targets, _grade_repair, max_workers):
        descriptors[nid] = desc

    if _stats is not None:
        _stats["regenerated"] = len(fresh)
        _stats["reused"] = len(descriptors) - len(fresh)
        sibling_groups = [
            [descriptors[c.id] for c in n.children]
            for n in tree.root.walk()
            if len(n.children) >= 2
        ]
        _stats["collisions"] = sibling_collision_report(sibling_groups, collision_threshold)
        vacuous = {
            n.id: flags
            for n in tree.root.walk()
            if n.id != tree.root.id and (flags := vacuity_flags(n.title, descriptors[n.id]))
        }
        _stats["vacuity"] = {"flagged": sorted(vacuous), "count": len(vacuous)}
    return descriptors


# --- deterministic model for offline use + tests ---------------------------


def _keywords(text: str, k: int = 6) -> list[str]:
    stop = {"the", "a", "an", "to", "of", "for", "and", "or", "is", "in", "on", "with", "this", "that"}
    seen: list[str] = []
    for w in _WORD.findall(text.lower()):
        if len(w) > 2 and w not in stop and w not in seen:
            seen.append(w)
        if len(seen) >= k:
            break
    return seen


def _first_sentence(text: str) -> str:
    text = " ".join(text.split())
    for sep in (". ", "\n"):
        if sep in text:
            return text.split(sep, 1)[0].strip()
    return text[:120].strip()


class FakeDescriptorModel(DescriptorModel):
    """Deterministic descriptors derived from titles/hints/content. No model
    calls — used for offline builds, the CLI `--fake` flag, and tests."""

    def describe_leaf(self, node: SourceNode, *, feedback: str | None = None) -> Descriptor:
        title = node.title or node.id
        body = node.hint or _first_sentence(node.content or "")
        return Descriptor(
            what=f"{title}: {body}".strip()[:160],
            when=f"Use when the task involves {title.lower()}.",
            keywords=node.keywords or _keywords(f"{title} {node.hint or ''} {node.content or ''}"),
        )

    def describe_branch(self, node: SourceNode, children: list[Descriptor], *, feedback: str | None = None) -> Descriptor:
        title = node.title or node.id
        return Descriptor(
            what=(node.hint or f"{title}: {len(children)} items.")[:160],
            when=f"Consult for anything about {title.lower()}.",
            keywords=_keywords(" ".join(c.what for c in children)),
        )


# --- real model ------------------------------------------------------------


class LLMDescriptorModel(DescriptorModel):
    _JSON = {"type": "json_object"}

    def __init__(self, client: LLMClient):
        self.client = client

    def _complete_json(self, prompt: str) -> dict:
        return parse_json_object(self.client.complete(prompt, system=self._SYS, response_format=self._JSON))

    _SYS = (
        "You write navigation index entries for an agent browsing a capability tree "
        "under a tight token budget. Be terse — every wasted word costs the agent "
        "context. 'what': ≤80 chars, short verb phrase, core action only, no "
        "sub-clauses, no trailing punctuation. 'when': ≤80 chars, the user goal "
        "that makes this the right choice over its siblings. Reply with strict JSON only."
    )

    @staticmethod
    def _hint_line(hint: str | None) -> str:
        return f"Author hint: {hint}\n" if hint else ""

    @staticmethod
    def _feedback_line(feedback: str | None) -> str:
        return f"Revise — prior entry was weak because: {feedback}\n" if feedback else ""

    def describe_leaf(self, node: SourceNode, *, feedback: str | None = None) -> Descriptor:
        content = (node.content or "")[:_MAX_CONTENT_CHARS]
        prompt = (
            f"Title: {node.title}\n"
            f"{self._hint_line(node.hint)}"
            f"Content:\n{content}\n\n"
            f"{self._feedback_line(feedback)}"
            'Return {"what": str, "when": str, "keywords": [str, ...]}.'
        )
        title = node.title or node.id
        fallback = Descriptor(what=(node.hint or title)[:80], when=f"Use for {title}.", keywords=node.keywords)
        return self._call(prompt, fallback)

    def describe_branch(self, node: SourceNode, children: list[Descriptor], *, feedback: str | None = None) -> Descriptor:
        listing = "\n".join(f"- {c.what}" for c in children)
        prompt = (
            f"Title: {node.title}\nThis node groups these children:\n{listing}\n\n"
            f"{self._feedback_line(feedback)}"
            'Summarize the group. Return {"what": str, "when": str, "keywords": [str, ...]}.'
        )
        title = node.title or node.id
        fallback = Descriptor(what=(node.hint or title)[:80], when=f"Anything about {title}.", keywords=[])
        return self._call(prompt, fallback)

    def contrast(self, parent_title: str | None, siblings: list[tuple[SourceNode, Descriptor]]) -> list[Descriptor]:
        originals = [d for _, d in siblings]
        rows = "\n".join(
            f"{i}. id {n.id} | what: {d.what} | when: {d.when}" for i, (n, d) in enumerate(siblings)
        )
        prompt = (
            f"These are sibling options under {parent_title!r}. Rewrite each 'when' so it "
            f"clearly DISCRIMINATES from the others — an agent must be able to pick the right "
            f"one. Keep 'what' unless it is wrong. Preserve order.\n\n{rows}\n\n"
            'Return {"items": [{"what": ..., "when": ..., "keywords": [...]}, ...]} with one item per row.'
        )
        try:
            items = self._complete_json(prompt).get("items", [])
        except (ValueError, KeyError):
            return originals  # contrast is an enhancement; never fail the build over it
        if len(items) != len(originals):
            return originals
        return [
            Descriptor(
                what=item.get("what", orig.what),
                when=item.get("when", orig.when),
                keywords=item.get("keywords", orig.keywords),
            )
            for orig, item in zip(originals, items)
        ]

    def grade(self, node: SourceNode, descriptor: Descriptor, siblings: list[Descriptor]) -> Grade:
        others = "\n".join(f"- {d.when}" for d in siblings) or "(none)"
        prompt = (
            f"Grade this navigation entry for an agent choosing among siblings.\n"
            f"Entry what: {descriptor.what}\nEntry when: {descriptor.when}\n"
            f"Sibling 'when' lines:\n{others}\n\n"
            f"Score 0-1 on TWO channels, and report the lower: (1) navigation — how well "
            f"'when' discriminates this from its siblings for an agent reading the index; "
            f"(2) retrieval — whether 'when'/'what' carry distinctive, searchable keywords "
            f"rather than generic connective prose (a descriptor that reads well but is all "
            f"filler words is un-searchable). "
            'Return {"score": <float>, "reason": <string>}.'
        )
        try:
            obj = self._complete_json(prompt)
            return Grade(score=float(obj.get("score", 1.0)), reason=str(obj.get("reason", "")))
        except (ValueError, KeyError):
            return Grade(1.0)  # accept on parse failure rather than crash

    def _call(self, prompt: str, fallback: Descriptor) -> Descriptor:
        try:
            obj = self._complete_json(prompt)
        except (ValueError, KeyError):
            return fallback  # degrade to a hint-based descriptor, never crash the build
        what = str(obj.get("what", "")).strip()[:80] or fallback.what
        return Descriptor(
            what=what,
            when=str(obj.get("when", "")).strip()[:80] or fallback.when,
            keywords=list(obj.get("keywords", [])) or fallback.keywords,
        )
