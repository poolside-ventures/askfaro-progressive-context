"""The compiler: source content -> annotated tree -> pcx manifest variants.

Pipeline: an Adapter yields a SourceTree (native structure, verbatim leaves),
the descriptor engine generates what/when/keywords, cost annotation tokenizes
and rolls up subtree costs, and emit writes one manifest per budget variant
plus an llms.txt export.
"""

from .compiler import BuildResult, compile_source
from .descriptors import (
    Descriptor,
    DescriptorModel,
    FakeDescriptorModel,
    Grade,
    LLMDescriptorModel,
    cache_from_manifest,
    generate_descriptors,
)
from .fidelity import (
    FidelityModel,
    FidelityReport,
    FidelityScore,
    LexicalFidelityModel,
    LLMFidelityModel,
    score_fidelity,
)
from .ir import SourceNode, SourceTree

__all__ = [
    "BuildResult",
    "Descriptor",
    "DescriptorModel",
    "FakeDescriptorModel",
    "FidelityModel",
    "FidelityReport",
    "FidelityScore",
    "Grade",
    "LLMDescriptorModel",
    "LexicalFidelityModel",
    "LLMFidelityModel",
    "SourceNode",
    "SourceTree",
    "cache_from_manifest",
    "compile_source",
    "generate_descriptors",
    "score_fidelity",
]
