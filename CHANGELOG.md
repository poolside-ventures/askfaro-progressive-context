# Changelog

## Unreleased

## 0.5.1 - see-also why-phrase generation + facet-first eval hooks (2026-07-07)

Additive, backward-compatible — makes the pcx v0.2 cross-links/facets usable, not
just present.

- **`infer_cross_links(..., why_fn=...)` / `compile_source(..., cross_link_why_fn=...)`.**
  The embedding pass picks *which* cross-branch edge to draw, but the reason is
  semantic — lexical token overlap can't name it (the contrastive pass drove the
  branches' salient tokens apart), so the old `why` label read "shares need". A
  builder can now supply a `why_fn(src_desc, dst_desc, shared) -> str` (e.g. a
  model) to state the actual relation; it is called once per directed edge and
  must not raise (failures fall back). Optional — omitting it keeps the
  deterministic label, now de-noised (generic descriptor filler is dropped, and a
  no-overlap edge says "related capability in another area" instead of naming
  stopwords).
- **`PROTOCOL_USAGE` is now directive.** The self-describing usage block tells a
  navigator to *filter by facet before scanning* and to *follow see-also links
  when a result is close-but-not-exact*, instead of only mentioning that `links`
  and `facets` exist. This is what actually drives an agent to use them.
- **Eval harness scores facets/links.** `NavCase` gains an optional `facet`;
  `run_case`/`run_eval` gain `use_facets=` (pre-narrow the frontier to the case's
  facet — filter-first precision) and `use_related=` (let a run that lands close
  follow a see-also link to the target — lateral rescue). Off by default, so the
  delta between configs quantifies what cross-links/facets add.

## 0.5.0 - embedding-based cross-link inference (2026-07-07)

- **`infer_cross_links(..., vectors=...)`** — cross-link inference can now use
  **cosine similarity over per-node embeddings** instead of only lexical Jaccard.
  This matters because the contrastive pass deliberately drives sibling *tokens*
  apart, so lexical cross-branch similarity is near-zero on good descriptors —
  the lexical measure finds almost no links on a real corpus. Pass a
  `{node_id: vector}` map (embeddings of each descriptor) to get semantically
  related see-also links. Tune `min_sim` to the measure (Jaccard ~0.3, cosine
  ~0.6-0.8). `compile_source` gains `cross_link_vectors=` / `cross_link_min_sim=`.
  Lexical remains the zero-dependency default when no vectors are supplied.

## 0.4.0 - measurable descriptor quality + pcx format v0.2 (2026-07-07)

Descriptor quality is now *measured and enforced*, not asserted — and the format
gained the lateral navigation a pure tree can't express.

- **Contrastive convergence loop + collision gate.** The contrastive sibling
  pass iterates against a lexical distinctiveness measure until the worst sibling
  pair drops below `--collision-threshold` (bounded by `--max-contrast-rounds`),
  and — when a level exceeds the chunk size — splits it by *similarity* so
  near-duplicates are contrasted together (fixes the cross-chunk gap). Build
  surfaces `max_sibling_similarity`; `--max-collision` is a CI gate. Also fixed a
  latent bug: the root's children were being contrasted twice every build.
- **Predict-then-verify fidelity eval.** `build/fidelity.py` scores each
  descriptor on whether it predicts its node's content (`LexicalFidelityModel`
  offline, `LLMFidelityModel` real). `pcx build --fidelity [lexical|llm]` +
  `--min-fidelity` gate.
- **Dual-channel grading.** A deterministic paraphrase/vacuity detector
  (`distinct.vacuity_flags`) forces a repair for descriptors that read well but
  are un-searchable; the LLM grade now scores navigation *and* retrieval channels.
- **Branch synthesis.** `LLMDescriptorModel(synthesis=True)` / `--synthesis`
  writes branch descriptors from descendant *content* (tensions, where-to-start),
  not assembled child descriptors.
- **NavSession leaf context envelope.** Opening a leaf prepends its ancestor
  descriptor chain (`Runtime.ancestors`), so atomic content isn't read stripped
  of where it sits. Mode-configurable (`ModeConfig.leaf_context`).
- **Tree-shape lints + regime-awareness.** Report-only warnings for over-wide
  levels, over-deep/small-corpus trees, and does-too-much branch `what`; opt-in
  `--flatten` collapses single-child branches.
- **Memory namespaces + presets.** The memory adapter separates
  knowledge/operational/agent-self memory into namespaces; `--preset` fills a
  coherent config with a justification chain.
- **pcx format v0.2 (breaking, no back-compat).** Nodes carry `links` (see-also
  cross-links with a why-phrase) and `facets` (orthogonal dimensions).
  `--cross-links` infers links from cross-branch descriptor similarity;
  `build/links.betweenness` flags bridge nodes. Runtime gains `related()`
  (explore), `find_by_facets()` (facet-first precision), and `reconcile()`
  (staleness/dangling-route detection). Schema is now `schema/pcx-0.2.schema.json`.

