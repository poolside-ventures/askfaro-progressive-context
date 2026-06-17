"""Incremental rebuilds: only re-describe what actually changed."""

from pathlib import Path

from askfaro_progressive_context.build import FakeDescriptorModel, compile_source
from askfaro_progressive_context.build.adapters import get_adapter

FIX = Path(__file__).parent / "fixtures"


class _CountingModel(FakeDescriptorModel):
    """Counts how many describe calls hit the 'model' (the expensive part)."""

    def __init__(self):
        self.leaf_calls = 0
        self.branch_calls = 0

    def describe_leaf(self, node, *, feedback=None):
        self.leaf_calls += 1
        return super().describe_leaf(node, feedback=feedback)

    def describe_branch(self, node, children, *, feedback=None):
        self.branch_calls += 1
        return super().describe_branch(node, children, feedback=feedback)


def _skills_tree():
    return get_adapter("skills").load(FIX / "skills")


def test_unchanged_rebuild_describes_nothing():
    tree = _skills_tree()
    first = compile_source(tree, _CountingModel(), [4096])
    prior = first.manifests[4096]

    model = _CountingModel()
    result = compile_source(tree, model, [4096], prior_manifest=prior)
    # identical input + cache ⇒ zero model calls, everything reused
    assert model.leaf_calls == 0 and model.branch_calls == 0
    assert result.stats["regenerated"] == 0
    assert result.stats["reused"] == result.stats["nodes"]


def test_full_build_without_cache_describes_everything():
    tree = _skills_tree()
    model = _CountingModel()
    result = compile_source(tree, model, [4096])
    leaves = result.stats["leaves"]
    assert model.leaf_calls == leaves  # every leaf described once
    assert result.stats["reused"] == 0


def test_changed_leaf_regenerates_only_its_path():
    tree = _skills_tree()
    prior = compile_source(tree, _CountingModel(), [4096]).manifests[4096]

    # mutate one leaf's content; its ancestor path's hashes change too
    target = next(n for n in tree.root.walk() if n.id == "draft-post")
    target.content = (target.content or "") + "\n\nNEW: include a hashtag."

    model = _CountingModel()
    result = compile_source(tree, model, [4096], prior_manifest=prior)

    # the changed leaf is re-described; siblings (unchanged content) are not
    assert model.leaf_calls == 1
    # but far fewer than a full rebuild
    assert result.stats["regenerated"] < result.stats["nodes"]
    assert result.stats["reused"] > 0


def test_descriptors_match_full_rebuild_after_change():
    # Incremental result for the changed subtree should equal a from-scratch build.
    tree = _skills_tree()
    prior = compile_source(tree, FakeDescriptorModel(), [4096]).manifests[4096]
    target = next(n for n in tree.root.walk() if n.id == "draft-post")
    target.content = (target.content or "") + "\n\nNEW LINE"

    incr = compile_source(tree, FakeDescriptorModel(), [4096], prior_manifest=prior).manifests[4096]
    full = compile_source(tree, FakeDescriptorModel(), [4096]).manifests[4096]
    assert incr["nodes"]["draft-post"]["what"] == full["nodes"]["draft-post"]["what"]
