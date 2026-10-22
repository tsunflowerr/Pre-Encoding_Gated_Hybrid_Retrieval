from __future__ import annotations

import math
from dataclasses import asdict, dataclass

from contracts.types import Ranking
from pegh.data.qrels import positive_qrels


@dataclass(frozen=True)
class QueryMetrics:
    query_id: str
    domain: str
    ndcg_at_10: float
    mrr_at_10: float
    recall_at_10: float
    recall_at_100: float
    relevant_count: int
    retrieved_count: int

    def as_dict(self) -> dict:
        return asdict(self)


def _gain(relevance: float) -> float:
    return 2**relevance - 1


def _dcg(relevances: list[float]) -> float:
    return sum(
        _gain(relevance) / math.log2(rank + 1) for rank, relevance in enumerate(relevances, 1)
    )


def query_metrics(
    query_id: str,
    domain: str,
    qrels: dict[str, dict[str, float]],
    ranking: Ranking | None,
    *,
    remove_self: bool = True,
) -> QueryMetrics:
    relevant = positive_qrels(qrels, query_id, remove_self=remove_self)
    hits = () if ranking is None else ranking.hits
    if ranking is not None:
        ranking.validate()
        if ranking.query_id != query_id or ranking.domain != domain:
            raise ValueError("ranking does not match the evaluated query/domain")
    ideal = sorted(relevant.values(), reverse=True)[:10]
    observed = [relevant.get(hit.doc_id, 0.0) for hit in hits[:10]]
    idcg = _dcg(ideal)
    ndcg = _dcg(observed) / idcg if idcg else 0.0
    reciprocal_rank = next(
        (1 / rank for rank, hit in enumerate(hits[:10], 1) if hit.doc_id in relevant), 0.0
    )
    relevant_ids = set(relevant)
    recall_10 = (
        len(relevant_ids & {hit.doc_id for hit in hits[:10]}) / len(relevant_ids)
        if relevant_ids
        else 0.0
    )
    recall_100 = (
        len(relevant_ids & {hit.doc_id for hit in hits[:100]}) / len(relevant_ids)
        if relevant_ids
        else 0.0
    )
    return QueryMetrics(
        query_id,
        domain,
        ndcg,
        reciprocal_rank,
        recall_10,
        recall_100,
        len(relevant_ids),
        len(hits),
    )


def evaluate_rankings(
    query_ids: list[str],
    domain: str,
    qrels: dict[str, dict[str, float]],
    rankings: dict[str, Ranking],
    *,
    remove_self: bool = True,
) -> list[QueryMetrics]:
    unknown = set(rankings) - set(query_ids)
    if unknown:
        raise ValueError(f"run contains unknown query IDs: {sorted(unknown)[:5]}")
    return [
        query_metrics(
            query_id,
            domain,
            qrels,
            rankings.get(query_id),
            remove_self=remove_self,
        )
        for query_id in query_ids
    ]


def aggregate_metrics(rows: list[QueryMetrics]) -> dict:
    if not rows:
        raise ValueError("cannot aggregate an empty evaluation")
    fields = ("ndcg_at_10", "mrr_at_10", "recall_at_10", "recall_at_100")
    return {
        "query_count": len(rows),
        "missing_or_empty_rankings": sum(row.retrieved_count == 0 for row in rows),
        **{field: sum(getattr(row, field) for row in rows) / len(rows) for field in fields},
    }


def utility_rows(baseline: list[QueryMetrics], candidate: list[QueryMetrics]) -> list[dict]:
    baseline_by_id = {row.query_id: row for row in baseline}
    candidate_by_id = {row.query_id: row for row in candidate}
    if baseline_by_id.keys() != candidate_by_id.keys():
        raise ValueError("baseline and candidate query sets differ")
    rows = []
    for query_id in sorted(baseline_by_id):
        left, right = baseline_by_id[query_id], candidate_by_id[query_id]
        if left.domain != right.domain:
            raise ValueError("baseline and candidate domains differ")
        rows.append(
            {
                "query_id": query_id,
                "domain": left.domain,
                "utility_baseline": left.ndcg_at_10,
                "utility_candidate": right.ndcg_at_10,
                "delta_utility": right.ndcg_at_10 - left.ndcg_at_10,
            }
        )
    return rows
