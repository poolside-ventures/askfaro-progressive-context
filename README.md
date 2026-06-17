# faro-progressive-context

**Compile any content into a tiered, budget-aware, agent-navigable progressive-disclosure manifest — for small / on-device context windows.**

On-device models have tiny context windows (~4k today, ~32k near-term). Stuffing everything in — or lossily compressing it — loses information. The alternative is **progressive disclosure**: give the model a compact, accurate *index* of what exists and *when each piece is relevant*, then let it fetch detail on demand within a hard token budget.

`faro-progressive-context` is the open-source compiler + format + runtime for that index. It is the **agent-navigated** half of Faro's context tooling (the model reads the index and decides what to expand); its sibling [`faro-embedded-search`](https://github.com/poolside-ventures/faro-embedded-search) is the retrieval-driven half. The two stay independent — this library has no hard dependency on it.

> Status: **Phase 1 (pre-alpha).** The format, expansion runtime, eval harness, **and the compiler (`pcx build`)** are here and tested — adapters for `tools`/`docs`/`skills`/`memory`, the descriptor engine (bottom-up + contrastive + self-grade), cost annotation, and per-budget emit. Still to come: per-budget frontier shaping, `website`/`file` adapters with clustering (Phase 3), and the hosted Faro registry (Phase 5).

## The idea in one screen

A **progressive-context manifest** (`pcx.json`) is a tree of nodes. Every node carries:

- a **descriptor** — `what` (one line: what this is) and `when` (one line: when it's relevant). These are the *navigation index*, and their quality is the whole game.
- **token costs** — so the runtime can plan expansion against a budget *without fetching anything*.
- either **children** (a branch) or a **payload pointer** (a leaf). Leaves are never inlined and always **verbatim** — no information is lost to a summary.

Variants are **pre-generated per budget** (`pcx.4k.json`, `pcx.32k.json`, …); budgets are arbitrary integers, so a developer who needs headroom for their own content can build a `31k` variant — or reserve it at runtime.

## What's here (Phase 0)

| Module | What it does |
|---|---|
| `schema/pcx-0.1.schema.json` | the format, as JSON Schema |
| `faro_progressive_context.types` | `Manifest` / `Node` / `Payload` dataclasses |
| `faro_progressive_context.validate` | structural (zero-dep) + JSON Schema validation |
| `faro_progressive_context.runtime` | the expansion protocol: `peek` / `expand` / `collapse` / `search`, with **hard budget enforcement** and a runtime `reserve` |
| `faro_progressive_context.navigator` | `KeywordNavigator` (deterministic baseline, no model) and `LLMNavigator` (bring your own `complete()`) |
| `faro_progressive_context.eval` | the **`navigation-success @ budget`** harness — the headline quality metric |

## Quick start

```bash
pip install -e ".[dev,schema]"

# validate a manifest
pcx validate examples/skills/manifest.pcx.4k.json --schema

# score navigation-success @ budget with the deterministic baseline navigator
pcx eval examples/skills/manifest.pcx.4k.json examples/skills/cases.json -v
```

```python
from faro_progressive_context import Manifest, Runtime

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
from faro_progressive_context import Manifest, NavSession

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
