"""Run one C5 request through B's isolated benchmark worker."""

from __future__ import annotations

import argparse
import json
from dataclasses import replace
from pathlib import Path

from contracts.io import load_queries
from pegh.profiling.runner import run_benchmark
from pegh.profiling.runtime import RuntimeSettings


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", required=True)
    parser.add_argument("--queries", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    entry = json.loads(Path(args.registry).read_text(encoding="utf-8"))["methods"][0]
    kwargs = entry["kwargs"]
    queries = load_queries(args.queries, kwargs["domain"])[:1]
    settings = replace(
        RuntimeSettings.from_yaml("configs/runtime/cpu4.yaml"),
        warmup_queries=0,
        repetitions=1,
        detailed_stages=True,
    )
    receipt = run_benchmark(
        [entry], queries, [], args.output, settings, split="c5_integration", fold=kwargs["fold"]
    )
    assert receipt["status"] == "complete"
    print("C5 B-worker smoke passed")


if __name__ == "__main__":
    main()
