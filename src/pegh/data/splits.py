"""Deterministic grouped five-fold query splits for the supervised track."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import defaultdict
from pathlib import Path

from contracts.types import Query
from pegh.data.artifacts import atomic_json, object_hash


class _DisjointSet:
    def __init__(self, values: list[str]):
        self.parent = {value: value for value in values}

    def find(self, value: str) -> str:
        parent = self.parent[value]
        if parent != value:
            self.parent[value] = self.find(parent)
        return self.parent[value]

    def union(self, left: str, right: str) -> None:
        left_root, right_root = self.find(left), self.find(right)
        if left_root != right_root:
            self.parent[max(left_root, right_root)] = min(left_root, right_root)


def normalized_query_text(text: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text).casefold()).strip()


def query_groups(queries: list[Query], qrels: dict[str, dict[str, float]]) -> list[tuple[str, ...]]:
    query_ids = {query.query_id for query in queries}
    dsu = _DisjointSet(sorted(query_ids))
    by_text: dict[str, list[str]] = defaultdict(list)
    by_relevant_document: dict[str, list[str]] = defaultdict(list)
    for query in queries:
        by_text[normalized_query_text(query.text)].append(query.query_id)
        for doc_id, relevance in qrels.get(query.query_id, {}).items():
            if relevance > 0 and doc_id != query.query_id:
                by_relevant_document[doc_id].append(query.query_id)
                if doc_id in query_ids:
                    dsu.union(query.query_id, doc_id)
    for members in (*by_text.values(), *by_relevant_document.values()):
        for member in members[1:]:
            dsu.union(members[0], member)
    components: dict[str, list[str]] = defaultdict(list)
    for query_id in sorted(query_ids):
        components[dsu.find(query_id)].append(query_id)
    return [tuple(members) for _, members in sorted(components.items())]


def assign_buckets(
    groups: list[tuple[str, ...]], *, bucket_count: int = 5, seed: int = 42
) -> list[list[str]]:
    if bucket_count < 2:
        raise ValueError("at least two buckets are required")

    def tie_key(group: tuple[str, ...]) -> str:
        material = f"{seed}:" + "\n".join(group)
        return hashlib.sha256(material.encode()).hexdigest()

    ordered = sorted(groups, key=lambda group: (-len(group), tie_key(group), group))
    buckets: list[list[str]] = [[] for _ in range(bucket_count)]
    for group in ordered:
        target = min(range(bucket_count), key=lambda index: (len(buckets[index]), index))
        buckets[target].extend(group)
    return [sorted(bucket) for bucket in buckets]


def make_five_fold_splits(
    queries_by_domain: dict[str, list[Query]],
    qrels_by_domain: dict[str, dict[str, dict[str, float]]],
    *,
    seed: int = 42,
    dataset_hashes: dict[str, str] | None = None,
) -> dict:
    domains = {}
    for domain in sorted(queries_by_domain):
        queries = queries_by_domain[domain]
        if any(query.domain != domain for query in queries):
            raise ValueError("query domain differs from split domain")
        groups = query_groups(queries, qrels_by_domain[domain])
        buckets = assign_buckets(groups, seed=seed)
        domains[domain] = {
            "query_count": len(queries),
            "group_count": len(groups),
            "groups": [list(group) for group in groups],
            "buckets": buckets,
        }
    manifest = {
        "schema_version": "1.0",
        "seed": seed,
        "fold_count": 5,
        "grouping": "normalized_text_and_shared_positive_qrel_v1",
        "dataset_hashes": dataset_hashes or {},
        "domains": domains,
    }
    manifest["split_hash"] = object_hash(manifest)
    validate_five_fold_splits(manifest)
    return manifest


def fold_record(manifest: dict, fold: int) -> dict:
    if type(fold) is not int or not 0 <= fold < manifest["fold_count"]:
        raise ValueError("fold is outside the split manifest")
    domains = {}
    for domain, data in manifest["domains"].items():
        buckets = data["buckets"]
        test_bucket = fold
        validation_bucket = (fold + 1) % manifest["fold_count"]
        domains[domain] = {
            "train": sorted(
                query_id
                for index, bucket in enumerate(buckets)
                if index not in (test_bucket, validation_bucket)
                for query_id in bucket
            ),
            "validation": sorted(buckets[validation_bucket]),
            "test": sorted(buckets[test_bucket]),
        }
    return {
        "schema_version": manifest["schema_version"],
        "split_hash": manifest["split_hash"],
        "fold": fold,
        "domains": domains,
    }


def validate_five_fold_splits(manifest: dict) -> None:
    if manifest.get("fold_count") != 5:
        raise ValueError("the registered protocol requires five folds")
    recorded_hash = manifest.get("split_hash")
    unsigned = {key: value for key, value in manifest.items() if key != "split_hash"}
    if not isinstance(recorded_hash, str) or object_hash(unsigned) != recorded_hash:
        raise ValueError("split manifest hash is missing or does not match its contents")
    for domain, data in manifest["domains"].items():
        if len(data["buckets"]) != 5:
            raise ValueError(f"{domain}: exactly five buckets are required")
        flat_ids = [query_id for bucket in data["buckets"] for query_id in bucket]
        expected = set(flat_ids)
        if len(expected) != len(flat_ids) or len(expected) != data["query_count"]:
            raise ValueError(f"{domain}: duplicate or missing bucket query IDs")
        group_ids = [qid for group in data["groups"] for qid in group]
        if (
            any(not group for group in data["groups"])
            or len(group_ids) != len(set(group_ids))
            or set(group_ids) != expected
            or data["group_count"] != len(data["groups"])
        ):
            raise ValueError(f"{domain}: groups must partition all bucket query IDs")
        test_counts = {query_id: 0 for query_id in expected}
        group_bucket = {}
        for bucket_number, bucket in enumerate(data["buckets"]):
            for query_id in bucket:
                group_bucket[query_id] = bucket_number
        for group in data["groups"]:
            if len({group_bucket[query_id] for query_id in group}) != 1:
                raise ValueError(f"{domain}: a query group was split across buckets")
        for fold in range(5):
            record = fold_record(manifest, fold)
            parts = record["domains"][domain]
            sets = {name: set(ids) for name, ids in parts.items()}
            if sets["train"] & sets["validation"] or sets["train"] & sets["test"]:
                raise ValueError(f"{domain}: fold {fold} overlaps")
            if sets["validation"] & sets["test"] or set().union(*sets.values()) != expected:
                raise ValueError(f"{domain}: fold {fold} does not partition queries")
            for query_id in sets["test"]:
                test_counts[query_id] += 1
        if any(count != 1 for count in test_counts.values()):
            raise ValueError(f"{domain}: every query must be test exactly once")


def write_five_fold_splits(output: str | Path, manifest: dict) -> None:
    directory = Path(output)
    directory.mkdir(parents=True, exist_ok=True)
    atomic_json(directory / "manifest.json", manifest)
    for fold in range(manifest["fold_count"]):
        atomic_json(directory / f"fold_{fold}.json", fold_record(manifest, fold))
