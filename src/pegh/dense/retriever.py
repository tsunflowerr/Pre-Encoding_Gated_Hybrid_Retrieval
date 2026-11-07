from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

import faiss
import numpy as np

from contracts.types import Hit, Query, Ranking, SearchResponse
from pegh.dense.artifacts import checked_child, object_hash
from pegh.dense.encoder import TextEncoder, checked_vectors, implementation_fingerprint
from pegh.dense.index import package_versions, verify_index
from pegh.profiling.trace import NullTraceSink, TraceSink


class FaissDenseRetriever:
    def __init__(
        self,
        directory: str | Path,
        encoder: TextEncoder,
        *,
        trace: TraceSink | NullTraceSink | None = None,
    ):
        self.directory = Path(directory)
        self.manifest, self.doc_ids = verify_index(directory)
        if self.manifest["package_versions"] != package_versions():
            raise ValueError("query/index package versions differ; use the frozen environment")
        if self.manifest["embedding_fingerprint"] != encoder.config.embedding_fingerprint:
            raise ValueError("query encoder and corpus embeddings are incompatible")
        if self.manifest["encoder_implementation_hash"] != implementation_fingerprint(encoder):
            raise ValueError("query/corpus encoder implementations are incompatible")
        faiss.omp_set_num_threads(encoder.config.faiss_threads)
        self.index = faiss.read_index(
            str(checked_child(self.directory, self.manifest["index_file"]))
        )
        if (
            not isinstance(self.index, faiss.IndexFlatIP)
            or self.index.d != encoder.config.dimension
            or self.index.ntotal != len(self.doc_ids)
        ):
            raise ValueError("unexpected FAISS type/dimension/count")
        self.encoder = encoder
        self.trace = trace if trace is not None else NullTraceSink()
        self.encoder_calls = 0
        self.vector_search_calls = 0
        self.retriever_hash = object_hash(
            {
                "index_sha256": self.manifest["index_sha256"],
                "embedding": self.manifest["embedding_fingerprint"],
                "tie_policy": "exact_score_then_doc_id_v1",
            }
        )

    def _ranking(self, query: Query, hits: tuple[Hit, ...]) -> Ranking:
        ranking = Ranking(
            query.query_id, query.domain, hits, self.manifest["corpus_sha256"], self.retriever_hash
        )
        ranking.validate()
        return ranking

    def search(self, query: Query, k: int = 100) -> Ranking:
        if k < 1 or query.domain != self.manifest["domain"]:
            raise ValueError("positive k and matching domain are required")
        if not query.text.strip():
            return self._ranking(query, ())
        return self.search_vector(query, self.encode_query(query), k=k)

    def encode_query(self, query: Query) -> np.ndarray:
        """Encode once with instrumentation; enables QDAP-style vector reuse later."""
        if query.domain != self.manifest["domain"] or not query.text.strip():
            raise ValueError("encoding requires a nonempty query in the index domain")
        with self.trace.stage("encode"):
            self.encoder_calls += 1
            self.trace.increment("encoder_calls")
            vector = checked_vectors(self.encoder.encode([query.text]), 1, self.index.d)
        return vector

    def search_vector(self, query: Query, vector: np.ndarray, k: int = 100) -> Ranking:
        """Optional vector reuse boundary; does not encode or maintain a query cache."""
        if k < 1 or query.domain != self.manifest["domain"]:
            raise ValueError("positive k and matching domain are required")
        vector = checked_vectors(vector, 1, self.index.d)
        with self.trace.stage("vector"):
            count = min(self.index.ntotal, k + 1)
            while True:
                self.vector_search_calls += 1
                self.trace.increment("vector_search_calls")
                scores, rows = self.index.search(vector, count)
                candidates = sorted(
                    [
                        (self.doc_ids[int(row)], float(score))
                        for row, score in zip(rows[0], scores[0], strict=True)
                        if row >= 0 and self.doc_ids[int(row)] != query.query_id
                    ],
                    key=lambda item: (-item[1], item[0]),
                )
                # Expand exact cutoff ties so deterministic IDs do not depend on
                # which tied vectors FAISS happens to return at the boundary.
                expand = len(candidates) < k or (
                    len(candidates) >= k and float(scores[0, -1]) == candidates[k - 1][1]
                )
                if count >= self.index.ntotal or not expand:
                    break
                count = min(self.index.ntotal, max(count + 1, count * 2))
        return self._ranking(
            query,
            tuple(
                Hit(doc_id, score, rank) for rank, (doc_id, score) in enumerate(candidates[:k], 1)
            ),
        )


class DenseOnlyMethod:
    """Benchmark adapter. Gate/hybrid adapters will be supplied by person C."""

    def __init__(self, retriever: FaissDenseRetriever):
        self.retriever = retriever
        self.provenance = {
            "dense_config": asdict(retriever.encoder.config),
            "corpus_sha256": retriever.manifest["corpus_sha256"],
            "index_sha256": retriever.manifest["index_sha256"],
            "retriever_hash": retriever.retriever_hash,
            "query_embedding_cache": False,
        }

    def search(self, query: Query, k: int = 100) -> SearchResponse:
        before = self.retriever.encoder_calls
        ranking = self.retriever.search(query, k=k)
        calls = self.retriever.encoder_calls - before
        return SearchResponse(
            ranking, calls > 0, None, calls, "empty_query" if not query.text.strip() else None
        )
