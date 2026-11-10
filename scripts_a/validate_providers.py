"""Cross-check the local BM25 and evaluator against independent providers."""

from __future__ import annotations

import argparse
import json
import math

import bm25s
import ir_measures
import numpy as np
from ir_measures import RR, R, nDCG

from contracts.io import iter_corpus, load_queries
from pegh.data.artifacts import atomic_json, file_hash
from pegh.data.qrels import load_qrels, positive_qrels
from pegh.evaluation.metrics import aggregate_metrics, evaluate_rankings
from pegh.evaluation.runs import load_rankings
from pegh.sparse.index import SQLiteBM25


def _evaluator_parity(query_ids: list[str], domain: str, qrels_path: str, run_path: str) -> dict:
    qrels = load_qrels(qrels_path, domain)
    rankings, _ = load_rankings(run_path, domain=domain)
    local = aggregate_metrics(evaluate_rankings(query_ids, domain, qrels, rankings))
    provider_qrels = {
        query_id: {
            doc_id: int(relevance)
            for doc_id, relevance in positive_qrels(qrels, query_id, remove_self=True).items()
        }
        for query_id in query_ids
    }
    provider_run = {
        query_id: {hit.doc_id: hit.score for hit in rankings.get(query_id, ()).hits}
        if query_id in rankings
        else {}
        for query_id in query_ids
    }
    measures = [nDCG @ 10, RR @ 10, R @ 10, R @ 100]
    provider = ir_measures.calc_aggregate(measures, provider_qrels, provider_run)
    mapped = {
        "ndcg_at_10": float(provider[nDCG @ 10]),
        "mrr_at_10": float(provider[RR @ 10]),
        "recall_at_10": float(provider[R @ 10]),
        "recall_at_100": float(provider[R @ 100]),
    }
    absolute_differences = {key: abs(local[key] - mapped[key]) for key in mapped}
    return {
        "provider": f"ir-measures-{ir_measures.__version__}",
        "local": {key: local[key] for key in mapped},
        "provider_metrics": mapped,
        "absolute_differences": absolute_differences,
        "max_absolute_difference": max(absolute_differences.values()),
        "passed": max(absolute_differences.values()) <= 1e-12,
    }


