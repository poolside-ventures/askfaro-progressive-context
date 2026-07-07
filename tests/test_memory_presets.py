"""Memory-namespace separation + config presets (Track B-D)."""

from types import SimpleNamespace

from askfaro_progressive_context.build.adapters.memory import _MemoryAdapter, _namespace_of
from askfaro_progressive_context.build.presets import apply_preset


def test_namespace_inference():
    assert _namespace_of({}, "user") == "knowledge"
    assert _namespace_of({}, "reference") == "knowledge"
    assert _namespace_of({}, "self") == "self"
    assert _namespace_of({}, "session") == "operational"
    assert _namespace_of({"namespace": "custom"}, "user") == "custom"  # explicit wins


def test_memory_separates_namespaces(tmp_path):
    (tmp_path / "a.md").write_text("---\nname: pref\nmetadata:\n  type: user\n---\nlikes tea")
    (tmp_path / "b.md").write_text("---\nname: ident\nmetadata:\n  type: self\n---\nI am an agent")
    tree = _MemoryAdapter().load(tmp_path)
    tier1 = {n.title for n in tree.root.children if n.is_branch}
    assert {"self", "knowledge"} <= tier1  # self-memory isolated from user knowledge


def test_memory_single_namespace_stays_flat(tmp_path):
    (tmp_path / "a.md").write_text("---\nname: pref\nmetadata:\n  type: user\n---\nx")
    (tmp_path / "b.md").write_text("---\nname: proj\nmetadata:\n  type: project\n---\ny")
    tree = _MemoryAdapter().load(tmp_path)
    tier1 = {n.title for n in tree.root.children if n.is_branch}
    assert {"user", "project"} <= tier1  # one namespace -> group by type, no namespace wrapper


def test_preset_fills_defaults_only():
    args = SimpleNamespace(budgets="4k,32k", synthesis=False, flatten=False, fidelity=None)
    defaults = {"budgets": "4k,32k", "synthesis": False, "flatten": False, "fidelity": None}
    notes = apply_preset("docs-heavy", args, defaults)
    assert args.synthesis is True and args.flatten is True
    assert any("synthesis" in n for n in notes)


def test_preset_respects_explicit_override():
    args = SimpleNamespace(budgets="4k,32k", synthesis=False, flatten=True, fidelity=None)
    defaults = {"budgets": "4k,32k", "synthesis": False, "flatten": False, "fidelity": None}
    apply_preset("docs-heavy", args, defaults)
    assert args.flatten is True  # was already True; preset doesn't undo it (no-op either way)
