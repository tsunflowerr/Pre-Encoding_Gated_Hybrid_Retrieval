"""Validate the common fixture/model contract; optionally compare a real corpus to B v1."""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict
from itertools import zip_longest
from pathlib import Path

from contracts.io import iter_corpus, load_queries
from contracts.model import get_primary_model
from pegh.dense.config import DenseConfig
from pegh.dense.corpus import iter_corpus as legacy_corpus
from pegh.dense.corpus import load_queries as legacy_queries


def check_corpus(path: Path, domain: str) -> int:
    count = 0
    for document, old in zip_longest(iter_corpus(path, domain), legacy_corpus(path, domain)):
        if (
            document is None
            or old is None
            or (document.doc_id, document.text) != (old.doc_id, old.text)
        ):
            raise ValueError(f"shared/B-v1 text or ID mismatch at row {count}: {path}")
        count += 1
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures", type=Path, default=Path("tests/fixtures/shared"))
    parser.add_argument("--corpus", type=Path)
    parser.add_argument("--domain")
    args = parser.parse_args()
    if bool(args.corpus) != bool(args.domain):
        parser.error("--corpus and --domain must be supplied together")
    expected = asdict(get_primary_model())
    for config in (DenseConfig(), DenseConfig.from_yaml("configs/dense/primary.yaml")):
        if any(getattr(config, key) != value for key, value in expected.items()):
            raise ValueError("frozen dense defaults/YAML differ from the shared primary model")
    manifest = json.loads((args.fixtures / "manifest.json").read_text(encoding="utf-8"))
    for relative, digest in manifest["sha256"].items():
        if hashlib.sha256((args.fixtures / relative).read_bytes()).hexdigest() != digest:
            raise ValueError(f"fixture checksum mismatch: {relative}")
    for domain, counts in manifest["domains"].items():
        corpus_path, query_path = (
            args.fixtures / domain / name for name in ("corpus.jsonl", "queries.jsonl")
        )
        count = check_corpus(corpus_path, domain)
        queries = load_queries(query_path, domain)
        if count != counts["documents"] or len(queries) != counts["queries"]:
            raise ValueError("fixture count mismatch")
        if queries != legacy_queries(query_path, domain):
            raise ValueError("shared/B-v1 queries differ")
        print(f"{domain}: {count} documents, {len(queries)} queries; shared/B-v1 parity passed")
    if args.corpus:
        print(f"Real corpus parity passed: {check_corpus(args.corpus, args.domain)} documents")
    print("Pinned model/default/YAML agreement passed")


if __name__ == "__main__":
    main()
