from pathlib import Path

from faro_progressive_context.build.adapters import get_adapter

FIX = Path(__file__).parent / "fixtures"


def _ids(tree):
    return {n.id for n in tree.root.walk()}


def test_tools_groups_by_namespace():
    tree = get_adapter("tools").load(FIX / "tools.json")
    # web-search.* and calendar.* become branches; email.send is a lone ns too
    branch_titles = {n.title for n in tree.root.children if n.is_branch}
    assert "web-search" in branch_titles
    assert "calendar" in branch_titles
    # leaf content is the verbatim schema (json), hint is the description
    q = next(n for n in tree.root.walk() if n.id == "web-search-query")
    assert q.is_leaf and q.format == "json" and "ranked result" in (q.hint or "")


def test_memory_groups_by_type_and_skips_index():
    tree = get_adapter("memory").load(FIX / "memory")
    branch_titles = {n.title for n in tree.root.children if n.is_branch}
    assert {"user", "project"} <= branch_titles
    assert "likes-tea" in _ids(tree)


def test_docs_mirrors_directory_tree():
    tree = get_adapter("docs").load(FIX / "docs")
    branch_titles = {n.title for n in tree.root.children if n.is_branch}
    assert "Guide" in branch_titles and "Reference" in branch_titles
    # H1 becomes the title
    gs = next(n for n in tree.root.walk() if n.id == "getting-started")
    assert gs.title == "Getting started"


def test_skills_groups_by_category_with_when_hint():
    tree = get_adapter("skills").load(FIX / "skills")
    branch_titles = {n.title for n in tree.root.children if n.is_branch}
    assert {"posts", "research"} <= branch_titles
    draft = next(n for n in tree.root.walk() if n.id == "draft-post")
    assert "When to use" in (draft.hint or "")
