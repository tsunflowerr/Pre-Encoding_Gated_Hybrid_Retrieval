from __future__ import annotations

import json
from pathlib import Path

import pytest

from contracts.io import load_queries
from pegh.data.manifest import audit_dataset
from pegh.data.qrels import load_qrels, positive_qrels
from pegh.data.splits import fold_record, make_five_fold_splits

SHARED = Path("tests/fixtures/shared")
A_FIXTURE = Path("tests/fixtures/a")


def test_qrels_use_canonical_ids_and_remove_self():
    qrels = load_qrels(A_FIXTURE / "unix/qrels.tsv", "unix")
    assert qrels["unix:q01"] == {"unix:001": 1.0}
    assert positive_qrels(qrels, "unix:001") == {}
    assert positive_qrels(qrels, "unix:001", remove_self=False) == {"unix:001": 1.0}


def test_dataset_audit_checks_hashes_counts_and_coverage():
    manifest = audit_dataset(
        SHARED / "programmers/corpus.jsonl",
        SHARED / "programmers/queries.jsonl",
        A_FIXTURE / "programmers/qrels.tsv",
        "programmers",
    )
    assert manifest["counts"] == {
        "documents": 10,
        "queries": 3,
        "qrel_queries": 3,
        "qrel_pairs": 3,
    }
    assert manifest["coverage"]["queries_without_positive_nonself_qrel"] == ["programmers:001"]
    assert len(manifest["manifest_hash"]) == 64


def test_dataset_audit_rejects_dangling_qrels(tmp_path):
    qrels = tmp_path / "qrels.jsonl"
    qrels.write_text(
        json.dumps({"query_id": "q01", "doc_id": "missing", "relevance": 1}) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unknown IDs"):
        audit_dataset(
            SHARED / "unix/corpus.jsonl",
            SHARED / "unix/queries.jsonl",
            qrels,
            "unix",
        )


def test_five_fold_split_keeps_shared_relevance_group_and_tests_once():
    queries = {
        domain: load_queries(SHARED / domain / "queries.jsonl", domain)
        for domain in ("programmers", "unix")
    }
    qrels = {domain: load_qrels(A_FIXTURE / domain / "qrels.tsv", domain) for domain in queries}
    manifest = make_five_fold_splits(queries, qrels, seed=42)
    for domain in queries:
        buckets = manifest["domains"][domain]["buckets"]
        bucket_by_query = {
            query_id: number for number, bucket in enumerate(buckets) for query_id in bucket
        }
        assert bucket_by_query[f"{domain}:q01"] == bucket_by_query[f"{domain}:001"]
        observed = []
        for fold in range(5):
            parts = fold_record(manifest, fold)["domains"][domain]
            assert not (set(parts["train"]) & set(parts["validation"]))
            assert not (set(parts["train"]) & set(parts["test"]))
            observed.extend(parts["test"])
        assert sorted(observed) == sorted(query.query_id for query in queries[domain])
