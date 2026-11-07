"""Create paper-ready quality figures and a query-level failure audit from OOF output."""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import defaultdict
from pathlib import Path

from contracts.io import load_queries
from pegh.evaluation.quality_plot import plot_quality


def _query_class(text: str) -> str:
    if len(text.split()) <= 4:
        return "short"
    if re.search(r"(--?\w+|[/\\]|\w+[.#:]\w+|\([^)]*\))", text):
        return "code_or_cli"
    if len(text.split()) >= 25:
        return "long"
    return "natural_language"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--oof-dir", required=True)
    parser.add_argument("--queries", action="append", required=True, metavar="DOMAIN=PATH")
    parser.add_argument("--output", required=True)
    parser.add_argument("--worst", type=int, default=20)
    args = parser.parse_args()
    source = Path(args.oof_dir)
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    with (source / "summary.json").open(encoding="utf-8") as stream:
        summary = json.load(stream)
    with (source / "per_query.csv").open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    query_text = {}
    for assignment in args.queries:
        domain, path = assignment.split("=", 1)
        query_text.update({query.query_id: query.text for query in load_queries(path, domain)})

    methods = sorted(summary["summaries"])
    plot_quality(summary, rows, output, methods=methods)
    write_baseline_failures(rows, query_text, methods, output, args.worst)


def write_baseline_failures(rows, query_text, methods, output, worst):
    domains = sorted({row["domain"] for row in rows})
    failure_rows = []
    for method in methods:
        for domain in domains:
            selected = sorted(
                (row for row in rows if row["method"] == method and row["domain"] == domain),
                key=lambda row: (float(row["ndcg_at_10"]), row["query_id"]),
            )[:worst]
            for row in selected:
                text = query_text.get(row["query_id"], "")
                failure_rows.append(
                    {
                        "method": method,
                        "domain": domain,
                        "fold": row["fold"],
                        "query_id": row["query_id"],
                        "query_class": _query_class(text),
                        "ndcg_at_10": row["ndcg_at_10"],
                        "mrr_at_10": row["mrr_at_10"],
                        "recall_at_100": row["recall_at_100"],
                        "query": text.replace("\n", " "),
                    }
                )
    with (output / "failure-cases.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(failure_rows[0]))
        writer.writeheader()
        writer.writerows(failure_rows)
    class_counts: dict[str, int] = defaultdict(int)
    for row in failure_rows:
        class_counts[row["query_class"]] += 1
    lines = [
        "# Failure analysis",
        "",
        f"Audit set: bottom {worst} nDCG@10 queries per method and domain.",
        "",
        "| Query class | Count |",
        "|---|---:|",
        *(f"| {name} | {count} |" for name, count in sorted(class_counts.items())),
        "",
        "The CSV beside this report contains query text, fold, and all inspected metrics. "
        "Classes are deterministic lexical heuristics and are descriptive, not causal labels.",
    ]
    (output / "FAILURE_ANALYSIS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote figures and {len(failure_rows)} failure cases under {output}")


if __name__ == "__main__":
    main()
