"""Navigators — the policy that, given the frontier + a query + remaining
budget, decides which node to expand next.

The eval harness scores a *navigator over a manifest*. Two implementations:

- `KeywordNavigator` — deterministic lexical baseline. Needs no model, so the
  harness (and CI) runs offline. It is intentionally simple: it measures how
  navigable the descriptors are to a dumb reader, which is a useful floor.
- `LLMNavigator` — wraps a `complete(prompt) -> str` callable so a real model
  can drive navigation. The harness stays model-agnostic.
"""

from __future__ import annotations

import json
import re
from typing import Callable, Protocol

from .runtime import FrontierEntry

_WORD = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> set[str]:
    return set(_WORD.findall(text.lower()))


class Navigator(Protocol):
    def choose(self, query: str, frontier: list[FrontierEntry], budget_remaining: int) -> str | None:
        """Return the node_id to expand next, or None to stop."""
        ...


class KeywordNavigator:
    """Pick the unexpanded frontier node whose descriptor best lexically
    overlaps the query. Ties broken toward leaves (commit over re-expand)."""

    def __init__(self, stopwords: set[str] | None = None):
        self.stop = stopwords or {
            "the", "a", "an", "to", "of", "for", "and", "or", "is", "in", "on",
            "this", "that", "should", "when", "how", "do", "i", "my", "with",
        }

    def _score(self, q: set[str], entry: FrontierEntry) -> int:
        text = " ".join(filter(None, [entry.title, entry.what, entry.when]))
        return len((q - self.stop) & _tokens(text))

    def choose(self, query: str, frontier: list[FrontierEntry], budget_remaining: int) -> str | None:
        q = _tokens(query)
        candidates = [e for e in frontier if not e.expanded and e.expand_cost <= budget_remaining]
        if not candidates:
            return None
        # Highest overlap; prefer leaves, then cheaper expansions, for stability.
        best = max(candidates, key=lambda e: (self._score(q, e), e.is_leaf, -e.expand_cost))
        if self._score(q, best) == 0:
            return None
        return best.node_id


class LLMNavigator:
    """Drive navigation with a real model via a `complete(prompt) -> str`
    callable that returns a node_id (or 'STOP'). Model-agnostic by design."""

    PROMPT = (
        "You are navigating a tiered knowledge index to answer a query. "
        "Pick the ONE option most likely to lead to the answer, or STOP if none fit.\n\n"
        "Query: {query}\nBudget remaining: {budget} tokens\n\nOptions:\n{options}\n\n"
        "Reply with only the id (or STOP)."
    )

    def __init__(self, complete: Callable[[str], str]):
        self.complete = complete

    def choose(self, query: str, frontier: list[FrontierEntry], budget_remaining: int) -> str | None:
        options = [e for e in frontier if not e.expanded and e.expand_cost <= budget_remaining]
        if not options:
            return None
        lines = [
            f"- id={e.node_id} | {e.what} | relevant when: {e.when} | cost={e.expand_cost}"
            for e in options
        ]
        prompt = self.PROMPT.format(query=query, budget=budget_remaining, options="\n".join(lines))
        raw = self.complete(prompt).strip()
        if raw.upper().startswith("STOP"):
            return None
        choice = raw.splitlines()[0].strip().strip("`\"' ")
        choice = choice.replace("id=", "")
        valid = {e.node_id for e in options}
        return choice if choice in valid else None

    @staticmethod
    def parse_json_choice(raw: str, valid: set[str]) -> str | None:  # convenience for JSON-mode models
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            return None
        cid = obj.get("id") if isinstance(obj, dict) else None
        return cid if cid in valid else None
