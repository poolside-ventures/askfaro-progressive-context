"""Tiny frontmatter reader for markdown sources.

Uses PyYAML if available; otherwise a minimal parser that handles the shapes
our adapters need: top-level `key: value`, inline lists `[a, b]`, and a single
nested mapping block (e.g. a one-fact memory store's `metadata:`). Keeps the core
dependency-free.
"""

from __future__ import annotations

from typing import Any


def split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    block = text[3:end].strip("\n")
    body = text[end + 4 :].lstrip("\n")
    return _parse_yaml(block), body


def _parse_yaml(block: str) -> dict[str, Any]:
    try:
        import yaml  # type: ignore

        data = yaml.safe_load(block)
        return data if isinstance(data, dict) else {}
    except ImportError:
        return _minimal_parse(block)


def _scalar(v: str) -> Any:
    v = v.strip()
    if v.startswith("[") and v.endswith("]"):
        inner = v[1:-1].strip()
        return [x.strip().strip("\"'") for x in inner.split(",")] if inner else []
    return v.strip("\"'")


def _minimal_parse(block: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    parent: str | None = None
    for line in block.splitlines():
        if not line.strip() or line.strip().startswith("#"):
            continue
        indented = line[0] in " \t"
        key, _, val = line.strip().partition(":")
        key = key.strip()
        if indented and parent is not None:
            if not isinstance(out.get(parent), dict):
                out[parent] = {}
            out[parent][key] = _scalar(val)
        elif val.strip() == "":
            out[key] = {}
            parent = key
        else:
            out[key] = _scalar(val)
            parent = None
    return out
