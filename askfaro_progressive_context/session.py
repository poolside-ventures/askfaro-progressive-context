"""NavSession — the agent-facing navigation policy.

Wraps a `Runtime` with mode-aware defaults and three verbs an agent loop drives:

    index()       -> the current frontier, shortest-useful view first
    look(ids)     -> escalate specific candidates to the full descriptor (the
                     'I can't decide from the index' valve), without committing
    open(id)      -> branch: drill into its children; leaf: splice the verbatim
                     content (budget-enforced)

The model's choice of verb *is* the confidence signal — no threshold. If the
index is enough it calls open; if not, it calls look first.

**Modes** encode the latency tradeoff (tokens vs round-trips):

- `local` — expansion is an O(1) resident splice, so round-trips are ~free.
  Start at the shortest useful view (`brief`) and let the agent escalate. Many
  tiny steps are fine.
- `remote` — each round-trip costs real network latency, so disclose more per
  step to need fewer hops: a fuller index (`full`) and small leaves inlined
  straight into the index so they need no second call.
"""

from __future__ import annotations

from dataclasses import dataclass

from .runtime import LeafResolver, Runtime
from .types import Manifest


@dataclass(frozen=True)
class ModeConfig:
    view_level: str  # frontier view shown by index()
    inline_small_leaves: bool  # inline leaf content into index() to save round-trips
    inline_max_tokens: int = 200  # only inline leaves at/under this size
    leaf_context: bool = True  # prepend the ancestor descriptor chain when a leaf opens


LOCAL = ModeConfig(view_level="brief", inline_small_leaves=False)
REMOTE = ModeConfig(view_level="full", inline_small_leaves=True)

_MODES = {"local": LOCAL, "remote": REMOTE}


class NavSession:
    def __init__(
        self,
        manifest: Manifest,
        *,
        mode: str = "local",
        budget: int | None = None,
        reserve: int = 0,
        resolver: LeafResolver | None = None,
        config: ModeConfig | None = None,
    ):
        if config is None:
            if mode not in _MODES:
                raise ValueError(f"mode must be one of {sorted(_MODES)} (or pass config=), got {mode!r}")
            config = _MODES[mode]
        self.mode = mode
        self.cfg = config
        # `budget` sizes the session to a non-standard window (overrides the
        # manifest variant's budget); `reserve` is host headroom on top.
        self.rt = Runtime(
            manifest, budget=budget, reserve=reserve, resolver=resolver, view_level=config.view_level
        )

    # --- verbs -------------------------------------------------------------

    def index(self) -> str:
        """The current frontier at the mode's view level. In remote mode, small
        leaves are inlined (and charged) so the agent needn't open them."""
        lines = [self.rt.frontier_view()]
        if self.cfg.inline_small_leaves:
            for entry in self.rt.peek():
                if entry.is_leaf and not entry.expanded and entry.expand_cost <= self.cfg.inline_max_tokens:
                    try:
                        content = self.rt.expand(entry.node_id)
                    except Exception:
                        continue
                    lines.append(f"--- {entry.node_id} (inlined) ---\n{content}")
        return "\n".join(lines)

    def look(self, ids: list[str]) -> str:
        """Escalate candidates to the full descriptor without opening them."""
        return self.rt.disclose_more(ids, level="full")

    def open(self, node_id: str):
        """Drill into a branch (returns child frontier entries) or splice a
        leaf's verbatim content (returns the content/ref). For a leaf, the
        ancestor descriptor chain is prepended as a context envelope so the
        atomic content isn't read stripped of where it sits (mode-configurable)."""
        result = self.rt.expand(node_id)
        if self.cfg.leaf_context and isinstance(result, str) and self.rt.m.get(node_id).is_leaf:
            envelope = self._context_envelope(node_id)
            if envelope:
                return f"{envelope}\n\n{result}"
        return result

    def _context_envelope(self, node_id: str) -> str:
        """Breadcrumb of ancestor `what` lines — the meaning an isolated leaf
        loses. Not re-charged: these descriptors were already seen on the way
        down (the runtime charged them as the frontier was revealed)."""
        chain = self.rt.ancestors(node_id)
        if not chain:
            return ""
        crumbs = " › ".join((n.title or n.id) for n in chain)
        lines = [f"[context] {crumbs}"]
        lines += [f"  - {(n.title or n.id)}: {n.what}" for n in chain]
        return "\n".join(lines)

    def related(self, node_id: str):
        """Explore: the node's see-also cross-links (with why-phrases), as
        frontier entries. Nothing is opened — this is the lateral counterpart to
        drilling the tree with open()."""
        return self.rt.related(node_id)

    def filter(self, **facets: str):
        """Facet-first precision: node ids matching every facet key=value, to
        narrow the space before reading descriptors."""
        return self.rt.find_by_facets(**facets)

    def close(self, node_id: str) -> int:
        return self.rt.collapse(node_id)

    # --- accounting --------------------------------------------------------

    @property
    def shown_tokens(self) -> int:
        """Everything the model has seen this session — the real length."""
        return self.rt.spent

    @property
    def budget_remaining(self) -> int:
        return self.rt.budget_remaining
