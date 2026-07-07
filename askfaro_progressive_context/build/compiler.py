"""Compiler orchestration: SourceTree -> descriptors -> costs -> manifests."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..tokenizer import Tokenizer, heuristic_tokenizer
from .cost import annotate
from .descriptors import DescriptorModel, cache_from_manifest, generate_descriptors
from .emit import build_manifest, to_llms_txt
from .ir import SourceTree


@dataclass
class BuildResult:
    source_id: str
    manifests: dict[int, dict[str, Any]]  # budget -> manifest dict
    llms_txt: str
    stats: dict[str, Any] = field(default_factory=dict)


def compile_source(
    tree: SourceTree,
    model: DescriptorModel,
    budgets: list[int],
    *,
    tokenizer: Tokenizer | None = None,
    contrastive: bool = True,
    contrast_chunk: int = 8,
    collision_threshold: float = 0.5,
    max_contrast_rounds: int = 2,
    grade_threshold: float = 0.7,
    max_repairs: int = 1,
    max_workers: int = 1,
    prior_manifest: dict | None = None,
    generated_at: str | None = None,
) -> BuildResult:
    tokenizer = tokenizer or heuristic_tokenizer()
    budgets = sorted(set(budgets))

    cache = cache_from_manifest(prior_manifest) if prior_manifest else None
    gen_stats: dict = {}
    descriptors = generate_descriptors(
        tree,
        model,
        contrastive=contrastive,
        contrast_chunk=contrast_chunk,
        collision_threshold=collision_threshold,
        max_contrast_rounds=max_contrast_rounds,
        grade_threshold=grade_threshold,
        max_repairs=max_repairs,
        max_workers=max_workers,
        cache=cache,
        _stats=gen_stats,
    )
    costs = annotate(tree.root, descriptors, tokenizer)

    manifests = {
        b: build_manifest(tree, descriptors, costs, b, siblings=budgets, generated_at=generated_at)
        for b in budgets
    }

    nodes = list(tree.root.walk())
    leaves = [n for n in nodes if n.is_leaf]
    stats = {
        "nodes": len(nodes),
        "leaves": len(leaves),
        "branches": len(nodes) - len(leaves),
        "full_tokens": costs[tree.root.id].subtree_tokens,
        "manifest_tokens": manifests[budgets[0]]["variant"]["manifest_tokens"],
        "regenerated": gen_stats.get("regenerated", len(nodes)),
        "reused": gen_stats.get("reused", 0),
        "collisions": gen_stats.get("collisions", {}),
        "max_sibling_similarity": gen_stats.get("collisions", {}).get("max_similarity", 0.0),
    }
    return BuildResult(source_id=tree.source_id, manifests=manifests, llms_txt=to_llms_txt(tree, descriptors), stats=stats)
