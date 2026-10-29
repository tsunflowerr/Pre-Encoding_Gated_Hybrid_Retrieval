from __future__ import annotations

import numpy as np
import pytest

from pegh.v3.pipeline import (
    HYBRIDS,
    DomainData,
    FoldScores,
    at_budget,
    bootstrap,
    select_fusion,
    select_threshold,
)


def _domain(name: str, n: int = 10, utilities: dict | None = None) -> DomainData:
    rows = np.arange(n)
    folds = [{"train": rows[:6], "validation": rows[6:8], "test": rows[8:]} for _ in range(5)]
    base = {m: np.zeros(n) for m in ("bm25", "dense", *HYBRIDS)}
    base.update(utilities or {})
    v1 = np.ones((n, 21))
    v1[:, 12] = 0.0  # in-vocabulary queries; OOV rows are forced dense
    return DomainData(
        name,
        [f"{name}:q{i}" for i in range(n)],
        base,
        folds,
        [f"g{i}" for i in range(n)],
        {"v1": v1},
    )


def test_fusion_ties_prefer_rrf_then_lower_alpha_and_static_order() -> None:
    value = np.full(10, 0.5)
    data = _domain("unix", utilities={"cc_alpha_0.3": value, "cc_alpha_0.7": value})
    assert select_fusion(data, 0)["h_star"] == "cc_alpha_0.3"
    data.utilities["rrf"] = value
    assert select_fusion(data, 0)["h_star"] == "rrf"
    data.utilities["bm25"] = value
    assert select_fusion(data, 0)["s_star"] == "bm25"  # equal static: cheaper option first


def test_threshold_rule_picks_lowest_feasible_dense_ratio() -> None:
    gain = np.array([0, 0, 0, 0, 0, 0, 0.4, 0.0, 0.4, 0.0])
    group = []
    scored = {}
    for name in ("a", "b"):
        data = _domain(name, utilities={"cc_alpha_0.1": gain.copy()})
        score = np.where(gain > 0, 1.0, 0.0)
        folds = [FoldScores("bm25", "cc_alpha_0.1", "cc_alpha_0.1", {}, {"m": score})] * 5
        group.append(data)
        scored[name] = folds
    choice = select_threshold(group, scored, "m", 0)
    assert choice["status"] == "selected"
    # Routing only the two positive-gain validation queries loses nothing vs S*; budgets 0.4
    # and 0.5 give the same dense count, so the lower budget wins the registered tie-break.
    assert choice["budget"] == 0.4 and choice["threshold"] == 0.0


def test_exact_budget_routes_forced_rows_first_and_oracle_skips_nonpositive() -> None:
    gain = np.array([0, 0, 0, 0, 0, 0, 0, 0, 0.5, 0.0])
    data = _domain("a", utilities={"cc_alpha_0.1": gain})
    data.features["v1"][9, 12] = 1.0  # sparse OOV: forced dense
    folds = [
        FoldScores("bm25", "cc_alpha_0.1", "cc_alpha_0.1", {}, {"oracle": gain, "s": -gain})
    ] * 5
    counts = {"a": [1] * 5}
    assert at_budget([data], {"a": folds}, "s", counts)["a"][8:].tolist() == [0.0, 0.0]
    assert at_budget([data], {"a": folds}, "oracle", {"a": [2] * 5})["a"][8:].tolist() == [0.5, 0.0]


def test_bootstrap_is_deterministic_and_centered() -> None:
    diff = {"a": np.array([0.1, 0.1, 0.1]), "b": np.array([0.0, 0.0, 0.0])}
    groups = {"a": ["x", "y", "z"], "b": ["x", "y", "z"]}
    first, second = bootstrap(diff, groups, samples=200), bootstrap(diff, groups, samples=200)
    assert first == second
    assert first["mean_difference"] == pytest.approx(0.05)
    assert first["p_superiority"] == 0.0
    assert first["one_sided_lower_95"] == pytest.approx(0.05)
