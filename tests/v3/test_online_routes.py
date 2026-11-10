from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import yaml

from contracts import Query
from pegh.dense.index import build_index
from pegh.gating.features import QueryFeatureExtractor
from pegh.profiling.trace import TraceSink
from pegh.sparse.config import BM25Config
from pegh.sparse.fast import FORMAT, NumpyBM25, compile_index
from pegh.sparse.index import build_index as build_sparse
from pegh.v3.build import load_dense_vectors
from pegh.v3.online import TierSearchMethod
from pegh.v3.rescore import candidate_fusion, rescored_ranking
from tests.b.fakes import DeterministicEncoder


class _Predictor:
    def __init__(self, score):
        self.score = score

    def predict_score(self, features):
        assert len(features.values) == 21
        return self.score


class _Proxy:
    def embed(self, text):
        vector = np.ones(8, dtype=np.float32)
        return vector / np.linalg.norm(vector)


def _method(tmp_path, route, score=0.0):
    corpus = Path("tests/fixtures/shared/unix/corpus.jsonl")
    sparse_dir, dense_dir = tmp_path / "sparse", tmp_path / "dense"
    build_sparse(corpus, sparse_dir, "unix", BM25Config())
    compile_index(sparse_dir, sparse_dir / FORMAT)
    encoder = DeterministicEncoder()
    build_index(corpus, dense_dir, "unix", encoder, expected_count=10)
    vectors, rows, _ = load_dense_vectors(dense_dir)
    trace = TraceSink(detailed=False)
    sparse = NumpyBM25(sparse_dir, trace=trace)
    recipe = yaml.safe_load(Path("configs/gating/protocol_v1.yaml").read_text(encoding="utf-8"))
    method = TierSearchMethod(
        route,
        sparse,
        trace=trace,
        provenance={"fixture": True},
        low_alpha=0.5 if route != "bm25" else None,
        high_alpha=0.6,
        proxy=_Proxy(),
        encoder=encoder,
        vectors=vectors,
        rows=rows,
        extractor=QueryFeatureExtractor(recipe["features"], sparse.tokenizer),
        predictor=_Predictor(score),
        threshold=0.0,
        identities={"proxy": "p", "query": "q"},
    )
    return method, trace, encoder, vectors, rows


@pytest.mark.parametrize(
    "route,score,text,calls",
    [
        ("bm25", 0, "process TCP port", 0),
        ("proxy", 0, "process TCP port", 0),
        ("rescore", 0, "process TCP port", 1),
        ("cascade", -1, "process TCP port", 0),
        ("cascade", 1, "process TCP port", 1),
        ("cascade", -1, "zzzz_wholly_unknown_token", 1),
    ],
)
def test_routes_encode_only_on_the_expensive_tier(tmp_path, route, score, text, calls) -> None:
    method, trace, encoder, vectors, rows = _method(tmp_path, route, score)
    query = Query("unix:q01", "unix", text)
    before = encoder.encode_calls
    trace.begin_request()
    response = method.search(query)
    measured = trace.end_request()
    assert response.encoder_calls == measured["encoder_calls"] == calls
    assert encoder.encode_calls - before == calls
    assert measured["vector_search_calls"] == 0
    assert measured["stage_calls"]["sparse"] == 1
    sparse = method.sparse.search(query)
    if calls:
        vector = DeterministicEncoder().encode([text])[0]
        expected = candidate_fusion(
            sparse, rescored_ranking(sparse, vector, vectors, rows, "q"), 0.6
        )
        assert response.ranking == expected
    elif route == "bm25":
        assert response.ranking == sparse
    else:
        cheap = rescored_ranking(sparse, _Proxy().embed(text), vectors, rows, "p")
        assert response.ranking == candidate_fusion(sparse, cheap, 0.5)
    method.close()


def test_empty_query_returns_without_backend_calls(tmp_path) -> None:
    method, trace, encoder, _, _ = _method(tmp_path, "rescore")
    before = encoder.encode_calls
    trace.begin_request()
    response = method.search(Query("unix:q01", "unix", "   "))
    measured = trace.end_request()
    assert response.fallback_reason == "empty_query" and not response.ranking.hits
    assert measured["encoder_calls"] == encoder.encode_calls - before == 0
    method.close()
