"""Run strict five-fold OOF evaluation from a versioned run registry."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from pegh.data.artifacts import atomic_json
from pegh.evaluation.oof import run_oof


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--bootstrap-samples", type=int, default=10_000)
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    report = run_oof(args.registry, bootstrap_samples=args.bootstrap_samples)
    rows = report.pop("per_query")
    utility = report.pop("utility")
    with (output / "per_query.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    atomic_json(output / "summary.json", report)
    if report["comparison"] is not None:
        atomic_json(output / "comparison.json", report["comparison"])
    if utility:
        with (output / "utility.csv").open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(utility[0]))
            writer.writeheader()
            writer.writerows(utility)
    table_rows = []
    for method, values in report["summaries"].items():
        table_rows.append(
            {
                "method": method,
                **{
                    f"{domain}_{metric}": score
                    for domain, domain_values in values["domains"].items()
                    for metric, score in domain_values.items()
                    if metric not in {"query_count", "missing_or_empty_rankings"}
                },
                **{
                    f"macro_{metric}": score
                    for metric, score in values["macro"].items()
                    if metric != "domain_count"
                },
            }
        )
    with (output / "quality_table.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(table_rows[0]))
        writer.writeheader()
        writer.writerows(table_rows)
    print(json.dumps(report["summaries"], indent=2))


if __name__ == "__main__":
    main()
