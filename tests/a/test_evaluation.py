from __future__ import annotations

import pytest

from contracts import Ranking, SearchHit
from pegh.evaluation.bootstrap import macro_group_bootstrap, paired_group_bootstrap
from pegh.evaluation.metrics import (
    aggregate_metrics,
    evaluate_rankings,
    query_metrics,
    utility_rows,
)


def ranking(query_id: str, doc_ids: list[str]) -> Ranking:
    result = Ranking(
        query_id,
        "unix",
        tuple(
            SearchHit(doc_id, float(len(doc_ids) - rank), rank)
            for rank, doc_id in enumerate(doc_ids, 1)
        ),
        "corpus",
        "retriever",
    )
    result.validate()
    return result


def test_ndcg_uses_all_qrels_not_only_retrieved_candidates():
    qrels = {"unix:q": {"unix:d1": 1.0, "unix:d2": 1.0}}
    row = query_metrics("unix:q", "unix", qrels, ranking("unix:q", ["unix:d1"]))
    assert row.ndcg_at_10 == pytest.approx(0.6131471927654584)
    assert row.mrr_at_10 == 1
    assert row.recall_at_10 == 0.5


def test_missing_query_is_zero_and_stays_in_denominator():
    qrels = {
        "unix:q1": {"unix:d1": 1.0},
        "unix:q2": {"unix:d2": 1.0},
    }
    rows = evaluate_rankings(
        ["unix:q1", "unix:q2"],
        "unix",
        qrels,
        {"unix:q1": ranking("unix:q1", ["unix:d1"])},
    )
    summary = aggregate_metrics(rows)
    assert summary["query_count"] == 2
    assert summary["missing_or_empty_rankings"] == 1
    assert summary["ndcg_at_10"] == 0.5


def test_utility_join_and_bootstrap_are_paired_and_reproducible():
    qrels = {
        "unix:q1": {"unix:d1": 1.0},
        "unix:q2": {"unix:d2": 1.0},
    }
    baseline = evaluate_rankings(
        ["unix:q1", "unix:q2"],
        "unix",
        qrels,
        {"unix:q1": ranking("unix:q1", ["unix:x"])},
    )
    candidate = evaluate_rankings(
        ["unix:q1", "unix:q2"],
        "unix",
        qrels,
        {
            "unix:q1": ranking("unix:q1", ["unix:d1"]),
            "unix:q2": ranking("unix:q2", ["unix:d2"]),
        },
    )
    rows = utility_rows(baseline, candidate)
    assert [row["delta_utility"] for row in rows] == [1.0, 1.0]
    result = paired_group_bootstrap(
        {row["query_id"]: row["delta_utility"] for row in rows}, samples=100, seed=7
    )
    assert result["mean_difference"] == 1
    assert result["two_sided_95"] == [1, 1]


def test_self_qrel_is_removed_from_ideal_and_retrieved_sets():
    qrels = {"unix:q": {"unix:q": 1.0, "unix:d1": 1.0}}
    row = query_metrics("unix:q", "unix", qrels, ranking("unix:q", ["unix:d1"]))
    assert row.ndcg_at_10 == 1
    assert row.relevant_count == 1


def test_macro_bootstrap_preserves_equal_domain_weighting():
    result = macro_group_bootstrap(
        {
            "programmers": {"p1": 1.0, "p2": 1.0},
            "unix": {"u1": -1.0},
        },
        {
            "programmers": {"p1": "pg", "p2": "pg"},
            "unix": {"u1": "ug"},
        },
        samples=20,
        seed=3,
    )
    assert result["mean_difference"] == 0
    assert result["two_sided_95"] == [0, 0]
