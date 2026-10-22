"""Create per-query nDCG utility gain from compatible baseline/candidate runs."""

from __future__ import annotations

import argparse

from contracts.io import load_queries
from pegh.data.artifacts import write_jsonl
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
    queries = load_queries(args.queries, args.domain)
    query_ids = [query.query_id for query in queries]
    qrels = load_qrels(args.qrels, args.domain)
    baseline, baseline_metadata = load_rankings(args.baseline_run, domain=args.domain)
    candidate, candidate_metadata = load_rankings(args.candidate_run, domain=args.domain)
    if baseline_metadata["corpus_hash"] != candidate_metadata["corpus_hash"]:
        raise ValueError("utility runs use different corpus hashes")
    baseline_metrics = evaluate_rankings(query_ids, args.domain, qrels, baseline)
    candidate_metrics = evaluate_rankings(query_ids, args.domain, qrels, candidate)
    write_jsonl(args.output, utility_rows(baseline_metrics, candidate_metrics))
    print(f"Wrote utility for {len(query_ids)} queries to {args.output}")


if __name__ == "__main__":
    main()
