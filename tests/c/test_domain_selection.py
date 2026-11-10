import pytest

from pegh.gating.selection import select_domain_thresholds, threshold_metrics


def test_independent_domain_scales_do_not_force_extra_dense():
    rows = {
        domain: [
            {"score": base + index, "force_dense": False, "U_B": 0.0, "U_H": float(index > 4)}
            for index in range(10)
        ]
        for domain, base in (("a", 100), ("b", 0))
    }
    result = select_domain_thresholds(rows, -1.0, macro_tolerance=0, domain_tolerance=0)
    assert result["actual_dense_ratio"] == 0.5
    assert result["domains"]["a"]["threshold"] != result["domains"]["b"]["threshold"]
    assert result["macro_ndcg_at_10"] == 0.5


def test_equal_scores_skip_and_forced_routes_are_counted():
    rows = [
        {"score": 1.0, "force_dense": forced, "U_B": 0.0, "U_H": 1.0} for forced in (True, False)
    ]
    point = threshold_metrics(rows, 1.0)
    assert point["dense_count"] == 1
    assert point["ndcg_at_10"] == 0.5
    with pytest.raises(ValueError, match="non-finite"):
        threshold_metrics([{**rows[0], "score": float("nan")}], 0.0)
