from __future__ import annotations

import json
import random

import pytest

from contracts import Query
from pegh.data.artifacts import write_jsonl
from pegh.sparse.config import BM25Config
from pegh.sparse.fast import FORMAT, NumpyBM25, compile_index
from pegh.sparse.index import SQLiteBM25, build_index


def test_numpy_postings_match_scalar_scores_stats_self_filter_and_cutoff_ties(tmp_path):
    rng = random.Random(42)
    corpus = tmp_path / "corpus.jsonl"
    vocabulary = ["alpha", "beta", "gamma", "--verbose", "socket", "error.code", "café"]
    write_jsonl(
        corpus,
        (
            {
                "_id": f"{i:03d}",
                "title": "common token",
                "text": " ".join(rng.choices(vocabulary, k=rng.randint(2, 30))),
            }
            for i in range(120)
        ),
    )
    directory = tmp_path / "index"
    build_index(corpus, directory, "unix", BM25Config())
    compile_index(directory, directory / FORMAT)
    queries = [
        Query("unix:010", "unix", text)
        for text in (
            "alpha beta",
            "beta beta beta socket",
            "common",
            "café --verbose error.code",
            "",
            "unseen-identifier",
        )
    ]
    queries += [
        Query(f"unix:q{i}", "unix", " ".join(rng.choices(vocabulary, k=10))) for i in range(15)
    ]
    with SQLiteBM25(directory) as scalar, NumpyBM25(directory) as fast:
        for query in queries:
            assert fast.query_stats(query) == scalar.query_stats(query)
            for k in (1, 5, 100, 200):
                assert fast.search(query, k=k) == scalar.search(query, k=k)
        assert fast.execution_provenance["query_result_cache"] is False


def test_compiled_index_rejects_mutated_binary_array(tmp_path):
    directory = tmp_path / "index"
    build_index("tests/fixtures/shared/unix/corpus.jsonl", directory, "unix", BM25Config())
    compiled = directory / FORMAT
    compile_index(directory, compiled)
    with (compiled / "rows.npy").open("ab") as stream:
        stream.write(b"modified")
    with pytest.raises(ValueError, match="file checksum"):
        NumpyBM25(directory)


def test_compiled_index_keeps_its_logical_index_identity(tmp_path):
    directory = tmp_path / "index"
    original = build_index(
        "tests/fixtures/shared/unix/corpus.jsonl", directory, "unix", BM25Config()
    )
    compiled = compile_index(directory, directory / FORMAT)
    assert compiled["logical_retriever_hash"] == original["retriever_hash"]
    assert json.loads((directory / "manifest.json").read_text(encoding="utf-8")) == original
    with pytest.raises(FileExistsError):
        compile_index(directory, directory / FORMAT)
