"""Input boundary for B; no qrels, split generation or sparse/evaluation logic."""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from contracts.types import Query

TEXT_POLICY = "join_nonempty_title_text_newline_v1"


def namespace(identifier: str, domain: str) -> str:
    if not isinstance(identifier, str) or not identifier:
        raise ValueError("IDs must be nonempty strings")
    if identifier.startswith(domain + ":"):
        return identifier
    return domain + ":" + identifier


@dataclass(frozen=True)
class CorpusDocument:
    doc_id: str
    text: str


def iter_corpus(path: str | Path, domain: str) -> Iterator[CorpusDocument]:
    seen: set[str] = set()
    with Path(path).open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            doc_id = namespace(row.get("_id", row.get("doc_id")), domain)
            if doc_id in seen:
                raise ValueError(f"duplicate doc_id {doc_id} at line {line_number}")
            seen.add(doc_id)
            title, body = row.get("title", ""), row.get("text", "")
            if not isinstance(title, str) or not isinstance(body, str):
                raise TypeError(f"title/text must be strings at line {line_number}")
            text = "\n".join(part for part in (title, body) if part)
            if not text.strip():
                raise ValueError(f"empty document {doc_id}")
            yield CorpusDocument(doc_id, text)


def load_queries(path: str | Path, domain: str) -> list[Query]:
    queries: list[Query] = []
    seen: set[str] = set()
    with Path(path).open(encoding="utf-8") as stream:
        for line in stream:
            if not line.strip():
                continue
            row = json.loads(line)
            query_id = namespace(row.get("_id", row.get("query_id")), domain)
            if query_id in seen:
                raise ValueError(f"duplicate query_id: {query_id}")
            seen.add(query_id)
            queries.append(Query(query_id, domain, row["text"]))
    return queries
