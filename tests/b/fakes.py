from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path

import numpy as np

from contracts.types import SearchResponse
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
