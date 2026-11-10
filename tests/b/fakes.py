from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path

import numpy as np

from contracts.types import Hit, Query, Ranking, SearchResponse
from pegh.dense.artifacts import read_json
from pegh.dense.config import DenseConfig
from pegh.dense.retriever import DenseOnlyMethod, FaissDenseRetriever


class DeterministicEncoder:
    """Non-neural fixture only. No retrieval-quality/latency research claim uses it."""

    def __init__(self, config: DenseConfig | None = None):
        self.config = config or DenseConfig(
            model_id="fixture-only",
            revision="fixture-v1",
            dimension=8,
            batch_size=2,
            checkpoint_documents=4,
            torch_threads=1,
            faiss_threads=1,
        )
        self.encode_calls = 0
        self.encoded_texts: list[str] = []

    def encode(self, texts):
        self.encode_calls += 1
        self.encoded_texts.extend(texts)
        rows = []
        for text in texts:
            seed = int.from_bytes(hashlib.sha256(text.encode()).digest()[:8], "little")
            vector = (
                np.random.default_rng(seed).normal(size=self.config.dimension).astype("float32")
            )
            rows.append(vector / np.linalg.norm(vector))
        return np.stack(rows)

    def token_lengths(self, texts):
        return [len(text.split()) + 2 for text in texts]


def create_fixture_dense(*, trace, index_dir: str):
    config = DenseConfig(**read_json(Path(index_dir) / "manifest.json")["config"])
    return DenseOnlyMethod(
        FaissDenseRetriever(index_dir, DeterministicEncoder(config), trace=trace)
    )


def create_wrong_counter(*, trace, index_dir: str):
    delegate = create_fixture_dense(trace=trace, index_dir=index_dir)

    class WrongCounter:
        def search(self, query, k=100):
            response = delegate.search(query, k=k)
            return replace(response, encoder_calls=0)

    return WrongCounter()


def create_fallback_method(*, trace, index_dir: str):
    delegate = create_fixture_dense(trace=trace, index_dir=index_dir)

    class Fallback:
        def search(self, query, k=100):
            response = delegate.search(query, k=k)
            return SearchResponse(response.ranking, True, None, 1, "dense_failed")

    return Fallback()


def create_false_empty_fallback(*, trace, index_dir: str):
    delegate = create_fixture_dense(trace=trace, index_dir=index_dir)

    class FalseEmpty:
        def search(self, query, k=100):
            return replace(delegate.search(query, k=k), fallback_reason="empty_query")

    return FalseEmpty()


def create_cached_query_vector(*, trace, index_dir: str):
    delegate = create_fixture_dense(trace=trace, index_dir=index_dir)
    vector = delegate.retriever.encode_query(Query("unix:cached", "unix", "cached query"))

    class CachedVector:
        def search(self, query, k=100):
            ranking = delegate.retriever.search_vector(query, vector, k=k)
            return SearchResponse(ranking, False, None, 0, None)

    return CachedVector()


def create_fixture_gated(*, trace, index_dir: str):
    """Counter integration fixture; not a learned gate or research baseline."""
    delegate = create_fixture_dense(trace=trace, index_dir=index_dir)

    class FixtureGate:
        def search(self, query, k=100):
            with trace.stage("sparse"):
                ids = [i for i in delegate.retriever.doc_ids if i != query.query_id][:k]
                sparse = Ranking(
                    query.query_id,
                    query.domain,
                    tuple(Hit(doc_id, 1 / rank, rank) for rank, doc_id in enumerate(ids, 1)),
                    delegate.retriever.manifest["corpus_sha256"],
                    "fixture-sparse-only",
                )
            with trace.stage("gate"):
                use_dense = query.query_id.endswith(("1", "3", "warm"))
            if use_dense:
                return delegate.search(query, k=k)
            return SearchResponse(sparse, False, None, 0, None)

    return FixtureGate()


def create_repeated_sparse(*, trace, index_dir: str):
    delegate = create_fixture_gated(trace=trace, index_dir=index_dir)

    class RepeatedSparse:
        def search(self, query, k=100):
            with trace.stage("sparse"):
                pass  # Simulate a second sparse execution in an orchestration layer.
            return delegate.search(query, k=k)

    return RepeatedSparse()
