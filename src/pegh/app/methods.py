"""Run a pre-encoding gate and reuse its one sparse ranking for fusion."""

from __future__ import annotations

import math

from contracts.types import GateDecision, Query, Ranking, SearchResponse
from pegh.profiling.trace import NullTraceSink


class ScoreThresholdGate:
    def __init__(self, predictor, threshold: float):
        if (
            isinstance(threshold, bool)
            or not isinstance(threshold, (int, float))
            or not math.isfinite(threshold)
        ):
            raise ValueError("gate threshold must be a finite number")
        self.predictor = predictor
        self.threshold = float(threshold)

    def decide(self, features) -> GateDecision:
        score = self.predictor.predict_score(features)
        if not math.isfinite(score):
            raise ValueError("gate score must be finite")
        return GateDecision(score > self.threshold, score, self.threshold, "model_threshold")


class HybridSearchMethod:
    def __init__(self, sparse, dense, extractor, gate, fusion, *, trace=None, provenance: dict):
        self.sparse = sparse
        self.dense = dense
        self.extractor = extractor
        self.gate = gate
        self.fusion = fusion
        self.trace = trace if trace is not None else NullTraceSink()
        self.provenance = provenance

    def search(self, query: Query, k: int = 100) -> SearchResponse:
        if type(k) is not int or k < 1:
            raise ValueError("k must be a positive integer")
        if query.domain != self.sparse.manifest["domain"]:
            raise ValueError("query domain differs from method domain")
        if not query.text.strip():
            empty = Ranking(
                query.query_id,
                query.domain,
                (),
                self.sparse.manifest["corpus_sha256"],
                self.sparse.manifest["retriever_hash"],
            )
            empty.validate()
            return SearchResponse(empty, False, None, 0, "empty_query")

        sparse = self.sparse.search(query, k=k)
        stats = self.sparse.query_stats(query)
        with self.trace.stage("features"):
            if self.gate.predictor.manifest["feature_set"] == "general":
                features = self.extractor.transform_general(query, sparse, stats)
            else:
                features = self.extractor.transform(query, sparse, stats)
        with self.trace.stage("gate"):
            decision = self.gate.decide(features)
            # An absent vocabulary match cannot be a useful sparse-only answer.
            use_dense = stats.token_count == 0 or stats.oov_ratio == 1.0 or decision.use_dense
        if not use_dense:
            sparse.validate()
            return SearchResponse(sparse, False, decision.score, 0, None)

        before = self.dense.encoder_calls
        dense = self.dense.search(query, k=k)
        calls = self.dense.encoder_calls - before
        if calls != 1:
            raise ValueError("dense route must encode exactly once")
        with self.trace.stage("fusion"):
            ranking = self.fusion.fuse(sparse, dense, k=k)
        ranking.validate()
        return SearchResponse(ranking, True, decision.score, calls, None)

    def close(self) -> None:
        self.sparse.close()


class StaticHybridMethod:
    """Always execute the selected fusion baseline without gate work."""

    def __init__(self, sparse, dense, fusion, *, trace=None, provenance: dict):
        self.sparse = sparse
        self.dense = dense
        self.fusion = fusion
        self.trace = trace if trace is not None else NullTraceSink()
        self.provenance = provenance

    def search(self, query: Query, k: int = 100) -> SearchResponse:
        if type(k) is not int or k < 1 or query.domain != self.sparse.manifest["domain"]:
            raise ValueError("positive k and matching domain are required")
        if not query.text.strip():
            ranking = Ranking(
                query.query_id,
                query.domain,
                (),
                self.sparse.manifest["corpus_sha256"],
                self.sparse.manifest["retriever_hash"],
            )
            ranking.validate()
            return SearchResponse(ranking, False, None, 0, "empty_query")
        sparse = self.sparse.search(query, k=k)
        before = self.dense.encoder_calls
        dense = self.dense.search(query, k=k)
        calls = self.dense.encoder_calls - before
        if calls != 1:
            raise ValueError("static hybrid must encode exactly once")
        with self.trace.stage("fusion"):
            ranking = self.fusion.fuse(sparse, dense, k=k)
        ranking.validate()
        return SearchResponse(ranking, True, None, calls, None)

    def close(self) -> None:
        self.sparse.close()
