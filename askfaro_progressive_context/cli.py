"""`pcx` command-line interface.

Phase 0 ships `validate` and `eval`. `build` (the compiler) lands in Phase 1.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from .eval import NavCase, run_eval
from .navigator import KeywordNavigator
from .types import Manifest
from .validate import validate


def _parse_budgets(spec: str) -> list[tuple[str, int]]:
    out = []
    for raw in spec.split(","):
        label = raw.strip()
        if not label:
            continue
        n = int(label[:-1]) * 1024 if label[-1].lower() == "k" else int(label)
        out.append((label, n))
    return out


def _load_manifest(path: str) -> Manifest:
    return Manifest.from_dict(json.loads(Path(path).read_text()))


def cmd_validate(args: argparse.Namespace) -> int:
    raw = json.loads(Path(args.manifest).read_text())
    errors = validate(raw, use_schema=args.schema)
    if errors:
        print(f"INVALID: {len(errors)} error(s)", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1
    print(f"OK: {args.manifest} is a valid pcx {raw.get('pcx_version')} manifest")
    return 0


def cmd_eval(args: argparse.Namespace) -> int:
    manifest = _load_manifest(args.manifest)
    cases_raw = json.loads(Path(args.cases).read_text())
    cases = [NavCase(query=c["query"], target=c["target"], note=c.get("note")) for c in cases_raw]

    # Phase 0 baseline navigator is deterministic and needs no model.
    navigator = KeywordNavigator()
    report = run_eval(manifest, navigator, cases, reserve=args.reserve, max_hops=args.max_hops)

    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(f"manifest : {args.manifest}  (budget {manifest.variant.budget}, reserve {args.reserve})")
        print(f"navigator: KeywordNavigator (baseline)\n")
        print(report.summary())
        if args.verbose:
            print("\nper-case:")
            for r in report.cases:
                mark = "ok " if r.success else "MISS"
                print(f"  [{mark}] {r.query!r} -> {r.target}  path={r.path}")
    return 0


def cmd_build(args: argparse.Namespace) -> int:
    from .build import (
        FakeDescriptorModel,
        LexicalFidelityModel,
        LLMDescriptorModel,
        LLMFidelityModel,
        compile_source,
    )
    from .build.adapters import get_adapter
    from .llm import OpenAICompatibleClient
    from .tokenizer import make_tokenizer

    if args.preset:
        from .build.presets import apply_preset

        preset_defaults = {
            "budgets": "4k,32k", "synthesis": False, "flatten": False,
            "fidelity": None, "collision_threshold": 0.5, "max_collision": None,
        }
        try:
            notes = apply_preset(args.preset, args, preset_defaults)
        except KeyError as exc:
            print(str(exc).strip('"'), file=sys.stderr)
            return 2
        print(f"preset {args.preset!r}: " + "; ".join(notes) if notes else f"preset {args.preset!r} (all overridden)")

    budgets = _parse_budgets(args.budgets)
    if not budgets:
        print("no budgets given", file=sys.stderr)
        return 2

    src = Path(args.path)
    if not src.exists():
        print(f"source not found: {src}", file=sys.stderr)
        return 2
    try:
        tree = get_adapter(args.kind).load(src, source_id=args.source_id)
    except KeyError as exc:
        print(str(exc).strip('"'), file=sys.stderr)
        return 2

    if args.flatten:
        from .build.ir import flatten_single_child_branches

        flatten_single_child_branches(tree.root)

    client = None
    if args.fake:
        model = FakeDescriptorModel()
    else:
        if not (args.endpoint and args.model):
            print("non-fake build needs --endpoint and --model (or pass --fake for the offline model)", file=sys.stderr)
            return 2
        api_key = os.environ.get(args.api_key_env, "")
        if not api_key:
            print(f"no API key in ${args.api_key_env}. Set it, or use a different var with "
                  f"--api-key-env, or pass --fake to build offline.", file=sys.stderr)
            return 2
        client = OpenAICompatibleClient(args.endpoint, api_key, args.model)
        model = LLMDescriptorModel(client, synthesis=args.synthesis)
    if args.synthesis and args.fake:
        print("note: --synthesis needs a real model; the offline --fake model ignores it", file=sys.stderr)

    fidelity_model = None
    if args.fidelity == "llm":
        if client is None:
            print("--fidelity llm needs a real model (--endpoint/--model); use --fidelity lexical for offline",
                  file=sys.stderr)
            return 2
        fidelity_model = LLMFidelityModel(client)
    elif args.fidelity == "lexical":
        fidelity_model = LexicalFidelityModel()

    result = compile_source(
        tree,
        model,
        [n for _, n in budgets],
        tokenizer=make_tokenizer(args.tokenizer),
        contrastive=not args.no_contrastive,
        collision_threshold=args.collision_threshold,
        max_contrast_rounds=args.max_contrast_rounds,
        max_repairs=args.max_repairs,
        fidelity_model=fidelity_model,
        cross_links=args.cross_links,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for label, n in budgets:
        path = out / f"{result.source_id}.pcx.{label}.json"
        path.write_text(json.dumps(result.manifests[n], indent=2))
        written.append(str(path))
    llms_path = out / f"{result.source_id}.llms.txt"
    llms_path.write_text(result.llms_txt)
    written.append(str(llms_path))

    s = result.stats
    print(f"built {result.source_id} ({args.kind}): {s['nodes']} nodes, {s['leaves']} leaves, "
          f"{s['branches']} branches")
    print(f"  manifest baseline: {s['manifest_tokens']} tok   full expansion: {s['full_tokens']} tok")
    print(f"  variants: {', '.join(label for label, _ in budgets)}")
    max_sim = s.get("max_sibling_similarity", 0.0)
    colliding = s.get("collisions", {}).get("colliding_groups", 0)
    print(f"  descriptor distinctiveness: worst sibling similarity {max_sim:.3f}"
          f" ({colliding} group(s) ≥ {args.collision_threshold})")
    fidelity = s.get("fidelity")
    if fidelity:
        print(f"  descriptor fidelity: mean {fidelity['mean_score']:.2f}/5"
              f" ({len(fidelity['flagged'])} node(s) flagged < 3)")
    for w in written:
        print(f"  wrote {w}")
    for warning in s.get("warnings", []):
        print(f"  warn: {warning}", file=sys.stderr)

    if args.max_collision is not None and max_sim > args.max_collision:
        print(f"FAIL: worst sibling similarity {max_sim:.3f} exceeds --max-collision "
              f"{args.max_collision:.3f}. Colliding descriptors are not discriminating.", file=sys.stderr)
        return 3
    if args.min_fidelity is not None and fidelity and fidelity["mean_score"] < args.min_fidelity:
        print(f"FAIL: mean descriptor fidelity {fidelity['mean_score']:.2f} is below --min-fidelity "
              f"{args.min_fidelity:.2f}. Descriptors do not predict their content.", file=sys.stderr)
        return 3
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pcx", description="progressive-context manifest tools")
    sub = parser.add_subparsers(dest="command", required=True)

    p_val = sub.add_parser("validate", help="validate a manifest against the pcx format")
    p_val.add_argument("manifest")
    p_val.add_argument("--schema", action="store_true", help="also run full JSON Schema validation (needs the 'schema' extra)")
    p_val.set_defaults(func=cmd_validate)

    p_eval = sub.add_parser("eval", help="score navigation-success @ budget over a case set")
    p_eval.add_argument("manifest")
    p_eval.add_argument("cases", help="JSON array of {query, target} cases")
    p_eval.add_argument("--reserve", type=int, default=0, help="tokens to reserve for host content")
    p_eval.add_argument("--max-hops", type=int, default=8, dest="max_hops")
    p_eval.add_argument("--json", action="store_true")
    p_eval.add_argument("-v", "--verbose", action="store_true")
    p_eval.set_defaults(func=cmd_eval)

    p_build = sub.add_parser("build", help="compile content into pcx manifest variants")
    p_build.add_argument("path", help="source file (tools) or directory (docs/skills/memory)")
    p_build.add_argument("--kind", required=True, choices=["tools", "docs", "skills", "memory"])
    p_build.add_argument("--budgets", default="4k,32k", help="comma-separated, e.g. 4k,32k,31000")
    p_build.add_argument("--preset", default=None,
                         help="named config preset (docs-heavy | tool-routing | low-budget); explicit flags override it")
    p_build.add_argument("--out", default="dist", help="output directory")
    p_build.add_argument("--source-id", dest="source_id", default=None)
    p_build.add_argument("--fake", action="store_true", help="use the deterministic offline model (no API)")
    p_build.add_argument("--endpoint", default=None, help="OpenAI-compatible base URL")
    p_build.add_argument("--model", default=None, help="model id (caller-supplied; nothing hardcoded)")
    p_build.add_argument("--api-key-env", dest="api_key_env", default="OPENAI_API_KEY")
    p_build.add_argument("--tokenizer", default=None, help="tiktoken encoding name (needs the 'tokenize' extra)")
    p_build.add_argument("--no-contrastive", dest="no_contrastive", action="store_true")
    p_build.add_argument("--synthesis", action="store_true",
                         help="synthesize branch descriptors from descendant content (tensions, where-to-start); needs a real model")
    p_build.add_argument("--flatten", action="store_true",
                         help="collapse single-child branches (pointless navigation hops) before compiling")
    p_build.add_argument("--cross-links", dest="cross_links", action="store_true",
                         help="infer lateral see-also links between related nodes in different branches (pcx v0.2)")
    p_build.add_argument("--collision-threshold", dest="collision_threshold", type=float, default=0.5,
                         help="sibling similarity at/above which the contrastive pass keeps rewriting (0-1)")
    p_build.add_argument("--max-contrast-rounds", dest="max_contrast_rounds", type=int, default=2,
                         help="max contrastive rewrite rounds per sibling group")
    p_build.add_argument("--max-collision", dest="max_collision", type=float, default=None,
                         help="CI gate: exit non-zero if the worst sibling similarity exceeds this (0-1)")
    p_build.add_argument("--fidelity", nargs="?", const="lexical", choices=["lexical", "llm"], default=None,
                         help="score predict-then-verify descriptor fidelity ('lexical' offline, 'llm' uses the model)")
    p_build.add_argument("--min-fidelity", dest="min_fidelity", type=float, default=None,
                         help="CI gate: exit non-zero if mean descriptor fidelity is below this (1-5)")
    p_build.add_argument("--max-repairs", dest="max_repairs", type=int, default=1)
    p_build.set_defaults(func=cmd_build)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
