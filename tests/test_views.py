"""Multi-level frontier views (shortest first) + local leaf resolution."""

import pytest

from faro_progressive_context import Runtime, dict_resolver


def test_shorter_levels_cost_fewer_tokens(manifest):
    rt = Runtime(manifest)
    title = rt.frontier_tokens("title")
    brief = rt.frontier_tokens("brief")
    full = rt.frontier_tokens("full")
    # title is the shortest first view; each level adds signal and tokens
    assert title < brief < full


def test_title_view_is_substantially_cheaper(manifest):
    rt = Runtime(manifest)
    # the whole point: the cheapest first view is a large cut over the full one
    assert rt.frontier_tokens("title") < rt.frontier_tokens("full") / 2


def test_frontier_view_text_includes_ids(manifest):
    rt = Runtime(manifest)
    text = rt.frontier_view("title")
    assert "posts" in text and "\t" in text


def test_bad_level_raises(manifest):
    with pytest.raises(ValueError):
        Runtime(manifest).frontier_tokens("enormous")


def test_resolver_returns_resident_content(manifest):
    leaves = {"posts.draft": "VERBATIM DRAFT GUIDE"}
    rt = Runtime(manifest, resolver=dict_resolver(leaves))
    rt.expand("posts")
    assert rt.expand("posts.draft") == "VERBATIM DRAFT GUIDE"


def test_resolver_missing_leaf_is_clear(manifest):
    rt = Runtime(manifest, resolver=dict_resolver({}))
    rt.expand("posts")
    with pytest.raises(KeyError, match="resident content"):
        rt.expand("posts.draft")


def test_without_resolver_returns_ref(manifest):
    rt = Runtime(manifest)
    rt.expand("posts")
    assert rt.expand("posts.draft") == "node://posts.draft"
