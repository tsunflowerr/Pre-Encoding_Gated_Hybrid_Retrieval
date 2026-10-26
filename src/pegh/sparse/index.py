"""SQLite-backed exact BM25 reference implementation with persistent provenance."""

from __future__ import annotations

import math
import os
import sqlite3
import statistics
from collections import Counter, defaultdict
from contextlib import nullcontext
from pathlib import Path

from contracts.io import iter_corpus
from contracts.types import LexicalStats, Query, Ranking, SearchHit
from pegh.data.artifacts import atomic_json, file_hash, object_hash
from pegh.sparse.config import BM25Config
from pegh.sparse.tokenizer import TechnicalTokenizer


def build_index(
    corpus_path: str | Path,
    output: str | Path,
    domain: str,
    config: BM25Config,
) -> dict:
    source, directory = Path(corpus_path), Path(output)
    directory.mkdir(parents=True, exist_ok=True)
    if any(directory.iterdir()):
        raise FileExistsError("sparse output directory must be empty")
    database = directory / "index.sqlite3"
    temporary = database.with_suffix(".sqlite3.tmp")
    connection = sqlite3.connect(temporary)
    document_count = total_length = 0
    dfs: Counter[str] = Counter()
    try:
        connection.executescript("""
            PRAGMA journal_mode=OFF;
            PRAGMA synchronous=FULL;
            CREATE TABLE documents (
                row_id INTEGER PRIMARY KEY,
                doc_id TEXT NOT NULL UNIQUE,
                length INTEGER NOT NULL
            );
            CREATE TABLE postings (
                term TEXT NOT NULL,
                row_id INTEGER NOT NULL,
                tf INTEGER NOT NULL,
                PRIMARY KEY (term, row_id),
                FOREIGN KEY (row_id) REFERENCES documents(row_id)
            );
            CREATE TABLE terms (
                term TEXT PRIMARY KEY,
                df INTEGER NOT NULL,
                idf REAL NOT NULL
            );
            """)
        tokenizer = TechnicalTokenizer(config)
        for row_id, document in enumerate(iter_corpus(source, domain), 1):
            frequencies = Counter(tokenizer.tokenize(document.text))
            length = sum(frequencies.values())
            connection.execute(
                "INSERT INTO documents(row_id, doc_id, length) VALUES (?, ?, ?)",
                (row_id, document.doc_id, length),
            )
            connection.executemany(
                "INSERT INTO postings(term, row_id, tf) VALUES (?, ?, ?)",
                ((term, row_id, frequency) for term, frequency in frequencies.items()),
            )
            dfs.update(frequencies.keys())
            document_count += 1
            total_length += length
        if document_count == 0:
            raise ValueError("cannot build a sparse index from an empty corpus")
        connection.executemany(
            "INSERT INTO terms(term, df, idf) VALUES (?, ?, ?)",
            (
                (
                    term,
                    df,
                    math.log(1 + (document_count - df + 0.5) / (df + 0.5)),
                )
                for term, df in dfs.items()
            ),
        )
        connection.executescript("""
            CREATE INDEX postings_term ON postings(term);
            CREATE INDEX postings_row ON postings(row_id);
            PRAGMA optimize;
            """)
        connection.commit()
    finally:
        connection.close()
    os.replace(temporary, database)
    database_hash = file_hash(database)
    manifest = {
        "schema_version": "1.0",
        "status": "complete",
        "domain": domain,
        "implementation": config.implementation,
        "config": {
            "implementation": config.implementation,
            "k1": config.k1,
            "b": config.b,
            "lowercase": config.lowercase,
            "token_pattern": config.token_pattern,
            "output_k": config.output_k,
        },
        "tokenizer_hash": config.fingerprint,
        "corpus_sha256": file_hash(source),
        "document_count": document_count,
        "total_tokens": total_length,
        "average_document_length": total_length / document_count,
        "vocabulary_size": len(dfs),
        "database_file": database.name,
        "database_sha256": database_hash,
        "formula": "robertson_bm25_idf_log1p_v1",
        "tie_policy": "score_desc_doc_id_asc_v1",
    }
    manifest["retriever_hash"] = object_hash(manifest)
    atomic_json(directory / "manifest.json", manifest)
    return manifest


