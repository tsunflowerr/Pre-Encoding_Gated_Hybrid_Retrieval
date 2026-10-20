from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path

import numpy as np

from pegh.dense.artifacts import atomic_json, checked_child, file_hash, read_json
from pegh.profiling.trace import STAGES


def load_complete_run(directory: str | Path) -> tuple[dict, list[dict], list[dict]]:
    directory = Path(directory)
    manifest = read_json(directory / "manifest.json")
    if manifest["status"] != "complete":
        raise ValueError("only complete benchmark runs can be summarized")
    expected = len(manifest["registry"]) * manifest["settings"]["repetitions"]
    if len(manifest["workers"]) != expected:
        raise ValueError("missing worker receipts")
    rows: list[dict] = []
    receipts: list[dict] = []
    seen: set[tuple] = set()
    for worker in manifest["workers"]:
        path = checked_child(directory, worker["directory"])
        receipt = read_json(path / "worker.json")
        if (
            file_hash(path / "worker.json") != worker["receipt_sha256"]
            or file_hash(path / "requests.jsonl") != receipt["requests_sha256"]
            or file_hash(path / "memory_samples.jsonl") != receipt["memory_samples_sha256"]
        ):
            raise ValueError("raw artifact/receipt checksum mismatch")
        if (
            worker["returncode"]
            or receipt["status"] != "complete"
            or receipt["completed_requests"] != manifest["query_count"]
        ):
            raise ValueError("incomplete/failed worker receipt")
        receipts.append(receipt)
        current = [
            json.loads(line)
            for line in (path / "requests.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        if len(current) != manifest["query_count"]:
            raise ValueError("request count differs from receipt")
        for row in current:
            key = (row["method"], row["domain"], row["fold"], row["query_id"], row["repetition"])
            if key in seen:
                raise ValueError("duplicate measured request")
            seen.add(key)
            if (
                row["method"] != worker["method"]
                or row["repetition"] != worker["repetition"]
                or row["total_ns"] < 0
                or row["process_cpu_ns"] < 0
            ):
                raise ValueError("request metadata/timing mismatch")
            if row["encoder_calls"] not in (0, 1):
                raise ValueError("invalid encoder call count")
        rows.extend(current)
    methods = {method["id"] for method in manifest["registry"]}
    by_method: dict[str, dict[int, set[str]]] = defaultdict(lambda: defaultdict(set))
    for row in rows:
        by_method[row["method"]][row["repetition"]].add(row["query_id"])
    if set(by_method) != methods:
        raise ValueError("method set differs from registry")
    canonical_ids: set[str] | None = None
    for repetitions in by_method.values():
        if set(repetitions) != set(range(manifest["settings"]["repetitions"])):
            raise ValueError("repetition coverage mismatch")
        for ids in repetitions.values():
            if canonical_ids is None:
                canonical_ids = ids
            if ids != canonical_ids:
                raise ValueError("query coverage differs across methods/repetitions")
    return manifest, rows, receipts


def summarize_run(directory: str | Path, *, bootstrap_samples: int = 1000, seed: int = 42) -> dict:
    if bootstrap_samples < 1:
        raise ValueError("bootstrap_samples must be positive")
    directory = Path(directory)
    manifest, rows, receipts = load_complete_run(directory)
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for row in rows:
        groups[(row["method"], row["domain"])].append(row)
    summaries = []
    for (method, domain), samples in sorted(groups.items()):
        latencies = np.array([r["total_ns"] / 1e6 for r in samples])
        cpu = np.array([r["process_cpu_ns"] / 1e6 for r in samples])
        clustered: dict[str, list[float]] = defaultdict(list)
        for row in samples:
            clustered[row["query_id"]].append(row["total_ns"] / 1e6)
        if any(len(values) != manifest["settings"]["repetitions"] for values in clustered.values()):
            raise ValueError("each query must retain all timing repetitions")
        query_means = np.array([np.mean(clustered[key]) for key in sorted(clustered)])
        rng = np.random.default_rng(seed)
        bootstrap_means = np.array(
            [
                rng.choice(query_means, size=len(query_means), replace=True).mean()
                for _ in range(bootstrap_samples)
            ]
        )
        memory = [r["memory"] for r in receipts if r["method"] == method]
        peaks = [m["os_peak_rss_bytes"] or m["sampled_peak_rss_bytes"] for m in memory]
        stage_means = {}
        for stage in STAGES:
            values = [row[f"{stage}_ns"] for row in samples]
            stage_means[stage + "_ms"] = (
                None if any(v is None for v in values) else float(np.mean(values) / 1e6)
            )
        summaries.append(
            {
                "method": method,
                "domain": domain,
                "unique_queries": len(clustered),
                "timing_samples": len(samples),
                "repetitions": manifest["settings"]["repetitions"],
                "mean_ms": float(latencies.mean()),
                "p50_ms": float(np.quantile(latencies, 0.5)),
                "p90_ms": float(np.quantile(latencies, 0.9)),
                "p95_ms": float(np.quantile(latencies, 0.95)),
                "cpu_mean_ms": float(cpu.mean()),
                "dense_call_ratio": sum(r["encoder_calls"] for r in samples) / len(samples),
                "mean_ms_ci95": [float(v) for v in np.quantile(bootstrap_means, [0.025, 0.975])],
                "bootstrap_unit": "query retaining all repeats; mean-latency CI only",
                "bootstrap_samples": bootstrap_samples,
                "bootstrap_seed": seed,
                "peak_rss_bytes": max(peaks),
                "rss_load_and_warmup_included": True,
                "stage_means": stage_means,
            }
        )
    report = {
        "schema_version": "1.0",
        "run_id": manifest["run_id"],
        "run_manifest_sha256": file_hash(directory / "manifest.json"),
        "split": manifest["split"],
        "fold": manifest["fold"],
        "quantile_method": "numpy.linear on measured samples; repeats are not independent queries",
        "quality_measured_by_this_report": False,
        "summaries": summaries,
    }
    atomic_json(directory / "summary.json", report)
    flat_rows = [
        {
            key: summary[key]
            for key in (
                "method",
                "domain",
                "unique_queries",
                "timing_samples",
                "dense_call_ratio",
                "mean_ms",
                "p50_ms",
                "p90_ms",
                "p95_ms",
                "cpu_mean_ms",
                "peak_rss_bytes",
            )
        }
        for summary in summaries
    ]
    with (directory / "summary.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(flat_rows[0]))
        writer.writeheader()
        writer.writerows(flat_rows)
    first_runtime = receipts[0]["runtime"]
    lines = [
        f"# Online profile: {manifest['run_id']}",
        "",
        f"Split: `{manifest['split']}`; fold: `{manifest['fold']}`.",
        "",
        f"OS: {first_runtime['platform']}; affinity: "
        f"{first_runtime['resources']['effective_affinity']}; memory policy: "
        f"{first_runtime['resources']['memory_limit_kind']}.",
        "",
        "| Method/domain | Queries × repeats | Dense % | Mean ms | p95 ms | CPU ms | Peak RSS MiB |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in summaries:
        lines.append(
            f"| {row['method']}/{row['domain']} | {row['unique_queries']} × "
            f"{row['repetitions']} | {100 * row['dense_call_ratio']:.1f} | "
            f"{row['mean_ms']:.3f} | {row['p95_ms']:.3f} | "
            f"{row['cpu_mean_ms']:.3f} | {row['peak_rss_bytes'] / 2**20:.1f} |"
        )
    lines.extend(
        [
            "",
            "Model/index load and disk logging are outside request latency. "
            "RSS includes process setup, model/index loading and warmup.",
            "",
            "Quality is not evaluated here. No gate improvement or non-inferiority "
            "is inferred from these timings. Repeated timings are not independent queries.",
            "",
        ]
    )
    if manifest["split"] != "test":
        lines.extend(
            ["This run is development/fixture validation, not the registered final test.", ""]
        )
    (directory / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    return report


def make_figures(directory: str | Path, quality_csv: str | Path | None = None) -> list[str]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    directory = Path(directory)
    manifest, rows, _ = load_complete_run(directory)
    report = read_json(directory / "summary.json")
    outputs = []
    for domain in sorted({r["domain"] for r in rows}):
        fig, axis = plt.subplots(figsize=(7, 4))
        for method in sorted({r["method"] for r in rows}):
            times = sorted(
                r["total_ns"] / 1e6 for r in rows if r["domain"] == domain and r["method"] == method
            )
            if times:
                axis.plot(times, np.arange(1, len(times) + 1) / len(times), label=method)
        axis.set(
            xlabel="Online request latency (ms)",
            ylabel="Empirical CDF",
            title=f"{domain} · {manifest['split']} · batch 1",
        )
        axis.grid(alpha=0.2)
        axis.legend()
        fig.tight_layout()
        path = directory / f"latency-cdf-{domain}.png"
        fig.savefig(path, dpi=160)
        plt.close(fig)
        outputs.append(str(path))
    measured = [
        s for s in report["summaries"] if all(v is not None for v in s["stage_means"].values())
    ]
    if measured:
        fig, axis = plt.subplots(figsize=(9, 4))
        labels = [s["method"] + "/" + s["domain"] for s in measured]
        left = np.zeros(len(measured))
        for stage in STAGES:
            values = np.array([s["stage_means"][stage + "_ms"] for s in measured])
            axis.barh(labels, values, left=left, label=stage)
            left += values
        axis.set(
            xlabel="Mean measured stage time (ms)",
            title="Detailed profile; excludes unassigned overhead",
        )
        axis.legend(ncol=4, fontsize=8)
        fig.tight_layout()
        path = directory / "stage-breakdown.png"
        fig.savefig(path, dpi=160)
        plt.close(fig)
        outputs.append(str(path))
    if quality_csv is not None:
        with Path(quality_csv).open(encoding="utf-8", newline="") as stream:
            quality = list(csv.DictReader(stream))
        if not {"method", "domain", "ndcg_at_10", "run_id"}.issubset(quality[0] if quality else {}):
            raise ValueError("quality CSV requires method,domain,ndcg_at_10,run_id")
        lookup = {(r["method"], r["domain"]): r for r in quality}
        if len(lookup) != len(quality):
            raise ValueError("duplicate quality method/domain rows")
        points = []
        for summary in report["summaries"]:
            row = lookup.get((summary["method"], summary["domain"]))
            if row is None or row["run_id"] != manifest["run_id"]:
                raise ValueError("quality/latency run identity or coverage mismatch")
            value = float(row["ndcg_at_10"])
            if not 0 <= value <= 1:
                raise ValueError("nDCG must be on the 0..1 scale")
            points.append((summary["domain"], summary["method"], summary["mean_ms"], value))
        for domain in sorted({p[0] for p in points}):
            selected = [p for p in points if p[0] == domain]
            fig, axis = plt.subplots(figsize=(7, 4))
            for _, method, latency, value in selected:
                axis.scatter(latency, value)
                axis.annotate(method, (latency, value), fontsize=8)
            frontier = sorted(
                (p[2], p[3])
                for p in selected
                if not any(
                    q[2] <= p[2] and q[3] >= p[3] and (q[2] < p[2] or q[3] > p[3]) for q in selected
                )
            )
            axis.plot(
                [p[0] for p in frontier],
                [p[1] for p in frontier],
                linestyle="--",
                alpha=0.5,
                label="Observed non-dominated points",
            )
            axis.set(
                xlabel="Measured mean latency (ms)",
                ylabel="nDCG@10",
                title=f"{domain} · evaluator A quality · {manifest['split']}",
            )
            axis.legend(fontsize=8)
            fig.tight_layout()
            path = directory / f"quality-latency-{domain}.png"
            fig.savefig(path, dpi=160)
            plt.close(fig)
            outputs.append(str(path))
    return outputs
