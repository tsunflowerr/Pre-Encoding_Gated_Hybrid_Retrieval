from __future__ import annotations

import json
from pathlib import Path

from contracts.ranking import ranking_from_record
from contracts.types import Ranking


def load_rankings(
    path: str | Path, *, domain: str | None = None
) -> tuple[dict[str, Ranking], dict]:
    rankings: dict[str, Ranking] = {}
    metadata: dict[str, set] = {key: set() for key in ("method", "split", "run_id", "fold")}
    metadata_presence = {key: 0 for key in metadata}
    corpus_hashes: set[str] = set()
    retriever_hashes: set[str] = set()
    with Path(path).open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                ranking = ranking_from_record(record)
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                raise ValueError(f"{path}:{line_number}: {exc}") from exc
            if domain is not None and ranking.domain != domain:
                raise ValueError(f"{path}:{line_number}: ranking domain mismatch")
            if ranking.query_id in rankings:
                raise ValueError(f"{path}:{line_number}: duplicate query ranking")
            rankings[ranking.query_id] = ranking
            corpus_hashes.add(ranking.corpus_hash)
            retriever_hashes.add(ranking.retriever_hash)
            for key in metadata:
                if key in record:
                    metadata[key].add(record[key])
                    metadata_presence[key] += 1
    if len(corpus_hashes) > 1:
        raise ValueError("a run mixes multiple corpus hashes")
    if len(retriever_hashes) > 1:
        raise ValueError("a run mixes multiple retriever hashes")
    inconsistent = {key: values for key, values in metadata.items() if len(values) > 1}
    if inconsistent:
        raise ValueError(f"run metadata is inconsistent: {inconsistent}")
    partial = {
        key: count for key, count in metadata_presence.items() if count not in (0, len(rankings))
    }
    if partial:
        raise ValueError(f"run metadata is only present on some records: {partial}")
    return rankings, {
        "query_count": len(rankings),
        "corpus_hash": next(iter(corpus_hashes), None),
        "retriever_hash": next(iter(retriever_hashes), None),
        "metadata_complete": {
            key: count == len(rankings) and bool(rankings)
            for key, count in metadata_presence.items()
        },
        **{key: next(iter(values), None) for key, values in metadata.items()},
    }
