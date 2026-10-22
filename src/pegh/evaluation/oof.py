"""Strict out-of-fold evaluation and macro aggregation."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from contracts.io import load_queries
from pegh.data.artifacts import file_hash, object_hash
from pegh.data.qrels import load_qrels
from pegh.data.splits import fold_record, validate_five_fold_splits
from pegh.evaluation.bootstrap import macro_group_bootstrap, paired_group_bootstrap
from pegh.evaluation.metrics import QueryMetrics, aggregate_metrics, evaluate_rankings
from pegh.evaluation.runs import load_rankings


def _resolve(root: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def _group_map(split_manifest: dict, domain: str) -> dict[str, str]:
    result = {}
    for index, group in enumerate(split_manifest["domains"][domain]["groups"]):
        for query_id in group:
            result[query_id] = f"{domain}:group:{index}"
    return result


def _load_dataset_manifest(path: Path, domain: str, split_manifest: dict) -> dict:
    with path.open(encoding="utf-8") as stream:
        manifest = json.load(stream)
    if manifest.get("domain") != domain:
        raise ValueError(f"{domain}: dataset manifest domain differs")
    unsigned = {
        "schema_version": manifest["schema_version"],
        "domain": domain,
        "file_hashes": {
            name: manifest["files"][name]["sha256"] for name in ("corpus", "queries", "qrels")
        },
        "counts": manifest["counts"],
        "coverage": manifest["coverage"],
        "policies": manifest["policies"],
        "source": manifest.get("source"),
    }
    if object_hash(unsigned) != manifest.get("manifest_hash"):
        raise ValueError(f"{domain}: dataset manifest hash differs from contents")
    if split_manifest.get("dataset_hashes", {}).get(domain) != manifest["manifest_hash"]:
        raise ValueError(f"{domain}: split is not bound to the dataset manifest")
    return manifest


def _verify_run_sidecar(
    run_path: Path,
    *,
    domain: str,
    method: str,
    fold: int,
    query_ids: list[str],
    split_hash: str,
    corpus_hash: str,
    run_metadata: dict,
) -> None:
    sidecar_path = run_path.with_suffix(run_path.suffix + ".meta.json")
    if not sidecar_path.is_file():
        raise ValueError(f"{run_path}: required run sidecar is missing")
    with sidecar_path.open(encoding="utf-8") as stream:
        sidecar = json.load(stream)
    expected = {
        "ranking_sha256": file_hash(run_path),
        "query_ids_hash": object_hash(query_ids),
        "query_count": len(query_ids),
        "split_hash": split_hash,
        "domain": domain,
        "method": method,
        "fold": fold,
        "split": "test",
        "run_id": run_metadata["run_id"],
        "corpus_hash": corpus_hash,
    }
    mismatches = {
        key: {"expected": value, "actual": sidecar.get(key)}
        for key, value in expected.items()
        if sidecar.get(key) != value
    }
    if mismatches:
        raise ValueError(f"{run_path}: sidecar provenance differs: {mismatches}")


def run_oof(registry_path: str | Path, *, bootstrap_samples: int = 10_000) -> dict:
    registry_path = Path(registry_path).resolve()
    with registry_path.open(encoding="utf-8") as stream:
        registry = json.load(stream)
    root = registry_path.parent
    split_path = _resolve(root, registry["split_manifest"])
    with split_path.open(encoding="utf-8") as stream:
        split_manifest = json.load(stream)
    validate_five_fold_splits(split_manifest)
    all_rows: list[dict] = []
    rows_by_method_domain: dict[str, dict[str, list[QueryMetrics]]] = defaultdict(
        lambda: defaultdict(list)
    )
    input_hashes = {"split_manifest": file_hash(split_path)}
    provenance: dict[str, dict] = {}
    method_names: set[str] | None = None
    for domain, domain_config in sorted(registry["domains"].items()):
        if domain not in split_manifest["domains"]:
            raise ValueError(f"{domain}: absent from split manifest")
        queries_path = _resolve(root, domain_config["queries"])
        qrels_path = _resolve(root, domain_config["qrels"])
        dataset_manifest_path = _resolve(root, domain_config["dataset_manifest"])
        dataset_manifest = _load_dataset_manifest(dataset_manifest_path, domain, split_manifest)
        queries = load_queries(queries_path, domain)
        query_by_id = {query.query_id: query for query in queries}
        qrels = load_qrels(qrels_path, domain)
        input_hashes[f"{domain}.queries"] = file_hash(queries_path)
        input_hashes[f"{domain}.qrels"] = file_hash(qrels_path)
        input_hashes[f"{domain}.dataset_manifest"] = file_hash(dataset_manifest_path)
        if input_hashes[f"{domain}.queries"] != dataset_manifest["files"]["queries"]["sha256"]:
            raise ValueError(f"{domain}: query file differs from canonical dataset manifest")
        if input_hashes[f"{domain}.qrels"] != dataset_manifest["files"]["qrels"]["sha256"]:
            raise ValueError(f"{domain}: qrels file differs from canonical dataset manifest")
        canonical_corpus_hash = dataset_manifest["files"]["corpus"]["sha256"]
        current_methods = set(domain_config["runs"])
        if method_names is None:
            method_names = current_methods
        elif method_names != current_methods:
            raise ValueError("all domains must contain the same methods")
        for method, fold_runs in sorted(domain_config["runs"].items()):
            if set(fold_runs) != {str(index) for index in range(5)}:
                raise ValueError(f"{domain}/{method}: exactly folds 0..4 are required")
            corpus_hashes = set()
            retriever_hash_by_fold = {}
            for fold in range(5):
                expected = fold_record(split_manifest, fold)["domains"][domain]["test"]
                missing_queries = set(expected) - query_by_id.keys()
                if missing_queries:
                    raise ValueError(f"{domain}/fold {fold}: split queries are missing")
                run_path = _resolve(root, fold_runs[str(fold)])
                rankings, metadata = load_rankings(run_path, domain=domain)
                if set(rankings) != set(expected):
                    missing = sorted(set(expected) - rankings.keys())[:5]
                    extra = sorted(rankings.keys() - set(expected))[:5]
                    raise ValueError(
                        f"{domain}/{method}/fold {fold}: run must equal test IDs; "
                        f"missing={missing}, extra={extra}"
                    )
                if any(len(ranking.hits) > 100 for ranking in rankings.values()):
                    raise ValueError(f"{domain}/{method}/fold {fold}: run exceeds top-100")
                if metadata["fold"] != fold:
                    raise ValueError(f"{domain}/{method}/fold {fold}: embedded fold differs")
                if metadata["split"] != "test":
                    raise ValueError(f"{domain}/{method}/fold {fold}: expected test run")
                if metadata["method"] != method:
                    raise ValueError(f"{domain}/{method}/fold {fold}: embedded method differs")
                if not isinstance(metadata["run_id"], str) or not metadata["run_id"]:
                    raise ValueError(f"{domain}/{method}/fold {fold}: run_id is required")
                if metadata["corpus_hash"] != canonical_corpus_hash:
                    raise ValueError(f"{domain}/{method}/fold {fold}: noncanonical corpus hash")
                _verify_run_sidecar(
                    run_path,
                    domain=domain,
                    method=method,
                    fold=fold,
                    query_ids=expected,
                    split_hash=split_manifest["split_hash"],
                    corpus_hash=canonical_corpus_hash,
                    run_metadata=metadata,
                )
                rows = evaluate_rankings(expected, domain, qrels, rankings)
                rows_by_method_domain[method][domain].extend(rows)
                for row in rows:
                    all_rows.append({"method": method, "fold": fold, **row.as_dict()})
                input_hashes[f"{domain}.{method}.fold_{fold}"] = file_hash(run_path)
                corpus_hashes.add(metadata["corpus_hash"])
                retriever_hash_by_fold[str(fold)] = metadata["retriever_hash"]
            if len(corpus_hashes) != 1:
                raise ValueError(f"{domain}/{method}: corpus provenance changes across folds")
            provenance[f"{domain}.{method}"] = {
                "corpus_hash": next(iter(corpus_hashes)),
                "retriever_hash_by_fold": retriever_hash_by_fold,
            }
    summaries = {}
    for method, domain_rows in sorted(rows_by_method_domain.items()):
        per_domain = {
            domain: aggregate_metrics(rows) for domain, rows in sorted(domain_rows.items())
        }
        metric_names = ("ndcg_at_10", "mrr_at_10", "recall_at_10", "recall_at_100")
        macro = {
            metric: sum(values[metric] for values in per_domain.values()) / len(per_domain)
            for metric in metric_names
        }
        pooled_rows = [row for rows in domain_rows.values() for row in rows]
        summaries[method] = {
            "domains": per_domain,
            "macro": {"domain_count": len(per_domain), **macro},
            "micro": aggregate_metrics(pooled_rows),
        }
    comparison = None
    utility_output = []
    comparison_config = registry.get("comparison")
    if comparison_config:
        baseline = comparison_config["baseline"]
        candidate = comparison_config["candidate"]
        metric = comparison_config.get("metric", "ndcg_at_10")
        differences_by_domain = {}
        groups_by_domain = {}
        domain_ci = {}
        for domain in sorted(registry["domains"]):
            baseline_rows = {row.query_id: row for row in rows_by_method_domain[baseline][domain]}
            candidate_rows = {row.query_id: row for row in rows_by_method_domain[candidate][domain]}
            if baseline_rows.keys() != candidate_rows.keys():
                raise ValueError(f"{domain}: comparison query sets differ")
            differences = {
                query_id: getattr(candidate_rows[query_id], metric)
                - getattr(baseline_rows[query_id], metric)
                for query_id in baseline_rows
            }
            groups = _group_map(split_manifest, domain)
            differences_by_domain[domain] = differences
            groups_by_domain[domain] = groups
            utility_output.extend(
                {
                    "utility_name": "primary_comparison",
                    "query_id": query_id,
                    "domain": domain,
                    "metric": metric,
                    "baseline": baseline,
                    "candidate": candidate,
                    "utility_baseline": getattr(baseline_rows[query_id], metric),
                    "utility_candidate": getattr(candidate_rows[query_id], metric),
                    "delta_utility": difference,
                }
                for query_id, difference in sorted(differences.items())
            )
            domain_ci[domain] = paired_group_bootstrap(
                differences, groups, samples=bootstrap_samples
            )
        comparison = {
            "baseline": baseline,
            "candidate": candidate,
            "metric": metric,
            "domains": domain_ci,
            "macro": macro_group_bootstrap(
                differences_by_domain,
                groups_by_domain,
                samples=bootstrap_samples,
            ),
        }
    if registry.get("utilities"):
        utility_output = []
        for specification in registry["utilities"]:
            name = specification["name"]
            baseline = specification["baseline"]
            candidate = specification["candidate"]
            metric = specification.get("metric", "ndcg_at_10")
            for domain in sorted(registry["domains"]):
                baseline_rows = {
                    row.query_id: row for row in rows_by_method_domain[baseline][domain]
                }
                candidate_rows = {
                    row.query_id: row for row in rows_by_method_domain[candidate][domain]
                }
                if baseline_rows.keys() != candidate_rows.keys():
                    raise ValueError(f"{domain}/{name}: utility query sets differ")
                utility_output.extend(
                    {
                        "utility_name": name,
                        "query_id": query_id,
                        "domain": domain,
                        "metric": metric,
                        "baseline": baseline,
                        "candidate": candidate,
                        "utility_baseline": getattr(baseline_rows[query_id], metric),
                        "utility_candidate": getattr(candidate_rows[query_id], metric),
                        "delta_utility": getattr(candidate_rows[query_id], metric)
                        - getattr(baseline_rows[query_id], metric),
                    }
                    for query_id in sorted(baseline_rows)
                )
    return {
        "schema_version": "1.0",
        "protocol": "grouped_5_fold_oof_v1",
        "split_hash": split_manifest["split_hash"],
        "input_hashes": input_hashes,
        "provenance": provenance,
        "summaries": summaries,
        "comparison": comparison,
        "per_query": all_rows,
        "utility": utility_output,
    }
