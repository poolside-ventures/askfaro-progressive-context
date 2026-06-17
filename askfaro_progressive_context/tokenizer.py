"""Token counting for cost annotation.

Default is a dependency-free char-based heuristic (the same ratio the runtime
uses to estimate descriptor cost). Install the `tokenize` extra for an exact
tiktoken-based count against a named encoding.
"""

from __future__ import annotations

from typing import Callable

from .types import estimate_tokens

Tokenizer = Callable[[str], int]


def heuristic_tokenizer() -> Tokenizer:
    return estimate_tokens


def tiktoken_tokenizer(encoding: str = "o200k_base") -> Tokenizer:
    import tiktoken  # type: ignore

    enc = tiktoken.get_encoding(encoding)
    return lambda text: len(enc.encode(text))


def make_tokenizer(encoding: str | None = None) -> Tokenizer:
    """Return a tokenizer. With an encoding name, try tiktoken and fall back
    to the heuristic if the extra isn't installed."""
    if not encoding:
        return heuristic_tokenizer()
    try:
        return tiktoken_tokenizer(encoding)
    except ImportError:
        return heuristic_tokenizer()
