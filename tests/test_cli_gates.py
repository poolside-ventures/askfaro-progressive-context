"""CLI CI gates: --max-collision and --min-fidelity exit codes (A2/A3)."""

from askfaro_progressive_context.cli import main

FIXT = "tests/fixtures/skills"


def _build(tmp_path, *extra):
    return main(["build", FIXT, "--kind", "skills", "--budgets", "4k", "--fake",
                 "--out", str(tmp_path), *extra])


def test_build_succeeds_without_gates(tmp_path):
    assert _build(tmp_path) == 0


def test_max_collision_gate_fails_when_exceeded(tmp_path):
    # any sibling overlap > 0 trips a zero threshold
    assert _build(tmp_path, "--max-collision", "0.0") == 3


def test_max_collision_gate_passes_when_slack(tmp_path):
    assert _build(tmp_path, "--max-collision", "1.0") == 0


def test_min_fidelity_gate_fails_when_below(tmp_path):
    assert _build(tmp_path, "--fidelity", "lexical", "--min-fidelity", "5.0") == 3


def test_min_fidelity_gate_passes_when_met(tmp_path):
    assert _build(tmp_path, "--fidelity", "lexical", "--min-fidelity", "1.0") == 0


def test_preset_applies_and_builds(tmp_path):
    assert main(["build", FIXT, "--kind", "skills", "--fake", "--preset", "low-budget",
                 "--out", str(tmp_path)]) == 0


def test_cross_links_flag_builds(tmp_path):
    assert _build(tmp_path, "--cross-links") == 0
