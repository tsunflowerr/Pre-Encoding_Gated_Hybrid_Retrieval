"""Evaluate one ranking-v1 run; missing expected queries receive zero scores."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from contracts.io import load_queries
from pegh.data.artifacts import atomic_json, file_hash
from pegh.data.qrels import load_qrels
from pegh.evaluation.metrics import aggregate_metrics, evaluate_rankings
from pegh.evaluation.runs import load_rankings


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queries", required=True)
    parser.add_argument("--qrels", required=True)
    parser.add_argument("--run", required=True)
    parser.add_argument("--domain", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    queries = load_queries(args.queries, args.domain)
    qrels = load_qrels(args.qrels, args.domain)
    rankings, run_metadata = load_rankings(args.run, domain=args.domain)
    rows = evaluate_rankings([query.query_id for query in queries], args.domain, qrels, rankings)
    csv_path = output / "per_query.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0].as_dict()))
        writer.writeheader()
        writer.writerows(row.as_dict() for row in rows)
    summary = {
        "schema_version": "1.0",
        "domain": args.domain,
        "metrics": aggregate_metrics(rows),
        "run": run_metadata,
        "inputs": {
            "queries_sha256": file_hash(args.queries),
            "qrels_sha256": file_hash(args.qrels),
            "run_sha256": file_hash(args.run),
        },
        "policies": {"remove_self_qrel": True, "missing_query_score": 0.0},
    }
    atomic_json(output / "summary.json", summary)
    print(summary["metrics"])


if __name__ == "__main__":
    main()
