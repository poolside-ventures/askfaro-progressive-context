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
    # leaf content is spliced, now wrapped in an ancestor context envelope (default on)
    out = s.open("posts.draft")
    assert "DRAFT GUIDE" in out
    assert "[context]" in out and "Posts" in out  # breadcrumb of the parent branch


def test_leaf_context_can_be_disabled(manifest):
    cfg = ModeConfig(view_level="brief", inline_small_leaves=False, leaf_context=False)
    s = NavSession(manifest, config=cfg, resolver=dict_resolver({"posts.draft": "DRAFT GUIDE"}))
    s.open("posts")
    assert s.open("posts.draft") == "DRAFT GUIDE"  # bare content, no envelope


def test_leaf_context_envelope_not_recharged(manifest):
    s = NavSession(manifest, mode="local", resolver=dict_resolver({"posts.draft": "DRAFT GUIDE"}))
    s.open("posts")
    before = s.shown_tokens
    s.open("posts.draft")
    after_first = s.shown_tokens
    # opening again is idempotent and the envelope adds no extra charge
    s.open("posts.draft")
    assert s.shown_tokens == after_first
    assert after_first > before  # the leaf splice itself was charged


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
