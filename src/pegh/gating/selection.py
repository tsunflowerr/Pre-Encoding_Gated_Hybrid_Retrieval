"""Validation-only threshold selection for independently trained domain models."""

from __future__ import annotations

import math
from itertools import product


def threshold_metrics(rows: list[dict], threshold: float) -> dict:
    if not rows or not math.isfinite(threshold):
        raise ValueError("nonempty rows and finite threshold required")
    if any(not all(math.isfinite(r[k]) for k in ("score", "U_B", "U_H")) for r in rows):
        raise ValueError("non-finite validation score/utility")
    routes = [r["force_dense"] or r["score"] > threshold for r in rows]
    quality = sum(r["U_H"] if d else r["U_B"] for r, d in zip(rows, routes, strict=True)) / len(
        rows
    )
    return {
        "threshold": threshold,
        "query_count": len(rows),
        "dense_count": sum(routes),
        "dense_ratio": sum(routes) / len(rows),
        "ndcg_at_10": quality,
        "loss_vs_s_star": sum(r["U_H"] for r in rows) / len(rows) - quality,
    }


def domain_grid(rows: list[dict], shared_threshold: float) -> list[dict]:
    eligible = sorted((r["score"] for r in rows if not r["force_dense"]), reverse=True)
    forced = sum(r["force_dense"] for r in rows)
    thresholds = [shared_threshold]
    for index in range(11):
        count = min(max(round(index / 10 * len(rows)) - forced, 0), len(eligible))
        if not eligible:
            threshold = 0.0
        elif count == 0:
            threshold = math.nextafter(eligible[0], math.inf)
        elif count == len(eligible):
            threshold = math.nextafter(eligible[-1], -math.inf)
        else:
            threshold = eligible[count]
        thresholds.append(threshold)
    return [threshold_metrics(rows, t) for t in sorted(set(thresholds))]


def select_domain_thresholds(
    rows: dict[str, list[dict]],
    shared_threshold: float,
    *,
    macro_tolerance: float = 0.005,
    domain_tolerance: float = 0.01,
) -> dict:
    """Include the old point, so grid discretization cannot remove a feasible reference."""
    if len(rows) < 2 or min(macro_tolerance, domain_tolerance) < 0:
        raise ValueError("two or more domains and nonnegative tolerances required")
    domains = sorted(rows)
    reference = {d: threshold_metrics(rows[d], shared_threshold) for d in domains}
    grids = {d: domain_grid(rows[d], shared_threshold) for d in domains}
    feasible = []
    for points in product(*(grids[d] for d in domains)):
        if (
            sum(p["loss_vs_s_star"] for p in points) / len(points) <= macro_tolerance
            and all(p["loss_vs_s_star"] <= domain_tolerance for p in points)
            and all(
                p["ndcg_at_10"] >= reference[d]["ndcg_at_10"] - 1e-12
                for d, p in zip(domains, points, strict=True)
            )
        ):
            feasible.append(points)
    if not feasible:
        raise ValueError("no feasible validation point, including always-hybrid")
    chosen = min(
        feasible,
        key=lambda points: (
            sum(p["dense_count"] for p in points),
            -sum(p["ndcg_at_10"] for p in points),
            tuple(p["threshold"] for p in points),
        ),
    )
    return {
        "domains": dict(zip(domains, chosen, strict=True)),
        "actual_dense_ratio": sum(p["dense_count"] for p in chosen)
        / sum(p["query_count"] for p in chosen),
        "macro_ndcg_at_10": sum(p["ndcg_at_10"] for p in chosen) / len(chosen),
        "candidate_counts": {d: len(grids[d]) for d in domains},
        "feasible_pairs": len(feasible),
        "reference_quality_preserved_each_domain": True,
        "reference": reference,
    }
