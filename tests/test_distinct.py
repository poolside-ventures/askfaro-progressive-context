"""Distinctiveness core (A1/A2): similarity, similarity-clustering, the
contrastive convergence loop, and the collision report surfaced in build stats."""

from askfaro_progressive_context.build import Descriptor, FakeDescriptorModel, compile_source
from askfaro_progressive_context.build.descriptors import generate_descriptors
from askfaro_progressive_context.build.distinct import (
    cluster_by_similarity,
    descriptor_tokens,
    max_pairwise,
    similarity,
    worst_pair,
)
from askfaro_progressive_context.build.ir import SourceNode, SourceTree


def _d(what, when, keywords=None):
    return Descriptor(what=what, when=when, keywords=keywords or [])


def test_similarity_bounds_and_symmetry():
    a = _d("create recurring booking", "user schedules a repeating meeting")
    b = _d("create recurring booking", "user schedules a repeating meeting")
    assert similarity(a, b) == 1.0
    assert similarity(a, b) == similarity(b, a)
    far = _d("delete invoice", "remove a billing document")
    assert similarity(a, far) < 0.2


def test_worst_pair_and_max_pairwise():
    near1 = _d("book meeting", "schedule a meeting with someone")
    near2 = _d("book meeting", "schedule a meeting with a person")
    far = _d("export csv", "download a spreadsheet report")
    i, j, s = worst_pair([near1, far, near2])
    assert {i, j} == {0, 2}  # the two near-duplicates, regardless of position
    assert s == max_pairwise([near1, far, near2]) > 0.5


def test_cluster_groups_near_duplicates_together_across_positions():
    # Two near-duplicate pairs interleaved so positional chunking would split them.
    items = ["a1", "b1", "a2", "b2"]
    descs = {
        "a1": _d("create recurring booking", "repeating appointment"),
        "a2": _d("create recurring booking", "repeating appointment slot"),
        "b1": _d("export invoice pdf", "download a billing document"),
        "b2": _d("export invoice pdf", "download billing documents"),
    }
    tokens = [descriptor_tokens(descs[i]) for i in items]
    groups = cluster_by_similarity(items, tokens, max_size=2)
    grouped = {frozenset(g) for g in groups}
    assert frozenset({"a1", "a2"}) in grouped
    assert frozenset({"b1", "b2"}) in grouped


def test_cluster_returns_single_group_when_under_max_size():
    items = ["x", "y"]
    tokens = [{"x"}, {"y"}]
    assert cluster_by_similarity(items, tokens, max_size=8) == [["x", "y"]]


class _ConvergingContrast(FakeDescriptorModel):
    """Separates a colliding group into fully-distinct descriptors in one call."""

    def __init__(self):
        self.calls = 0

    def contrast(self, parent_title, siblings):
        self.calls += 1
        return [
            Descriptor(what=f"uniqueaction{k}", when=f"scenariocontext{k}", keywords=[f"keyword{k}"])
            for k, _ in enumerate(siblings)
        ]


class _SlowContrast(FakeDescriptorModel):
    """Improves distinctiveness a little each round but never crosses threshold —
    exercises the max_contrast_rounds cap without an infinite loop."""

    def __init__(self):
        self.calls = 0

    def contrast(self, parent_title, siblings):
        self.calls += 1
        shared = max(1, 5 - self.calls)  # strictly shrinking shared token count
        common = [f"shared{t}" for t in range(shared)]
        return [
            Descriptor(what=" ".join(common + [f"unique{k}round{self.calls}"]), when="x", keywords=[])
            for k, _ in enumerate(siblings)
        ]


def _colliding_tree():
    # Three leaves whose FakeDescriptorModel descriptors collide on the shared title stem.
    kids = [SourceNode(id=f"book-{n}", title=f"book {n}", content=f"book a {n} slot") for n in ("a", "b", "c")]
    root = SourceNode(id="root", title="bookings", children=kids)
    return SourceTree(source_id="t", kind="skills", root=root)


def test_convergence_loop_stops_once_group_is_distinct():
    model = _ConvergingContrast()
    generate_descriptors(_colliding_tree(), model, collision_threshold=0.3, max_contrast_rounds=3)
    # The model separates the group in round 1, so no extra rounds are spent.
    assert model.calls == 1


def test_convergence_loop_respects_max_rounds_cap():
    model = _SlowContrast()
    generate_descriptors(_colliding_tree(), model, collision_threshold=0.3, max_contrast_rounds=3)
    # Never converges but keeps improving, so it runs exactly the cap.
    assert model.calls == 3


def test_collision_report_in_stats():
    tree = _colliding_tree()
    stats: dict = {}
    generate_descriptors(tree, FakeDescriptorModel(), _stats=stats, collision_threshold=0.3)
    assert "collisions" in stats
    assert 0.0 <= stats["collisions"]["max_similarity"] <= 1.0


def test_build_surfaces_max_sibling_similarity():
    result = compile_source(_colliding_tree(), FakeDescriptorModel(), [4096])
    assert "max_sibling_similarity" in result.stats
    assert isinstance(result.stats["max_sibling_similarity"], float)


def test_vacuity_flags_paraphrase_and_filler():
    from askfaro_progressive_context.build.distinct import vacuity_flags

    # `what` just echoes the title, `when` is generic filler
    bad = vacuity_flags("export csv", _d("export csv", "various general purposes"))
    assert any("restates the title" in f for f in bad)
    assert any("non-specific" in f or "no distinctive" in f for f in bad)

    # a grounded, discriminating descriptor is clean
    good = vacuity_flags("export csv", _d("stream ledger rows to a spreadsheet", "download monthly accounting data"))
    assert good == []


def test_vacuity_reported_in_stats():
    from askfaro_progressive_context.build.ir import SourceNode, SourceTree

    kids = [SourceNode(id="k1", title="thing", content="x"), SourceNode(id="k2", title="widget", content="y")]
    tree = SourceTree(source_id="t", kind="docs", root=SourceNode(id="root", title="root", children=kids))
    stats: dict = {}
    generate_descriptors(tree, FakeDescriptorModel(), _stats=stats)
    assert "vacuity" in stats and "count" in stats["vacuity"]
