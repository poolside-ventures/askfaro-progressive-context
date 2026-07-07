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

from dataclasses import dataclass, field
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
    meta: dict = field(default_factory=dict)  # domain attrs preserved from the node


class Runtime:
    def __init__(
        self,
        manifest: Manifest,
        *,
        budget: int | None = None,
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
        # `budget` overrides the variant's budget for a non-standard window (e.g. an
        # on-device model whose context isn't one of the precomputed tiers). Falls
        # back to the variant's budget. `reserve` is host headroom on top of either.
        base_budget = manifest.variant.budget if budget is None else budget
        self.budget = base_budget
        self.effective_budget = base_budget - reserve
        if self.effective_budget <= 0:
            raise ValueError(
                f"reserve ({reserve}) >= budget ({base_budget}); no room to navigate"
            )
        self.auto_evict = auto_evict
        self.search_backend = search_backend
        self.resolver = resolver
        self.view_level = view_level
        self._parents: dict[str, str] | None = None  # lazy child_id -> parent_id map

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
                    meta=node.meta,
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
            meta=node.meta,
        )

    def ancestors(self, node_id: str) -> list[Node]:
        """The chain of ancestor nodes from root down to `node_id`'s parent
        (empty for a tier-1 node). Used to restore the context an atomic leaf
        loses when it is read in isolation."""
        if self._parents is None:
            parents: dict[str, str] = {}
            stack = [self.m.root]
            while stack:
                n = stack.pop()
                for c in self.m.children_of(n):
                    parents[c.id] = n.id
                    stack.append(c)
            self._parents = parents
        chain: list[Node] = []
        cur = self._parents.get(node_id)
        while cur is not None:
            chain.append(self.m.get(cur))
            cur = self._parents.get(cur)
        chain.reverse()  # root ... immediate parent
        return chain

    def related(self, node_id: str) -> list[FrontierEntry]:
        """The see-also cross-links of a node, as frontier entries (the *explore*
        move: follow lateral relations across branches, vs *precision* which
        stays on the tree). Descriptors only — nothing is opened or charged."""
        node = self.m.get(node_id)
        out: list[FrontierEntry] = []
        for link in node.links:
            try:
                entry = self.peek_one(link.to)
            except KeyError:
                continue
            entry.meta = {**entry.meta, "link_why": link.why}
            out.append(entry)
        return out

    def reconcile(self, current_identity: str | None = None, live_ids: set[str] | None = None) -> list[str]:
        """Check the manifest against live state and return staleness warnings.

        An agent trusts a curated map completely, so a stale one is worse than
        none — it misroutes silently. This surfaces the drift instead:

        - `current_identity` — the origin's current content hash; if it differs
          from `manifest.identity`, the map is stale (content moved).
        - `live_ids` — the set of ids that still exist at the source; any leaf
          the manifest points at that is missing is a dangling route.

        Returns a (possibly empty) list of human-readable warnings; the caller
        decides whether to refetch. This is read-only detection, never a write.
        """
        warnings: list[str] = []
        mine = self.m.identity
        if current_identity is not None and mine is not None and current_identity != mine:
            warnings.append(
                f"manifest is stale: identity {mine!r} != origin {current_identity!r}; refetch before trusting routes"
            )
        if live_ids is not None:
            missing = [nid for nid in [self.m.root.id, *self.m.nodes] if nid not in live_ids]
            if missing:
                warnings.append(
                    f"{len(missing)} node(s) no longer exist at the source (dangling routes): "
                    f"{', '.join(sorted(missing)[:5])}"
                )
        return warnings

    def find_by_facets(self, **facets: str) -> list[str]:
        """Node ids whose facets match every given key=value pair. Facet-first
        filtering is multiplicative precision — cut the space by orthogonal
        dimensions before ranking descriptors. Empty query matches nothing."""
        if not facets:
            return []
        q = {str(k): str(v) for k, v in facets.items()}
        ids: list[str] = []
        for nid in [self.m.root.id, *self.m.nodes]:
            node = self.m.get(nid)
            if all(node.facets.get(k) == v for k, v in q.items()):
                ids.append(nid)
        return ids

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
