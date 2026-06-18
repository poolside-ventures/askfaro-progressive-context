"""Arbitrary navigation budget + preserved node metadata (0.2.0)."""

import pytest

from askfaro_progressive_context import NavSession, Runtime
from askfaro_progressive_context.types import Node


# ── arbitrary budget override ────────────────────────────────────────────────


def test_budget_overrides_variant(manifest):
    variant = manifest.variant.budget
    rt = Runtime(manifest, budget=1234)
    assert rt.budget == 1234
    assert rt.effective_budget == 1234
    assert 1234 != variant  # the fixture's tier is not 1234, so this is a real override


def test_budget_falls_back_to_variant(manifest):
    rt = Runtime(manifest)
    assert rt.effective_budget == manifest.variant.budget


def test_budget_and_reserve_compose(manifest):
    rt = Runtime(manifest, budget=2000, reserve=500)
    assert rt.effective_budget == 1500


def test_budget_too_small_after_reserve_raises(manifest):
    with pytest.raises(ValueError):
        Runtime(manifest, budget=300, reserve=300)


def test_navsession_passes_budget(manifest):
    s = NavSession(manifest, budget=900)
    assert s.rt.effective_budget == 900


def test_smaller_budget_bounds_expansion(manifest):
    # A tiny budget should make at least one expand breach the ceiling that a
    # large budget would allow.
    big = Runtime(manifest, budget=100_000)
    small = Runtime(manifest, budget=big.spent + 5)  # almost no headroom
    target = next(e.node_id for e in small.peek())
    from askfaro_progressive_context import BudgetExceeded

    # big can expand the first branch; small cannot (or is far tighter)
    big.expand(target)
    with pytest.raises(BudgetExceeded):
        # expand something expensive under the near-zero budget
        for e in small.peek():
            small.expand(e.node_id)


# ── node metadata preservation ───────────────────────────────────────────────


def test_node_preserves_unknown_fields():
    node = Node.from_dict(
        "n1",
        {
            "what": "a thing",
            "when": "when needed",
            "skill_id": "image",
            "economics": "charged",
        },
    )
    assert node.meta == {"skill_id": "image", "economics": "charged"}


def test_node_meta_empty_when_only_schema_fields():
    node = Node.from_dict("n1", {"what": "x", "when": "y", "tier": 1})
    assert node.meta == {}


def test_frontier_entry_surfaces_meta():
    # A minimal manifest: root with one child branch carrying a domain id.
    from askfaro_progressive_context import Manifest

    m = Manifest.from_dict(
        {
            "source": {},
            "variant": {"budget": 4096},
            "root": {"id": "r", "what": "root", "when": "", "children": ["c1"]},
            "nodes": {
                "c1": {
                    "what": "child",
                    "when": "",
                    "skill_id": "image",
                    "children": ["c1.leaf"],
                },
                "c1.leaf": {"what": "leaf", "when": "", "payload": {"ref": "node://c1.leaf"}},
            },
        }
    )
    rt = Runtime(m)
    entry = next(e for e in rt.peek() if e.node_id == "c1")
    assert entry.meta.get("skill_id") == "image"
