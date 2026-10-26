"""Audit frozen online results and paired query-bootstrap latency improvements."""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

import numpy as np

from pegh.data.artifacts import atomic_json, file_hash, object_hash
from pegh.profiling.report import load_complete_run, make_figures, quality_bindings

METHODS = ("h_star", "s_star", "pe_gh")


def paired_speedups(
    arrays: dict[str, np.ndarray], *, samples: int = 10_000, seed: int = 42
) -> dict:
    """Resample queries within domains, keeping all methods and timing repeats paired."""
    if (
        samples < 1
        or not arrays
        or any(
            a.ndim != 2 or a.shape[1] != 3 or len(a) == 0 or not np.isfinite(a).all()
            for a in arrays.values()
        )
    ):
        raise ValueError("paired bootstrap needs finite nonempty query-by-three-method arrays")
    total = sum(len(a) for a in arrays.values())
    point = sum(a.sum(axis=0) for a in arrays.values()) / total
    generator = np.random.default_rng(seed)
    estimates = np.empty((samples, 2), dtype=np.float64)
    for start in range(0, samples, 100):
        size = min(100, samples - start)
        means = np.zeros((size, 3))
        for domain in sorted(arrays):
            values = arrays[domain]
            indices = generator.integers(0, len(values), size=(size, len(values)))
            means += values[indices].sum(axis=1) / total
        if (means[:, :2] <= 0).any():
            raise ValueError("baseline latency must be positive")
        estimates[start : start + size] = 100 * (1 - means[:, 2, None] / means[:, :2])
    return {
        baseline: {
            "mean_speedup_percent": float(100 * (1 - point[2] / point[index])),
            "speedup_two_sided_95_percent": [
                float(v) for v in np.quantile(estimates[:, index], [0.025, 0.975])
            ],
            "speedup_one_sided_lower_95_percent": float(np.quantile(estimates[:, index], 0.05)),
            "bootstrap_samples": samples,
            "seed": seed,
            "unit": "query stratified by domain; all methods and all repeats retained",
        }
        for index, baseline in enumerate(METHODS[:2])
    }


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def metrics(rows: list[dict], peaks: list[int]) -> dict:
    values = np.array([r["total_ns"] / 1e6 for r in rows])
    return {
        "unique_queries": len({r["query_id"] for r in rows}),
        "timing_samples": len(rows),
        "mean_ms": float(values.mean()),
        "p95_ms": float(np.quantile(values, 0.95)),
        "cpu_mean_ms": float(np.mean([r["process_cpu_ns"] / 1e6 for r in rows])),
        "peak_rss_bytes": max(peaks),
        "dense_call_ratio": sum(r["encoder_calls"] for r in rows) / len(rows),
    }


