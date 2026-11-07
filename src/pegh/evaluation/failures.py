"""Deterministic, post-freeze case selection for the four registered routing outcomes."""

from __future__ import annotations

from collections import defaultdict

from pegh.data.artifacts import object_hash


def outcome(use_dense: bool, gain: float) -> str:
    if use_dense:
        return "useful_dense" if gain > 0 else "wasted_dense"
    return "missed_benefit" if gain > 0 else "safe_skip"


def select_cases(rows: list[dict], *, limit: int = 5, seed: int = 20261019) -> list[dict]:
    """Select at most limit per domain/outcome, including one median useful-dense case."""
    if limit < 1:
        raise ValueError("case limit must be positive")
    groups = defaultdict(list)
    seen = set()
    for row in rows:
        key = (row["domain"], row["query_id"])
        if key in seen:
            raise ValueError("duplicate query in failure analysis")
        seen.add(key)
        category = outcome(row["use_dense"], row["delta_u"])
        groups[(row["domain"], category)].append(row)
    selected = []
    for (_, category), candidates in sorted(groups.items()):
        if category == "safe_skip":
            ordered = sorted(
                candidates,
                key=lambda r: (object_hash([seed, r["query_id"]]), r["query_id"]),
            )
            chosen = [(row, "fixed_hash_sample") for row in ordered[:limit]]
        else:
            sign = 1 if category == "wasted_dense" else -1
            ordered = sorted(candidates, key=lambda r: (sign * r["delta_u"], r["query_id"]))
            chosen = [
                (row, "largest_harm" if sign == 1 else "largest_gain") for row in ordered[:limit]
            ]
            if category == "useful_dense" and limit > 1 and len(ordered) > limit:
                median = ordered[(len(ordered) - 1) // 2]
                if all(row["query_id"] != median["query_id"] for row, _ in chosen):
                    chosen[-1] = (median, "median_gain")
        selected.extend(
            {**row, "category": category, "selection_reason": reason} for row, reason in chosen
        )
    return selected
