"""memory adapter — a directory of one-fact markdown files with frontmatter.

Each file is a leaf; `name`/`description` frontmatter become the title/hint and
the body is the verbatim content. Files are grouped by `metadata.type` (e.g.
user / feedback / project / reference).

Memory is not one kind of thing: **user/domain knowledge** optimizes for
retrieval and composition, **operational** memory is ephemeral session state,
and **agent-self** memory optimizes for identity continuity and must be kept out
of the user-facing retrieval index. These want different containers, so when a
store spans more than one such *namespace* the adapter separates them into
tier-1 branches; a single-namespace store (the common case) just groups by type.
Namespace is taken from `metadata.namespace`, else inferred from `type`.
"""

from __future__ import annotations

from pathlib import Path

from .._frontmatter import split_frontmatter
from ..ir import SourceNode, SourceTree
from .base import register_adapter, slugify

# type -> namespace. Anything unmapped is user/domain knowledge (retrievable).
_TYPE_NAMESPACE = {
    "self": "self", "agent": "self", "identity": "self", "persona": "self",
    "operational": "operational", "session": "operational", "scratch": "operational", "task": "operational",
}
_NAMESPACE_HINT = {
    "self": "Agent self-memory (identity/continuity; keep out of the user retrieval index).",
    "operational": "Operational/session memory (ephemeral coordination state).",
    "knowledge": "User & domain knowledge (retrievable, composable).",
}


def _namespace_of(meta: dict, mtype: str) -> str:
    ns = (meta or {}).get("namespace")
    if ns:
        return str(ns)
    return _TYPE_NAMESPACE.get(mtype.lower(), "knowledge")


def _group_by_type(root: SourceNode, by_type: dict[str, list[SourceNode]]) -> None:
    """Attach leaves to `root`, grouped into type sub-branches (untyped inline)."""
    if len({t for t in by_type if t}) <= 1:
        for leaves in by_type.values():
            root.children.extend(leaves)
        return
    for mtype, leaves in sorted(by_type.items()):
        if not mtype:
            root.children.extend(leaves)
        else:
            root.children.append(
                SourceNode(id=slugify(f"{root.id}-{mtype}"), title=mtype, hint=f"{mtype} memories.", children=leaves)
            )


class _MemoryAdapter:
    kind = "memory"

    def load(self, path: Path, *, source_id: str | None = None) -> SourceTree:
        root_dir = Path(path)
        sid = source_id or root_dir.name

        # namespace -> type -> leaves
        groups: dict[str, dict[str, list[SourceNode]]] = {}
        for md in sorted(root_dir.glob("*.md")):
            if md.name.upper() == "MEMORY.md".upper():
                continue  # the index, not a fact
            fm, body = split_frontmatter(md.read_text())
            meta = fm.get("metadata") if isinstance(fm.get("metadata"), dict) else {}
            mtype = (meta or {}).get("type", "")
            name = fm.get("name") or md.stem
            leaf = SourceNode(id=slugify(name), title=name, content=body.strip(), hint=fm.get("description"))
            ns = _namespace_of(meta, mtype)
            groups.setdefault(ns, {}).setdefault(mtype, []).append(leaf)

        root = SourceNode(id="r", title=sid, hint="A memory store of discrete facts.")
        if len(groups) <= 1:
            # single namespace: keep the flat type grouping (the common case)
            for by_type in groups.values():
                _group_by_type(root, by_type)
        else:
            # multiple namespaces: separate them so self-memory stays isolated
            for ns, by_type in sorted(groups.items()):
                ns_branch = SourceNode(
                    id=slugify(ns), title=ns, hint=_NAMESPACE_HINT.get(ns, f"{ns} memories.")
                )
                _group_by_type(ns_branch, by_type)
                root.children.append(ns_branch)
        return SourceTree(source_id=sid, kind=self.kind, root=root)


MemoryAdapter = register_adapter(_MemoryAdapter())
