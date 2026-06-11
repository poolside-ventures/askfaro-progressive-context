"""Manifest validation.

Two layers:
- `structural_errors` — pure-stdlib checks of the invariants that matter for
  navigation (every child resolves, branch XOR leaf, descriptors present,
  no cycles). Always available, zero dependencies.
- `schema_errors` — full JSON Schema validation, if the optional `jsonschema`
  extra is installed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_SCHEMA_PATH = Path(__file__).parent / "schema" / "pcx-0.1.schema.json"
_FALLBACK_SCHEMA_PATH = Path(__file__).parent.parent / "schema" / "pcx-0.1.schema.json"


def schema_path() -> Path:
    return _SCHEMA_PATH if _SCHEMA_PATH.exists() else _FALLBACK_SCHEMA_PATH


def structural_errors(manifest: dict[str, Any]) -> list[str]:
    errors: list[str] = []

    if manifest.get("pcx_version") != "0.1":
        errors.append(f"pcx_version must be '0.1', got {manifest.get('pcx_version')!r}")
    if "variant" not in manifest or "budget" not in manifest.get("variant", {}):
        errors.append("variant.budget is required")

    root = manifest.get("root")
    if not isinstance(root, dict):
        errors.append("root must be an object")
        return errors

    nodes: dict[str, Any] = manifest.get("nodes", {})
    root_id = root.get("id", "r")
    known = set(nodes) | {root_id}

    def check_node(nid: str, node: dict[str, Any]) -> None:
        if not node.get("what"):
            errors.append(f"node {nid!r}: missing 'what'")
        if not node.get("when"):
            errors.append(f"node {nid!r}: missing 'when'")
        has_children = "children" in node
        has_payload = "payload" in node
        if has_children == has_payload:
            errors.append(f"node {nid!r}: must have exactly one of children/payload")
        for cid in node.get("children", []) or []:
            if cid not in known:
                errors.append(f"node {nid!r}: child {cid!r} not found in nodes")
        if has_payload and "ref" not in (node.get("payload") or {}):
            errors.append(f"node {nid!r}: payload.ref is required")

    check_node(root_id, root)
    for nid, node in nodes.items():
        if not isinstance(node, dict):
            errors.append(f"node {nid!r}: must be an object")
            continue
        check_node(nid, node)

    errors.extend(_cycle_errors(root_id, root, nodes))
    return errors


def _cycle_errors(root_id: str, root: dict[str, Any], nodes: dict[str, Any]) -> list[str]:
    visiting: set[str] = set()
    done: set[str] = set()
    errors: list[str] = []

    def walk(nid: str, node: dict[str, Any]) -> None:
        if nid in done:
            return
        if nid in visiting:
            errors.append(f"cycle detected at node {nid!r}")
            return
        visiting.add(nid)
        for cid in node.get("children", []) or []:
            child = root if cid == root_id else nodes.get(cid)
            if isinstance(child, dict):
                walk(cid, child)
        visiting.discard(nid)
        done.add(nid)

    walk(root_id, root)
    return errors


def schema_errors(manifest: dict[str, Any]) -> list[str]:
    """Full JSON Schema validation. Requires the `schema` extra (jsonschema)."""
    try:
        import jsonschema  # type: ignore
    except ImportError as exc:  # pragma: no cover - exercised only without extra
        raise RuntimeError(
            "JSON Schema validation requires the 'schema' extra: pip install 'faro-progressive-context[schema]'"
        ) from exc

    schema = json.loads(schema_path().read_text())
    validator = jsonschema.Draft202012Validator(schema)
    return [f"{'/'.join(map(str, e.path)) or '<root>'}: {e.message}" for e in validator.iter_errors(manifest)]


def validate(manifest: dict[str, Any], *, use_schema: bool = False) -> list[str]:
    errors = structural_errors(manifest)
    if use_schema:
        try:
            errors = schema_errors(manifest) + errors
        except RuntimeError as exc:
            errors.append(str(exc))
    return errors
