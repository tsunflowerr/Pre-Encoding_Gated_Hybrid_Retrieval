from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from contracts import Ranking, SearchHit
from contracts.io import load_queries
from contracts.ranking import ranking_to_record
from pegh.data.artifacts import atomic_json, file_hash, object_hash, write_jsonl
from pegh.data.manifest import audit_dataset, dataset_identity_payload
from pegh.data.splits import validate_five_fold_splits
from pegh.evaluation.oof import run_oof
from pegh.sparse.config import BM25Config
from pegh.sparse.index import SQLiteBM25, build_index
from scripts_a.build_utility import main as utility_main
from scripts_a.validate_providers import _bm25s_parity
from tests.a.test_oof import _fixture


def test_final_oof_rejects_a_consistent_split_omitting_a_canonical_query(tmp_path):
    registry_path, registry, split, _ = _fixture(tmp_path, query_count=10)
    domain = "programmers"
    removed = split["domains"][domain]["buckets"][0][0]
    data = split["domains"][domain]
    data["buckets"][0].remove(removed)
    data["groups"] = [g for g in data["groups"] if removed not in g]
    data["query_count"] -= 1
    data["group_count"] -= 1
    split["split_hash"] = object_hash({k: v for k, v in split.items() if k != "split_hash"})
    atomic_json(registry["split_manifest"], split)
    for d, configuration in registry["domains"].items():
        for runs in configuration["runs"].values():
            for fold, filename in runs.items():
                path = Path(filename)
                records = [
                    json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
                ]
                records = [r for r in records if r["query_id"] != removed]
                write_jsonl(path, records)
                sidecar = path.with_suffix(".jsonl.meta.json")
                meta = json.loads(sidecar.read_text(encoding="utf-8"))
                ids = split["domains"][d]["buckets"][int(fold)]
                meta.update(
                    split_hash=split["split_hash"],
                    ranking_sha256=file_hash(path),
                    query_ids_hash=object_hash(ids),
                    query_count=len(ids),
                )
                atomic_json(sidecar, meta)
    with pytest.raises(ValueError, match="canonical query"):
        run_oof(registry_path, bootstrap_samples=2)


def test_split_rejects_duplicate_members_even_if_counts_and_hash_are_resigned(tmp_path):
    _, _, split, _ = _fixture(tmp_path, query_count=10)
    bucket = split["domains"]["unix"]["buckets"][0]
    bucket.append(bucket[0])
    split["split_hash"] = object_hash({k: v for k, v in split.items() if k != "split_hash"})
    with pytest.raises(ValueError, match="duplicate"):
        validate_five_fold_splits(split)


def test_utility_rejects_mixed_split_fold_on_the_same_queries(tmp_path, monkeypatch):
    registry_path, registry, _, _ = _fixture(tmp_path)
    config = registry["domains"]["unix"]
    queries = load_queries(config["queries"], "unix")
    for label, split, fold in (("baseline", "train", 0), ("candidate", "test", 1)):
        write_jsonl(
            tmp_path / f"{label}.jsonl",
            (
                ranking_to_record(
                    Ranking(
                        q.query_id,
                        q.domain,
                        (SearchHit(q.query_id.replace(":q", ":d"), 1.0, 1),),
                        "corpus",
                        label,
                    ),
                    method=label,
                    split=split,
                    fold=fold,
                )
                for q in queries
            ),
        )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "build_utility",
            "--queries",
            config["queries"],
            "--qrels",
            config["qrels"],
            "--baseline-run",
            str(tmp_path / "baseline.jsonl"),
            "--candidate-run",
            str(tmp_path / "candidate.jsonl"),
            "--domain",
            "unix",
            "--output",
            str(tmp_path / "utility.jsonl"),
        ],
    )
    with pytest.raises(ValueError, match="same declared split and fold"):
        utility_main()
    assert registry_path.is_file()
    assert not (tmp_path / "utility.jsonl").exists()


def test_sparse_manifest_statistics_cannot_change_under_the_same_retriever_hash(tmp_path):
    directory = tmp_path / "sparse"
    build_index(
        "tests/fixtures/shared/programmers/corpus.jsonl", directory, "programmers", BM25Config()
    )
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    manifest["average_document_length"] *= 10
    atomic_json(directory / "manifest.json", manifest)
    with pytest.raises(ValueError, match="manifest/retriever"):
        SQLiteBM25(directory)


def test_provider_validation_rejects_large_finite_score_errors(tmp_path):
    corpus = Path("tests/fixtures/shared/programmers/corpus.jsonl")
    queries = Path("tests/fixtures/shared/programmers/queries.jsonl")
    directory = tmp_path / "sparse"
    build_index(corpus, directory, "programmers", BM25Config())
    records = []
    with SQLiteBM25(directory) as backend:
        for query in load_queries(queries, "programmers"):
            ranking = backend.search(query)
            changed = Ranking(
                ranking.query_id,
                ranking.domain,
                tuple(SearchHit(h.doc_id, h.score * 100, h.rank) for h in ranking.hits),
                ranking.corpus_hash,
                ranking.retriever_hash,
            )
            records.append(ranking_to_record(changed))
    run = tmp_path / "changed.jsonl"
    write_jsonl(run, records)
    result = _bm25s_parity(
        str(corpus), str(queries), str(directory), str(run), "programmers", k=100, max_queries=None
    )
    assert result["maximum_absolute_score_difference"] > 1
    assert result["minimum_jaccard_at_k"] == 1
    assert result["passed"] is False


def test_new_dataset_identity_ignores_machine_local_source_paths(tmp_path):
    hashes = []
    for local in ("data\\raw\\unix\\corpus.jsonl", "/a/different/cache/unix/corpus.jsonl"):
        source = tmp_path / "source.json"
        atomic_json(
            source,
            {
                "domain": "unix",
                "dataset_revision": "frozen",
                "files": [{"kind": "corpus", "canonical_path": local, "canonical_sha256": "same"}],
            },
        )
        manifest = audit_dataset(
            "tests/fixtures/shared/unix/corpus.jsonl",
            "tests/fixtures/shared/unix/queries.jsonl",
            "tests/fixtures/a/unix/qrels.tsv",
            "unix",
            source_manifest_path=source,
        )
        assert object_hash(dataset_identity_payload(manifest)) == manifest["manifest_hash"]
        hashes.append(manifest["manifest_hash"])
    assert hashes[0] == hashes[1]


def test_oof_rejects_sidecar_with_a_different_retriever(tmp_path):
    registry_path, registry, _, _ = _fixture(tmp_path)
    sidecar = Path(registry["domains"]["unix"]["runs"]["candidate"]["0"]).with_suffix(
        ".jsonl.meta.json"
    )
    meta = json.loads(sidecar.read_text(encoding="utf-8"))
    meta["retriever_hash"] = "a-different-model"
    atomic_json(sidecar, meta)
    with pytest.raises(ValueError, match="sidecar provenance"):
        run_oof(registry_path, bootstrap_samples=2)
