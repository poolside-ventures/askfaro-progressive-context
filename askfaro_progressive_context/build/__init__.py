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
from .ir import SourceNode, SourceTree

__all__ = [
    "BuildResult",
    "Descriptor",
    "DescriptorModel",
    "FakeDescriptorModel",
    "Grade",
    "LLMDescriptorModel",
    "SourceNode",
    "SourceTree",
    "cache_from_manifest",
    "compile_source",
    "generate_descriptors",
]
