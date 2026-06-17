import pytest

from askfaro_progressive_context import BudgetExceeded, Runtime


def test_initial_frontier_is_tier1(manifest):
    rt = Runtime(manifest)
    ids = {e.node_id for e in rt.peek()}
    assert ids == {"posts", "recurring", "research", "channels"}
    assert all(not e.is_leaf for e in rt.peek())


def test_expand_branch_reveals_children(manifest):
    rt = Runtime(manifest)
    new = rt.expand("posts")
    ids = {e.node_id for e in new}
    assert ids == {"posts.draft", "posts.schedule"}
    # children now appear in the frontier
    assert "posts.draft" in {e.node_id for e in rt.peek()}


def test_expand_leaf_splices_and_charges(manifest):
    rt = Runtime(manifest)
    rt.expand("posts")
    before = rt.budget_remaining
    ref = rt.expand("posts.draft")
    assert ref == "node://posts.draft"
    assert rt.budget_remaining == before - 1840


def test_collapse_reclaims(manifest):
    rt = Runtime(manifest)
    rt.expand("posts")
    rt.expand("posts.draft")
    spent = rt.spent
    reclaimed = rt.collapse("posts.draft")
    assert reclaimed == 1840
    assert rt.spent == spent - 1840


def test_budget_is_hard(manifest):
    # Reserve almost everything: a 2100-token leaf must be refused.
    rt = Runtime(manifest, reserve=manifest.variant.budget - 600)
    rt.expand("research")
    with pytest.raises(BudgetExceeded) as ei:
        rt.expand("research.web")  # costs 2100
    assert ei.value.overage > 0


def test_reserve_shrinks_effective_budget(manifest):
    full = Runtime(manifest)
    reserved = Runtime(manifest, reserve=1000)
    assert reserved.effective_budget == full.effective_budget - 1000


def test_reserve_cannot_exceed_budget(manifest):
    with pytest.raises(ValueError):
        Runtime(manifest, reserve=manifest.variant.budget)


def test_leaf_over_budget_raises_with_cost(manifest):
    rt = Runtime(manifest, reserve=manifest.variant.budget - 300)
    rt.expand("posts")
    with pytest.raises(BudgetExceeded) as ei:
        rt.expand("posts.draft")
    assert ei.value.cost == 1840
    assert ei.value.remaining < 1840


def test_auto_evict_frees_room(manifest):
    rt = Runtime(manifest, reserve=manifest.variant.budget - 2600, auto_evict=True)
    rt.expand("research")
    rt.expand("research.synthesize")  # 1700 spliced
    # now 2100 wouldn't fit alongside 1700, but auto-evict drops the older leaf
    ref = rt.expand("research.web")
    assert ref == "node://research.web"
    assert "research.synthesize" not in {nid for nid in rt._spliced}
