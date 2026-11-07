from __future__ import annotations

import math

import numpy as np
import pytest

from contracts.types import Ranking, SearchHit
from pegh.v3.features import PROXY_NAMES, proxy_features, qpp_features
from pegh.v3.proxy import StaticProxy, corpus_token_weights, save_proxy
from pegh.v3.rescore import candidate_fusion, rescored_ranking


def _ranking(scores, ids=None):
    ids = ids or [f"unix:d{i}" for i in range(len(scores))]
    hits = tuple(SearchHit(d, s, r) for r, (d, s) in enumerate(zip(ids, scores, strict=True), 1))
    return Ranking("unix:q", "unix", hits, "corpus", "bm25")


def test_qpp_features_match_hand_computation() -> None:
    scores = [4.0, 2.0, 2.0]
    nqc, wig, smv, ratio10, ratio_last, idf_max, idf_sum = qpp_features(scores, [1.0, 3.0, 1.0], 4)
    mean = 8 / 3
    assert nqc == pytest.approx(math.sqrt(((4 - mean) ** 2 + 2 * (2 - mean) ** 2) / 3) / mean)
    assert wig == 0.0  # fewer than ten hits: the top-10 mean is the full mean
    expected_smv = (4 * abs(math.log(4 / mean)) + 2 * 2 * abs(math.log(2 / mean))) / 3 / mean
    assert smv == pytest.approx(expected_smv)
    assert (ratio10, ratio_last, idf_max, idf_sum) == (0.5, 0.5, 3.0, 4.0)
    assert qpp_features([], [], 0) == (0.0,) * 7


def test_proxy_features_detect_semantic_candidate_below_cutoff() -> None:
    n = 12
    candidates = np.zeros((n, 2), dtype=np.float32)
    candidates[:, 0] = 1.0
    candidates[11] = [0.0, 1.0]
    query = np.array([0.0, 1.0], dtype=np.float32)
    values = dict(
        zip(PROXY_NAMES, proxy_features(query, candidates, list(range(n, 0, -1))), strict=True)
    )
    assert values["px_top1"] == 0.0
    assert values["px_gap_below10"] == 1.0
    assert values["px_argmax_rank"] == pytest.approx(math.log1p(11) / math.log(100))
    assert values["px_overlap10"] == 0.9
    assert proxy_features(np.zeros(2), candidates, [1.0] * n) == (0.0,) * len(PROXY_NAMES)


def test_rescore_orders_bm25_candidates_and_breaks_ties_by_id() -> None:
    sparse = _ranking([3.0, 2.0, 1.0], ["unix:b", "unix:a", "unix:c"])
    vectors = np.array([[1.0, 0.0], [1.0, 0.0], [0.0, 1.0]], dtype=np.float32)
    rows = {"unix:b": 0, "unix:a": 1, "unix:c": 2}
    ranked = rescored_ranking(sparse, np.array([1.0, 0.0]), vectors, rows, "id")
    assert [h.doc_id for h in ranked.hits] == ["unix:a", "unix:b", "unix:c"]
    fused = candidate_fusion(sparse, ranked, 1.0)
    assert {h.doc_id for h in fused.hits} == {"unix:a", "unix:b", "unix:c"}
    empty = _ranking([])
    assert rescored_ranking(empty, np.ones(2), vectors, rows, "id") is empty
    assert candidate_fusion(empty, empty, 0.5) is empty


class _Tokenizer:
    vocab = {"a": 0, "b": 1, "c": 2}

    def __len__(self):
        return 3

    def __call__(self, text, add_special_tokens=False, truncation=True, max_length=256):
        if isinstance(text, list):
            return {"input_ids": [self(t)["input_ids"] for t in text]}
        return {"input_ids": [self.vocab[t] for t in text.split() if t in self.vocab]}


def test_static_proxy_weights_checksums_and_empty_queries(tmp_path) -> None:
    table = np.eye(3, dtype=np.float32)
    weights = corpus_token_weights(_Tokenizer(), ["a a a b", "a"])
    assert weights[2] == 1.0 and weights[0] < weights[1] < 1.0
    save_proxy(tmp_path, table, weights, {"encoder": "fixture"})
    proxy = StaticProxy(tmp_path, _Tokenizer())
    vector = proxy.embed("a b")
    assert np.linalg.norm(vector) == pytest.approx(1.0)
    assert vector[1] > vector[0] > 0  # the rarer token weighs more
    assert not proxy.embed("zzz").any()
    np.save(tmp_path / "weights.npy", np.ones(3, dtype=np.float32))
    with pytest.raises(ValueError, match="checksum"):
        StaticProxy(tmp_path, _Tokenizer())
