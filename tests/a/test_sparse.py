from __future__ import annotations

import math
from pathlib import Path

import pytest

from contracts import Query
from pegh.sparse.config import BM25Config
from pegh.sparse.index import SQLiteBM25, build_index

CORPUS = Path("tests/fixtures/shared/programmers/corpus.jsonl")


def test_bm25_build_search_reload_stats_and_self_filter(tmp_path):
    directory = tmp_path / "bm25"
    manifest = build_index(CORPUS, directory, "programmers", BM25Config())
    assert manifest["document_count"] == 10
    assert manifest["vocabulary_size"] > 20
    with SQLiteBM25(directory) as first:
        query = Query("programmers:q01", "programmers", "threads shared counter updates")
        ranking = first.search(query, k=5)
        stats = first.query_stats(query)
        assert ranking.hits[0].doc_id == "programmers:001"
        assert stats.token_count == 4
        assert stats.oov_ratio == 0
        counter_stats = first.query_stats(Query("programmers:q03", "programmers", "counter"))
        assert counter_stats.idf_mean == pytest.approx(math.log(1 + 9.5 / 1.5))
    with SQLiteBM25(directory) as second:
        assert second.search(query, k=5) == ranking
        self_query = Query("programmers:001", "programmers", "threads shared counter")
        assert all(hit.doc_id != self_query.query_id for hit in second.search(self_query).hits)


def test_bm25_empty_oov_and_wrong_domain(tmp_path):
    directory = tmp_path / "bm25"
    build_index(CORPUS, directory, "programmers", BM25Config())
    with SQLiteBM25(directory) as backend:
        empty = Query("programmers:empty", "programmers", " \n")
        assert backend.search(empty).hits == ()
        assert backend.query_stats(empty).token_count == 0
        oov = Query("programmers:oov", "programmers", "zzzz_not_in_fixture")
        assert backend.search(oov).hits == ()
        assert backend.query_stats(oov).oov_ratio == 1
        with pytest.raises(ValueError, match="domain"):
            backend.search(Query("unix:q", "unix", "counter"))


def test_sparse_index_refuses_overwrite_and_detects_tamper(tmp_path):
    directory = tmp_path / "bm25"
    build_index(CORPUS, directory, "programmers", BM25Config())
    with pytest.raises(FileExistsError):
        build_index(CORPUS, directory, "programmers", BM25Config())
    with (directory / "index.sqlite3").open("ab") as stream:
        stream.write(b"tamper")
    with pytest.raises(ValueError, match="checksum"):
        SQLiteBM25(directory)
