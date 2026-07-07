"""Descriptor-fidelity eval (A3): grounding score, flagging, compiler wiring."""

from askfaro_progressive_context.build import (
    Descriptor,
    FakeDescriptorModel,
    LexicalFidelityModel,
    compile_source,
    generate_descriptors,
    score_fidelity,
)
from askfaro_progressive_context.build.ir import SourceNode, SourceTree


def _tree():
    kids = [
        SourceNode(id="grounded", title="export csv", content="export the ledger rows to a csv spreadsheet file"),
        SourceNode(id="ungrounded", title="thing", content="quarterly amortization of deferred revenue schedules"),
    ]
    return SourceTree(source_id="t", kind="docs", root=SourceNode(id="root", title="finance", children=kids))


def test_lexical_fidelity_rewards_grounded_descriptors():
    m = LexicalFidelityModel()
    grounded = m.assess(
        Descriptor(what="export csv spreadsheet", when="download ledger rows", keywords=["csv"]),
        "export the ledger rows to a csv spreadsheet file",
    )
    ungrounded = m.assess(
        Descriptor(what="handle miscellaneous stuff", when="various general purposes", keywords=[]),
        "export the ledger rows to a csv spreadsheet file",
    )
    assert grounded.score > ungrounded.score
    assert 1.0 <= ungrounded.score <= 5.0


def test_score_fidelity_flags_low_nodes_and_reports_mean():
    tree = _tree()
    descriptors = {
        "grounded": Descriptor(what="export csv spreadsheet", when="download ledger rows to csv", keywords=["csv"]),
        "ungrounded": Descriptor(what="do things", when="general use", keywords=[]),
        "root": Descriptor(what="finance", when="money", keywords=[]),
    }
    report = score_fidelity(tree, descriptors, LexicalFidelityModel(), flag_below=3.0)
    assert "ungrounded" in report.flagged
    assert "grounded" not in report.flagged
    assert 1.0 <= report.mean_score <= 5.0


def test_compiler_surfaces_fidelity_when_model_given():
    tree = _tree()
    result = compile_source(tree, FakeDescriptorModel(), [4096], fidelity_model=LexicalFidelityModel())
    assert "fidelity" in result.stats
    assert "mean_score" in result.stats["fidelity"]


def test_compiler_skips_fidelity_by_default():
    result = compile_source(_tree(), FakeDescriptorModel(), [4096])
    assert "fidelity" not in result.stats
