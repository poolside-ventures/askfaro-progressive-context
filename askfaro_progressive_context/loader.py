"""Manifest loading + caching — a transport-agnostic, revalidate-don't-expire cache.

A pcx manifest is small, identical for every reader, and changes only when its
source content changes. That makes it an ideal cache target — *but* a naive
time-to-live cache is unsafe here: a manifest is a routing index, so a stale copy
can point an agent at content that has moved or disappeared. The fix is to cache
keyed on the manifest's **identity** and revalidate against it, never to expire
blindly on a clock.

This module gives every consumer that safe pattern by default, while staying
**transport-agnostic** — it knows nothing about HTTP, files, S3, or ETags. You
supply a `Fetcher` that knows how to reach your origin; the loader supplies the
identity bookkeeping, the store, and the guarantee that a changed identity always
wins.

The shape::

    store   = MemoryStore()            # or FileStore("~/.cache/pcx")
    loader  = ManifestLoader(fetch=my_fetch, store=store)
    manifest = loader.load(ManifestKey(source_id="faro-catalog", budget="4k"))

Your `fetch(key, known_identity)` is handed the identity already in cache (or
``None``). It decides:

- nothing changed since `known_identity`  -> ``FetchOutcome.not_modified()``
  (e.g. your HTTP transport sent ``If-None-Match`` and got a 304). The loader
  reuses the cached body — zero parsing, zero transfer.
- there is fresh content                  -> ``FetchOutcome.fresh(identity, body)``
  The loader stores it under `key` and returns it.

The safety property is structural: a `Fetcher` that is too dumb to do conditional
requests and *always* returns fresh content still gets correct invalidation,
because the store is identity-stamped and re-storing the same identity is a
harmless no-op. There is no TTL knob that can serve a stale routing index past an
identity change. If you want to also skip the revalidation round-trip, don't call
`load()` in a hot loop — hold the returned `Manifest` and reload on your own
cadence. `load()` means "give me the current manifest, revalidating."
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Protocol

from .types import Manifest

# An opaque token identifying a manifest's content. Compared for equality only;
# never parsed. A content hash, an ETag, or "v{version}" are all valid.
Identity = str


class LoaderError(RuntimeError):
    """Raised when a transport returns an outcome the loader cannot honor."""


@dataclass(frozen=True)
class ManifestKey:
    """What identifies *which* manifest you want: its source and budget variant.

    A manifest's identity (content hash) is the same across budgets — same
    content, different token budget — so the cache key must include the budget.
    """

    source_id: str
    budget: str | int

    def cache_slug(self) -> str:
        """A filesystem- and dict-safe key for this (source, budget) pair."""
        raw = f"{self.source_id}@{self.budget}"
        safe = re.sub(r"[^A-Za-z0-9._-]", "_", raw)
        # Keep it readable but bounded, and disambiguate collisions from slugging.
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:8]
        return f"{safe[:80]}.{digest}"


@dataclass(frozen=True)
class FetchOutcome:
    """The result of a `Fetcher` call: either nothing changed, or fresh content."""

    not_modified: bool
    identity: Identity | None = None
    manifest: dict[str, Any] | None = None

    @classmethod
    def unchanged(cls) -> "FetchOutcome":
        """The `known_identity` you were handed is still current — reuse the cache."""
        return cls(not_modified=True)

    @classmethod
    def fresh(cls, identity: Identity, manifest: dict[str, Any]) -> "FetchOutcome":
        """New content. `identity` stamps it; pass the raw manifest dict as `manifest`."""
        return cls(not_modified=False, identity=identity, manifest=manifest)


# A transport. Given the key and the identity already cached (or None if nothing
# is cached), return whether it changed and, if so, the fresh body + its identity.
Fetcher = Callable[[ManifestKey, Identity | None], FetchOutcome]

# The async equivalent, for callers whose transport is a coroutine (e.g. an
# httpx.AsyncClient). Used by AsyncManifestLoader.
AsyncFetcher = Callable[[ManifestKey, Identity | None], Awaitable[FetchOutcome]]


def identity_of(manifest: dict[str, Any]) -> Identity:
    """Derive an identity from a raw manifest dict.

    Prefers the build's bottom-up ``source.content_hash``; falls back to a hash of
    the canonical body when absent. A `Fetcher` over a transport with no native
    validator (a plain GET, a file read) can use this to stamp what it fetched.
    """
    src = manifest.get("source")
    if isinstance(src, dict) and src.get("content_hash") is not None:
        return str(src["content_hash"])
    body = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(body).hexdigest()


@dataclass(frozen=True)
class StoredManifest:
    identity: Identity
    manifest: dict[str, Any]


class ManifestStore(Protocol):
    """Persistence for cached manifests, keyed by `ManifestKey`. Implementations
    must round-trip the identity stamp alongside the body."""

    def get(self, key: ManifestKey) -> StoredManifest | None: ...

    def put(self, key: ManifestKey, identity: Identity, manifest: dict[str, Any]) -> None: ...


class MemoryStore:
    """Process-local cache. The right default: trivial, and all a long-running
    process needs (a cold start re-fetches, which is cheap against a 304)."""

    def __init__(self) -> None:
        self._data: dict[str, StoredManifest] = {}

    def get(self, key: ManifestKey) -> StoredManifest | None:
        return self._data.get(key.cache_slug())

    def put(self, key: ManifestKey, identity: Identity, manifest: dict[str, Any]) -> None:
        self._data[key.cache_slug()] = StoredManifest(identity=identity, manifest=manifest)


class FileStore:
    """On-disk cache under a directory. Earns its keep for short-lived processes
    (CLIs, serverless, edge cold starts) that would otherwise re-download the
    manifest on every invocation. Each entry is one JSON file holding the identity
    stamp and the verbatim manifest body."""

    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory).expanduser()

    def _path(self, key: ManifestKey) -> Path:
        return self.directory / f"{key.cache_slug()}.json"

    def get(self, key: ManifestKey) -> StoredManifest | None:
        path = self._path(key)
        try:
            raw = json.loads(path.read_text())
        except (OSError, ValueError):
            # Missing or corrupt cache file is a miss, never an error — the loader
            # will refetch and overwrite it.
            return None
        identity, manifest = raw.get("identity"), raw.get("manifest")
        if not isinstance(identity, str) or not isinstance(manifest, dict):
            return None
        return StoredManifest(identity=identity, manifest=manifest)

    def put(self, key: ManifestKey, identity: Identity, manifest: dict[str, Any]) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self._path(key)
        body = json.dumps({"identity": identity, "manifest": manifest}, separators=(",", ":"))
        # Write-rename so a concurrent reader never sees a half-written file.
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(body)
        tmp.replace(path)


def _resolve_outcome(
    store: ManifestStore, key: ManifestKey, cached: StoredManifest | None, outcome: FetchOutcome
) -> dict[str, Any]:
    """Apply a fetch outcome against the cache: reuse on not_modified, else store
    and return the fresh body. Shared by the sync and async loaders."""
    if outcome.not_modified:
        if cached is None:
            raise LoaderError(
                f"fetcher reported not_modified for {key!r} but nothing is cached; "
                "a not_modified outcome is only valid when a known identity was supplied"
            )
        return cached.manifest

    if outcome.identity is None or outcome.manifest is None:
        raise LoaderError(f"fetcher returned fresh content for {key!r} without an identity and body")

    store.put(key, outcome.identity, outcome.manifest)
    return outcome.manifest


class ManifestLoader:
    """Ties a `Fetcher` to a `ManifestStore` with identity revalidation.

    `load()` returns a parsed `Manifest`; `load_dict()` returns the raw dict if you
    only need to forward it. The cache is keyed on identity, so it can never serve
    a stale routing index across a content change.
    """

    def __init__(self, fetch: Fetcher, store: ManifestStore | None = None) -> None:
        self.fetch = fetch
        self.store = store if store is not None else MemoryStore()

    def load_dict(self, key: ManifestKey) -> dict[str, Any]:
        cached = self.store.get(key)
        known = cached.identity if cached is not None else None
        outcome = self.fetch(key, known)
        return _resolve_outcome(self.store, key, cached, outcome)

    def load(self, key: ManifestKey) -> Manifest:
        return Manifest.from_dict(self.load_dict(key))


class AsyncManifestLoader:
    """`ManifestLoader` for an async transport — same identity-revalidation
    contract, but `fetch` is a coroutine (e.g. over an httpx.AsyncClient). The
    store stays synchronous: its get/put are fast local file or dict operations.
    """

    def __init__(self, fetch: AsyncFetcher, store: ManifestStore | None = None) -> None:
        self.fetch = fetch
        self.store = store if store is not None else MemoryStore()

    async def load_dict(self, key: ManifestKey) -> dict[str, Any]:
        cached = self.store.get(key)
        known = cached.identity if cached is not None else None
        outcome = await self.fetch(key, known)
        return _resolve_outcome(self.store, key, cached, outcome)

    async def load(self, key: ManifestKey) -> Manifest:
        return Manifest.from_dict(await self.load_dict(key))
