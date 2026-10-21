"""Public A/B/C contracts. Import these types instead of defining local copies."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Protocol

from contracts.ids import validate_id
from contracts.text import build_document_text


@dataclass(frozen=True)
class Document:
    doc_id: str
    domain: str
    title: str = ""
    body: str = ""

    def __post_init__(self) -> None:
        validate_id(self.doc_id, self.domain)
        if not self.text.strip():
            raise ValueError("document title/body must not both be empty or whitespace")

    @property
    def text(self) -> str:
        """The exact string fed to retrievers, preserving code and whitespace."""
        return build_document_text(self.title, self.body)


@dataclass(frozen=True)
class Query:
    query_id: str
    domain: str
    text: str

    def __post_init__(self) -> None:
        validate_id(self.query_id, self.domain)
        if not isinstance(self.text, str):
            raise TypeError("query text must be a string")


@dataclass(frozen=True)
class SearchHit:
    doc_id: str
    score: float
    rank: int

    def __post_init__(self) -> None:
        if not isinstance(self.doc_id, str) or ":" not in self.doc_id:
            raise ValueError("hit doc_id must be canonical")
        validate_id(self.doc_id, self.doc_id.split(":", 1)[0])
        if isinstance(self.score, bool) or not isinstance(self.score, (int, float)):
            raise TypeError("hit score must be a real JSON number")
        if not math.isfinite(self.score):
            raise ValueError("hit score must be finite")
        if type(self.rank) is not int or self.rank < 1:
            raise ValueError("hit rank must be a positive integer")


# Exact alias: old B imports and new A/C code create the same runtime class.
Hit = SearchHit


@dataclass(frozen=True)
class Ranking:
    query_id: str
    domain: str
    hits: tuple[SearchHit, ...]
    corpus_hash: str
    retriever_hash: str

    def validate(self) -> None:
        validate_id(self.query_id, self.domain)
        if not isinstance(self.hits, tuple) or any(not isinstance(h, SearchHit) for h in self.hits):
            raise TypeError("ranking hits must be a tuple of SearchHit")
        if any(not isinstance(h, str) or not h for h in (self.corpus_hash, self.retriever_hash)):
            raise ValueError("ranking corpus/retriever provenance must be nonempty strings")
        ids = [hit.doc_id for hit in self.hits]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate document IDs")
        for rank, hit in enumerate(self.hits, 1):
            if hit.rank != rank or not math.isfinite(hit.score):
                raise ValueError("ranking must have consecutive ranks and finite scores")
            validate_id(hit.doc_id, self.domain)
            if hit.doc_id == self.query_id:
                raise ValueError("self-hit must be removed before returning a ranking")
        if list(self.hits) != sorted(self.hits, key=lambda hit: (-hit.score, hit.doc_id)):
            raise ValueError("ranking order must be descending score then ascending doc_id")


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
