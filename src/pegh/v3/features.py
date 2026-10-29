"""v3 pre-dense features: v1 schema + BM25 query-performance predictors + semantic proxy.

All values use only the query text, sparse statistics, the BM25 top-100 list and stored
document vectors of those BM25 candidates. No query embedding is computed.
"""

from __future__ import annotations

import math
import statistics

import numpy as np

from contracts.types import FeatureVector, LexicalStats, Query, Ranking
from pegh.data.artifacts import object_hash
from pegh.gating.features import FEATURE_NAMES, QueryFeatureExtractor

QPP_NAMES = (
    "qpp_nqc100",
    "qpp_wig10",
    "qpp_smv100",
    "qpp_ratio10",
    "qpp_ratio_last",
    "idf_max",
    "idf_sum_unique",
)
PROXY_NAMES = (
    "px_top1",
    "px_max10",
    "px_mean10",
    "px_gap_below10",
    "px_argmax_rank",
    "px_overlap10",
    "px_rrf_overlap10",
    "px_spearman",
    "px_std",
)
GROUPS = {"v1": FEATURE_NAMES, "qpp": QPP_NAMES, "proxy": PROXY_NAMES}


def qpp_features(scores: list[float], token_idfs: list[float], token_count: int) -> tuple:
    n = len(scores)
    s1 = scores[0] if n else 0.0
    mean = statistics.fmean(scores) if n else 0.0
    nqc = statistics.pstdev(scores) / mean if n > 1 and mean > 0 else 0.0
    wig = (statistics.fmean(scores[:10]) - mean) / math.sqrt(max(token_count, 1)) if n else 0.0
    smv = (
        statistics.fmean(s * abs(math.log(s / mean)) for s in scores if s > 0) / mean
        if n and mean > 0
        else 0.0
    )
    ratio10 = scores[min(10, n) - 1] / s1 if n and s1 > 0 else 0.0
    ratio_last = scores[-1] / s1 if n and s1 > 0 else 0.0
    return (
        nqc,
        wig,
        smv,
        ratio10,
        ratio_last,
        max(token_idfs) if token_idfs else 0.0,
        float(sum(set(token_idfs))),
    )


def _overlap(left: list[int], right: list[int]) -> float:
    return len(set(left) & set(right)) / len(left) if left else 0.0


def proxy_features(query_vector: np.ndarray, candidates: np.ndarray, scores: list[float]) -> tuple:
    """candidates: stored dense vectors of BM25 hits, in BM25 rank order."""
    n = len(scores)
    if n == 0 or not np.any(query_vector):
        return (0.0,) * len(PROXY_NAMES)
    cos = candidates @ query_vector
    cut = min(10, n)
    bm25_top = list(range(cut))
    proxy_order = sorted(range(n), key=lambda i: (-float(cos[i]), i))
    proxy_rank = {row: rank for rank, row in enumerate(proxy_order, 1)}
    rrf = sorted(range(n), key=lambda i: (-(1 / (61 + i) + 1 / (60 + proxy_rank[i])), i))
    if n >= 3:
        bm25_ranks = np.arange(1, n + 1, dtype=np.float64)
        ranks = np.asarray([proxy_rank[i] for i in range(n)], dtype=np.float64)
        spearman = float(np.corrcoef(bm25_ranks, ranks)[0, 1])
        spearman = spearman if math.isfinite(spearman) else 0.0
    else:
        spearman = 0.0
    return (
        float(cos[0]),
        float(cos[:cut].max()),
        float(cos[:cut].mean()),
        float(cos[cut:].max() - cos[:cut].max()) if n > cut else 0.0,
        math.log1p(proxy_order[0]) / math.log(100),
        _overlap(bm25_top, proxy_order[:cut]),
        _overlap(bm25_top, rrf[:cut]),
        spearman,
        float(cos.std()),
    )


class ExtendedFeatureExtractor:
    """Concatenate selected feature groups in fixed order: v1, qpp, proxy."""

    def __init__(
        self,
        base: QueryFeatureExtractor,
        sparse_backend,
        groups: tuple[str, ...],
        *,
        proxy=None,
        doc_vectors: np.ndarray | None = None,
        doc_rows: dict[str, int] | None = None,
    ) -> None:
        if not groups or any(g not in GROUPS for g in groups) or groups[0] != "v1":
            raise ValueError("feature groups must start with v1 and use registered names")
        if "proxy" in groups and (proxy is None or doc_vectors is None or doc_rows is None):
            raise ValueError("proxy features need the static proxy and stored document vectors")
        terms = getattr(sparse_backend, "_terms", None)
        if not isinstance(terms, dict):
            raise ValueError("v3 IDF features need the compiled in-memory BM25 backend")
        self.base = base
        self.terms = terms
        self.groups = tuple(groups)
        self.proxy = proxy
        self.doc_vectors = doc_vectors
        self.doc_rows = doc_rows
        self.names = tuple(name for group in self.groups for name in GROUPS[group])
        self.schema_hash = object_hash(
            {
                "schema_version": "v3_features_1",
                "groups": list(self.groups),
                "names": list(self.names),
                "v1_schema_hash": base.schema_hash,
                "proxy": proxy.identity if "proxy" in self.groups else None,
            }
        )

    def transform(self, query: Query, sparse: Ranking, stats: LexicalStats) -> FeatureVector:
        values = list(self.base.transform(query, sparse, stats).values)
        scores = [hit.score for hit in sparse.hits]
        if "qpp" in self.groups:
            tokens = self.base.tokenizer.tokenize(query.text)
            idfs = [self.terms[t][2] for t in tokens if t in self.terms]
            values += qpp_features(scores, idfs, len(tokens))
        if "proxy" in self.groups:
            rows = [self.doc_rows[hit.doc_id] for hit in sparse.hits]
            values += proxy_features(self.proxy.embed(query.text), self.doc_vectors[rows], scores)
        if len(values) != len(self.names) or not all(math.isfinite(v) for v in values):
            raise ValueError("v3 feature transform produced an invalid vector")
        return FeatureVector(tuple(float(v) for v in values), self.schema_hash)
