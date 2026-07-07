"""Compiler orchestration: SourceTree -> descriptors -> costs -> manifests."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..tokenizer import Tokenizer, heuristic_tokenizer
from .cost import annotate
from .descriptors import DescriptorModel, cache_from_manifest, generate_descriptors
from .emit import build_manifest, to_llms_txt
from .fidelity import FidelityModel, score_fidelity
from .ir import SourceTree
from .lint import tree_shape_warnings
from .links import betweenness, infer_cross_links


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
    fidelity_model: FidelityModel | None = None,
    cross_links: bool = False,
    cross_link_vectors: dict[str, list[float]] | None = None,
    cross_link_min_sim: float = 0.35,
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
    links_added = (
        infer_cross_links(tree, descriptors, min_sim=cross_link_min_sim, vectors=cross_link_vectors)
        if cross_links
        else 0
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
    stats["warnings"] = tree_shape_warnings(tree, descriptors)
    if cross_links:
        stats["cross_links"] = links_added
        bc = betweenness(tree)
        stats["bridge_nodes"] = [
            {"node": nid, "betweenness": bc[nid]}
            for nid in sorted(bc, key=lambda n: -bc[n])[:5]
            if bc[nid] > 0
        ]
    if fidelity_model is not None:
        stats["fidelity"] = score_fidelity(tree, descriptors, fidelity_model, max_workers=max_workers).to_dict()
    return BuildResult(source_id=tree.source_id, manifests=manifests, llms_txt=to_llms_txt(tree, descriptors), stats=stats)
