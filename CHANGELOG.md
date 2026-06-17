# Changelog

## Unreleased

- **Docs: document `NavSession`.** Added a README section for the agent-loop API
  (`index` / `look` / `open` / `close`, the `local` / `remote` modes, and the
  `shown_tokens` / `budget_remaining` accounting). No functional change.

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
