from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from contracts import Query
from pegh.app.methods import HybridSearchMethod, ScoreThresholdGate, StaticHybridMethod
from pegh.dense.index import build_index
from pegh.dense.retriever import FaissDenseRetriever
from pegh.fusion.engines import CCFusion
from pegh.gating.features import QueryFeatureExtractor
from pegh.profiling.trace import TraceSink
from pegh.sparse.config import BM25Config
from pegh.sparse.fast import FORMAT, NumpyBM25, compile_index
from pegh.sparse.index import build_index as build_sparse
from tests.b.fakes import DeterministicEncoder


class ConstantPredictor:
    manifest = {"feature_set": "full"}

    def __init__(self, score):
        self.score = score

    def predict_score(self, features):
        assert len(features.values) == 21
        return self.score


def _backends(tmp_path):
    corpus = Path("tests/fixtures/shared/unix/corpus.jsonl")
    sparse_dir, dense_dir = tmp_path / "sparse", tmp_path / "dense"
    build_sparse(corpus, sparse_dir, "unix", BM25Config())
    compile_index(sparse_dir, sparse_dir / FORMAT)
    encoder = DeterministicEncoder()
    build_index(corpus, dense_dir, "unix", encoder, expected_count=10)
    trace = TraceSink(detailed=False)
    sparse = NumpyBM25(sparse_dir, trace=trace)
    dense = FaissDenseRetriever(dense_dir, encoder, trace=trace)
    recipe = yaml.safe_load(Path("configs/gating/protocol_v1.yaml").read_text(encoding="utf-8"))
    extractor = QueryFeatureExtractor(recipe["features"], sparse.tokenizer)
    return sparse, dense, trace, extractor


@pytest.mark.parametrize(
    "score,text,calls",
    [(-1, "process TCP port", 0), (1, "process TCP port", 1), (-1, "zzzz_wholly_unknown_token", 1)],
)
def test_real_sparse_dense_adapters_enforce_skip_dense_and_oov(tmp_path, score, text, calls):
    sparse, dense, trace, extractor = _backends(tmp_path)
    method = HybridSearchMethod(
        sparse,
        dense,
        extractor,
        ScoreThresholdGate(ConstantPredictor(score), 0),
        CCFusion(0.5),
        trace=trace,
        provenance={"fixture": True},
    )
    query = Query("unix:q01", "unix", text)
    trace.begin_request()
    response = method.search(query)
    measured = trace.end_request()
    assert response.encoder_calls == measured["encoder_calls"] == calls
    assert measured["stage_calls"]["sparse"] == measured["stage_calls"]["stats"] == 1
    assert measured["vector_search_calls"] == calls
    if not calls:
        assert response.ranking == sparse.search(query)
    method.close()


def test_parallel_baseline_reuses_one_search_per_branch_and_matches_sequential(tmp_path):
    sparse, dense, trace, _ = _backends(tmp_path)
    query = Query("unix:q01", "unix", "process TCP port")
    sequential = StaticHybridMethod(
        sparse, dense, CCFusion(0.5), trace=trace, provenance={"fixture": True}
    )
    expected = sequential.search(query).ranking
    parallel = StaticHybridMethod(
        sparse, dense, CCFusion(0.5), trace=trace, provenance={"fixture": True}, parallel=True
    )
    trace.begin_request()
    response = parallel.search(query)
    measured = trace.end_request()
    assert response.ranking == expected
    assert measured["encoder_calls"] == measured["vector_search_calls"] == 1
    assert measured["stage_calls"]["sparse"] == 1
    parallel.close()
