# Setup & troubleshooting

`faro-progressive-context` is dependency-free at its core; features that need
more (LLM descriptor generation, JSON Schema validation, exact tokenization)
live behind optional extras. This page maps the common setup mistakes to their
fix. The library tries to fail with an actionable message at each of these
points rather than a stack trace.

## Install

```bash
pip install faro-progressive-context            # core: format, runtime, eval
pip install 'faro-progressive-context[llm]'     # + OpenAI-compatible client (httpx)
pip install 'faro-progressive-context[schema]'  # + full JSON Schema validation
pip install 'faro-progressive-context[tokenize]'# + exact tiktoken counts
pip install 'faro-progressive-context[dev]'     # + pytest
```

You only need `[llm]` to run `pcx build` against a real model; everything else
(format, runtime, eval, the offline `--fake` build) works with the core install.

## Common errors and fixes

| What you see | Cause | Fix |
|---|---|---|
| `OpenAICompatibleClient needs httpx. Install the 'llm' extra` | building against a real model without the client dependency | `pip install 'faro-progressive-context[llm]'` |
| `non-fake build needs --endpoint and --model` | `pcx build` with no model configured | pass `--endpoint <url> --model <id>`, or `--fake` to build offline |
| `no API key in $OPENAI_API_KEY` | the key env var is unset (or named differently) | export the var, or point at another with `--api-key-env MY_KEY`, or use `--fake` |
| `no API key — pass api_key to OpenAICompatibleClient` | constructing the client in code with an empty key | pass the key string explicitly |
| `unknown adapter kind 'X'; known: [...]` | `--kind` is misspelled or unsupported | use one of `tools`, `docs`, `skills`, `memory` |
| `source not found: <path>` | the build path doesn't exist | check the path; `tools` wants a JSON file, the others a directory |
| `JSON Schema validation requires the 'schema' extra` | `pcx validate --schema` without jsonschema | `pip install 'faro-progressive-context[schema]'`, or drop `--schema` for the zero-dep structural check |
| `reserve (N) >= variant budget (M); no room to navigate` | runtime headroom reserve is larger than the manifest's budget | lower `reserve`, or load a larger-budget variant |
| `expand(...) needs T tokens, only R remaining` (`BudgetExceeded`) | the leaf doesn't fit the remaining budget | `collapse` a spliced leaf, use a cheaper render level, or raise the budget |
| `no resident content for node 'X'; ship its leaf in the local store` | the leaf resolver has no content for that node | include every leaf in the local store you pass to `Runtime(resolver=...)` |
| `LLM call failed after N attempts` | the model endpoint is unreachable or 5xx after retries | check the endpoint URL and network; transient 5xx auto-retries, client 4xx do not |

## Architecture-mismatch gotcha (Apple Silicon)

If the `[schema]` extra's native dependency (`rpds`, via `jsonschema`) fails to
import with an "incompatible architecture" error, your venv is on an Intel
Python. Recreate it on an arm64 interpreter:

```bash
uv venv --python 3.13     # or any arm64 python3.11+
uv pip install -e '.[dev,schema,llm]'
```

The core library and the structural validator are pure Python and unaffected.

## Building against any model

The package hardcodes no provider. `OpenAICompatibleClient` speaks
`/chat/completions`, so point it at any OpenAI-compatible endpoint (a hosted
provider, a local gateway, a LiteLLM proxy). Descriptor generation is a cached
batch step, so a fast, cheap "Flash-class" model is the intended tier — but
that is your choice, expressed entirely through `--endpoint`/`--model`.
