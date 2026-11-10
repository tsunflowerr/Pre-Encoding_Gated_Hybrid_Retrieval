"""Build the C7 gate analysis report and figures from frozen A/B/C artifacts."""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import yaml

from pegh.data.artifacts import atomic_json, file_hash, object_hash
from pegh.profiling.provenance import source_snapshot
from pegh.profiling.report import load_complete_run


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _figure_quality(rows: list[dict], output: Path) -> None:
    fig, ax = plt.subplots(figsize=(8.4, 5.6))
    for row in rows:
        method = row["method"]
        color = "#d95537" if method == "pe_gh" else "#526879"
        size = 100 if method == "pe_gh" else 43
        ax.scatter(row["dense_ratio"], row["macro_ndcg_at_10"], s=size, color=color, zorder=3)
    labeled = (
        "bm25",
        "dense",
        "s_star",
        "pe_gh",
        "logistic_gain_full",
        "linear_svc_gain_general",
        "bm25_margin",
        "rrf",
    )
    by_name = {row["method"]: row for row in rows}
    offsets = {
        "bm25": (6, 7),
        "dense": (-38, 7),
        "s_star": (-48, 8),
        "pe_gh": (6, -15),
        "logistic_gain_full": (6, 7),
        "linear_svc_gain_general": (-112, -12),
        "bm25_margin": (6, -15),
        "rrf": (-28, 7),
    }
    for method in labeled:
        row = by_name[method]
        ax.annotate(
            method.replace("_", " "),
            (row["dense_ratio"], row["macro_ndcg_at_10"]),
            xytext=offsets[method],
            textcoords="offset points",
            fontsize=8,
        )
    ax.set(
        xlabel="Dense calls / test queries",
        ylabel="Macro nDCG@10",
        title="Quality versus dense-call ratio on OOF test queries",
    )
    ax.set_xlim(-0.04, 1.12)
    ax.grid(alpha=0.2)
    fig.tight_layout()
    fig.savefig(output, dpi=180)
    plt.close(fig)


def _figure_validation(thresholds: dict, output: Path) -> None:
    fig, ax = plt.subplots(figsize=(8.4, 5.4))
    for fold in range(5):
        entry = thresholds["folds"][str(fold)]["ridge_gain_full"]
        grid = entry["grid"]
        ax.plot(
            [item["actual_dense_ratio"] for item in grid],
            [item["macro_loss_vs_s_star"] for item in grid],
            marker="o",
            markersize=3,
            label=f"fold {fold}",
        )
        chosen = next(
            item for item in grid if item["desired_dense_budget"] == entry["selected_budget"]
        )
        ax.scatter(
            [chosen["actual_dense_ratio"]],
            [chosen["macro_loss_vs_s_star"]],
            marker="*",
            s=110,
            edgecolor="black",
            linewidth=0.4,
            zorder=5,
        )
    ax.axhline(0.005, color="#a33b3b", linestyle="--", linewidth=1, label="macro loss limit")
    ax.set(
        xlabel="Validation dense-call ratio",
        ylabel="S* nDCG@10 minus routed nDCG@10",
        title="Registered validation thresholds (stars: selected)",
    )
    ax.grid(alpha=0.2)
    ax.legend(ncol=3, fontsize=8)
    fig.tight_layout()
    fig.savefig(output, dpi=180)
    plt.close(fig)


def _figure_folds(folds: dict, output: Path) -> None:
    domains = ("programmers", "unix")
    values = np.array(
        [
            [folds[f"{domain}.fold_{fold}"]["quality_delta"] for fold in range(5)]
            for domain in domains
        ]
    )
    ratios = np.array(
        [[folds[f"{domain}.fold_{fold}"]["dense_ratio"] for fold in range(5)] for domain in domains]
    )
    fig, axes = plt.subplots(2, 1, figsize=(8.4, 4.9), constrained_layout=True)
    panels = (
        (values, "PE-GH minus S* nDCG@10", "coolwarm", -0.02, 0.02),
        (ratios, "PE-GH dense-call ratio", "Blues", 0, 1),
    )
    for ax, (matrix, title, cmap, low, high) in zip(axes, panels, strict=True):
        image = ax.imshow(matrix, cmap=cmap, vmin=low, vmax=high, aspect="auto")
        ax.set(
            yticks=range(2),
            yticklabels=domains,
            xticks=range(5),
            xticklabels=[f"fold {index}" for index in range(5)],
            title=title,
        )
        for row in range(2):
            for col in range(5):
                ax.text(
                    col,
                    row,
                    f"{matrix[row, col]:+.3f}" if ax is axes[0] else f"{matrix[row, col]:.2f}",
                    ha="center",
                    va="center",
                    fontsize=8,
                )
        fig.colorbar(image, ax=ax, shrink=0.78)
    fig.savefig(output, dpi=180)
    plt.close(fig)


