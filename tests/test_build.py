from pathlib import Path

from askfaro_progressive_context import Manifest, Runtime, structural_errors
from askfaro_progressive_context.build import (
    Descriptor,
    FakeDescriptorModel,
    compile_source,
)
from askfaro_progressive_context.build.adapters import get_adapter
from askfaro_progressive_context.build.descriptors import generate_descriptors

FIX = Path(__file__).parent / "fixtures"


def _tree(kind, name):
    path = FIX / name
    return get_adapter(kind).load(path)


def test_compile_produces_valid_manifests_for_each_budget():
    tree = _tree("skills", "skills")
    result = compile_source(tree, FakeDescriptorModel(), [4096, 32768])
    assert set(result.manifests) == {4096, 32768}
    for budget, manifest in result.manifests.items():
        assert structural_errors(manifest) == [], f"budget {budget}: {structural_errors(manifest)}"
        assert manifest["variant"]["budget"] == budget
        assert budget not in manifest["variant"]["siblings"]


def test_compiled_manifest_is_navigable():
    tree = _tree("tools", "tools.json")
    result = compile_source(tree, FakeDescriptorModel(), [4096])
    m = Manifest.from_dict(result.manifests[4096])
    rt = Runtime(m)
    # expanding a namespace branch reveals its tool leaves
    frontier_ids = {e.node_id for e in rt.peek()}
    assert "web-search" in frontier_ids
    revealed = rt.expand("web-search")
    assert any(e.node_id == "web-search-query" for e in revealed)
    ref = rt.expand("web-search-query")
    assert ref == "node://web-search-query"


def test_disclosure_ratio_is_large():
    # The whole point: a tiny baseline manifest exposes a much larger tree.
    tree = _tree("tools", "tools.json")
    result = compile_source(tree, FakeDescriptorModel(), [4096])
    s = result.stats
    assert s["full_tokens"] > s["manifest_tokens"] * 3


def test_costs_roll_up_and_branches_are_zero():
    tree = _tree("skills", "skills")
    result = compile_source(tree, FakeDescriptorModel(), [4096])
    nodes = result.manifests[4096]["nodes"]
    posts = nodes["posts"]
    assert posts["tokens"] == 0  # branch
    assert posts["subtree_tokens"] == sum(
        nodes[c]["subtree_tokens"] for c in posts["children"]
    )


def test_llms_txt_export_is_nonempty():
    tree = _tree("docs", "docs")
    result = compile_source(tree, FakeDescriptorModel(), [4096])
    assert result.llms_txt.startswith("# ")
    assert "node://" in result.llms_txt
    assert "How to read this index" in result.llms_txt  # self-describing for cold agents


def test_manifest_self_describes_protocol():
    # A cold external agent must learn how to navigate from the file itself.
    tree = _tree("skills", "skills")
    manifest = compile_source(tree, FakeDescriptorModel(), [4096]).manifests[4096]
    assert "usage" in manifest
    assert "node://" in manifest["usage"] and "budget" in manifest["usage"]


class _SpyModel(FakeDescriptorModel):
    def __init__(self):
        self.contrast_groups = 0

    def contrast(self, parent_title, siblings):
        self.contrast_groups += 1
        # mark the rewrite so we can prove it was applied
        return [Descriptor(what=d.what, when=f"[contrasted] {d.when}", keywords=d.keywords) for _, d in siblings]


def test_contrastive_pass_runs_on_sibling_groups():
    tree = _tree("skills", "skills")
    spy = _SpyModel()
    descriptors = generate_descriptors(tree, spy)
    assert spy.contrast_groups >= 1  # at least the posts group (2 siblings)
    assert descriptors["draft-post"].when.startswith("[contrasted] ")


def test_contrastive_can_be_disabled():
    tree = _tree("skills", "skills")
    spy = _SpyModel()
    generate_descriptors(tree, spy, contrastive=False)
    assert spy.contrast_groups == 0
