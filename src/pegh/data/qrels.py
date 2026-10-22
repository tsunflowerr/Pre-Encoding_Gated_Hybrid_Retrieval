"""Strict qrels loader with the same canonical ID policy as retrieval runs."""

from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass
from pathlib import Path

from contracts.ids import canonical_id, validate_domain, validate_id


@dataclass(frozen=True)
class Qrel:
    query_id: str
    doc_id: str
    relevance: float

    def __post_init__(self) -> None:
        query_domain = self.query_id.split(":", 1)[0]
        doc_domain = self.doc_id.split(":", 1)[0]
        if query_domain != doc_domain:
            raise ValueError("qrel query/document domains differ")
        validate_id(self.query_id, query_domain)
        validate_id(self.doc_id, query_domain)
        if isinstance(self.relevance, bool) or not isinstance(self.relevance, (int, float)):
            raise TypeError("qrel relevance must be a real number")
        if not math.isfinite(self.relevance) or self.relevance < 0:
            raise ValueError("qrel relevance must be finite and nonnegative")


def _qrel(query_id: object, doc_id: object, relevance: object, domain: str) -> Qrel:
    if not isinstance(query_id, str) or not isinstance(doc_id, str):
        raise ValueError("qrel IDs must remain strings")
    if isinstance(relevance, bool):
        raise ValueError("qrel relevance cannot be boolean")
    try:
        score = float(relevance)
    except (TypeError, ValueError) as exc:
        raise ValueError("qrel relevance must be numeric") from exc
    return Qrel(canonical_id(query_id, domain), canonical_id(doc_id, domain), score)


def _load_jsonl(path: Path, domain: str) -> list[Qrel]:
    rows: list[Qrel] = []
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                if not isinstance(record, dict):
                    raise ValueError("record must be an object")
                query_id = record.get("query_id", record.get("query-id", record.get("_id")))
                doc_id = record.get("doc_id", record.get("corpus-id"))
                relevance = record.get("relevance", record.get("score"))
                rows.append(_qrel(query_id, doc_id, relevance, domain))
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                raise ValueError(f"{path}:{line_number}: {exc}") from exc
    return rows


def _load_tsv(path: Path, domain: str) -> list[Qrel]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream, delimiter="\t")
        if reader.fieldnames is None:
            raise ValueError(f"{path}: qrels TSV needs a header")
        aliases = {
            "query": next(
                (k for k in ("query-id", "query_id", "qid") if k in reader.fieldnames),
                None,
            ),
            "doc": next(
                (k for k in ("corpus-id", "doc_id", "docid") if k in reader.fieldnames),
                None,
            ),
            "rel": next((k for k in ("score", "relevance", "rel") if k in reader.fieldnames), None),
        }
        if any(value is None for value in aliases.values()):
            raise ValueError(f"{path}: unsupported qrels header {reader.fieldnames}")
        rows = []
        for line_number, record in enumerate(reader, 2):
            try:
                rows.append(
                    _qrel(
                        record[aliases["query"]],
                        record[aliases["doc"]],
                        record[aliases["rel"]],
                        domain,
                    )
                )
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{path}:{line_number}: {exc}") from exc
        return rows


def load_qrels(path: str | Path, domain: str) -> dict[str, dict[str, float]]:
    """Load BEIR-style TSV or native JSONL; reject duplicate query/document pairs."""
    validate_domain(domain)
    source = Path(path)
    rows = (
        _load_jsonl(source, domain)
        if source.suffix.lower() == ".jsonl"
        else _load_tsv(source, domain)
    )
    result: dict[str, dict[str, float]] = {}
    for row in rows:
        documents = result.setdefault(row.query_id, {})
        if row.doc_id in documents:
            raise ValueError(f"{source}: duplicate qrel pair {row.query_id}/{row.doc_id}")
        documents[row.doc_id] = row.relevance
    return result


def positive_qrels(
    qrels: dict[str, dict[str, float]], query_id: str, *, remove_self: bool = True
) -> dict[str, float]:
    return {
        doc_id: relevance
        for doc_id, relevance in qrels.get(query_id, {}).items()
        if relevance > 0 and (not remove_self or doc_id != query_id)
    }
