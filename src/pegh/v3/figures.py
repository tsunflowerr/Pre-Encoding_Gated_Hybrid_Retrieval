"""Static figures for the v3 report (light surface; validated categorical order)."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

SERIES = ("#2a78d6", "#eb6834", "#1baf7a", "#eda100")  # fixed slot order, validated light
SURFACE, INK, MUTED, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
MARKERS = ("o", "s", "^", "D")


def _axes(ax, title: str, xlabel: str, ylabel: str) -> None:
    ax.set_facecolor(SURFACE)
    ax.set_title(title, color=INK, fontsize=11, loc="left")
    ax.set_xlabel(xlabel, color=MUTED)
    ax.set_ylabel(ylabel, color=MUTED)
    ax.grid(color=GRID, linewidth=0.8)
    ax.tick_params(colors=MUTED)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)


def pareto(points: list[dict], output: Path) -> None:
    """points: name, latency_ms, ndcg, family ('v1' or 'v3'); direct-labelled scatter."""
    fig, ax = plt.subplots(figsize=(8.2, 5.2), facecolor=SURFACE)
    _axes(
        ax,
        "Chất lượng và độ trễ trung bình (programmers + unix, đo online)",
        "Độ trễ trung bình mỗi query (ms)",
        "Macro nDCG@10 (OOF)",
    )
    for slot, family, label in ((0, "v1", "Hệ thống v1"), (1, "v3", "Đề xuất v3")):
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
            xytext=(7, 5),
            color=INK,
            fontsize=9,
        )
    ax.legend(frameon=False, labelcolor=INK, loc="lower right")
    fig.tight_layout()
    fig.savefig(output, dpi=180, facecolor=SURFACE)
    plt.close(fig)


def budget_curves(panels: list[dict], output: Path) -> None:
    """panels: title, budgets, series{label: values}; same series order in every panel."""
    fig, axes = plt.subplots(
        1, len(panels), figsize=(6.0 * len(panels), 4.6), facecolor=SURFACE, sharey=False
    )
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
            # highest label above its line, the rest below, so close references never collide
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
        ax.legend(frameon=False, labelcolor=INK, fontsize=8, loc="lower right")
    fig.tight_layout()
    fig.savefig(output, dpi=180, facecolor=SURFACE)
    plt.close(fig)


def forest(rows: list[dict], output: Path) -> None:
    """rows: label, estimate, low, high, reference (0 or -0.01); one row per hypothesis."""
    fig, ax = plt.subplots(figsize=(8.4, 0.62 * len(rows) + 1.4), facecolor=SURFACE)
    _axes(
        ax,
        "Giả thuyết đăng ký trước (4 domain mới): ước lượng và CI 95%",
        "Chênh lệch macro nDCG@10",
        "",
    )
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
    low = min(r["low"] for r in rows)
    high = max(r["high"] for r in rows)
    ax.set_xlim(min(low, -0.012) - 0.002, high + (high - low) * 0.45)
    fig.tight_layout()
    fig.savefig(output, dpi=180, facecolor=SURFACE)
    plt.close(fig)
