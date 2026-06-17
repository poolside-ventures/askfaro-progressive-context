"""NavSession — mode-aware index/look/open navigation policy."""

import pytest

from askfaro_progressive_context import ModeConfig, NavSession, dict_resolver


def test_local_defaults_to_brief(manifest):
    s = NavSession(manifest, mode="local")
    assert s.cfg.view_level == "brief"
    # brief frontier is cheaper than full (omits `when`)
    assert s.rt.frontier_tokens("brief") < s.rt.frontier_tokens("full")
    assert "posts" in s.index()


def test_remote_defaults_to_full(manifest):
    s = NavSession(manifest, mode="remote")
    assert s.cfg.view_level == "full"


def test_open_branch_then_leaf(manifest):
    s = NavSession(manifest, mode="local", resolver=dict_resolver({"posts.draft": "DRAFT GUIDE"}))
    entries = s.open("posts")
    assert any(e.node_id == "posts.draft" for e in entries)
    assert s.open("posts.draft") == "DRAFT GUIDE"


def test_look_escalates_to_full_and_charges(manifest):
    s = NavSession(manifest, mode="local")
    before = s.shown_tokens
    out = s.look(["posts", "research"])
    assert "when:" in out  # full descriptor exposes the `when`
    assert s.shown_tokens > before  # escalation charged the delta


def test_remote_inlines_small_leaves(manifest):
    cfg = ModeConfig(view_level="full", inline_small_leaves=True, inline_max_tokens=5000)
    s = NavSession(
        manifest,
        config=cfg,
        resolver=dict_resolver({"posts.draft": "DRAFT GUIDE", "posts.schedule": "SCHED GUIDE"}),
    )
    s.open("posts")
    idx = s.index()
    assert "inlined" in idx and "DRAFT GUIDE" in idx


def test_local_does_not_inline(manifest):
    s = NavSession(manifest, mode="local", resolver=dict_resolver({"posts.draft": "X"}))
    s.open("posts")
    assert "inlined" not in s.index()


def test_shown_tokens_grows_on_open(manifest):
    s = NavSession(manifest, mode="local", resolver=dict_resolver({"posts.draft": "x" * 40}))
    s.open("posts")
    before = s.shown_tokens
    s.open("posts.draft")
    assert s.shown_tokens > before


def test_bad_mode_raises(manifest):
    with pytest.raises(ValueError):
        NavSession(manifest, mode="nonsense")
