"""Descriptor-fidelity eval (A3): predict-then-verify, the second quality axis.

`navigation-success @ budget` scores the *tree* — can an agent walk descriptors
to the right leaf. Fidelity scores each descriptor *in isolation*: given only
`what`/`when`, could you predict what the node actually contains? A descriptor
that reads well but doesn't let you anticipate the content is a filter that will
mislead a load decision.

This runs at build time, where the verbatim content is still in hand (a manifest
ships only `node://` refs, not content). Two models:

- `LexicalFidelityModel` — deterministic, no network. Scores how *grounded* the
  descriptor is in the content: the fraction of descriptor terms that actually
  occur in the node's content. Catches paraphrase-of-title and hallucinated
  descriptors offline / in CI. A coarse proxy, not a substitute for a real judge.
- `LLMFidelityModel` — real predict-then-verify: the model predicts the content
  from the descriptor, then grades its own prediction against the truth.

Scores are on a 1-5 scale; nodes below `flag_below` (default 3.0) are flagged.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..llm import LLMClient, parse_json_object
from .descriptors import Descriptor
from .distinct import descriptor_tokens, tokenize
from .ir import SourceNode, SourceTree

_MAX_CONTENT_CHARS = 6000


@dataclass
class FidelityScore:
    node_id: str
    score: float  # 1-5
    reason: str = ""


@dataclass
class FidelityReport:
    mean_score: float
    flagged: list[str] = field(default_factory=list)  # node ids below flag_below
    scores: list[FidelityScore] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "mean_score": round(self.mean_score, 3),
            "flagged": list(self.flagged),
            "worst": [
                {"node": s.node_id, "score": round(s.score, 2), "reason": s.reason}
                for s in sorted(self.scores, key=lambda s: s.score)[:10]
            ],
        }


def _actual_content(node: SourceNode) -> str:
    """The truth a descriptor is checked against: a leaf's content, or a branch's
    child titles/hints (a branch has no content of its own)."""
    if node.is_leaf:
        return (node.content or node.hint or node.title or "")[:_MAX_CONTENT_CHARS]
    return " ".join(filter(None, (c.title or c.hint for c in node.children)))


class FidelityModel:
    """Score how well a descriptor predicts its node's content (1-5)."""

    def assess(self, descriptor: Descriptor, actual_content: str) -> FidelityScore:
        raise NotImplementedError


class LexicalFidelityModel(FidelityModel):
    """Deterministic grounding score: fraction of descriptor terms present in the
    content, mapped to 1-5. No model calls."""

    def assess(self, descriptor: Descriptor, actual_content: str) -> FidelityScore:
        desc = descriptor_tokens(descriptor)
        content = tokenize(actual_content)
        if not desc:
            return FidelityScore("", 1.0, "empty descriptor")
        grounded = len(desc & content) / len(desc)
        score = 1.0 + 4.0 * grounded
        reason = "" if grounded >= 0.5 else f"only {grounded:.0%} of descriptor terms occur in the content"
        return FidelityScore("", round(score, 2), reason)


class LLMFidelityModel(FidelityModel):
    """Real predict-then-verify. The model predicts the content from the
    descriptor, then grades the prediction against the truth."""

    _JSON = {"type": "json_object"}
    _SYS = (
        "You audit navigation index entries. Given only an entry's `what`/`when`, "
        "predict what the underlying content contains, then compare your prediction "
        "to the actual content. Score 1-5 how well the entry let you anticipate the "
        "content (5 = fully predictable, 1 = misleading or generic). Reply strict JSON only."
    )

    def __init__(self, client: LLMClient):
        self.client = client

    def assess(self, descriptor: Descriptor, actual_content: str) -> FidelityScore:
        prompt = (
            f"Entry what: {descriptor.what}\nEntry when: {descriptor.when}\n\n"
            f"Actual content:\n{actual_content[:_MAX_CONTENT_CHARS]}\n\n"
            'Return {"score": <1-5>, "reason": <string>}.'
        )
        try:
            obj = parse_json_object(self.client.complete(prompt, system=self._SYS, response_format=self._JSON))
            return FidelityScore("", float(obj.get("score", 3.0)), str(obj.get("reason", "")))
        except (ValueError, KeyError):
            return FidelityScore("", 3.0, "unscored (parse failure)")


def score_fidelity(
    tree: SourceTree,
    descriptors: dict[str, Descriptor],
    model: FidelityModel | None = None,
    *,
    flag_below: float = 3.0,
    max_workers: int = 1,
) -> FidelityReport:
    """Score every non-root node's descriptor fidelity against its content."""
    from .descriptors import _run  # reuse the shared thread-pool map

    model = model or LexicalFidelityModel()
    targets = [n for n in tree.root.walk() if n.id != tree.root.id and n.id in descriptors]

    def _score(node: SourceNode) -> FidelityScore:
        s = model.assess(descriptors[node.id], _actual_content(node))
        s.node_id = node.id
        return s

    scores = _run(targets, _score, max_workers)
    mean = sum(s.score for s in scores) / len(scores) if scores else 0.0
    flagged = [s.node_id for s in scores if s.score < flag_below]
    return FidelityReport(mean_score=mean, flagged=flagged, scores=scores)
