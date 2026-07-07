"""Tree-shape lints (B7) + regime-awareness (B8)."""

from askfaro_progressive_context.build import Descriptor, FakeDescriptorModel, compile_source
from askfaro_progressive_context.build.ir import SourceNode, SourceTree, flatten_single_child_branches
from askfaro_progressive_context.build.lint import tree_shape_warnings


def _wide_tree(n):
    kids = [SourceNode(id=f"k{i}", title=f"item {i}", content=f"content {i}") for i in range(n)]
    return SourceTree(source_id="t", kind="docs", root=SourceNode(id="root", title="root", children=kids))


def test_warns_on_over_wide_level():
    warns = tree_shape_warnings(_wide_tree(12))
    assert any("basic-level width" in w for w in warns)


def test_warns_on_small_corpus_with_depth():
    inner = SourceNode(id="b", title="branch", children=[SourceNode(id="leaf", title="leaf", content="x")])
    tree = SourceTree(source_id="t", kind="docs", root=SourceNode(id="root", title="root", children=[inner]))
    warns = tree_shape_warnings(tree, min_tree_nodes=50)
    assert any("small corpus" in w for w in warns)


def test_warns_on_multi_concern_branch_what():
    tree = _wide_tree(2)
    descriptors = {
        "root": Descriptor("root", "root", []),
        "b": Descriptor("create and delete and export and import records", "manage", []),
        "k0": Descriptor("a", "a", []),
        "k1": Descriptor("b", "b", []),
    }
    tree.root.children.append(SourceNode(id="b", title="b", content=None, children=[SourceNode(id="c", content="x")]))
    warns = tree_shape_warnings(tree, descriptors)
    assert any("conjunctions" in w or "too much" in w for w in warns)


def test_flatten_collapses_single_child_branch():
    # root -> mid(1 child) -> leaf   collapses to   root -> leaf
    leaf = SourceNode(id="leaf", title="leaf", content="x")
    mid = SourceNode(id="mid", title="mid", children=[leaf])
    root = SourceNode(id="root", title="root", children=[mid])
    flatten_single_child_branches(root)
    assert [c.id for c in root.children] == ["leaf"]


def test_flatten_keeps_multi_child_branches():
    kids = [SourceNode(id="a", content="1"), SourceNode(id="b", content="2")]
    mid = SourceNode(id="mid", title="mid", children=kids)
    root = SourceNode(id="root", children=[mid])
    flatten_single_child_branches(root)
    # mid has 2 children, so it stays; only its own single-parent link isn't collapsed away
    assert root.children[0].id == "mid"


def test_compiler_surfaces_warnings():
    result = compile_source(_wide_tree(12), FakeDescriptorModel(), [4096])
    assert "warnings" in result.stats
    assert any("basic-level width" in w for w in result.stats["warnings"])
