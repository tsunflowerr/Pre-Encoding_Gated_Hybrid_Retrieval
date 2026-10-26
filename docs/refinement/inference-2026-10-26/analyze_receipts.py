"""Rebuild the supplementary resource audit and plot from retained raw receipts."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from pegh.data.artifacts import atomic_json, file_hash, object_hash
from pegh.profiling.report import load_complete_run
from scripts_shared.report_release import paired_speedups

DOMAINS = ("programmers", "unix")
METHODS = ("h_star", "pe_v1", "pe_v2")


def repeat_bootstrap(groups: list[tuple[int, np.ndarray]]) -> dict:
    rng = np.random.default_rng(42)
    point, boot, total = np.zeros(3), np.zeros((10000, 3)), 0
    for count, values in groups:
        assert values.shape == (5, 3)
        total += count
        point += values.mean(axis=0) * count
        indices = rng.integers(0, 5, size=(10000, 5))
        boot += values[indices].mean(axis=1) * count
    point, boot = point / total, boot / total
    return {
        method: {
            "mean_speedup_percent": float(100 * (1 - point[2] / point[i])),
            "speedup_two_sided_95_percent": np.quantile(
                100 * (1 - boot[:, 2] / boot[:, i]), [0.025, 0.975]
            ).tolist(),
            "unit": "paired process repetition within each fixed fold, query-count weighted",
            "bootstrap_samples": 10000,
            "seed": 42,
        }
        for i, method in enumerate(METHODS[:2])
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-root", type=Path, required=True)
    args = parser.parse_args()
    output = Path(__file__).resolve().parent
    frozen = json.loads((output / "freeze.json").read_text(encoding="utf-8"))
    report = json.loads((output / "report.json").read_text(encoding="utf-8"))
    grouped, peak, conditions, folds = defaultdict(list), defaultdict(list), set(), []
    arrays, repetition_groups = {}, defaultdict(list)
    for domain in DOMAINS:
        for fold in range(5):
            key = f"{domain}_fold_{fold}"
            directory = args.raw_root / "results/benchmark" / key
            manifest, rows, receipts = load_complete_run(directory)
            assert file_hash(directory / "manifest.json") == file_hash(
                output / "online-manifests" / f"{key}.json"
            )
            assert manifest["source_snapshot"]["combined_sha256"] == frozen["source_snapshot_hash"]
            assert not manifest["quality_cache_used"]
            for receipt in receipts:
                runtime = receipt["runtime"]
                conditions.add(
                    object_hash(
                        {
                            k: runtime[k]
                            for k in ("platform", "processor", "resources", "package_versions")
                        }
                    )
                )
                assert runtime["resources"]["effective_affinity"] == [0, 2, 4, 6]
                provenance = receipt["method_provenance"]
                assert (
                    not provenance["query_embedding_cache"] and not provenance["quality_cache_used"]
                )
                if receipt["method"] != "h_star":
                    assert provenance["model"]["inference_execution"] == (
                        "sklearn" if receipt["method"] == "pe_v1" else "numpy"
                    )
                peak[(domain, receipt["method"])].append(
                    receipt["memory"]["os_peak_rss_bytes"]
                    or receipt["memory"]["sampled_peak_rss_bytes"]
                )
            for row in rows:
                grouped[(domain, row["method"])].append(row)
            means = {
                m: float(np.mean([r["total_ns"] / 1e6 for r in rows if r["method"] == m]))
                for m in METHODS
            }
            repetition_groups[domain].append(
                (
                    manifest["query_count"],
                    np.array(
                        [
                            [
                                np.mean(
                                    [
                                        r["total_ns"] / 1e6
                                        for r in rows
                                        if r["method"] == m and r["repetition"] == rep
                                    ]
                                )
                                for m in METHODS
                            ]
                            for rep in range(5)
                        ]
                    ),
                )
            )
            folds.append(
                {
                    "domain": domain,
                    "fold": fold,
                    "mean_ms": means,
                    "mean_reduction_v2_vs_v1_percent": 100 * (1 - means["pe_v2"] / means["pe_v1"]),
                    "started_at_utc": datetime.fromtimestamp(
                        manifest["started_at_unix"], UTC
                    ).isoformat(),
                    "ended_at_utc": datetime.fromtimestamp(
                        manifest["ended_at_unix"], UTC
                    ).isoformat(),
                    "receipt_sha256": {
                        w["directory"]: w["receipt_sha256"] for w in manifest["workers"]
                    },
                }
            )
    assert len(conditions) == 1
    summaries = {}
    for domain in (*DOMAINS, "all"):
        summaries[domain] = {}
        by_method = {}
        for method in METHODS:
            measured = (
                grouped[(domain, method)]
                if domain != "all"
                else [r for d in DOMAINS for r in grouped[(d, method)]]
            )
            samples = defaultdict(list)
            for row in measured:
                samples[row["query_id"]].append(row["total_ns"] / 1e6)
            assert all(len(v) == 5 for v in samples.values())
            by_method[method] = {q: float(np.mean(v)) for q, v in samples.items()}
            peaks = (
                peak[(domain, method)]
                if domain != "all"
                else [v for d in DOMAINS for v in peak[(d, method)]]
            )
            summaries[domain][method] = {
                "query_count": len(samples),
                "requests": len(measured),
                "process_cpu_mean_ms": float(
                    np.mean([r["process_cpu_ns"] / 1e6 for r in measured])
                ),
                "peak_rss_bytes": max(peaks),
            }
            assert len(measured) == report["summaries"][domain][method]["requests"]
        if domain != "all":
            ids = sorted(by_method["h_star"])
            assert all(set(by_method[m]) == set(ids) for m in METHODS)
            arrays[domain] = np.array([[by_method[m][q] for m in METHODS] for q in ids])
    reductions = {
        d: paired_speedups({d: a}, baseline_names=("h_star", "pe_v1")) for d, a in arrays.items()
    }
    reductions["all"] = paired_speedups(arrays, baseline_names=("h_star", "pe_v1"))
    assert reductions["all"] == report["paired_speedup_v2_vs_h_star_and_v1"]
    repeat_reductions = {d: repeat_bootstrap(repetition_groups[d]) for d in DOMAINS}
    repeat_reductions["all"] = repeat_bootstrap([g for d in DOMAINS for g in repetition_groups[d]])
    audit = {
        "schema_version": "inference_resource_audit_v1",
        "source_snapshot_hash": frozen["source_snapshot_hash"],
        "raw_root": str(args.raw_root.resolve()),
        "summaries": summaries,
        "folds": folds,
        "paired_speedups_by_domain": reductions,
        "paired_process_repetition_bootstrap": repeat_reductions,
        "one_hardware_resource_package_condition": True,
        "analysis_source_sha256": file_hash(Path(__file__)),
        "timing_note": "Two completed folds predate the quota pause; the interrupted fold was archived and rerun entirely. Query bootstrap retains method pairs and five repeats; it does not model all process/thermal variation.",
    }
    audit["report_hash"] = object_hash(audit)
    atomic_json(output / "resource-audit.json", audit)

    fig, axes = plt.subplots(1, 3, figsize=(13.4, 5.1))
    labels = ("programmers", "unix", "all")
    x = np.arange(3)
    colors = ("#526879", "#c89b42", "#d95537")
    names = ("H*", "PE-GH sklearn", "PE-GH NumPy")
    for ax, metric, title in (
        (axes[0], "mean_ms", "Mean request latency"),
        (axes[1], "p95_ms", "p95 request latency"),
    ):
        for i, method in enumerate(METHODS):
            ax.bar(
                x + (i - 1) * 0.24,
                [report["summaries"][d][method][metric] for d in labels],
                width=0.24,
                color=colors[i],
                label=names[i],
            )
        ax.set(xticks=x, xticklabels=labels, ylabel="ms", title=title)
        ax.grid(axis="y", alpha=0.2)
        ax.set_axisbelow(True)
        ax.tick_params(axis="x", labelsize=9)
    axes[0].legend(fontsize=8)
    for index, domain in enumerate(labels):
        for values, offset, color, label in (
            (reductions, -0.08, colors[2], "Query CI"),
            (repeat_reductions, 0.08, "#526879", "Process-repeat CI"),
        ):
            value = values[domain]["pe_v1"]
            point = value["mean_speedup_percent"]
            lower, upper = value["speedup_two_sided_95_percent"]
            axes[2].errorbar(
                point,
                index + offset,
                xerr=[[point - lower], [upper - point]],
                fmt="o",
                color=color,
                capsize=4,
                label=label if index == 0 else None,
            )
    axes[2].axvline(0, color="#526879", linewidth=1)
    axes[2].set(
        yticks=x,
        yticklabels=labels,
        xlabel="Mean reduction vs PE-GH sklearn (%)",
        title="Two uncertainty views, 95% CI",
    )
    axes[2].invert_yaxis()
    axes[2].grid(axis="x", alpha=0.2)
    axes[2].legend(fontsize=8, loc="upper center", bbox_to_anchor=(0.5, -0.20), ncol=2)
    fig.suptitle(
        "Exact gate inference optimization — same models, thresholds and rankings", fontsize=13
    )
    fig.tight_layout()
    fig.savefig(output / "inference-comparison.png", dpi=180)
    plt.close(fig)
    print("Audited 150 receipts; rebuilt CPU/RSS summaries, paired confidence intervals and plot.")


if __name__ == "__main__":
    main()