## 0.3.0 - manifest caching (`ManifestLoader`) (2026-06-18)

- **New: a transport-agnostic, revalidate-don't-expire manifest cache.** A
  manifest is small, identical for every reader, and changes only when its source
  changes — ideal to cache — but it is a *routing index*, so a time-to-live cache
  is unsafe (a stale copy points an agent at content that moved). `ManifestLoader`
  caches on the manifest's **identity** and revalidates against it instead.
  - `ManifestLoader(fetch, store=...)` with `load()` / `load_dict()`.
  - You supply a `Fetcher` `(ManifestKey, known_identity) -> FetchOutcome`; the
    library knows nothing about HTTP/files/ETags. `FetchOutcome.unchanged()` reuses
    the cache (e.g. a 304); `FetchOutcome.fresh(identity, body)` replaces it.
  - `AsyncManifestLoader` for async transports (coroutine `fetch`, awaited
    `load()`); same identity-revalidation contract, synchronous store.
  - Stores: `MemoryStore` (default) and `FileStore(dir)` for short-lived processes.
  - `identity_of(dict)` derives an identity from a body (prefers
    `source.content_hash`, else hashes the body); `Manifest.identity` surfaces it.
  - Safety is structural: even a fetcher that always returns full content
    invalidates correctly, because the store is identity-stamped. No TTL can serve
    a stale routing index past a content change.
  - See the new README section "Caching the manifest: `ManifestLoader`".
- **Fix: `__version__` was stale** (`0.0.7`), now tracks the package version.

## 0.2.0 - arbitrary navigation budget + preserved node metadata (2026-06-18)

- **Arbitrary budget.** `Runtime(manifest, budget=N)` and
  `NavSession(manifest, budget=N)` size navigation to any context window,
  overriding the manifest variant's precomputed budget (previously only
  reducible via `reserve`). Composes with `reserve` (host headroom on top).
