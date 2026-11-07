"""Publication plots shared by baseline and final quality reports."""

from __future__ import annotations

import os
from collections import defaultdict
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", str(Path(".matplotlib").resolve()))
import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402


def plot_quality(summary: dict, rows: list[dict], output: Path, *, methods: list[str]) -> None:
    domains = sorted(next(iter(summary["summaries"].values()))["domains"])
    width = 0.8 / len(methods)
    figure, axis = plt.subplots(figsize=(8, 4.2))
    x = list(range(len(domains) + 1))
    for index, method in enumerate(methods):
        values = [summary["summaries"][method]["domains"][d]["ndcg_at_10"] for d in domains]
        values.append(summary["summaries"][method]["macro"]["ndcg_at_10"])
        offsets = [v + (index - (len(methods) - 1) / 2) * width for v in x]
        axis.bar(offsets, values, width=width, label=method)
    axis.set_xticks(x, [*domains, "macro"])
    axis.set_ylabel("nDCG@10")
    ymax = max(
        summary["summaries"][m][scope]["ndcg_at_10"]
        if scope == "macro"
        else summary["summaries"][m]["domains"][scope]["ndcg_at_10"]
        for m in methods
        for scope in [*domains, "macro"]
    )
    axis.set_ylim(0, ymax * 1.22)
    axis.grid(axis="y", alpha=0.25)
    axis.legend(frameon=False, ncol=min(len(methods), 5), loc="upper center", fontsize=8)
    figure.tight_layout()
    figure.savefig(output / "quality-ndcg10.png", dpi=200)
    plt.close(figure)
    by_fold = defaultdict(list)
    for row in rows:
        by_fold[(row["method"], row["domain"], int(row["fold"]))].append(float(row["ndcg_at_10"]))
    figure, axes = plt.subplots(1, len(domains), figsize=(8, 3.8), squeeze=False)
    for index, domain in enumerate(domains):
        axis = axes[0][index]
        for method in methods:
            values = [
                sum(by_fold[(method, domain, f)]) / len(by_fold[(method, domain, f)])
                for f in range(5)
            ]
            axis.plot(range(5), values, marker="o", label=method)
        axis.set_title(domain)
        axis.set_xlabel("OOF test fold")
        axis.set_xticks(range(5))
        axis.grid(alpha=0.25)
    axes[0][0].set_ylabel("mean nDCG@10")
    axes[0][-1].legend(frameon=False, fontsize=8)
    figure.tight_layout()
    figure.savefig(output / "fold-stability.png", dpi=200)
    plt.close(figure)
