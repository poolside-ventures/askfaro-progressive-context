"""memory adapter — a directory of one-fact markdown files with frontmatter.

Each file is a leaf; `name`/`description` frontmatter become the title/hint and
the body is the verbatim content. Files are grouped into tier-1 branches by
`metadata.type` (e.g. user / feedback / project / reference) when present —
matching a one-fact-per-file memory layout; generic to any such collection.
"""

from __future__ import annotations

from pathlib import Path

from .._frontmatter import split_frontmatter
from ..ir import SourceNode, SourceTree
from .base import register_adapter, slugify


class _MemoryAdapter:
    kind = "memory"

    def load(self, path: Path, *, source_id: str | None = None) -> SourceTree:
        root_dir = Path(path)
        sid = source_id or root_dir.name

        groups: dict[str, list[SourceNode]] = {}
        for md in sorted(root_dir.glob("*.md")):
            if md.name.upper() == "MEMORY.md".upper():
                continue  # the index, not a fact
            fm, body = split_frontmatter(md.read_text())
            meta = fm.get("metadata") if isinstance(fm.get("metadata"), dict) else {}
            mtype = (meta or {}).get("type", "")
            name = fm.get("name") or md.stem
            leaf = SourceNode(
                id=slugify(name),
                title=name,
                content=body.strip(),
                hint=fm.get("description"),
            )
            groups.setdefault(mtype, []).append(leaf)

        root = SourceNode(id="r", title=sid, hint="A memory store of discrete facts.")
        if len(groups) <= 1:
            for leaves in groups.values():
                root.children.extend(leaves)
        else:
            for mtype, leaves in sorted(groups.items()):
                if not mtype:
                    root.children.extend(leaves)
                    continue
                root.children.append(
                    SourceNode(id=slugify(mtype), title=mtype, hint=f"{mtype} memories.", children=leaves)
                )
        return SourceTree(source_id=sid, kind=self.kind, root=root)


MemoryAdapter = register_adapter(_MemoryAdapter())
