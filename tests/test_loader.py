"""Tests for the manifest loader + caching seam."""

from __future__ import annotations

import json

import pytest

from askfaro_progressive_context import (
    FetchOutcome,
    FileStore,
    LoaderError,
    Manifest,
    ManifestKey,
    ManifestLoader,
    MemoryStore,
    identity_of,
)

KEY = ManifestKey(source_id="assistant-skills", budget="4k")


def _bump(manifest: dict, content_hash: str) -> dict:
    """Return a copy of the manifest with a different content identity."""
    out = json.loads(json.dumps(manifest))
    out["source"]["content_hash"] = content_hash
    return out


# --- identity ---------------------------------------------------------------


def test_manifest_identity_from_content_hash(manifest: Manifest):
    assert manifest.identity == "sha256:demo"


def test_identity_of_prefers_content_hash(manifest_dict: dict):
    assert identity_of(manifest_dict) == "sha256:demo"


def test_identity_of_falls_back_to_body_hash(manifest_dict: dict):
    stripped = json.loads(json.dumps(manifest_dict))
    stripped["source"].pop("content_hash")
    ident = identity_of(stripped)
    assert ident.startswith("sha256:")
    # Deterministic: same body, same identity.
    assert ident == identity_of(json.loads(json.dumps(stripped)))


def test_manifest_identity_none_without_hash(manifest_dict: dict):
    stripped = json.loads(json.dumps(manifest_dict))
    stripped["source"].pop("content_hash")
    assert Manifest.from_dict(stripped).identity is None


# --- key slugging -----------------------------------------------------------


def test_cache_slug_is_filesystem_safe_and_stable():
    k = ManifestKey(source_id="faro/catalog:v2", budget="32k")
    slug = k.cache_slug()
    assert "/" not in slug and ":" not in slug
    assert slug == k.cache_slug()  # stable


def test_cache_slug_distinguishes_budgets():
    a = ManifestKey(source_id="cat", budget="4k").cache_slug()
    b = ManifestKey(source_id="cat", budget="32k").cache_slug()
    assert a != b


# --- loader: fresh / cached / revalidation ----------------------------------


def test_first_load_fetches_and_caches(manifest_dict: dict):
    calls: list = []

    def fetch(key, known):
        calls.append(known)
        return FetchOutcome.fresh("sha256:demo", manifest_dict)

    loader = ManifestLoader(fetch=fetch, store=MemoryStore())
    m = loader.load(KEY)
    assert isinstance(m, Manifest)
    assert calls == [None]  # nothing cached on the first call


def test_second_load_passes_known_identity_and_reuses_on_not_modified(manifest_dict: dict):
    seen: list = []

    def fetch(key, known):
        seen.append(known)
        if known == "sha256:demo":
            return FetchOutcome.unchanged()
        return FetchOutcome.fresh("sha256:demo", manifest_dict)

    loader = ManifestLoader(fetch=fetch, store=MemoryStore())
    loader.load(KEY)
    loader.load(KEY)
    # First call had no cache; second was handed the cached identity and 304'd.
    assert seen == [None, "sha256:demo"]


def test_changed_identity_replaces_cache(manifest_dict: dict):
    v2 = _bump(manifest_dict, "sha256:v2")

    def fetch(key, known):
        return FetchOutcome.fresh("sha256:demo", manifest_dict) if known is None else FetchOutcome.fresh("sha256:v2", v2)

    loader = ManifestLoader(fetch=fetch, store=MemoryStore())
    assert loader.load(KEY).identity == "sha256:demo"
    assert loader.load(KEY).identity == "sha256:v2"


def test_dumb_transport_still_invalidates(manifest_dict: dict):
    """A fetcher that ignores known_identity and always returns full content must
    still pick up a content change — the store is identity-stamped."""
    state = {"body": manifest_dict}

    def fetch(key, known):  # never returns not_modified
        body = state["body"]
        return FetchOutcome.fresh(identity_of(body), body)

    store = MemoryStore()
    loader = ManifestLoader(fetch=fetch, store=store)
    assert loader.load(KEY).identity == "sha256:demo"
    state["body"] = _bump(manifest_dict, "sha256:v2")
    assert loader.load(KEY).identity == "sha256:v2"
    assert store.get(KEY).identity == "sha256:v2"


def test_not_modified_without_cache_is_an_error():
    def fetch(key, known):
        return FetchOutcome.unchanged()

    loader = ManifestLoader(fetch=fetch, store=MemoryStore())
    with pytest.raises(LoaderError):
        loader.load(KEY)


def test_fresh_without_body_is_an_error():
    def fetch(key, known):
        return FetchOutcome(not_modified=False, identity="x", manifest=None)

    loader = ManifestLoader(fetch=fetch, store=MemoryStore())
    with pytest.raises(LoaderError):
        loader.load(KEY)


def test_default_store_is_memory(manifest_dict: dict):
    loader = ManifestLoader(fetch=lambda k, known: FetchOutcome.fresh("sha256:demo", manifest_dict))
    assert isinstance(loader.store, MemoryStore)
    loader.load(KEY)  # does not raise


# --- FileStore --------------------------------------------------------------


def test_file_store_round_trips_across_processes(tmp_path, manifest_dict: dict):
    """Simulate two short-lived processes sharing an on-disk cache: the second
    sees the first's cached identity and can 304."""
    fetches: list = []

    def fetch(key, known):
        fetches.append(known)
        if known == "sha256:demo":
            return FetchOutcome.unchanged()
        return FetchOutcome.fresh("sha256:demo", manifest_dict)

    # Process 1: cold disk -> fetch + write.
    ManifestLoader(fetch=fetch, store=FileStore(tmp_path)).load(KEY)
    # Process 2: fresh loader + store, warm disk -> reads cached identity, 304s.
    m = ManifestLoader(fetch=fetch, store=FileStore(tmp_path)).load(KEY)

    assert isinstance(m, Manifest)
    assert fetches == [None, "sha256:demo"]


def test_file_store_corrupt_file_is_a_miss(tmp_path, manifest_dict: dict):
    store = FileStore(tmp_path)
    store.put(KEY, "sha256:demo", manifest_dict)
    # Corrupt the cache file on disk.
    cache_file = next(tmp_path.glob("*.json"))
    cache_file.write_text("{not json")
    assert store.get(KEY) is None  # treated as a miss, not an error


def test_file_store_missing_dir_is_a_miss(tmp_path):
    assert FileStore(tmp_path / "does-not-exist").get(KEY) is None