def _bm25s_parity(
    corpus_path: str,
    queries_path: str,
    index_path: str,
    run_path: str,
    domain: str,
    *,
    k: int,
    max_queries: int | None,
) -> dict:
    with SQLiteBM25(index_path) as local:
        local_rankings, _ = load_rankings(run_path, domain=domain)
        documents = list(iter_corpus(corpus_path, domain))
        document_ids = np.asarray([document.doc_id for document in documents], dtype=object)
        tokenized_corpus = [local.tokenizer.tokenize(document.text) for document in documents]
        provider = bm25s.BM25(
            k1=local.config.k1,
            b=local.config.b,
            method="atire",
            idf_method="lucene",
            backend="numpy",
        )
        provider.index(tokenized_corpus, show_progress=False)
        queries = load_queries(queries_path, domain)
        if max_queries is not None:
            queries = queries[:max_queries]
        overlaps: list[float] = []
        exact_orders = 0
        maximum_score_difference = 0.0
        compared_scores = 0
        score_tolerance_passed = True
        non_tie_order_mismatches = 0
        absolute_tolerance, relative_tolerance = 1e-5, 1e-6
        for query in queries:
            expected = local_rankings[query.query_id]
            tokens = local.tokenizer.tokenize(query.text)
            if not tokens:
                actual_pairs: list[tuple[str, float]] = []
            else:
                scores = provider.get_scores(tokens)
                positive = np.flatnonzero(scores > 0)
                positive = positive[document_ids[positive] != query.query_id]
                order = np.lexsort((document_ids[positive], -scores[positive]))[:k]
                actual_pairs = [
                    (str(document_ids[index]), float(scores[index])) for index in positive[order]
                ]
            expected_ids = [hit.doc_id for hit in expected.hits]
            actual_ids = [doc_id for doc_id, _ in actual_pairs]
            exact_orders += expected_ids == actual_ids
            denominator = max(1, len(set(expected_ids) | set(actual_ids)))
            overlaps.append(len(set(expected_ids) & set(actual_ids)) / denominator)
            actual_scores = dict(actual_pairs)
            expected_scores = {hit.doc_id: hit.score for hit in expected.hits}
            for (left, _), (right, _) in zip(actual_pairs, actual_pairs[1:], strict=False):
                if left in expected_scores and right in expected_scores:
                    tolerance = absolute_tolerance + relative_tolerance * max(
                        abs(expected_scores[left]), abs(expected_scores[right])
                    )
                    if expected_scores[left] + tolerance < expected_scores[right]:
                        non_tie_order_mismatches += 1
            for hit in expected.hits:
                if hit.doc_id in actual_scores:
                    maximum_score_difference = max(
                        maximum_score_difference,
                        abs(hit.score - actual_scores[hit.doc_id]),
                    )
                    score_tolerance_passed &= math.isclose(
                        hit.score,
                        actual_scores[hit.doc_id],
                        abs_tol=absolute_tolerance,
                        rel_tol=relative_tolerance,
                    )
                    compared_scores += 1
        minimum_overlap = min(overlaps, default=1.0)
        return {
            "provider": f"bm25s-{bm25s.__version__}",
            "provider_configuration": {
                "method": "atire",
                "idf_method": "lucene",
                "tokenizer": "shared TechnicalTokenizer token lists",
                "k1": local.config.k1,
                "b": local.config.b,
            },
            "query_count": len(queries),
            "top_k": k,
            "exact_order_count": exact_orders,
            "minimum_jaccard_at_k": minimum_overlap,
            "mean_jaccard_at_k": sum(overlaps) / len(overlaps) if overlaps else 1.0,
            "compared_score_count": compared_scores,
            "maximum_absolute_score_difference": maximum_score_difference,
            "absolute_tolerance": absolute_tolerance,
            "relative_tolerance": relative_tolerance,
            "non_tie_order_mismatches": non_tie_order_mismatches,
            "passed": bool(queries)
            and minimum_overlap >= 0.999999
            and score_tolerance_passed
            and non_tie_order_mismatches == 0
            and math.isfinite(maximum_score_difference),
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", required=True)
    parser.add_argument("--queries", required=True)
    parser.add_argument("--qrels", required=True)
    parser.add_argument("--index", required=True)
    parser.add_argument("--run", required=True)
    parser.add_argument("--domain", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--k", type=int, default=100)
    parser.add_argument("--max-queries", type=int)
    args = parser.parse_args()
    if args.k < 1 or (args.max_queries is not None and args.max_queries < 1):
        raise ValueError("k and max-queries must be positive")
    queries = load_queries(args.queries, args.domain)
    query_ids = [query.query_id for query in queries]
    report = {
        "schema_version": "1.0",
        "domain": args.domain,
        "inputs": {
            "corpus_sha256": file_hash(args.corpus),
            "queries_sha256": file_hash(args.queries),
            "qrels_sha256": file_hash(args.qrels),
            "run_sha256": file_hash(args.run),
        },
        "bm25": _bm25s_parity(
            args.corpus,
            args.queries,
            args.index,
            args.run,
            args.domain,
            k=args.k,
            max_queries=args.max_queries,
        ),
        "evaluator": _evaluator_parity(query_ids, args.domain, args.qrels, args.run),
    }
    report["passed"] = report["bm25"]["passed"] and report["evaluator"]["passed"]
    atomic_json(args.output, report)
    print(json.dumps(report, indent=2))
    if not report["passed"]:
        raise SystemExit("provider validation failed")


if __name__ == "__main__":
    main()
