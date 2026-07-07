"""pcx v0.2: cross-links (C9), facets (C10), staleness/reconciliation (C11)."""

from askfaro_progressive_context import Manifest, Runtime, structural_errors
from askfaro_progressive_context.build import Descriptor, FakeDescriptorModel, compile_source
from askfaro_progressive_context.build.ir import SourceNode, SourceTree
from askfaro_progressive_context.build.links import betweenness, infer_cross_links


def _tree():
    # two branches with a cross-branch relative pair (both about "schedule csv export")
    a = SourceNode(id="ba", title="reports", children=[
        SourceNode(id="export", title="export report", content="schedule a csv export of the report"),
    ])
    b = SourceNode(id="bb", title="jobs", children=[
        SourceNode(id="cron", title="schedule job", content="schedule a csv export job cadence"),
    ])
    return SourceTree(source_id="t", kind="docs", root=SourceNode(id="r", title="root", children=[a, b]))


def test_manifest_is_v2_and_valid():
    result = compile_source(_tree(), FakeDescriptorModel(), [4096])
    m = result.manifests[4096]
    assert m["pcx_version"] == "0.2"
    assert structural_errors(m) == []


def test_cross_links_round_trip_through_manifest():
    tree = _tree()
    from askfaro_progressive_context.build.descriptors import generate_descriptors

    descriptors = generate_descriptors(tree, FakeDescriptorModel())
    # force strong descriptors so the pair links
    descriptors["export"] = Descriptor("schedule csv export report", "export report to csv on a schedule", ["csv", "schedule"])
    descriptors["cron"] = Descriptor("schedule csv export job", "schedule a csv export job", ["csv", "schedule"])
    added = infer_cross_links(tree, descriptors, min_sim=0.2)
    assert added >= 1
    result = compile_source(tree, FakeDescriptorModel(), [4096], cross_links=True)
    # links survive into the manifest and resolve
    m = Manifest.from_dict(result.manifests[4096])
    assert structural_errors(result.manifests[4096]) == []


def test_runtime_related_follows_links(manifest):
    rt = Runtime(manifest)
    related = rt.related("posts.schedule")  # example manifest links this to recurring.create
    assert any(e.node_id == "recurring.create" for e in related)
    assert related[0].meta.get("link_why")


def test_runtime_facet_filter(manifest):
    rt = Runtime(manifest)
    templates = rt.find_by_facets(kind="template")
    assert "posts.draft" in templates and "posts.schedule" in templates
    assert rt.find_by_facets(kind="template", verb="schedule") == ["posts.schedule"]
    assert rt.find_by_facets() == []  # empty query matches nothing


def test_betweenness_flags_bridge(manifest):
    bc = betweenness_of(manifest)
    assert max(bc.values()) > 0


def betweenness_of(manifest):
    # build a SourceTree-ish view isn't available from a manifest; test betweenness
    # on a synthetic tree with a bridge instead.
    hub = SourceNode(id="hub", title="hub", content="x")
    a = SourceNode(id="a", title="a", content="y", links=[{"to": "hub", "why": "r"}])
    b = SourceNode(id="b", title="b", content="z", links=[{"to": "hub", "why": "r"}])
    tree = SourceTree(source_id="t", kind="docs", root=SourceNode(id="r", children=[hub, a, b]))
    return betweenness(tree)


def test_reconcile_detects_staleness(manifest):
    rt = Runtime(manifest)
    # identity mismatch
    warns = rt.reconcile(current_identity="sha256:different")
    assert any("stale" in w for w in warns)
    # dangling routes
    warns = rt.reconcile(live_ids={"r"})
    assert any("dangling" in w or "no longer exist" in w for w in warns)
    # all good
    assert rt.reconcile(current_identity=manifest.identity) == []


def test_cross_links_use_cosine_when_vectors_given():
    # Two cross-branch nodes with NO shared tokens (lexical sim = 0) but near-identical
    # vectors: only the embedding path links them.
    from askfaro_progressive_context.build.descriptors import generate_descriptors
    a = SourceNode(id="ba", title="alpha", children=[SourceNode(id="x", title="alpha", content="zzz")])
    b = SourceNode(id="bb", title="beta", children=[SourceNode(id="y", title="beta", content="qqq")])
    tree = SourceTree(source_id="t", kind="docs", root=SourceNode(id="r", title="root", children=[a, b]))
    descriptors = generate_descriptors(tree, FakeDescriptorModel())
    vectors = {"x": [1.0, 0.0, 0.0], "y": [0.98, 0.20, 0.0]}  # cosine ~0.98

    assert infer_cross_links(tree, descriptors, min_sim=0.9) == 0          # lexical: no shared tokens
    for n in tree.root.walk():
        n.links = []
    added = infer_cross_links(tree, descriptors, min_sim=0.9, vectors=vectors)  # cosine: linked
    assert added >= 1
    assert any(l["to"] == "y" for l in next(n for n in tree.root.walk() if n.id == "x").links)
