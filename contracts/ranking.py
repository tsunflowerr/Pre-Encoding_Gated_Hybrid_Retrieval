"""Versioned ranking records for evaluator, fusion and quality-run interchange."""

from __future__ import annotations

import json
from dataclasses import asdict
from importlib.resources import files

from contracts.types import Ranking, SearchHit

SCHEMA_VERSION = "1.0"
_CORE = {"schema_version", "query_id", "domain", "hits", "corpus_hash", "retriever_hash"}
_META = {"method", "split", "run_id", "fold"}


def ranking_schema() -> dict:
    return json.loads(
        files("contracts").joinpath("schemas/ranking-v1.schema.json").read_text(encoding="utf-8")
    )


def ranking_to_record(ranking: Ranking, **metadata: str | int | None) -> dict:
    ranking.validate()
    if metadata.keys() - _META:
        raise ValueError("unknown ranking metadata fields")
    for key, value in metadata.items():
        if key == "fold":
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError("fold must be null or a nonnegative integer")
        elif not isinstance(value, str) or not value:
            raise ValueError(f"{key} must be a nonempty string")
    return {
        "schema_version": SCHEMA_VERSION,
        **asdict(ranking),
        **metadata,
        "hits": [asdict(h) for h in ranking.hits],
    }


def ranking_from_record(record: dict) -> Ranking:
    if not isinstance(record, dict) or not _CORE.issubset(record) or record.keys() - _CORE - _META:
        raise ValueError("missing/unknown ranking fields")
    if record["schema_version"] != SCHEMA_VERSION or not isinstance(record["hits"], list):
        raise ValueError("unsupported ranking schema version or invalid hits array")
    try:
        ranking = Ranking(
            record["query_id"],
            record["domain"],
            tuple(SearchHit(**h) for h in record["hits"]),
            record["corpus_hash"],
            record["retriever_hash"],
        )
        ranking_to_record(ranking, **{key: record[key] for key in _META if key in record})
    except (TypeError, KeyError) as exc:
        raise ValueError("invalid ranking/hit fields") from exc
    return ranking


def dumps_ranking(ranking: Ranking, **metadata: str | int | None) -> str:
    return json.dumps(
        ranking_to_record(ranking, **metadata),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
