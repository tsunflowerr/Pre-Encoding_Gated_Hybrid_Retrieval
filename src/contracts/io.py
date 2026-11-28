"""Streaming corpus/query boundary shared by A and C, with explicit BEIR aliases."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

from contracts.ids import canonical_id, validate_domain
from contracts.types import Document, Query


def _records(path: str | Path) -> Iterator[tuple[int, dict]]:
    with Path(path).open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number}: malformed JSON") from exc
            if not isinstance(row, dict):
                raise ValueError(f"{path}:{line_number}: record must be a JSON object")
            yield line_number, row


def _identifier(row: dict, key: str, domain: str) -> str:
    identifiers = [canonical_id(row[k], domain) for k in (key, "_id") if k in row]
    if not identifiers or len(set(identifiers)) != 1:
        raise ValueError(f"missing or conflicting {key}/_id")
    if "domain" in row and row["domain"] != domain:
        raise ValueError("record domain differs from the requested domain")
    return identifiers[0]


def iter_corpus(path: str | Path, domain: str) -> Iterator[Document]:
    """Preserve source order; hold only IDs for duplicate detection, not corpus text.

    BEIR `_id,title,text` uses text as body. Native `doc_id,title,body` is
    accepted at the same boundary; conflicting aliases fail instead of guessing.
    """
    validate_domain(domain)
    seen: set[str] = set()
    for line_number, row in _records(path):
        try:
            doc_id = _identifier(row, "doc_id", domain)
            if doc_id in seen:
                raise ValueError(f"duplicate doc_id {doc_id}")
            if "body" in row and "text" in row and row["body"] != row["text"]:
                raise ValueError("body/text aliases disagree; text in corpus JSONL means body")
            document = Document(
                doc_id, domain, row.get("title", ""), row.get("body", row.get("text", ""))
            )
            seen.add(doc_id)
            yield document
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{path}:{line_number}: {exc}") from exc


def iter_queries(path: str | Path, domain: str) -> Iterator[Query]:
    validate_domain(domain)
    seen: set[str] = set()
    for line_number, row in _records(path):
        try:
            query_id = _identifier(row, "query_id", domain)
            if query_id in seen:
                raise ValueError(f"duplicate query_id {query_id}")
            query = Query(query_id, domain, row["text"])
            seen.add(query_id)
            yield query
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"{path}:{line_number}: {exc}") from exc


def load_queries(path: str | Path, domain: str) -> list[Query]:
    return list(iter_queries(path, domain))
