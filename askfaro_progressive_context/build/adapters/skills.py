"""skills adapter — a directory of skills, one markdown file per skill.

Each skill file carries frontmatter (`name`, `description`, and optionally
`when`/`when_to_use` and `category`); the body is the verbatim skill content.
Skills are grouped into tier-1 branches by `category` when present. This is a
generic skills layout — a host-side shim maps your skill source
into it without this package importing the host app.

Skill *selection* is exactly the agent-navigated case: a name+purpose+when
manifest up front, the full skill body fetched on expand.
"""

from __future__ import annotations

from pathlib import Path

from .._frontmatter import split_frontmatter
from ..ir import SourceNode, SourceTree
from .base import register_adapter, slugify


class _SkillsAdapter:
    kind = "skills"

    def load(self, path: Path, *, source_id: str | None = None) -> SourceTree:
        root_dir = Path(path)
        sid = source_id or root_dir.name

        groups: dict[str, list[SourceNode]] = {}
        for md in sorted(root_dir.rglob("*.md")):
            fm, body = split_frontmatter(md.read_text())
            name = fm.get("name") or md.stem
            when_hint = fm.get("when") or fm.get("when_to_use")
            hint = fm.get("description")
            if when_hint:
                hint = f"{hint or ''}\nWhen to use: {when_hint}".strip()
            category = fm.get("category", "")
            leaf = SourceNode(
                id=slugify(name),
                title=name,
                content=body.strip(),
                hint=hint,
                keywords=fm.get("keywords", []) if isinstance(fm.get("keywords"), list) else [],
            )
            groups.setdefault(category, []).append(leaf)

        root = SourceNode(id="r", title=f"{sid} skills", hint="Reusable skills for performing tasks.")
        if len(groups) <= 1:
            for leaves in groups.values():
                root.children.extend(leaves)
        else:
            for category, leaves in sorted(groups.items()):
                if not category:
                    root.children.extend(leaves)
                    continue
                root.children.append(
                    SourceNode(id=slugify(category), title=category, hint=f"{category} skills.", children=leaves)
                )
        return SourceTree(source_id=sid, kind=self.kind, root=root)


SkillsAdapter = register_adapter(_SkillsAdapter())
