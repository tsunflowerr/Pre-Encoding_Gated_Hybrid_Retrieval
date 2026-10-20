"""Shared data contracts transcribed from the reviewed plan, without backend imports."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Query:
    query_id: str
    domain: str
    text: str

    def __post_init__(self) -> None:
        if not self.domain or not self.query_id.startswith(self.domain + ":"):
            raise ValueError("query_id must be namespaced with domain")
        if not isinstance(self.text, str):
            raise TypeError("query text must be a string")


@dataclass(frozen=True)
class Hit:
    doc_id: str
    score: float
    rank: int


@dataclass(frozen=True)
class Ranking:
    query_id: str
    domain: str
    hits: tuple[Hit, ...]
    corpus_hash: str
    retriever_hash: str

    def validate(self) -> None:
        ids = [hit.doc_id for hit in self.hits]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate document IDs")
        for rank, hit in enumerate(self.hits, 1):
            if hit.rank != rank or not math.isfinite(hit.score):
                raise ValueError("ranking must have consecutive ranks and finite scores")
            if not hit.doc_id.startswith(self.domain + ":"):
                raise ValueError("document domain mismatch")


@dataclass(frozen=True)
class LexicalStats:
    idf_min: float
    idf_mean: float
    idf_std: float
    oov_ratio: float
    token_count: int
    tokenizer_hash: str


@dataclass(frozen=True)
class FeatureVector:
    values: tuple[float, ...]
    schema_hash: str


@dataclass(frozen=True)
class GateDecision:
    use_dense: bool
    score: float
    threshold: float
    reason: str


@dataclass(frozen=True)
class SearchResponse:
    ranking: Ranking
    use_dense: bool
    gate_score: float | None
    encoder_calls: int
    fallback_reason: str | None


class SparseBackend(Protocol):
    def search(self, query: Query, k: int = 100) -> Ranking: ...
    def query_stats(self, query: Query) -> LexicalStats: ...


class DenseBackend(Protocol):
    def search(self, query: Query, k: int = 100) -> Ranking: ...


class FusionEngine(Protocol):
    def fuse(self, sparse: Ranking, dense: Ranking, k: int = 100) -> Ranking: ...


class FeatureExtractor(Protocol):
    def transform(self, query: Query, sparse: Ranking, stats: LexicalStats) -> FeatureVector: ...


class Gate(Protocol):
    def decide(self, features: FeatureVector) -> GateDecision: ...


class SearchMethod(Protocol):
    def search(self, query: Query, k: int = 100) -> SearchResponse: ...