- **Preserved node metadata.** `Node.from_dict` keeps any non-schema fields the
  manifest carries (e.g. a consumer's own id) in `Node.meta`, surfaced on
  `FrontierEntry.meta`. pcx never interprets these — they round-trip so a
  consumer can render its domain ids while pcx stays generic.

- **Tighter `what`/`when` defaults.** `LLMDescriptorModel` now instructs the
  model to write short verb phrases (≤80 chars, no sub-clauses, no trailing
  punctuation) instead of verbose full sentences. Hard clamps in `_call` reduced
  from 160 → 80 chars to match. Fallback strings updated to match.
- **Docs: document `NavSession`.** Added a README section for the agent-loop API
  (`index` / `look` / `open` / `close`, the `local` / `remote` modes, and the
  `shown_tokens` / `budget_remaining` accounting). No functional change.

## 0.1.0 - renamed to askfaro-progressive-context (2026-06-17)

- **Package renamed.** Distribution `faro-progressive-context` is now
  `askfaro-progressive-context`, and the import name `faro_progressive_context`
  is now `askfaro_progressive_context`, to match the AskFaro brand. Update
  imports and `pip install askfaro-progressive-context`. The old name ships one
  final `0.0.8` release that re-exports this package and warns on import. No
  functional change.

## 0.0.7 — first clean public release (2026-06-11)

- Genericized examples and docs for the public release (neutral fixtures; no
  product-specific references). No functional change vs 0.0.6. 0.0.6 is yanked.

## 0.0.6 — incremental rebuilds (2026-06-11)

- **Reuse descriptors for unchanged content.** `compile_source(prior_manifest=...)`
  builds a `content_hash`-keyed cache (`cache_from_manifest`) and reuses the
  prior descriptor for any node whose content is unchanged. Because a node's
  hash rolls up its whole subtree, a change re-describes only that node and its
  ancestor path; only sibling groups whose parent changed are re-contrasted, and
  only regenerated nodes are re-graded. Stats: `reused` / `regenerated`.
- Net effect: an unchanged full-catalog rebuild (213 tools) makes **0 model
  calls**; a one-tool change makes a handful — so the LLM-quality manifest is
  cheap to keep fresh on every catalog change (seed once, refresh incrementally).

## 0.0.5 — self-describing manifests + concurrent builds (unreleased)

- **Self-description (`usage`).** Every manifest now ships a top-level `usage`
  block — a plain-language explanation of the navigation protocol — so a cold
  external agent that has never seen the format knows how to navigate it
  (descriptors vs content, `node://` refs, the budget, index/open/look). The
  llms.txt export gets a matching "How to read this index" header.
- **Concurrent descriptor generation.** `generate_descriptors`/`compile_source`
  take `max_workers`; the three phases parallelize (level-by-level so a branch's
  children are always ready). Brings a ~280-node catalog build from ~35 min to
  ~8 min. Deterministic-equivalent to sequential.
- **More robust LLM parsing.** Extract the first balanced JSON object (handles
  trailing "Extra data"); `describe_leaf/branch` degrade to a hint-based
  descriptor on parse failure instead of crashing a large build.

## 0.0.4 — navigation policy (NavSession + modes) (unreleased)

- **`NavSession`** — the agent-facing navigation policy with three verbs:
  `index()` (frontier, shortest-useful view), `look(ids)` (escalate candidates
  to the full descriptor without committing), `open(id)` (drill a branch /
  splice a leaf). The model's choice of verb is the confidence signal.
- **Explicit `local`/`remote` modes** encoding the tokens-vs-round-trips
  tradeoff: `local` opens at a `brief` index and escalates (round-trips ~free);
  `remote` discloses a `full` index and inlines small leaves to cut round-trips.
- Runtime is now **view-level aware** in its budget accounting (`view_level`),
  with `disclose_more()` charging only the escalation delta. `shown_tokens`
  on the session is the real length the model saw.

## 0.0.3 — length, escalation, locality, error guidance (unreleased)

- **Length is now a first-class metric.** The eval reports `first_view_tokens`,
  `tokens_to_answer`, and a `disclosure_ratio` vs loading everything — alongside
  accuracy. (bake-off (24-tool catalog): pcx reaches the answer at ~2.2k tokens vs
  ~15k to load all schemas, 6.9× less, while being more accurate *and* shorter.)
- **Shortest-first-view + escalation.** `Runtime.frontier_view(level)` /
  `frontier_tokens(level)` render the frontier at `title` → `brief` → `full`.
  A `title`-first view is ~14× smaller than `full` on a 24-tool catalog; the agent
  escalates only when it can't decide.
- **Latency/locality.** `Runtime(resolver=...)` resolves leaves from a local
  in-memory store so `expand` is an O(1) splice, not a network fetch; missing
  leaves error loudly. `dict_resolver` for the common case.
- **Error guidance.** Actionable messages for the common setup mistakes
  (missing `[llm]` extra, no endpoint/model, empty API key, unknown adapter
  kind, missing source, reserve ≥ budget) + `docs/troubleshooting.md`.

## 0.0.2 — Phase 1 (unreleased)

The compiler: `pcx build` turns content into manifest variants.

- **Adapters** for the four already-hierarchical source kinds — `tools` (JSON
  schemas, grouped by namespace), `docs` (markdown tree), `skills` (per-skill
  markdown, grouped by category), `memory` (one-fact files, grouped by type).
  No clustering/structure-inference yet (that's Phase 3).
- **Descriptor engine** (the moat): bottom-up generation, a contrastive sibling
  pass that rewrites each `when` to discriminate from its siblings, and a
  self-grade + repair loop. `DescriptorModel` is pluggable — `FakeDescriptorModel`
  for offline/CI, `LLMDescriptorModel` for a real (Flash-class) model via any
  OpenAI-compatible endpoint.
- **Cost annotation**: per-node `tokens`/`desc_tokens`, bottom-up
  `subtree_tokens` rollup, and `content_hash` for incremental rebuilds.
- **Emit**: one manifest per `--budgets` variant + an `llms.txt` export.
- **CLI**: `pcx build <path> --kind ... --budgets ... [--fake | --endpoint --model]`.

### Not yet
- Per-budget frontier-depth/verbosity shaping (variants currently share the tree).
- `website`/`file` adapters + embedding-based grouping (Phase 3).
- The host-side wiring + the real bake-off vs flat manifests (consumer task).

## 0.0.1 — Phase 0 (unreleased)

Spec freeze + eval harness, ahead of the compiler.

- **Format**: `pcx` v0.1 progressive-context manifest, defined as JSON Schema
  (`schema/pcx-0.1.schema.json`). Tiered nodes with `what`/`when` descriptors,
  per-node and subtree token costs, branch/leaf split, verbatim leaf pointers,
  and pre-generated per-budget variants.
- **Validation**: zero-dependency structural checks + optional full JSON Schema
  validation (`pcx validate`).
- **Expansion runtime**: `peek` / `expand` / `collapse` / `search` with hard
  budget enforcement, a runtime `reserve` for host headroom, optional LRU
  auto-eviction, and a pluggable search backend.
- **Navigators**: `KeywordNavigator` (deterministic, offline baseline) and
  `LLMNavigator` (bring-your-own model).
- **Eval harness**: `navigation-success @ budget`, first-hop precision, and
  average hops (`pcx eval`), with a `skills` example fixture.

### Not yet
- `pcx build` — the compiler (adapters, descriptor generation, cost annotation).
  Lands in Phase 1.