class SQLiteBM25:
    def __init__(self, directory: str | Path, *, trace=None):
        self.directory = Path(directory)
        import json

        with (self.directory / "manifest.json").open(encoding="utf-8") as stream:
            self.manifest = json.load(stream)
        unsigned = {key: value for key, value in self.manifest.items() if key != "retriever_hash"}
        if object_hash(unsigned) != self.manifest.get("retriever_hash"):
            raise ValueError("sparse manifest/retriever checksum mismatch")
        if (
            self.manifest.get("status") != "complete"
            or self.manifest.get("schema_version") != "1.0"
        ):
            raise ValueError("sparse index is incomplete or has an unsupported schema")
        database = self.directory / self.manifest["database_file"]
        if file_hash(database) != self.manifest["database_sha256"]:
            raise ValueError("sparse index checksum mismatch")
        self.config = BM25Config(**self.manifest["config"])
        if self.config.fingerprint != self.manifest["tokenizer_hash"]:
            raise ValueError("sparse tokenizer/config fingerprint mismatch")
        self.tokenizer = TechnicalTokenizer(self.config)
        self.connection = sqlite3.connect(f"file:{database.resolve()}?mode=ro", uri=True)
        self.trace = trace

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> SQLiteBM25:
        return self

    def __exit__(self, *_args) -> None:
        self.close()

    def _stage(self, name: str):
        return self.trace.stage(name) if self.trace is not None else nullcontext()

    def _term_rows(self, terms: list[str]):
        unique = sorted(set(terms))
        for start in range(0, len(unique), 900):
            block = unique[start : start + 900]
            placeholders = ",".join("?" for _ in block)
            yield from self.connection.execute(
                f"""
                SELECT p.term, d.doc_id, d.length, p.tf, t.idf
                FROM postings p
                JOIN documents d ON d.row_id = p.row_id
                JOIN terms t ON t.term = p.term
                WHERE p.term IN ({placeholders})
                """,
                block,
            )

    def search(self, query: Query, k: int = 100) -> Ranking:
        if k < 1 or query.domain != self.manifest["domain"]:
            raise ValueError("positive k and matching sparse domain are required")
        with self._stage("sparse"):
            tokens = self.tokenizer.tokenize(query.text)
            frequencies = Counter(tokens)
            scores: dict[str, float] = defaultdict(float)
            average_length = self.manifest["average_document_length"]
            for term, doc_id, length, term_frequency, idf in self._term_rows(tokens):
                denominator = term_frequency + self.config.k1 * (
                    1 - self.config.b + self.config.b * length / average_length
                )
                scores[doc_id] += (
                    frequencies[term] * idf * term_frequency * (self.config.k1 + 1) / denominator
                )
            ordered = sorted(
                (
                    (doc_id, float(score))
                    for doc_id, score in scores.items()
                    if doc_id != query.query_id and score > 0
                ),
                key=lambda item: (-item[1], item[0]),
            )[:k]
            ranking = Ranking(
                query.query_id,
                query.domain,
                tuple(
                    SearchHit(doc_id, score, rank)
                    for rank, (doc_id, score) in enumerate(ordered, 1)
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
            unique = sorted(set(tokens))
            idf_by_term = {}
            for start in range(0, len(unique), 900):
                block = unique[start : start + 900]
                placeholders = ",".join("?" for _ in block)
                idf_by_term.update(
                    self.connection.execute(
                        f"SELECT term, idf FROM terms WHERE term IN ({placeholders})", block
                    ).fetchall()
                )
            values = [idf_by_term[token] for token in tokens if token in idf_by_term]
            oov = sum(token not in idf_by_term for token in tokens) / len(tokens)
            return LexicalStats(
                min(values) if values else 0.0,
                statistics.fmean(values) if values else 0.0,
                statistics.pstdev(values) if len(values) > 1 else 0.0,
                oov,
                len(tokens),
                self.config.fingerprint,
            )
