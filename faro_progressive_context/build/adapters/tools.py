"""tools adapter — a JSON file of tool/function schemas.

Accepts an OpenAI-style list (`[{name, description, parameters}, ...]`), a
`{"tools": [...]}` wrapper, or a `{name: schema}` mapping. Each tool becomes a
leaf whose verbatim content is its full schema; the existing `description`
becomes a descriptor hint. Tools are grouped into tier-1 branches by namespace
(the part before the first `.`/`/`/`:`/`__` in the name) when present.

This is the proven progressive-tool-disclosure pattern: a tiny name+purpose
manifest up front, the full schema fetched on expand.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from ..ir import SourceNode, SourceTree
from .base import register_adapter, slugify

_NS = re.compile(r"[./:]|__")


def _normalize(raw) -> list[dict]:
    if isinstance(raw, dict) and "tools" in raw:
        raw = raw["tools"]
    if isinstance(raw, dict):
        out = []
        for name, schema in raw.items():
            entry = dict(schema) if isinstance(schema, dict) else {"schema": schema}
            entry.setdefault("name", name)
            out.append(entry)
        return out
    return list(raw)


def _name_of(tool: dict) -> str:
    return tool.get("name") or tool.get("function", {}).get("name") or "tool"


def _description_of(tool: dict) -> str | None:
    return tool.get("description") or tool.get("function", {}).get("description")


class _ToolsAdapter:
    kind = "tools"

    def load(self, path: Path, *, source_id: str | None = None) -> SourceTree:
        tools = _normalize(json.loads(Path(path).read_text()))
        sid = source_id or Path(path).stem

        groups: dict[str, list[SourceNode]] = {}
        for tool in tools:
            name = _name_of(tool)
            ns_match = _NS.split(name, 1)
            ns = ns_match[0] if len(ns_match) > 1 else ""
            leaf = SourceNode(
                id=slugify(name),
                title=name,
                content=json.dumps(tool, indent=2, sort_keys=True),
                format="json",
                hint=_description_of(tool),
                keywords=[t for t in _NS.split(name) if t],
            )
            groups.setdefault(ns, []).append(leaf)

        root = SourceNode(id="r", title=f"{sid} tools", hint="Callable tools and their schemas.")
        if len(groups) == 1 and "" in groups:
            root.children = groups[""]
        else:
            for ns, leaves in sorted(groups.items()):
                if ns == "":
                    root.children.extend(leaves)
                    continue
                root.children.append(
                    SourceNode(id=slugify(ns), title=ns, hint=f"Tools in the {ns} namespace.", children=leaves)
                )
        return SourceTree(source_id=sid, kind=self.kind, root=root)


ToolsAdapter = register_adapter(_ToolsAdapter())
