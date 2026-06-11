"""docs adapter — a directory tree of markdown.

Mirrors the filesystem: directories become branches, `.md`/`.mdx` files become
leaves. Titles come from the first H1 if present, else the filename. The native
hierarchy is used as-is (no clustering).
"""

from __future__ import annotations

import re
from pathlib import Path

from .._frontmatter import split_frontmatter
from ..ir import SourceNode, SourceTree
from .base import register_adapter, slugify

_H1 = re.compile(r"^#\s+(.+)$", re.MULTILINE)
_DOC_EXT = {".md", ".mdx", ".markdown"}


def _title_of(body: str, fallback: str) -> str:
    m = _H1.search(body)
    return m.group(1).strip() if m else fallback


def _humanize(name: str) -> str:
    return name.replace("-", " ").replace("_", " ").strip().title()


class _DocsAdapter:
    kind = "docs"

    def _file_node(self, file: Path) -> SourceNode:
        fm, body = split_frontmatter(file.read_text())
        title = fm.get("title") or _title_of(body, _humanize(file.stem))
        return SourceNode(
            id=slugify(file.stem),
            title=title,
            content=body.strip(),
            hint=fm.get("description"),
        )

    def _dir_node(self, directory: Path, node_id: str, title: str) -> SourceNode:
        node = SourceNode(id=node_id, title=title, hint=f"Docs under {directory.name}/.")
        for child in sorted(directory.iterdir(), key=lambda p: (p.is_file(), p.name)):
            if child.is_dir():
                sub = self._dir_node(child, slugify(child.name), _humanize(child.name))
                if sub.children:
                    node.children.append(sub)
            elif child.suffix.lower() in _DOC_EXT:
                node.children.append(self._file_node(child))
        return node

    def load(self, path: Path, *, source_id: str | None = None) -> SourceTree:
        root_dir = Path(path)
        sid = source_id or root_dir.name
        root = self._dir_node(root_dir, "r", sid)
        return SourceTree(source_id=sid, kind=self.kind, root=root)


DocsAdapter = register_adapter(_DocsAdapter())
