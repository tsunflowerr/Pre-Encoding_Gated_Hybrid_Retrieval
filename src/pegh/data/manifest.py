from __future__ import annotations

import json
from pathlib import Path

from contracts.io import iter_corpus, load_queries
from pegh.data.artifacts import file_hash, object_hash
from pegh.data.qrels import load_qrels, positive_qrels


def audit_dataset(
    corpus_path: str | Path,
    queries_path: str | Path,
    qrels_path: str | Path,
    domain: str,
    *,
    expected: dict | None = None,
    source_manifest_path: str | Path | None = None,
) -> dict:
    corpus_path, queries_path, qrels_path = map(Path, (corpus_path, queries_path, qrels_path))
    documents = list(iter_corpus(corpus_path, domain))
    queries = load_queries(queries_path, domain)
    qrels = load_qrels(qrels_path, domain)
    document_ids = {document.doc_id for document in documents}
    query_ids = {query.query_id for query in queries}
    dangling_queries = sorted(set(qrels) - query_ids)
    dangling_documents = sorted(
        {doc_id for values in qrels.values() for doc_id in values} - document_ids
    )
    if dangling_queries or dangling_documents:
        raise ValueError(
            f"qrels reference unknown IDs: queries={dangling_queries[:5]}, "
            f"documents={dangling_documents[:5]}"
        )
    missing_qrels = sorted(query_ids - set(qrels))
    no_positive_qrels = sorted(
        query_id for query_id in query_ids if not positive_qrels(qrels, query_id)
    )
    hashes = {
        "corpus": file_hash(corpus_path),
        "queries": file_hash(queries_path),
        "qrels": file_hash(qrels_path),
    }
    counts = {
        "documents": len(documents),
        "queries": len(queries),
        "qrel_queries": len(qrels),
        "qrel_pairs": sum(len(values) for values in qrels.values()),
    }
    if expected is not None:
        checks = {
            "documents": counts["documents"],
            "queries": counts["queries"],
            "qrel_pairs": counts["qrel_pairs"],
            "corpus_sha256": hashes["corpus"],
            "queries_sha256": hashes["queries"],
            "qrels_sha256": hashes["qrels"],
        }
        mismatches = {
            key: {"expected": expected[key], "actual": actual}
            for key, actual in checks.items()
            if key in expected and expected[key] != actual
        }
        if mismatches:
            raise ValueError(f"pinned dataset checks failed: {mismatches}")
    source_manifest = None
    if source_manifest_path is not None:
        with Path(source_manifest_path).open(encoding="utf-8") as stream:
            source_manifest = json.load(stream)
        if source_manifest.get("domain") != domain:
            raise ValueError("source manifest domain mismatch")
    payload = {
        "schema_version": "1.0",
        "domain": domain,
        "files": {
            "corpus": {"path": str(corpus_path), "sha256": hashes["corpus"]},
            "queries": {"path": str(queries_path), "sha256": hashes["queries"]},
            "qrels": {"path": str(qrels_path), "sha256": hashes["qrels"]},
        },
        "counts": counts,
        "coverage": {
            "missing_qrels": missing_qrels,
            "queries_without_positive_nonself_qrel": no_positive_qrels,
            "dangling_query_ids": [],
            "dangling_document_ids": [],
        },
        "policies": {
            "id": "domain:source_id",
            "text": "join_nonempty_title_text_newline_v1",
            "evaluation_self_qrel": "removed",
        },
        "source": source_manifest,
    }
    payload["manifest_hash"] = object_hash(
        {
            "schema_version": payload["schema_version"],
            "domain": domain,
            "file_hashes": hashes,
            "counts": counts,
            "coverage": payload["coverage"],
            "policies": payload["policies"],
            "source": source_manifest,
        }
    )
    return payload
