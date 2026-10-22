from __future__ import annotations

import csv

import pytest

from contracts import Query, Ranking, SearchHit
from contracts.ranking import ranking_to_record
from pegh.data.artifacts import atomic_json, file_hash, object_hash, write_jsonl
from pegh.data.manifest import audit_dataset
from pegh.data.splits import (
    make_five_fold_splits,
    validate_five_fold_splits,
    write_five_fold_splits,
)
from pegh.evaluation.oof import run_oof


def _fixture(tmp_path):
    domains = ("programmers", "unix")
    queries_by_domain = {
        domain: [Query(f"{domain}:q{index}", domain, f"query {index}") for index in range(5)]
        for domain in domains
    }
    qrels_by_domain = {
        domain: {f"{domain}:q{index}": {f"{domain}:d{index}": 1.0} for index in range(5)}
        for domain in domains
    }
    registry = {
        "split_manifest": str(tmp_path / "splits" / "manifest.json"),
        "domains": {},
        "utilities": [{"name": "candidate_gain", "baseline": "base", "candidate": "candidate"}],
        "comparison": {"baseline": "base", "candidate": "candidate"},
    }
    manifests = {}
    paths = {}
    for domain in domains:
        corpus_path = tmp_path / f"{domain}-corpus.jsonl"
        queries_path = tmp_path / f"{domain}-queries.jsonl"
        qrels_path = tmp_path / f"{domain}-qrels.tsv"
        write_jsonl(
            corpus_path,
            (
                {"_id": f"{domain}:d{index}", "title": "", "text": f"document {index}"}
                for index in range(5)
            ),
        )
        write_jsonl(
            queries_path,
            ({"_id": query.query_id, "text": query.text} for query in queries_by_domain[domain]),
        )
        with qrels_path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream, delimiter="\t", lineterminator="\n")
            writer.writerow(("query-id", "corpus-id", "score"))
            for index in range(5):
                writer.writerow((f"{domain}:q{index}", f"{domain}:d{index}", 1))
        manifest = audit_dataset(corpus_path, queries_path, qrels_path, domain)
        manifest_path = tmp_path / f"{domain}-manifest.json"
        atomic_json(manifest_path, manifest)
        manifests[domain] = manifest
        paths[domain] = (queries_path, qrels_path, manifest_path)
    split = make_five_fold_splits(
        queries_by_domain,
        qrels_by_domain,
        dataset_hashes={
            domain: manifest["manifest_hash"] for domain, manifest in manifests.items()
        },
    )
    write_five_fold_splits(tmp_path / "splits", split)
    for domain in domains:
        method_runs = {}
        for method in ("base", "candidate"):
            fold_runs = {}
            for fold, query_ids in enumerate(split["domains"][domain]["buckets"]):
                run_path = tmp_path / f"{domain}-{method}-{fold}.jsonl"
                run_id = f"{domain}-{method}-{fold}"
                write_jsonl(
                    run_path,
                    (
                        ranking_to_record(
                            Ranking(
                                query_id,
                                domain,
                                (SearchHit(query_id.replace(":q", ":d"), 1.0, 1),),
                                manifests[domain]["files"]["corpus"]["sha256"],
                                f"{method}-retriever-{fold}",
                            ),
                            method=method,
                            split="test",
                            fold=fold,
                            run_id=run_id,
                        )
                        for query_id in query_ids
                    ),
                )
                atomic_json(
                    run_path.with_suffix(run_path.suffix + ".meta.json"),
                    {
                        "ranking_sha256": file_hash(run_path),
                        "query_ids_hash": object_hash(query_ids),
                        "query_count": len(query_ids),
                        "split_hash": split["split_hash"],
                        "domain": domain,
                        "method": method,
                        "fold": fold,
                        "split": "test",
                        "run_id": run_id,
                        "corpus_hash": manifests[domain]["files"]["corpus"]["sha256"],
                    },
                )
                fold_runs[str(fold)] = str(run_path)
            method_runs[method] = fold_runs
        queries_path, qrels_path, manifest_path = paths[domain]
        registry["domains"][domain] = {
            "dataset_manifest": str(manifest_path),
            "queries": str(queries_path),
            "qrels": str(qrels_path),
            "runs": method_runs,
        }
    registry_path = tmp_path / "registry.json"
    atomic_json(registry_path, registry)
    return registry_path, registry, split, manifests


def test_final_oof_requires_exact_provenance_and_macro_aggregates(tmp_path):
    registry_path, _, _, _ = _fixture(tmp_path)
    result = run_oof(registry_path, bootstrap_samples=20)
    assert result["summaries"]["candidate"]["macro"]["ndcg_at_10"] == 1
    assert result["comparison"]["macro"]["mean_difference"] == 0
    assert len(result["utility"]) == 10
    assert {row["utility_name"] for row in result["utility"]} == {"candidate_gain"}


def test_final_oof_rejects_missing_metadata_and_noncanonical_corpus(tmp_path):
    registry_path, registry, split, manifests = _fixture(tmp_path)
    domain, method, fold = "programmers", "base", 0
    run_path = registry["domains"][domain]["runs"][method][str(fold)]
    query_ids = split["domains"][domain]["buckets"][fold]
    write_jsonl(
        run_path,
        (
            ranking_to_record(
                Ranking(
                    query_id,
                    domain,
                    (SearchHit(query_id.replace(":q", ":d"), 1.0, 1),),
                    manifests[domain]["files"]["corpus"]["sha256"],
                    "retriever",
                )
            )
            for query_id in query_ids
        ),
    )
    with pytest.raises(ValueError, match="embedded fold"):
        run_oof(registry_path, bootstrap_samples=2)
    write_jsonl(
        run_path,
        (
            ranking_to_record(
                Ranking(
                    query_id,
                    domain,
                    (SearchHit(query_id.replace(":q", ":d"), 1.0, 1),),
                    "bogus-corpus",
                    "retriever",
                ),
                method=method,
                split="test",
                fold=fold,
                run_id="bogus-run",
            )
            for query_id in query_ids
        ),
    )
    with pytest.raises(ValueError, match="noncanonical corpus"):
        run_oof(registry_path, bootstrap_samples=2)


def test_split_hash_tampering_is_rejected(tmp_path):
    _, _, split, _ = _fixture(tmp_path)
    split["split_hash"] = "forged"
    with pytest.raises(ValueError, match="split manifest hash"):
        validate_five_fold_splits(split)
