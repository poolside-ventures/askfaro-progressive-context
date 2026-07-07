# askfaro-progressive-context

**Compile any content into a tiered, budget-aware, agent-navigable progressive-disclosure manifest — for small / on-device context windows.**

On-device models have tiny context windows (~4k today, ~32k near-term). Stuffing everything in — or lossily compressing it — loses information. The alternative is **progressive disclosure**: give the model a compact, accurate *index* of what exists and *when each piece is relevant*, then let it fetch detail on demand within a hard token budget.

`askfaro-progressive-context` is the open-source compiler + format + runtime for that index. It is the **agent-navigated** half of Faro's context tooling (the model reads the index and decides what to expand); its sibling [`askfaro-embedded-search`](https://github.com/poolside-ventures/askfaro-embedded-search) is the retrieval-driven half. The two stay independent — this library has no hard dependency on it.

> Status: **pre-alpha, but published** — `pip install askfaro-progressive-context` (v0.4.0 on PyPI). Shipped and tested: the format, the compiler (`pcx build`) with adapters for `tools`/`docs`/`skills`/`memory`, the descriptor engine (bottom-up + contrastive + self-grade), incremental rebuilds (descriptor reuse keyed on `content_hash`), the expansion runtime, the `NavSession` agent-loop API (`index`/`look`/`open`/`close`, `local`/`remote` modes), identity-revalidated manifest caching (`ManifestLoader` / `AsyncManifestLoader`), and the eval harness. Still to come: per-budget frontier shaping, `website`/`file` adapters with clustering, and the hosted Faro registry.

## The idea in one screen

A **progressive-context manifest** (`pcx.json`) is a tree of nodes. Every node carries:

