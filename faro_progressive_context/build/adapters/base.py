from __future__ import annotations

from pathlib import Path
from typing import Protocol

from ..ir import SourceTree

_REGISTRY: dict[str, "Adapter"] = {}


class Adapter(Protocol):
    kind: str

    def load(self, path: Path, *, source_id: str | None = None) -> SourceTree:
        ...


def register_adapter(adapter: "Adapter") -> "Adapter":
    _REGISTRY[adapter.kind] = adapter
    return adapter


def get_adapter(kind: str) -> "Adapter":
    if kind not in _REGISTRY:
        raise KeyError(f"unknown adapter kind {kind!r}; known: {sorted(_REGISTRY)}")
    return _REGISTRY[kind]


def slugify(text: str) -> str:
    out = "".join(c if c.isalnum() else "-" for c in text.lower()).strip("-")
    while "--" in out:
        out = out.replace("--", "-")
    return out or "node"
