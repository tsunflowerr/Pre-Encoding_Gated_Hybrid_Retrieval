"""Create per-query nDCG utility gain from compatible baseline/candidate runs."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from pathlib import Path

from contracts.io import load_queries
from pegh.data.artifacts import atomic_json, file_hash, object_hash, write_jsonl
from pegh.data.qrels import load_qrels
from pegh.evaluation.metrics import evaluate_rankings, utility_rows
from pegh.evaluation.runs import load_rankings


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queries", required=True)
    parser.add_argument("--qrels", required=True)
    parser.add_argument("--baseline-run", required=True)
    parser.add_argument("--candidate-run", required=True)
    parser.add_argument("--domain", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = Path(args.output)
    sidecar = output.with_suffix(output.suffix + ".meta.json")
    if output.exists() or sidecar.exists():
        raise FileExistsError("choose a new utility output path")
    queries = load_queries(args.queries, args.domain)
    query_ids = [query.query_id for query in queries]
    qrels = load_qrels(args.qrels, args.domain)
    baseline, baseline_metadata = load_rankings(args.baseline_run, domain=args.domain)
    candidate, candidate_metadata = load_rankings(args.candidate_run, domain=args.domain)
    if baseline_metadata["corpus_hash"] != candidate_metadata["corpus_hash"]:
        raise ValueError("utility runs use different corpus hashes")
    if set(baseline) != set(query_ids) or set(candidate) != set(query_ids):
        raise ValueError("utility runs must each cover the exact expected query set")
    if (
        baseline_metadata["split"] is None
        or baseline_metadata["split"] != candidate_metadata["split"]
        or baseline_metadata["fold"] != candidate_metadata["fold"]
    ):
        raise ValueError("utility runs must use the same declared split and fold")
    baseline_metrics = evaluate_rankings(query_ids, args.domain, qrels, baseline)
    candidate_metrics = evaluate_rankings(query_ids, args.domain, qrels, candidate)
    write_jsonl(output, utility_rows(baseline_metrics, candidate_metrics))
    atomic_json(
        sidecar,
        {
            "schema_version": "utility_v2",
            "query_count": len(queries),
            "queries_hash": object_hash([asdict(query) for query in queries]),
            "qrels_sha256": file_hash(args.qrels),
            "baseline_sha256": file_hash(args.baseline_run),
            "candidate_sha256": file_hash(args.candidate_run),
            "baseline": baseline_metadata,
            "candidate": candidate_metadata,
            "utility_sha256": file_hash(output),
        },
    )
    print(f"Wrote utility for {len(query_ids)} queries to {args.output}")


if __name__ == "__main__":
    main()
