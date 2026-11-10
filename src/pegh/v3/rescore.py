"""Re-score the BM25 candidate list with a query vector and stored document vectors.

One implementation serves offline utilities and online methods, so online rankings can be
checked against the offline cache. No vector index search is performed.
"""

from __future__ import annotations

import numpy as np

from contracts.types import Ranking, SearchHit
from pegh.data.artifacts import object_hash
from pegh.fusion import fuse_cc


def rescored_ranking(
    sparse: Ranking,
    query_vector: np.ndarray,
    doc_vectors: np.ndarray,
    doc_rows: dict[str, int],
    identity: str,
) -> Ranking:
    """BM25 candidates ordered by inner product with the query vector; ties by doc ID."""
    if not sparse.hits:
        return sparse
    ids = [hit.doc_id for hit in sparse.hits]
    scores = doc_vectors[[doc_rows[doc_id] for doc_id in ids]] @ query_vector
    order = sorted(zip(ids, scores.tolist(), strict=True), key=lambda item: (-item[1], item[0]))
    ranking = Ranking(
        sparse.query_id,
        sparse.domain,
        tuple(
            SearchHit(doc_id, float(score), rank) for rank, (doc_id, score) in enumerate(order, 1)
        ),
        sparse.corpus_hash,
        identity,
    )
    ranking.validate()
    return ranking


def candidate_fusion(
    sparse: Ranking, rescored: Ranking, alpha_dense: float, k: int = 100
) -> Ranking:
    """CC fusion restricted to the BM25 candidate set; empty sparse lists stay empty."""
    if not sparse.hits:
        return sparse
    return fuse_cc(sparse, rescored, alpha_dense=alpha_dense, k=k)


def rescore_identity(kind: str, source: str) -> str:
    return object_hash({"kind": kind, "source": source, "candidates": "bm25_top100_v1"})
