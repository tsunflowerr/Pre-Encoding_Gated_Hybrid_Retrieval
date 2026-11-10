"""Exact float64 BM25 over immutable corpus postings loaded before request timing."""

from __future__ import annotations

import json
import statistics
from array import array
from collections import Counter
from pathlib import Path

import numpy as np

from contracts.types import LexicalStats, Query, Ranking, SearchHit
from pegh.data.artifacts import atomic_json, file_hash, object_hash
from pegh.sparse.index import SQLiteBM25

FORMAT = "numpy_bm25_postings_v1"


def compile_index(source: str | Path, output: str | Path) -> dict:
    """Compile static document postings, never query vectors or query rankings."""
    directory = Path(output)
    directory.mkdir(parents=True, exist_ok=False)
    with SQLiteBM25(source) as backend:
        documents = list(
            backend.connection.execute(
                "SELECT row_id, doc_id, length FROM documents ORDER BY row_id"
            )
        )
        if [row[0] for row in documents] != list(range(1, len(documents) + 1)):
            raise ValueError("sparse document rows must be contiguous")
        if len(documents) != backend.manifest["document_count"]:
            raise ValueError("sparse document count differs from manifest")
        ids = [row[1] for row in documents]
        lengths = np.array([row[2] for row in documents], dtype=np.float64)
        if int(lengths.sum()) != backend.manifest["total_tokens"]:
            raise ValueError("sparse token count differs from manifest")
        average = backend.manifest["average_document_length"]
        if average != float(lengths.mean()):
            raise ValueError("sparse average length differs from database")
        normalizers = (
            backend.config.k1 * (1 - backend.config.b + backend.config.b * lengths / average)
            if average
            else np.zeros(len(ids))
        )
        lexical_order = np.empty(len(ids), dtype=np.uint32)
        lexical_order[sorted(range(len(ids)), key=ids.__getitem__)] = np.arange(
            len(ids), dtype=np.uint32
        )
        idf = dict(backend.connection.execute("SELECT term, idf FROM terms"))
        rows, frequencies = array("I"), array("I")
        terms = {}
        previous = None
        start = 0
        for term, row, frequency in backend.connection.execute(
            "SELECT term, row_id, tf FROM postings ORDER BY term, row_id"
        ):
            if term != previous:
                if previous is not None:
                    terms[previous] = [start, len(rows), idf[previous]]
                previous, start = term, len(rows)
            rows.append(row - 1)
            frequencies.append(frequency)
        if previous is not None:
            terms[previous] = [start, len(rows), idf[previous]]
        arrays = {
            "rows": np.asarray(rows, dtype="<u4"),
            "frequencies": np.asarray(frequencies, dtype="<u4"),
            "normalizers": normalizers.astype("<f8"),
            "lexical_order": lexical_order.astype("<u4"),
        }
        for name, values in arrays.items():
            np.save(directory / f"{name}.npy", values, allow_pickle=False)
        atomic_json(directory / "documents.json", ids)
        atomic_json(directory / "terms.json", terms)
        manifest = {
            "schema_version": FORMAT,
            "status": "complete",
            "logical_retriever_hash": backend.manifest["retriever_hash"],
            "source_database_sha256": backend.manifest["database_sha256"],
            "compiler_sha256": file_hash(__file__),
            "document_count": len(ids),
            "posting_count": len(rows),
            "files": {
                name: file_hash(directory / name)
                for name in (
                    "rows.npy",
                    "frequencies.npy",
                    "normalizers.npy",
                    "lexical_order.npy",
                    "documents.json",
                    "terms.json",
                )
            },
            "arithmetic": "float64_original_operation_order_sorted_terms",
            "top_k_policy": "partition_expand_exact_cutoff_ties_then_score_doc_id",
        }
        manifest["compiled_hash"] = object_hash(manifest)
        atomic_json(directory / "manifest.json", manifest)
        return manifest


