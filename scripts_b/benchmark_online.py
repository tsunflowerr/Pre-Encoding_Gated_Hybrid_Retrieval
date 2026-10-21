from __future__ import annotations

import argparse
from dataclasses import replace

from contracts.io import load_queries
from pegh.dense.artifacts import read_json
from pegh.profiling.runner import run_benchmark
from pegh.profiling.runtime import RuntimeSettings


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Isolated CPU online benchmark, with fresh query encoding"
    )
    parser.add_argument("--registry", required=True)
    parser.add_argument("--queries", required=True)
    parser.add_argument("--warmup-queries", required=True)
    parser.add_argument("--domain", required=True)
    parser.add_argument("--split", required=True)
    parser.add_argument("--fold", type=int)
    parser.add_argument("--runtime", default="configs/runtime/cpu4.yaml")
    parser.add_argument("--output", required=True)
    parser.add_argument("--repetitions", type=int)
    parser.add_argument("--detailed-stages", action="store_true")
    parser.add_argument("--stop-file")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    settings = RuntimeSettings.from_yaml(args.runtime)
    if args.repetitions is not None:
        settings = replace(settings, repetitions=args.repetitions)
    if args.detailed_stages:
        settings = replace(settings, detailed_stages=True)
    queries = load_queries(args.queries, args.domain)
    if args.limit is not None:
        if args.split == "test":
            raise ValueError("refusing to truncate a final test benchmark")
        queries = queries[: args.limit]
    registry = read_json(args.registry)["methods"]
    manifest = run_benchmark(
        registry,
        queries,
        load_queries(args.warmup_queries, args.domain),
        args.output,
        settings,
        split=args.split,
        fold=args.fold,
        stop_file=args.stop_file,
    )
    print(manifest["status"])
    return 0 if manifest["status"] == "complete" else 75


if __name__ == "__main__":
    raise SystemExit(main())