def _figure_random(diagnostic: dict, output: Path) -> None:
    values = [item["macro_ndcg_at_10"] for item in diagnostic["random30"]["per_seed"].values()]
    pegh = diagnostic["pe_gh"]["macro_ndcg_at_10"]
    oracle = diagnostic["oracle"]["macro_ndcg_at_10"]
    fig, (distribution, overview) = plt.subplots(
        1, 2, figsize=(9.5, 4.3), gridspec_kw={"width_ratios": [3, 2]}
    )
    distribution.hist(values, bins=10, color="#7298a7", edgecolor="white")
    distribution.axvline(pegh, color="#d95537", linewidth=2, label="PE-GH")
    distribution.set(
        xlabel="Macro nDCG@10",
        ylabel="Seeds",
        title="30 random seeds",
        xlim=(min(values) - 0.001, pegh + 0.001),
    )
    distribution.legend()
    distribution.grid(axis="y", alpha=0.2)
    names = ("random mean", "PE-GH", "batch oracle")
    scores = (diagnostic["random30"]["macro_mean_ndcg_at_10"], pegh, oracle)
    overview.barh(names, scores, color=("#7298a7", "#d95537", "#394b5c"))
    overview.set(xlim=(0.29, 0.34), xlabel="Macro nDCG@10", title="Exact dense budget")
    overview.invert_yaxis()
    for index, score in enumerate(scores):
        overview.text(score + 0.0004, index, f"{score:.4f}", va="center", fontsize=8)
    overview.grid(axis="x", alpha=0.2)
    fig.tight_layout()
    fig.savefig(output, dpi=180)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="results/reports/c7_report.json")
    parser.add_argument("--figure-dir", default="paper/figures")
    parser.add_argument("--facts-output", default="docs/person_c/validation/C7_FACTS.json")
    args = parser.parse_args()
    root = Path.cwd()
    freeze_path = root / "results/frozen/c6_manifest.json"
    frozen = _read(freeze_path)
    if (
        object_hash({key: value for key, value in frozen.items() if key != "freeze_hash"})
        != frozen["freeze_hash"]
        or source_snapshot()["combined_sha256"] != frozen["source_snapshot_hash"]
    ):
        raise ValueError("C6 freeze or executable source changed")
    threshold_path = root / "results/thresholds/c6_validation.json"
    thresholds = _read(threshold_path)
    if file_hash(threshold_path) != frozen["threshold_report_sha256"]:
        raise ValueError("threshold report changed after freeze")
    quality_path = root / "results/oof/c6_controls/summary.json"
    main_quality_path = root / "results/oof/c6_final/summary.json"
    comparison_path = root / "results/oof/c6_final/comparison.json"
    diagnostic_path = root / "results/oof/c6_final/random30_oracle.json"
    quality, main_quality = _read(quality_path), _read(main_quality_path)
    comparison, diagnostic = _read(comparison_path), _read(diagnostic_path)
    if comparison["baseline"] != "s_star" or comparison["candidate"] != "pe_gh":
        raise ValueError("unexpected final comparison")
    if diagnostic["freeze_hash"] != frozen["freeze_hash"] or len(quality["summaries"]) != 14:
        raise ValueError("diagnostic or control method coverage differs")
    for method in main_quality["summaries"]:
        if quality["summaries"][method] != main_quality["summaries"][method]:
            raise ValueError("primary quality differs after adding controls")
    methods = []
    for method, scores in sorted(quality["summaries"].items()):
        sidecars = [
            root / f"results/oof_runs/{method}/{domain}/fold_{fold}.jsonl.meta.json"
            for domain in ("programmers", "unix")
            for fold in range(5)
        ]
        density = 0 if method == "bm25" else sum(_read(path)["dense_count"] for path in sidecars)
        methods.append(
            {
                "method": method,
                "macro_ndcg_at_10": scores["macro"]["ndcg_at_10"],
                "dense_count": density,
                "dense_ratio": density / 1948,
            }
        )
    per_query_path = root / "results/oof/c6_final/per_query.csv"
    with per_query_path.open(encoding="utf-8", newline="") as stream:
        per_query = list(csv.DictReader(stream))
    grouped: dict[tuple[str, str, int], list[float]] = defaultdict(list)
    for row in per_query:
        grouped[(row["method"], row["domain"], int(row["fold"]))].append(float(row["ndcg_at_10"]))
    folds = {}
    for domain in ("programmers", "unix"):
        for fold in range(5):
            sidecar = _read(root / f"results/oof_runs/pe_gh/{domain}/fold_{fold}.jsonl.meta.json")
            pe, baseline = grouped[("pe_gh", domain, fold)], grouped[("s_star", domain, fold)]
            folds[f"{domain}.fold_{fold}"] = {
                "query_count": len(pe),
                "dense_count": sidecar["dense_count"],
                "dense_ratio": sidecar["dense_ratio"],
                "quality_delta": sum(pe) / len(pe) - sum(baseline) / len(baseline),
            }
    sample_dir = root / "results/benchmark/c6_programmers_fold_0"
    sample_manifest, sample_rows, sample_receipts = load_complete_run(sample_dir)
    if (
        sample_manifest["split"] != "test"
        or sample_manifest["fold"] != 0
        or sample_manifest["settings"]["repetitions"] != 1
        or any(
            receipt["source_hash"] != frozen["source_snapshot_hash"] for receipt in sample_receipts
        )
    ):
        raise ValueError("online integration sample differs from frozen method")
    sample_summary = _read(sample_dir / "summary.json")
    full_online_root = root / "results/benchmark/c6_full"
    expected_online = [
        (domain, fold, full_online_root / f"{domain}_fold_{fold}")
        for domain in ("programmers", "unix")
        for fold in range(5)
    ]
    complete_online = []
    online_full_fold_summaries = []
    online_rows: dict[tuple[str, str], list[dict]] = defaultdict(list)
    online_rss: dict[tuple[str, str], list[int]] = defaultdict(list)
    online_ranking_matches = 0
    for domain, fold, directory in expected_online:
        if not (directory / "summary.json").is_file():
            continue
        manifest, rows, receipts = load_complete_run(directory)
        if (
            manifest["domain"] != domain
            or manifest["fold"] != fold
            or manifest["split"] != "test"
            or manifest["settings"]["repetitions"] != 5
            or {method["id"] for method in manifest["registry"]} != {"h_star", "s_star", "pe_gh"}
            or any(receipt["source_hash"] != frozen["source_snapshot_hash"] for receipt in receipts)
        ):
            raise ValueError(f"full online run differs from frozen profile: {directory}")
        summary = _read(directory / "summary.json")
        if (
            summary["run_manifest_sha256"] != file_hash(directory / "manifest.json")
            or {row["method"] for row in summary["summaries"]} != {"h_star", "s_star", "pe_gh"}
            or any(
                row["repetitions"] != 5 or row["domain"] != domain for row in summary["summaries"]
            )
        ):
            raise ValueError(f"full online summary differs from verified run: {directory}")
        for method in ("h_star", "s_star", "pe_gh"):
            offline = root / f"results/oof_runs/{method}/{domain}/fold_{fold}.jsonl"
            sidecar = _read(offline.with_suffix(offline.suffix + ".meta.json"))
            if (
                file_hash(offline) != sidecar["ranking_sha256"]
                or sidecar["freeze_hash"] != frozen["freeze_hash"]
            ):
                raise ValueError(f"offline ranking differs from frozen run: {offline}")
            with offline.open(encoding="utf-8") as stream:
                expected = {
                    record["query_id"]: object_hash([hit["doc_id"] for hit in record["hits"]])
                    for record in (json.loads(line) for line in stream)
                }
            measured = [row for row in rows if row["method"] == method]
            if len(expected) != sidecar["query_count"] or len(measured) != 5 * len(expected):
                raise ValueError(f"online/offline query coverage differs: {offline}")
            if any(
                row["ranking_hash"] != expected.get(row["query_id"])
                or row["encoder_calls"] != int(row["use_dense"])
                or (method != "pe_gh" and row["encoder_calls"] != 1)
                for row in measured
            ):
                raise ValueError(f"online ranking or encoder call differs from offline: {offline}")
            if sum(row["encoder_calls"] for row in measured) != 5 * sidecar["dense_count"]:
                raise ValueError(f"online dense count differs from offline: {offline}")
            online_rows[(domain, method)].extend(measured)
            online_ranking_matches += len(measured)
        for item in summary["summaries"]:
            online_rss[(domain, item["method"])].append(item["peak_rss_bytes"])
        complete_online.append(directory)
        online_full_fold_summaries.append(
            {
                "domain": domain,
                "fold": fold,
                "summary_sha256": file_hash(directory / "summary.json"),
                "methods": summary["summaries"],
            }
        )
    online_status = (
        "complete"
        if len(complete_online) == 10
        else "partial_full_run"
        if complete_online
        else "integration_sample_only"
    )
    online_pooled = {}
    if online_status == "complete":
        if online_ranking_matches != 1948 * 3 * 5:
            raise ValueError("full online request count differs from OOF test coverage")
        for domain in ("programmers", "unix"):
            online_pooled[domain] = {}
            for method in ("h_star", "s_star", "pe_gh"):
                measured = online_rows[(domain, method)]
                latency = np.array([row["total_ns"] / 1e6 for row in measured])
                online_pooled[domain][method] = {
                    "unique_queries": len({row["query_id"] for row in measured}),
                    "timing_samples": len(measured),
                    "mean_ms": float(latency.mean()),
                    "p95_ms": float(np.quantile(latency, 0.95)),
                    "cpu_mean_ms": float(
                        np.mean([row["process_cpu_ns"] / 1e6 for row in measured])
                    ),
                    "dense_call_ratio": sum(row["encoder_calls"] for row in measured)
                    / len(measured),
                    "peak_rss_bytes": max(online_rss[(domain, method)]),
                    "sparse_mean_ms": None
                    if any(row["sparse_ns"] is None for row in measured)
                    else float(np.mean([row["sparse_ns"] / 1e6 for row in measured])),
                }
        online_pooled["all"] = {}
        for method in ("h_star", "s_star", "pe_gh"):
            measured = online_rows[("programmers", method)] + online_rows[("unix", method)]
            latency = np.array([row["total_ns"] / 1e6 for row in measured])
            online_pooled["all"][method] = {
                "unique_queries": len({row["query_id"] for row in measured}),
                "timing_samples": len(measured),
                "mean_ms": float(latency.mean()),
                "p95_ms": float(np.quantile(latency, 0.95)),
                "cpu_mean_ms": float(np.mean([row["process_cpu_ns"] / 1e6 for row in measured])),
                "dense_call_ratio": sum(row["encoder_calls"] for row in measured) / len(measured),
                "peak_rss_bytes": max(
                    max(online_rss[(domain, method)]) for domain in ("programmers", "unix")
                ),
                "sparse_mean_ms": None
                if any(row["sparse_ns"] is None for row in measured)
                else float(np.mean([row["sparse_ns"] / 1e6 for row in measured])),
            }
            if online_pooled["all"][method]["unique_queries"] != 1948:
                raise ValueError("full online query IDs do not cover the OOF test set exactly once")
    figure_dir = root / args.figure_dir
    figure_dir.mkdir(parents=True, exist_ok=True)
    figures = {
        "quality_compute": figure_dir / "c7_quality_compute.png",
        "validation_thresholds": figure_dir / "c7_validation_thresholds.png",
        "fold_analysis": figure_dir / "c7_fold_analysis.png",
        "random_oracle": figure_dir / "c7_random_oracle.png",
    }
    _figure_quality(methods, figures["quality_compute"])
    _figure_validation(thresholds, figures["validation_thresholds"])
    _figure_folds(folds, figures["fold_analysis"])
    _figure_random(diagnostic, figures["random_oracle"])
    margin = yaml.safe_load((root / "configs/gating/protocol_v1.yaml").read_text(encoding="utf-8"))[
        "test"
    ]["noninferiority_margin"]
    report = {
        "schema_version": "c7_gate_report_v1",
        "freeze_hash": frozen["freeze_hash"],
        "input_sha256": {
            name: file_hash(path)
            for name, path in {
                "freeze": freeze_path,
                "thresholds": threshold_path,
                "quality_controls": quality_path,
                "quality_primary": main_quality_path,
                "comparison": comparison_path,
                "diagnostic": diagnostic_path,
                "per_query": per_query_path,
                "online_sample": sample_dir / "summary.json",
            }.items()
        },
        "methods": methods,
        "folds": folds,
        "comparison": comparison,
        "noninferiority_margin": margin,
        "observed_noninferiority": comparison["macro"]["one_sided_lower_95"] > -margin,
        "random30_macro_mean_ndcg_at_10": diagnostic["random30"]["macro_mean_ndcg_at_10"],
        "oracle_macro_ndcg_at_10": diagnostic["oracle"]["macro_ndcg_at_10"],
        "online_status": online_status,
        "online_complete_fold_count": len(complete_online),
        "online_full_fold_summaries": online_full_fold_summaries,
        "online_pooled": online_pooled,
        "online_ranking_matches": online_ranking_matches,
        "online_integration_sample": sample_summary["summaries"],
        "online_sample_request_count": len(sample_rows),
        "figures": {
            key: {"path": path.relative_to(root).as_posix(), "sha256": file_hash(path)}
            for key, path in figures.items()
        },
    }
    report["report_hash"] = object_hash(report)
    atomic_json(root / args.output, report)
    atomic_json(root / args.facts_output, report)
    print(f"C7 report: {report['report_hash']}")
    print(f"online status: {online_status}")


if __name__ == "__main__":
    main()