def build_report(root: Path, *, samples: int = 10_000) -> dict:
    frozen = read(root / "results/frozen/c6_manifest.json")
    facts = read(root / "results/reports/release-facts.json")
    if (
        facts["freeze_hash"] != frozen["freeze_hash"]
        or facts["online_status"] != "complete"
        or facts["online_ranking_matches"] != 1948 * 3 * 5
    ):
        raise ValueError("complete frozen online/offline C audit is required")
    if object_hash({k: v for k, v in facts.items() if k != "report_hash"}) != facts["report_hash"]:
        raise ValueError("C report checksum differs")
    grouped, peaks = defaultdict(list), defaultdict(list)
    runs, conditions = [], set()
    quality = read(root / "results/oof/c6_final/summary.json")
    with (root / "results/oof/c6_final/per_query.csv").open(encoding="utf-8", newline="") as stream:
        quality_rows = list(csv.DictReader(stream))
    first_runtime = None
    for domain in ("programmers", "unix"):
        for fold in range(5):
            key = f"{domain}_fold_{fold}"
            directory = root / "results/benchmark/c6_full" / key
            manifest, rows, receipts = load_complete_run(directory)
            expected_registry = read(root / f"results/frozen/benchmark/{key}.json")
            if (
                manifest["registry_hash"] != object_hash(expected_registry["methods"])
                or manifest["queries_hash"]
                != frozen["benchmark_inputs"][key]["test"]["queries_hash"]
                or manifest["settings"]["detailed_stages"]
            ):
                raise ValueError(
                    "final benchmark registry/query identity or timing profile differs"
                )
            for receipt in receipts:
                runtime = receipt["runtime"]
                first_runtime = first_runtime or runtime
                conditions.add(
                    object_hash(
                        {
                            k: runtime[k]
                            for k in ("platform", "processor", "resources", "package_versions")
                        }
                    )
                )
                method = receipt["method"]
                if (
                    receipt["method_provenance"]["sparse_execution"]
                    != frozen["domains"][domain]["sparse_execution"]
                ):
                    raise ValueError("methods did not use the same frozen sparse execution")
                memory = receipt["memory"]
                peaks[(domain, method)].append(
                    memory["os_peak_rss_bytes"] or memory["sampled_peak_rss_bytes"]
                )
            scores = {}
            for method in METHODS:
                offline = root / f"results/oof_runs/{method}/{domain}/fold_{fold}.jsonl"
                sidecar = read(offline.with_suffix(".jsonl.meta.json"))
                if (
                    sidecar["freeze_hash"] != frozen["freeze_hash"]
                    or file_hash(offline) != sidecar["ranking_sha256"]
                ):
                    raise ValueError("quality input differs from freeze")
                expected_ids = {
                    r["query_id"]: object_hash([h["doc_id"] for h in r["hits"]])
                    for r in (
                        json.loads(line)
                        for line in offline.read_text(encoding="utf-8").splitlines()
                    )
                }
                measured = [row for row in rows if row["method"] == method]
                if any(
                    row["ranking_hash"] != expected_ids.get(row["query_id"])
                    or row["stage_calls"].get("sparse") != 1
                    for row in measured
                ):
                    raise ValueError(
                        "online ranking/sparse calls differ from the frozen quality result"
                    )
                if sum(r["encoder_calls"] for r in measured) != 5 * sidecar["dense_count"]:
                    raise ValueError("online encoder counts differ from the frozen gate")
                values = [
                    r
                    for r in quality_rows
                    if r["method"] == method and r["domain"] == domain and int(r["fold"]) == fold
                ]
                if len(values) != len(expected_ids):
                    raise ValueError("quality score coverage differs from online queries")
                scores[method] = sum(float(r["ndcg_at_10"]) for r in values) / len(values)
                grouped[(domain, method)].extend(measured)
            csv_path = directory / "quality.csv"
            bindings = quality_bindings(directory)
            with csv_path.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(
                    stream,
                    fieldnames=[
                        "method",
                        "domain",
                        "ndcg_at_10",
                        "run_id",
                        "queries_hash",
                        "method_provenance_hash",
                    ],
                )
                writer.writeheader()
                writer.writerows(
                    {**binding, "ndcg_at_10": scores[binding["method"]]} for binding in bindings
                )
            make_figures(directory, csv_path)
            runs.append(
                {
                    "domain": domain,
                    "fold": fold,
                    "manifest_sha256": file_hash(directory / "manifest.json"),
                    "summary_sha256": file_hash(directory / "summary.json"),
                    "quality_csv_sha256": file_hash(csv_path),
                    "backend_threads_by_method": {
                        r["method"]: r["runtime"]["backend_threads_after_factory"] for r in receipts
                    },
                }
            )
    if len(conditions) != 1:
        raise ValueError("hardware/resources/packages differed across final runs")
    summary, query_arrays = {}, {}
    for domain, expected_count in (("programmers", 876), ("unix", 1072)):
        summary[domain], by_query = {}, {}
        for method in METHODS:
            rows = grouped[(domain, method)]
            query_rows = defaultdict(list)
            for row in rows:
                query_rows[row["query_id"]].append(row["total_ns"] / 1e6)
            if len(query_rows) != expected_count or any(len(v) != 5 for v in query_rows.values()):
                raise ValueError("each canonical query must retain five timing repeats")
            by_query[method] = {q: float(np.mean(v)) for q, v in query_rows.items()}
            summary[domain][method] = metrics(rows, peaks[(domain, method)])
            summary[domain][method]["ndcg_at_10"] = quality["summaries"][method]["domains"][domain][
                "ndcg_at_10"
            ]
        ids = sorted(by_query[METHODS[0]])
        if any(set(by_query[m]) != set(ids) for m in METHODS):
            raise ValueError("paired method query sets differ")
        query_arrays[domain] = np.array([[by_query[m][q] for m in METHODS] for q in ids])
    summary["all"] = {
        m: metrics(
            [r for domain in ("programmers", "unix") for r in grouped[(domain, m)]],
            [v for domain in ("programmers", "unix") for v in peaks[(domain, m)]],
        )
        for m in METHODS
    }
    improvements = {
        domain: paired_speedups({domain: values}, samples=samples)
        for domain, values in query_arrays.items()
    }
    improvements["all"] = paired_speedups(query_arrays, samples=samples)
    margin = facts["noninferiority_margin"]
    return {
        "schema_version": "pegh_integration_release_v2",
        "freeze_hash": frozen["freeze_hash"],
        "source_snapshot_hash": frozen["source_snapshot_hash"],
        "runtime": {
            k: first_runtime[k] for k in ("platform", "processor", "resources", "package_versions")
        },
        "measured_requests": sum(len(v) for v in grouped.values()),
        "every_online_ranking_matches_frozen_offline": True,
        "runtime_comparisons_use_same_fast_backend": True,
        "summaries": summary,
        "paired_speedups": improvements,
        "quality_comparison": facts["comparison"],
        "targets": {
            "dense_ratio_at_most_60_percent": summary["all"]["pe_gh"]["dense_call_ratio"] <= 0.60,
            "mean_latency_reduction_at_least_20_percent_vs_h_star": improvements["all"]["h_star"][
                "mean_speedup_percent"
            ]
            >= 20,
            "quality_noninferiority_macro": facts["comparison"]["macro"]["one_sided_lower_95"]
            > -margin,
            "quality_noninferiority_each_domain": all(
                v["one_sided_lower_95"] > -margin for v in facts["comparison"]["domains"].values()
            ),
        },
        "quality_methods": facts["methods"],
        "runs": runs,
        "limitations": [
            "query-bootstrap intervals condition on fixed models/execution selections and observed timing repeats",
            "Windows memory cap is process commit memory, RSS is measured separately",
            "wall-time comparisons apply to the same local machine/backend/profile; no cross-machine speedup is inferred",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="results/reports/integration_release.json")
    args = parser.parse_args()
    root = Path.cwd()
    report = build_report(root)
    report["report_hash"] = object_hash(report)
    atomic_json(root / args.output, report)
    print(
        json.dumps(
            {"targets": report["targets"], "paired_speedups": report["paired_speedups"]["all"]},
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