- a **descriptor** — `what` (one line: what this is) and `when` (one line: when it's relevant). These are the *navigation index*, and their quality is the whole game.
- **token costs** — so the runtime can plan expansion against a budget *without fetching anything*.
- either **children** (a branch) or a **payload pointer** (a leaf). Leaves are never inlined and always **verbatim** — no information is lost to a summary.

Variants are **pre-generated per budget** (`pcx.4k.json`, `pcx.32k.json`, …); budgets are arbitrary integers, so a developer who needs headroom for their own content can build a `31k` variant — or reserve it at runtime.

## What's here (v0.4.0)

| Module | What it does |
|---|---|
| `schema/pcx-0.2.schema.json` | the format, as JSON Schema (v0.2: adds cross-links + facets) |
| `askfaro_progressive_context.types` | `Manifest` / `Node` / `Link` / `Payload` / `Variant` dataclasses |
| `askfaro_progressive_context.validate` | structural (zero-dep) + JSON Schema validation |
| `askfaro_progressive_context.build` (`pcx build`) | the compiler: adapters, descriptor engine (bottom-up + **contrastive convergence** + dual-channel self-grade + optional branch **synthesis**), **distinctiveness/fidelity metrics + CI gates**, cross-link inference, tree-shape lints, incremental rebuilds, per-budget emit + `llms.txt` |
| `askfaro_progressive_context.runtime` | the expansion protocol: `peek` / `expand` / `collapse` / `search` / `related` / `find_by_facets` / `reconcile`, with **hard budget enforcement** and a runtime `reserve` |
| `askfaro_progressive_context.session` | `NavSession` — the agent-loop API (`index`/`look`/`open`/`close`/`related`/`filter`) with `local`/`remote` modes + leaf context envelopes |
| `askfaro_progressive_context.navigator` | `KeywordNavigator` (deterministic baseline, no model) and `LLMNavigator` (bring your own `complete()`) |
| `askfaro_progressive_context.loader` | `ManifestLoader` / `AsyncManifestLoader` + `MemoryStore` / `FileStore` — transport-agnostic, identity-revalidated manifest caching |
| `askfaro_progressive_context.eval` | the **`navigation-success @ budget`** harness — the headline quality metric |

## Quick start

```bash
pip install askfaro-progressive-context          # runtime + CLI
pip install "askfaro-progressive-context[llm]"   # + the LLM descriptor engine for `pcx build`
```

```bash
# build manifest variants from a source tree (use --fake for an offline/CI build)
pcx build ./skills --kind skills --budgets 4k,32k --endpoint $ENDPOINT --model $MODEL

# validate a manifest
pcx validate examples/skills/manifest.pcx.4k.json --schema

# score navigation-success @ budget with the deterministic baseline navigator
pcx eval examples/skills/manifest.pcx.4k.json examples/skills/cases.json -v
```

> Working from a clone? Install editable with the dev + schema extras instead:
> `pip install -e ".[dev,schema]"`.

```python
from askfaro_progressive_context import Manifest, Runtime

m = Manifest.from_dict(json.load(open("examples/skills/manifest.pcx.4k.json")))
rt = Runtime(m, reserve=1024)          # leave 1k for your own content

rt.peek()                               # frontier: tier-1 descriptors + budget_remaining
rt.expand("recurring")                  # reveal a branch's children (charged against budget)
ref = rt.expand("recurring.create")     # splice a leaf's verbatim payload; raises if over budget
```

## The expansion protocol

The runtime — not the model — is the budget authority. `effective_budget = variant.budget − reserve`, and every `expand` is checked against it. When full it auto-collapses LRU leaves (opt-in) or refuses and tells the agent to choose. **The budget is never silently exceeded.**

## Driving it from an agent loop: `NavSession`

`Runtime` is the low-level budget authority; `NavSession` wraps it with the three verbs an agent loop actually drives, plus mode-aware defaults. The model's *choice of verb is the confidence signal* — there is no threshold to tune:

```python
from askfaro_progressive_context import Manifest, NavSession

s = NavSession(manifest, mode="local", reserve=1024)

s.index()                        # current frontier, shortest-useful view first
s.look(["recurring", "one_off"]) # escalate candidates to full descriptors WITHOUT opening them
s.open("recurring")              # branch -> drill into its children;
                                 # leaf   -> splice the verbatim content (budget-enforced)
s.close("recurring")             # collapse a node to reclaim budget

s.shown_tokens                   # everything the model has seen this session (the real "length")
s.budget_remaining
```

If the index is enough, the model calls `open`; if it can't decide, it calls `look` first. **Modes** encode the tokens-vs-round-trips tradeoff:

| mode | frontier view | small leaves | use when |
|---|---|---|---|
| `local` (default) | `brief` | resolved on demand (O(1) resident splice) | on-device / resident manifest — round-trips are ~free, so take many tiny steps |
| `remote` | `full` | inlined into `index()` (≤200 tokens) | network-backed — each hop costs latency, so disclose more per step to need fewer |

Pass `config=ModeConfig(...)` for a custom policy; an unknown `mode` raises with the valid options.

## Caching the manifest: `ManifestLoader`

A manifest is small, identical for every reader, and changes only when its source content changes — an ideal cache target. But it is also a *routing index*, so a stale copy can point an agent at content that has moved or vanished. A plain time-to-live cache is therefore the wrong tool: the safe pattern is to cache on the manifest's **identity** and *revalidate* against it, never to expire blindly on a clock.

`ManifestLoader` gives every consumer that pattern by default, while staying **transport-agnostic** — it knows nothing about HTTP, files, S3, or ETags. You supply a `Fetcher` that reaches your origin; the loader owns the identity bookkeeping, the store, and the guarantee that a changed identity always wins.

```python
from askfaro_progressive_context import (
    FetchOutcome, FileStore, ManifestKey, ManifestLoader, identity_of,
)
import httpx

def fetch(key: ManifestKey, known_identity: str | None) -> FetchOutcome:
    # Your transport decides "changed?" however it likes. Over HTTP, let the
    # origin do it with a conditional request:
    headers = {"If-None-Match": known_identity} if known_identity else {}
    r = httpx.get(f"https://api.example.com/pcx/manifest?budget={key.budget}", headers=headers)
    if r.status_code == 304:
        return FetchOutcome.unchanged()                       # reuse the cache, no transfer
    body = r.json()
    return FetchOutcome.fresh(r.headers.get("ETag") or identity_of(body), body)

loader = ManifestLoader(fetch=fetch, store=FileStore("~/.cache/pcx"))
manifest = loader.load(ManifestKey(source_id="my-catalog", budget="4k"))   # -> Manifest
```

Your `fetch(key, known_identity)` is handed the identity already in cache (or `None`) and returns one of two outcomes:

- **`FetchOutcome.unchanged()`** — nothing changed since `known_identity` (e.g. a 304). The loader reuses the cached body: zero transfer, zero parsing.
- **`FetchOutcome.fresh(identity, body)`** — fresh content. The loader stores it under the key and returns it.

The safety property is **structural**: a `Fetcher` too dumb to do conditional requests and *always* returning full content still gets correct invalidation, because the store is identity-stamped and re-storing the same identity is a no-op. There is no TTL knob that can serve a stale routing index past an identity change.

| piece | role |
|---|---|
| `ManifestKey(source_id, budget)` | what you want — budget is part of the key (identity is shared across budgets) |
| `identity` (a `str`) | opaque content token: a content hash, an ETag, `"v{n}"` — compared for equality only, never parsed |
| `Fetcher` | **your** transport: `(key, known_identity) -> FetchOutcome`. The one bit you write |
| `MemoryStore` (default) | process-local; all a long-running process needs |
| `FileStore(dir)` | on-disk; earns its keep for short-lived processes (CLIs, serverless, edge cold starts) that would otherwise re-download every run |
| `identity_of(dict)` | derive an identity from a manifest body (prefers `source.content_hash`, else hashes the body) — for transports with no native validator |

Identity comes from the build: `emit` stamps each manifest with a bottom-up `source.content_hash`, surfaced as `manifest.identity`. `load()` means *"give me the current manifest, revalidating."* If you want to skip even the revalidation round-trip, don't call `load()` in a hot loop — hold the returned `Manifest` and reload on your own cadence.

For an async transport (e.g. an `httpx.AsyncClient`), use **`AsyncManifestLoader`** — same contract, but `fetch` is a coroutine and `load()` is awaited. The store stays synchronous (its get/put are fast local operations):

```python
from askfaro_progressive_context import AsyncManifestLoader, FetchOutcome, FileStore, ManifestKey

async def fetch(key, known_identity):
    r = await async_http.get(f"/pcx/manifest?budget={key.budget}",
                             headers={"If-None-Match": known_identity} if known_identity else {})
    if r.status_code == 304:
        return FetchOutcome.unchanged()
    return FetchOutcome.fresh(r.headers.get("ETag") or identity_of(r.json()), r.json())

loader = AsyncManifestLoader(fetch=fetch, store=FileStore("~/.cache/pcx"))
manifest = await loader.load(ManifestKey(source_id="my-catalog", budget="4k"))
```

> **For origins:** to let clients revalidate cheaply, serve the manifest with an `ETag` (the `source.content_hash` is a ready-made one) and honor `If-None-Match` with a `304`. Without that, clients still cache correctly via `identity_of`, they just re-transfer the body on each `load()`.

## Why a benchmark, not vibes

The moat is descriptor quality, so quality is measured, not asserted. The eval harness gives a navigator *only* the manifest and a budget plus `(query → correct leaf)` cases, and reports **navigation-success @ budget**, **first-hop precision**, and **average hops**. The deterministic `KeywordNavigator` establishes an offline floor; swap in an `LLMNavigator` to score a real model.

## Length is the point

Accuracy without length misses why this exists. The eval reports
`first_view_tokens` and `tokens_to_answer` next to accuracy, and the runtime
renders the frontier at progressively shorter levels (`title` → `brief` →
`full`) so the agent opens with the **shortest** view and escalates only when
unsure. On a 24-tool catalog, a `title`-first view is ~14× smaller than the full
descriptor set, and the model reaches the right tool having seen ~6.9× less
context than loading every schema.

Progressive disclosure trades tokens for round-trips, so the whole artifact is
meant to stay **resident**: `Runtime(resolver=...)` resolves leaves from a local
store, making every `expand` an O(1) splice rather than a network fetch.

## Troubleshooting

Setup mistakes fail with actionable messages; see [`docs/troubleshooting.md`](docs/troubleshooting.md)
for the full table (missing extras, model config, architecture mismatches).

## License

MIT © Faro
