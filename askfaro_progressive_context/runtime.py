"""The expansion protocol — how a small model navigates a manifest in a loop.

The runtime, not the model, is the budget authority. It exposes four ops:

    peek()                  -> current frontier + budget_remaining (cheap)
    expand(node_id, level)  -> reveal a branch's children, or splice a leaf
    collapse(node_id)       -> drop a spliced leaf to reclaim budget
    search(query)           -> optional retrieval bridge (pluggable backend)

`effective_budget = manifest.variant.budget - reserve`, where `reserve` is
headroom the host needs for its own content. Every expand is checked against
it; the budget is never silently exceeded.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol

from .types import Manifest, Node, estimate_tokens

# Progressive view levels for the frontier, shortest first. The agent starts
# at "title" (cheapest) and escalates a node — or the whole frontier — to a
# fuller view only when it can't decide. This minimizes the first-view length.
VIEW_LEVELS = ("title", "brief", "full")


def render_descriptor(title: str | None, what: str, when: str, level: str) -> str:
    name = title or ""
    if level == "title":
        return name or what[:40]
    if level == "brief":
        return f"{name}: {what}".strip(": ")
    return f"{name}: {what} | when: {when}".strip(": ")


class BudgetExceeded(Exception):
    def __init__(self, node_id: str, cost: int, remaining: int, suggestion: str | None = None):
        self.node_id = node_id
        self.cost = cost
        self.remaining = remaining
        self.overage = cost - remaining
        self.suggestion = suggestion
        msg = f"expand({node_id!r}) needs {cost} tokens, only {remaining} remaining (over by {self.overage})"
        if suggestion:
            msg += f"; {suggestion}"
        super().__init__(msg)


class SearchBackend(Protocol):
    """Pluggable retrieval bridge (e.g. faro-embedded-search). Optional."""

    def search(self, query: str, k: int) -> list[str]:  # returns ranked node ids
        ...


# node_id -> verbatim content. Progressive disclosure trades *tokens*, not
# *latency*: the whole artifact is meant to be resident next to the inference
# loop so every expand is an O(1) local splice. Remote per-leaf fetches in the
# hot path defeat the purpose — keep this a local lookup.
LeafResolver = Callable[[str], str]


def dict_resolver(leaves: dict[str, str]) -> LeafResolver:
    def resolve(node_id: str) -> str:
        if node_id not in leaves:
            raise KeyError(f"no resident content for node {node_id!r}; ship its leaf in the local store")
        return leaves[node_id]

    return resolve


@dataclass
class FrontierEntry:
    node_id: str
    title: str | None
    what: str
    when: str
    tier: int
    is_leaf: bool
    expand_cost: int  # what expand() would charge right now
    expanded: bool


class Runtime:
    def __init__(
        self,
        manifest: Manifest,
        *,
        reserve: int = 0,
        auto_evict: bool = False,
        search_backend: SearchBackend | None = None,
        resolver: LeafResolver | None = None,
        view_level: str = "full",
    ):
        if view_level not in VIEW_LEVELS:
            raise ValueError(f"view_level must be one of {VIEW_LEVELS}, got {view_level!r}")
        self.m = manifest
        self.reserve = reserve
        self.effective_budget = manifest.variant.budget - reserve
        if self.effective_budget <= 0:
            raise ValueError(
                f"reserve ({reserve}) >= variant budget ({manifest.variant.budget}); no room to navigate"
            )
        self.auto_evict = auto_evict
        self.search_backend = search_backend
        self.resolver = resolver
        self.view_level = view_level

        # Visible frontier: nodes whose descriptor the agent can act on.
        self._frontier: dict[str, Node] = {}
        # Branches we've expanded (children revealed).
        self._revealed: set[str] = set()
        # Spliced leaf payloads: node_id -> (level, tokens). Insertion order = LRU.
        self._spliced: dict[str, tuple[str, int]] = {}
        # Nodes escalated to a fuller descriptor view via disclose_more().
        self._extra_disclosed = 0

        if view_level == "full":
            self._spent_baseline = manifest.baseline_tokens()  # honors stored manifest_tokens
        else:
            self._spent_baseline = self._dcost(manifest.root) + sum(
                self._dcost(c) for c in manifest.children_of(manifest.root)
            )
        for child in manifest.children_of(manifest.root):
            self._frontier[child.id] = child

    # --- budget accounting -------------------------------------------------

    def _dcost(self, node: Node) -> int:
        """Descriptor cost at the runtime's view level (brief frontier is
        cheaper than full)."""
        if self.view_level == "full":
            return node.descriptor_cost()
        return estimate_tokens(render_descriptor(node.title, node.what, node.when, self.view_level))

    @property
    def spent(self) -> int:
        return self._spent_baseline + self._extra_disclosed + sum(tok for _, tok in self._spliced.values())

    @property
    def budget_remaining(self) -> int:
        return self.effective_budget - self.spent

    # --- ops ---------------------------------------------------------------

    def frontier_view(self, level: str | None = None) -> str:
        """Render the current frontier at a view level (default: the runtime's
        view_level). `title` is the shortest first view; `brief` adds `what`;
        `full` adds `when`."""
        level = level or self.view_level
        if level not in VIEW_LEVELS:
            raise ValueError(f"level must be one of {VIEW_LEVELS}, got {level!r}")
        return "\n".join(
            f"{e.node_id}\t{render_descriptor(e.title, e.what, e.when, level)}"
            for e in self.peek()
            if not e.expanded
        )

    def frontier_tokens(self, level: str | None = None) -> int:
        """Token cost of showing the current frontier at `level` (default: the
        runtime's view_level) — the first-view length the model pays."""
        level = level or self.view_level
        if level not in VIEW_LEVELS:
            raise ValueError(f"level must be one of {VIEW_LEVELS}, got {level!r}")
        return sum(
            estimate_tokens(render_descriptor(e.title, e.what, e.when, level))
            for e in self.peek()
            if not e.expanded
        )

    def disclose_more(self, node_ids: list[str], level: str = "full") -> str:
        """Escalate specific frontier nodes to a fuller descriptor view without
        committing to opening them — the 'look' step. Charges only the extra
        tokens over the current view level, budget-checked."""
        if level not in VIEW_LEVELS:
            raise ValueError(f"level must be one of {VIEW_LEVELS}, got {level!r}")
        lines, delta = [], 0
        for nid in node_ids:
            node = self.m.get(nid)
            full = estimate_tokens(render_descriptor(node.title, node.what, node.when, level))
            delta += max(0, full - self._dcost(node))
            lines.append(f"{nid}\t{render_descriptor(node.title, node.what, node.when, level)}")
        if delta > self.budget_remaining:
            raise BudgetExceeded("disclose_more", delta, self.budget_remaining, "narrow the set or collapse a leaf")
        self._extra_disclosed += delta
        return "\n".join(lines)

    def peek(self) -> list[FrontierEntry]:
        out: list[FrontierEntry] = []
        for nid, node in self._frontier.items():
            out.append(
                FrontierEntry(
                    node_id=nid,
                    title=node.title,
                    what=node.what,
                    when=node.when,
                    tier=node.tier,
                    is_leaf=node.is_leaf,
                    expand_cost=self._expand_cost(node),
                    expanded=(nid in self._revealed or nid in self._spliced),
                )
            )
        return out

    def _expand_cost(self, node: Node, level: str = "full") -> int:
        if node.is_branch:
            return sum(self._dcost(c) for c in self.m.children_of(node))
        return node.render_cost(level)

    def expand(self, node_id: str, level: str = "full") -> str | list[FrontierEntry]:
        """Expand a node. Branch -> reveal children descriptors (returns new
        frontier entries). Leaf -> splice verbatim payload ref (returns it).
        Raises BudgetExceeded if it would breach the effective budget.
        """
        node = self.m.get(node_id)

        if node.is_leaf and node_id in self._spliced:
            return node.payload.ref  # idempotent
        if node.is_branch and node_id in self._revealed:
            return self.peek()

        cost = self._expand_cost(node, level)
        self._ensure_budget(node_id, cost, node)

        if node.is_branch:
            self._revealed.add(node_id)
            new_entries: list[FrontierEntry] = []
            for child in self.m.children_of(node):
                self._frontier[child.id] = child
                # branch-reveal cost is folded into baseline once revealed
                self._spent_baseline += self._dcost(child)
                new_entries.append(self.peek_one(child.id))
            return new_entries

        # leaf — splice the verbatim content (resident, O(1)) or return the ref
        self._spliced[node_id] = (level, cost)
        if self.resolver is not None:
            return self.resolver(node_id)
        return node.payload.ref

    def peek_one(self, node_id: str) -> FrontierEntry:
        node = self.m.get(node_id)
        return FrontierEntry(
            node_id=node_id,
            title=node.title,
            what=node.what,
            when=node.when,
            tier=node.tier,
            is_leaf=node.is_leaf,
            expand_cost=self._expand_cost(node),
            expanded=(node_id in self._revealed or node_id in self._spliced),
        )

    def collapse(self, node_id: str) -> int:
        """Drop a spliced leaf; returns tokens reclaimed."""
        entry = self._spliced.pop(node_id, None)
        return entry[1] if entry else 0

    def search(self, query: str, k: int = 5) -> list[str]:
        if self.search_backend is None:
            raise RuntimeError("no search backend configured (search is optional)")
        return self.search_backend.search(query, k)

    # --- internals ---------------------------------------------------------

    def _ensure_budget(self, node_id: str, cost: int, node: Node) -> None:
        if cost <= self.budget_remaining:
            return
        if self.auto_evict and node.is_leaf:
            self._evict_until(cost, protect=node_id)
            if cost <= self.budget_remaining:
                return
        suggestion = None
        if node.is_leaf and node.summary_tokens is not None and node.summary_tokens <= self.budget_remaining:
            suggestion = "try level='summary'"
        elif self._spliced:
            oldest = next(iter(self._spliced))
            suggestion = f"collapse a spliced leaf first (e.g. {oldest!r})"
        raise BudgetExceeded(node_id, cost, self.budget_remaining, suggestion)

    def _evict_until(self, needed: int, protect: str) -> None:
        for nid in list(self._spliced):
            if self.budget_remaining >= needed:
                return
            if nid == protect:
                continue
            self.collapse(nid)
