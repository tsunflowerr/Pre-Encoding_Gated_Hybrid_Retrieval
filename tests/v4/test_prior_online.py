from __future__ import annotations

import json
from types import SimpleNamespace

import numpy as np
import pytest

from contracts.types import FeatureVector, Hit, Query, Ranking
from pegh.profiling.trace import TraceSink
from pegh.v3.pipeline import GENERAL
from pegh.v4.online import V2SearchMethod
from pegh.v4.prior import BertRouter, LinearSVM, fit_litegator
from pegh.v4.prior_online import latency_comparison, select_litegator


@pytest.mark.parametrize("c,weight", [(0.1, None), (1, None), (10, "balanced")])
def test_exported_svm_matches_sklearn_decision_function(c, weight):
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    from sklearn.svm import LinearSVC

    rng = np.random.default_rng(123)
    x, evaluation = rng.normal(size=(130, 21)), rng.normal(size=(40, 21))
    x[:, GENERAL[2] - 1] = 7  # StandardScaler must preserve scale=1 for constant columns.
    y = (x[:, GENERAL[0] - 1] - 0.8 * x[:, GENERAL[-1] - 1] > 0.7).astype(int)
    reference = make_pipeline(
        StandardScaler(),
        LinearSVC(C=c, class_weight=weight, dual=False, random_state=42, max_iter=5000),
    ).fit(x[:, np.asarray(GENERAL) - 1], y)
    exported = fit_litegator([x[:70], x[70:]], [y[:70], y[70:]], c=c, class_weight=weight)
    restored = LinearSVM.from_json(json.loads(json.dumps(exported.to_json())))
    np.testing.assert_allclose(
        restored.score(evaluation),
        reference.decision_function(evaluation[:, np.asarray(GENERAL) - 1]),
        rtol=0,
        atol=1e-12,
    )
    assert restored.sha256 == exported.sha256
    np.testing.assert_allclose(
        [restored.score(row)[0] for row in evaluation], restored.score(evaluation), atol=1e-12
    )


def test_bert_seed_is_applied_before_head_initialization(monkeypatch):
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    threads = torch.get_num_threads()
    monkeypatch.setattr(AutoTokenizer, "from_pretrained", lambda *a, **k: object())
    monkeypatch.setattr(
        AutoModelForSequenceClassification, "from_pretrained", lambda *a, **k: torch.rand(2, 8)
    )
    try:
        first = BertRouter("unused", 1, seed=42).model
        torch.rand(100)
        second = BertRouter("unused", 1, seed=42).model
        assert torch.equal(first, second)
    finally:
        torch.set_num_threads(threads)


@pytest.mark.parametrize(
    "scorer,score,forced,expected_dense",
    [
        ("litegator", -1, False, False),
        ("litegator", 1, False, True),
        ("arabzadeh_bert", 0.4, False, False),
        ("arabzadeh_bert", 0.9, False, True),
        ("arabzadeh_bert", 0.4, True, True),
    ],
)
def test_prior_scorers_reuse_bm25_and_do_not_cache_bert(scorer, score, forced, expected_dense):
    trace = TraceSink(detailed=True)
    query = Query("unix:q01", "unix", "query text")
    ranking = Ranking(query.query_id, "unix", (Hit("unix:d01", 2.0, 1),), "corpus", "sparse")
    calls = {"sparse": 0, "bert": 0, "features": 0}

    class Sparse:
        manifest = {"domain": "unix"}

        def search(self, query, k):
            calls["sparse"] += 1
            return ranking

        def query_stats(self, query):
            return SimpleNamespace(token_count=3, oov_ratio=float(forced))

    class Bert:
        def score(self, pairs, batch):
            assert pairs == [(query.text, "top document")]
            assert batch == 1
            calls["bert"] += 1
            return np.array([score])

    class Extractor:
        def transform(self, *args):
            calls["features"] += 1
            return FeatureVector(tuple(range(21)), "fixture")

    method = V2SearchMethod(
        "gated",
        Sparse(),
        trace=trace,
        provenance={},
        scorer=scorer,
        gate=SimpleNamespace(score=lambda x: np.array([score])),
        extractor=Extractor(),
        bert=Bert(),
        documents={"unix:d01": "top document"},
        threshold=0.5,
    )
    method.full = lambda q, s: ranking
    method.cheap = lambda q, s: ranking
    for _ in range(2):
        trace.begin_request()
        response = method.search(query)
        measured = trace.end_request()
        assert response.use_dense == expected_dense
        assert measured["stage_calls"]["gate"] == 1
    assert calls["sparse"] == 2
    assert calls["bert"] == (2 if scorer == "arabzadeh_bert" else 0)
    assert calls["features"] == (0 if scorer == "arabzadeh_bert" else 2)


def test_litegator_selection_fits_only_other_topics(monkeypatch):
    from pegh.v4 import prior_online as po

    domains = [
        SimpleNamespace(
            domain=str(i),
            features={"v1": np.zeros((5, 21))},
            ids=[f"{i}:{q}" for q in range(5)],
            forced=np.zeros(5, dtype=bool),
            utilities={"bm25": np.ones(5), "cc_alpha_0.1": np.ones(5)},
        )
        for i in range(3)
    ]
    fits = []

    def fit(train, tiers, params):
        fits.append(tuple(d.domain for d in train))
        return SimpleNamespace(score=lambda x: np.arange(len(x), dtype=float))

    monkeypatch.setattr(po, "fit_svm", fit)
    monkeypatch.setattr(
        "pegh.v4.gate.fixed_tiers", lambda _: {"p_star": "bm25", "h_star": "cc_alpha_0.1"}
    )
    result = select_litegator(domains)
    assert len(fits) == 3 * 6
    for held in range(3):
        assert all(str(held) not in names for names in fits[held * 6 : (held + 1) * 6])
    assert result["selected"] == {"C": 0.1, "class_weight": None}  # declared tie rule


def test_latency_bootstrap_pairs_query_repetitions_and_keeps_slow_requests():
    left = {"a": [10, 20], "b": [100, 200]}
    right = {"a": [5, 10], "b": [50, 100]}
    result = latency_comparison(left, right, samples=1000)
    assert result["mean_difference_ms"] == pytest.approx(41.25)
    assert result["reduction_ci95"] == pytest.approx([0.5, 0.5])
    assert result["two_sided_95_ms"][1] > result["mean_difference_ms"]