class NumpyBM25(SQLiteBM25):
    """Same ranking identity as SQLite; execution identity is recorded separately."""

    def __init__(
        self, directory: str | Path, *, trace=None, compiled_dir: str | Path | None = None
    ):
        super().__init__(directory, trace=trace)
        self.connection.close()
        compiled = Path(compiled_dir) if compiled_dir is not None else Path(directory) / FORMAT
        data = json.loads((compiled / "manifest.json").read_text(encoding="utf-8"))
        if object_hash({k: v for k, v in data.items() if k != "compiled_hash"}) != data.get(
            "compiled_hash"
        ):
            raise ValueError("compiled sparse manifest checksum differs")
        if (
            data["schema_version"] != FORMAT
            or data["status"] != "complete"
            or data["logical_retriever_hash"] != self.manifest["retriever_hash"]
            or data["source_database_sha256"] != self.manifest["database_sha256"]
            or data["compiler_sha256"] != file_hash(__file__)
        ):
            raise ValueError(
                "compiled sparse source/implementation differs; recompile into a new directory"
            )
        expected_files = {
            "rows.npy",
            "frequencies.npy",
            "normalizers.npy",
            "lexical_order.npy",
            "documents.json",
            "terms.json",
        }
        if set(data["files"]) != expected_files:
            raise ValueError("unexpected compiled sparse files")
        for filename, expected in data["files"].items():
            if file_hash(compiled / filename) != expected:
                raise ValueError("compiled sparse file checksum differs")
        self._rows = np.load(compiled / "rows.npy", allow_pickle=False)
        self._tf = np.load(compiled / "frequencies.npy", allow_pickle=False)
        self._norm = np.load(compiled / "normalizers.npy", allow_pickle=False)
        self._lexical_order = np.load(compiled / "lexical_order.npy", allow_pickle=False)
        self._ids = json.loads((compiled / "documents.json").read_text(encoding="utf-8"))
        self._terms = json.loads((compiled / "terms.json").read_text(encoding="utf-8"))
        self._document_row = {doc_id: row for row, doc_id in enumerate(self._ids)}
        count = self.manifest["document_count"]
        if (
            len(self._ids) != count
            or self._norm.shape != (count,)
            or self._lexical_order.shape != (count,)
            or self._rows.shape != self._tf.shape
            or self._rows.size != data["posting_count"]
        ):
            raise ValueError("compiled sparse array dimensions differ")
        if self._rows.size and (int(self._rows.max()) >= count or not (self._tf > 0).all()):
            raise ValueError("invalid compiled sparse posting")
        if not np.isfinite(self._norm).all():
            raise ValueError("nonfinite compiled sparse normalization")
        for values in (self._rows, self._tf, self._norm, self._lexical_order):
            values.flags.writeable = False
        self.execution_provenance = {
            "implementation": FORMAT,
            "implementation_sha256": file_hash(__file__),
            "compiled_hash": data["compiled_hash"],
            "logical_retriever_hash": self.manifest["retriever_hash"],
            "numpy_version": np.__version__,
            "score_dtype": "float64",
            "query_result_cache": False,
        }

    def search(self, query: Query, k: int = 100) -> Ranking:
        if type(k) is not int or k < 1 or query.domain != self.manifest["domain"]:
            raise ValueError("positive integer k and matching sparse domain are required")
        with self._stage("sparse"):
            frequencies = Counter(self.tokenizer.tokenize(query.text))
            scores = np.zeros(len(self._ids), dtype=np.float64)
            for term in sorted(frequencies):
                posting = self._terms.get(term)
                if posting is None:
                    continue
                start, end, idf = posting
                rows = self._rows[start:end]
                tf = self._tf[start:end]
                # Match the scalar reference's operation order, including query TF.
                scores[rows] += (
                    frequencies[term] * idf * tf * (self.config.k1 + 1) / (tf + self._norm[rows])
                )
            own_row = self._document_row.get(query.query_id)
            if own_row is not None:
                scores[own_row] = 0
            candidates = np.flatnonzero(scores > 0)
            if len(candidates) > k:
                cutoff = np.partition(scores[candidates], len(candidates) - k)[len(candidates) - k]
                candidates = candidates[scores[candidates] >= cutoff]
            order = np.lexsort((self._lexical_order[candidates], -scores[candidates]))[:k]
            ranking = Ranking(
                query.query_id,
                query.domain,
                tuple(
                    SearchHit(self._ids[int(row)], float(scores[row]), rank)
                    for rank, row in enumerate(candidates[order], 1)
                ),
                self.manifest["corpus_sha256"],
                self.manifest["retriever_hash"],
            )
            ranking.validate()
            return ranking

    def query_stats(self, query: Query) -> LexicalStats:
        if query.domain != self.manifest["domain"]:
            raise ValueError("query/sparse domain mismatch")
        with self._stage("stats"):
            tokens = self.tokenizer.tokenize(query.text)
            if not tokens:
                return LexicalStats(0.0, 0.0, 0.0, 0.0, 0, self.config.fingerprint)
            values = [self._terms[token][2] for token in tokens if token in self._terms]
            return LexicalStats(
                min(values) if values else 0.0,
                statistics.fmean(values) if values else 0.0,
                statistics.pstdev(values) if len(values) > 1 else 0.0,
                sum(token not in self._terms for token in tokens) / len(tokens),
                len(tokens),
                self.config.fingerprint,
            )


def open_backend(directory: str | Path, *, trace=None, execution: str = "numpy"):
    if execution == "numpy":
        return NumpyBM25(directory, trace=trace)
    if execution == "sqlite":
        backend = SQLiteBM25(directory, trace=trace)
        backend.execution_provenance = {
            "implementation": "sqlite_bm25_v1",
            "implementation_sha256": file_hash(Path(__file__).with_name("index.py")),
            "logical_retriever_hash": backend.manifest["retriever_hash"],
            "query_result_cache": False,
        }
        return backend
    raise ValueError("unsupported sparse execution backend")
