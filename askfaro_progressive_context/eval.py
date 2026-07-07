"""The eval harness — `navigation-success @ budget`, the headline metric.

Give a navigator ONLY the manifest and a budget, and a set of (query ->
correct leaf) cases. Measure whether it expands to the correct leaf within
budget, and how directly. This scores the product claim and, because the
descriptors are the only signal the navigator gets, it scores descriptor
quality — the moat.

Metrics:
  navigation_success  fraction of cases that reach the correct leaf
  first_hop_precision fraction where the first expansion is on the correct
                      tier-1 branch (most sensitive to `when` quality)
  avg_hops            mean expansions over successful cases
  budget_exhausted    cases that failed because budget ran out
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from .navigator import Navigator
from .runtime import BudgetExceeded, Runtime
from .types import Manifest


@dataclass
class NavCase:
    query: str
    target: str  # the correct leaf node id
    note: str | None = None
    # The facet(s) an agent could filter on before scanning for this query (e.g.
    # {"category": "Finance & Markets"}). Only consulted when run with
    # use_facets=True; lets the harness score facet-first navigation vs cold scan.
    facet: dict[str, str] | None = None


@dataclass
class CaseResult:
    query: str
    target: str
    success: bool
    hops: int
    first_hop_correct: bool
    budget_exhausted: bool
    # Length is the point: how many tokens the model actually saw.
    tokens_to_answer: int  # everything spliced into context to reach (or give up on) the answer
    path: list[str] = field(default_factory=list)


@dataclass
class EvalReport:
    navigation_success: float
    first_hop_precision: float
    avg_hops: float
    budget_exhausted: int
    n: int
    # Length metrics — the headline alongside accuracy.
    first_view_tokens: int  # what the model sees before any expansion (the frontier)
    avg_tokens_to_answer: float  # avg tokens seen to reach the answer, over successes
    full_load_tokens: int  # cost of the flat alternative: load everything
    cases: list[CaseResult] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def disclosure_ratio(self) -> float:
        """How much smaller the answer-path context is vs loading everything."""
        return self.full_load_tokens / self.avg_tokens_to_answer if self.avg_tokens_to_answer else 0.0

    def summary(self) -> str:
        return (
            f"navigation_success @ budget : {self.navigation_success:.0%} ({self.n} cases)\n"
            f"first_hop_precision        : {self.first_hop_precision:.0%}\n"
            f"avg_hops (successes)       : {self.avg_hops:.2f}\n"
            f"first_view_tokens          : {self.first_view_tokens}\n"
            f"avg_tokens_to_answer       : {self.avg_tokens_to_answer:.0f} "
            f"(vs {self.full_load_tokens} to load all → {self.disclosure_ratio:.1f}x less)\n"
            f"budget_exhausted           : {self.budget_exhausted}"
        )


def _parent_map(manifest: Manifest) -> dict[str, str]:
    parent: dict[str, str] = {}
    stack = [manifest.root]
    while stack:
        node = stack.pop()
        for child in manifest.children_of(node):
            parent[child.id] = node.id
            stack.append(child)
    return parent


def _tier1_ancestor(manifest: Manifest, parent: dict[str, str], node_id: str) -> str | None:
    """The tier-1 branch (direct child of root) that contains node_id."""
    cur = node_id
    root_id = manifest.root.id
    while cur in parent and parent[cur] != root_id:
        cur = parent[cur]
    return cur if parent.get(cur) == root_id else None


def _facet_scope(rt: Runtime, manifest: Manifest, facet: dict[str, str]) -> set[str]:
    """Surface the facet-matched nodes directly on the frontier — the harness model
    of `/pcx/filter` (or `NavSession.filter`): the agent names a facet and gets the
    matching descriptors to rank, skipping the tree descent. Reveals the branches
    that contain the matches (so they enter the frontier), then returns the set the
    frontier is restricted to (the matches + root). Returns an empty set when the
    facet matches nothing, leaving navigation unrestricted."""
    matched = set(rt.find_by_facets(**facet))
    if not matched:
        return set()
    for mid in matched:
        for anc in rt.ancestors(mid):
            if anc.id != manifest.root.id and not anc.is_leaf and anc.id not in rt._revealed:
                try:
                    rt.expand(anc.id)
                except BudgetExceeded:
                    break
    return matched | {manifest.root.id}


def run_case(
    manifest: Manifest,
    navigator: Navigator,
    case: NavCase,
    *,
    reserve: int = 0,
    budget: int | None = None,
    max_hops: int = 8,
    use_facets: bool = False,
    use_related: bool = False,
) -> CaseResult:
    """Navigate to `case.target`. `use_facets` pre-narrows the frontier to the
    case's facet (filter-first precision); `use_related` lets a run that lands
    close follow a see-also link to the target (lateral rescue). Both default off
    so the baseline is a pure tree walk — the delta between configs is the value
    the cross-links/facets add. `budget` overrides the manifest variant's budget
    (e.g. to isolate navigation quality from a tight window)."""
    rt = Runtime(manifest, budget=budget, reserve=reserve)
    parent = _parent_map(manifest)
    target_branch = _tier1_ancestor(manifest, parent, case.target)

    allowed = None
    if use_facets and case.facet:
        scope = _facet_scope(rt, manifest, case.facet)
        allowed = scope or None  # empty facet match ⇒ no restriction

    path: list[str] = []
    first_hop_correct = False
    budget_exhausted = False

    for hop in range(max_hops):
        frontier = rt.peek()
        if allowed is not None:
            frontier = [e for e in frontier if e.node_id in allowed]
        choice = navigator.choose(case.query, frontier, rt.budget_remaining)
        if choice is None:
            break
        if hop == 0:
            first_hop_correct = _tier1_ancestor(manifest, parent, choice) == target_branch or choice == target_branch
        path.append(choice)
        try:
            rt.expand(choice)
        except BudgetExceeded:
            budget_exhausted = True
            break
        if choice == case.target:
            return CaseResult(case.query, case.target, True, len(path), first_hop_correct, False, rt.spent, path)

    # Lateral rescue: we didn't reach the target by drilling, but a node we opened
    # may have a see-also link straight to it — the "close but not exact" case.
    if use_related and not budget_exhausted:
        for nid in list(path):
            if any(e.node_id == case.target for e in rt.related(nid)):
                try:
                    rt.expand(case.target)
                except BudgetExceeded:
                    budget_exhausted = True
                    break
                path.append(case.target)
                return CaseResult(case.query, case.target, True, len(path), first_hop_correct, False, rt.spent, path)

    return CaseResult(case.query, case.target, False, len(path), first_hop_correct, budget_exhausted, rt.spent, path)


def run_eval(
    manifest: Manifest,
    navigator: Navigator,
    cases: list[NavCase],
    *,
    reserve: int = 0,
    budget: int | None = None,
    max_hops: int = 8,
    use_facets: bool = False,
    use_related: bool = False,
) -> EvalReport:
    results = [
        run_case(manifest, navigator, c, reserve=reserve, budget=budget, max_hops=max_hops,
                 use_facets=use_facets, use_related=use_related)
        for c in cases
    ]
    n = len(results)
    successes = [r for r in results if r.success]
    return EvalReport(
        navigation_success=(len(successes) / n) if n else 0.0,
        first_hop_precision=(sum(r.first_hop_correct for r in results) / n) if n else 0.0,
        avg_hops=(sum(r.hops for r in successes) / len(successes)) if successes else 0.0,
        budget_exhausted=sum(r.budget_exhausted for r in results),
        n=n,
        first_view_tokens=manifest.baseline_tokens(),
        avg_tokens_to_answer=(sum(r.tokens_to_answer for r in successes) / len(successes)) if successes else 0.0,
        full_load_tokens=manifest.full_tokens or 0,
        cases=results,
    )
