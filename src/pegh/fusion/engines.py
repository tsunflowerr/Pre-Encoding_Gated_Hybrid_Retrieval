from __future__ import annotations

import math

from contracts.types import Ranking, SearchHit
from pegh.data.artifacts import object_hash


def _validate_inputs(sparse: Ranking, dense: Ranking, k: int) -> None:
    if type(k) is not int or k < 1:
        raise ValueError("k must be a positive integer")
    sparse.validate()
    dense.validate()
    if (sparse.query_id, sparse.domain, sparse.corpus_hash) != (
        dense.query_id,
        dense.domain,
        dense.corpus_hash,
    ):
        raise ValueError("fusion inputs must share query, domain, and corpus")


def _ranking(
    sparse: Ranking, dense: Ranking, scores: dict[str, float], *, method: str, config: dict, k: int
) -> Ranking:
    hits = tuple(
        SearchHit(doc_id, score, rank)
        for rank, (doc_id, score) in enumerate(
            sorted(scores.items(), key=lambda item: (-item[1], item[0]))[:k], 1
        )
    )
    result = Ranking(
        sparse.query_id,
        sparse.domain,
        hits,
        sparse.corpus_hash,
        object_hash(
            {
                "method": method,
                "config": config,
                "sparse_retriever_hash": sparse.retriever_hash,
                "dense_retriever_hash": dense.retriever_hash,
            }
        ),
    )
    result.validate()
    return result


def _minmax(ranking: Ranking) -> dict[str, float]:
    if not ranking.hits:
        return {}
    values = [hit.score for hit in ranking.hits]
    scale = max(abs(value) for value in values)
    if scale == 0:
        return {hit.doc_id: 1.0 for hit in ranking.hits}
    scaled = [value / scale for value in values]
    low, high = min(scaled), max(scaled)
    if high == low:
        return {hit.doc_id: 1.0 for hit in ranking.hits}
    return {hit.doc_id: (hit.score / scale - low) / (high - low) for hit in ranking.hits}


def fuse_cc(sparse: Ranking, dense: Ranking, *, alpha_dense: float, k: int = 100) -> Ranking:
    """Combine min-max normalized scores, assigning zero to a missing branch."""
    _validate_inputs(sparse, dense, k)
    if isinstance(alpha_dense, bool) or not isinstance(alpha_dense, (int, float)):
        raise TypeError("alpha_dense must be numeric")
    if not math.isfinite(alpha_dense) or not 0 <= alpha_dense <= 1:
        raise ValueError("alpha_dense must be finite and between 0 and 1")
    if alpha_dense == 0:
        return _ranking(
            sparse,
            dense,
            {hit.doc_id: hit.score for hit in sparse.hits},
            method="cc_v1",
            config={"alpha_dense": 0.0},
            k=k,
        )
    if alpha_dense == 1:
        return _ranking(
            sparse,
            dense,
            {hit.doc_id: hit.score for hit in dense.hits},
            method="cc_v1",
            config={"alpha_dense": 1.0},
            k=k,
        )
    sparse_scores, dense_scores = _minmax(sparse), _minmax(dense)
    scores = {
        doc_id: (1 - alpha_dense) * sparse_scores.get(doc_id, 0.0)
        + alpha_dense * dense_scores.get(doc_id, 0.0)
        for doc_id in sparse_scores.keys() | dense_scores.keys()
    }
    return _ranking(
        sparse,
        dense,
        scores,
        method="cc_v1",
        config={"alpha_dense": float(alpha_dense)},
        k=k,
    )


def fuse_rrf(sparse: Ranking, dense: Ranking, *, rrf_k: int = 60, k: int = 100) -> Ranking:
    """Reciprocal rank fusion over the union; absent documents add no score."""
    _validate_inputs(sparse, dense, k)
    if type(rrf_k) is not int or rrf_k < 1:
        raise ValueError("rrf_k must be a positive integer")
    scores: dict[str, float] = {}
    for ranking in (sparse, dense):
        for hit in ranking.hits:
            scores[hit.doc_id] = scores.get(hit.doc_id, 0.0) + 1 / (rrf_k + hit.rank)
    return _ranking(
        sparse,
        dense,
        scores,
        method="rrf_v1",
        config={"rrf_k": rrf_k},
        k=k,
    )


class CCFusion:
    def __init__(self, alpha_dense: float) -> None:
        self.alpha_dense = alpha_dense

    def fuse(self, sparse: Ranking, dense: Ranking, k: int = 100) -> Ranking:
        return fuse_cc(sparse, dense, alpha_dense=self.alpha_dense, k=k)


class RRFFusion:
    def __init__(self, rrf_k: int = 60) -> None:
        self.rrf_k = rrf_k

    def fuse(self, sparse: Ranking, dense: Ranking, k: int = 100) -> Ranking:
        return fuse_rrf(sparse, dense, rrf_k=self.rrf_k, k=k)
