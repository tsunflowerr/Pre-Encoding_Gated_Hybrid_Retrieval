"""Static figures for the v4 report; same palette and axes style as v3."""

from __future__ import annotations

from pathlib import Path

from pegh.v3.figures import GRID, INK, MARKERS, MUTED, SERIES, SURFACE, _axes, plt

__all__ = ["budget_curves", "forest", "pareto"]


def budget_curves(panels: list[dict], output: Path) -> None:
    """v3 layout, but the legend sits top-left (under the H* label), clear of the P* line."""
    fig, axes = plt.subplots(1, len(panels), figsize=(6.0 * len(panels), 4.6), facecolor=SURFACE)
    axes = axes if len(panels) > 1 else [axes]
    for ax, panel in zip(axes, panels, strict=True):
        _axes(ax, panel["title"], "Tỷ lệ query được encode (ngân sách dense)", "Macro nDCG@10")
        budgets = panel["budgets"]
        for slot, (label, values) in enumerate(panel["series"].items()):
            ax.plot(
                budgets,
                values,
                color=SERIES[slot],
                linewidth=2,
                marker=MARKERS[slot],
                markersize=5,
                label=label,
            )
        references = sorted(panel.get("references", {}).items(), key=lambda item: -item[1])
        for rank, (name, value) in enumerate(references):
            ax.axhline(value, color=MUTED, linewidth=1, linestyle="--")
            ax.annotate(
                name,
                (budgets[0], value),
                textcoords="offset points",
                xytext=(0, 4 if rank == 0 else -4),
                va="bottom" if rank == 0 else "top",
                color=MUTED,
                fontsize=8,
            )
        ax.set_xlim(budgets[0] - 0.03, budgets[-1] + 0.03)
        ax.legend(
            frameon=False, labelcolor=INK, fontsize=8, loc="upper left", bbox_to_anchor=(0, 0.93)
        )
    fig.tight_layout()
    fig.savefig(output, dpi=180, facecolor=SURFACE)
    plt.close(fig)


def pareto(points: list[dict], output: Path, title: str) -> None:
    """points: name, latency_ms, ndcg, family ('v1'/'v2'), optional offset and ha."""
    fig, ax = plt.subplots(figsize=(8.6, 5.4), facecolor=SURFACE)
    _axes(ax, title, "Độ trễ trung bình mỗi query (ms)", "Macro nDCG@10 (OOF)")
    for slot, family, label in ((0, "v1", "PE-GH v1 và mốc cũ"), (1, "v2", "PE-GH v2 và mốc mới")):
        chosen = [p for p in points if p["family"] == family]
        ax.scatter(
            [p["latency_ms"] for p in chosen],
            [p["ndcg"] for p in chosen],
            s=64,
            color=SERIES[slot],
            marker=MARKERS[slot],
            edgecolor=SURFACE,
            linewidth=2,
            label=label,
            zorder=3,
        )
    for p in points:
        ax.annotate(
            p["name"],
            (p["latency_ms"], p["ndcg"]),
            textcoords="offset points",
            xytext=p.get("offset", (7, 5)),
            ha=p.get("ha", "left"),
            color=INK,
            fontsize=8.5,
        )
    ax.legend(frameon=False, labelcolor=INK, loc="lower right")
    fig.tight_layout()
    fig.savefig(output, dpi=180, facecolor=SURFACE)
    plt.close(fig)


def forest(rows: list[dict], output: Path, title: str) -> None:
    """rows: label, estimate, low, high, verdict; non-inferiority margin drawn at -0.01."""
    fig, ax = plt.subplots(figsize=(8.8, 0.62 * len(rows) + 1.5), facecolor=SURFACE)
    _axes(ax, title, "Chênh lệch macro nDCG@10", "")
    for index, row in enumerate(reversed(rows)):
        ax.plot([row["low"], row["high"]], [index, index], color=SERIES[0], linewidth=2)
        ax.scatter(
            [row["estimate"]],
            [index],
            color=SERIES[0],
            s=64,
            edgecolor=SURFACE,
            linewidth=2,
            zorder=3,
        )
        ax.annotate(
            row["verdict"],
            (row["high"], index),
            textcoords="offset points",
            xytext=(8, 0),
            va="center",
            color=INK,
            fontsize=8,
        )
    ax.axvline(0, color=MUTED, linewidth=1)
    ax.axvline(-0.01, color=MUTED, linewidth=1, linestyle="--")
    ax.annotate(
        "biên không-kém −0,01",
        (-0.01, len(rows) - 1),
        textcoords="offset points",
        xytext=(4, -10),
        va="top",
        color=MUTED,
        fontsize=8,
    )
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels([r["label"] for r in reversed(rows)], color=INK, fontsize=9)
    low, high = min(r["low"] for r in rows), max(r["high"] for r in rows)
    ax.set_xlim(min(low, -0.012) - 0.002, high + (high - low) * 0.45)
    ax.grid(color=GRID, linewidth=0.8)
    fig.tight_layout()
    fig.savefig(output, dpi=180, facecolor=SURFACE)
    plt.close(fig)
