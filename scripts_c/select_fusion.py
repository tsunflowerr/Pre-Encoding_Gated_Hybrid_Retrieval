"""Select H*/S* on validation buckets only and write an auditable C1 report."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import yaml

from contracts.io import load_queries
from pegh.data.artifacts import atomic_json, file_hash, object_hash
from pegh.data.qrels import load_qrels
from pegh.data.splits import fold_record, validate_five_fold_splits
from pegh.evaluation.metrics import aggregate_metrics, evaluate_rankings
from pegh.evaluation.runs import load_rankings
from pegh.fusion import fuse_cc, fuse_rrf


def _rankings(root: Path, domain: str, method: str, query_ids: set[str], corpus_hash: str):
    path = root / "results" / "quality" / method / f"{domain}.jsonl"
    sidecar_path = path.with_suffix(path.suffix + ".meta.json")
    rankings, metadata = load_rankings(path, domain=domain)
    sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    expected = {
        "ranking_sha256": file_hash(path),
        "queries_sha256": file_hash(root / "data" / "raw" / domain / "queries.jsonl"),
        "corpus_sha256": corpus_hash,
        "query_count": len(query_ids),
        "split": "development_validation",
        "output_k": 100,
        "retriever_hash": metadata["retriever_hash"],
    }
    mismatches = {
        key: (value, sidecar.get(key))
        for key, value in expected.items()
        if sidecar.get(key) != value
    }
    if mismatches:
        raise ValueError(f"{method}/{domain} sidecar differs: {mismatches}")
    if set(rankings) != query_ids:
        raise ValueError(f"{method}/{domain} query IDs differ from the canonical dataset")
    if metadata["method"] != method or metadata["split"] != "development_validation":
        raise ValueError(f"{method}/{domain} embedded run metadata differs")
    return rankings, {
        "ranking_sha256": file_hash(path),
        "sidecar_sha256": file_hash(sidecar_path),
        "retriever_hash": metadata["retriever_hash"],
        "run_id": metadata["run_id"],
    }


def _metrics(query_ids: list[str], domain: str, qrels: dict, rankings: dict) -> dict:
    selected = {query_id: rankings[query_id] for query_id in query_ids if query_id in rankings}
    return aggregate_metrics(evaluate_rankings(query_ids, domain, qrels, selected))


def _choose(
    candidates: dict[str, dict],
    names: list[str],
    epsilon: float,
    preferred: list[str] | None = None,
) -> tuple[str, list[str]]:
    best = max(candidates[name]["ndcg_at_10"] for name in names)
    tied = [name for name in names if best - candidates[name]["ndcg_at_10"] <= epsilon]
    order = (preferred or []) + [name for name in names if name not in (preferred or [])]
    return next(name for name in order if name in tied), tied


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="configs/gating/protocol_v1.yaml")
    parser.add_argument("--output", default="results/fusion/selection_v1.json")
    args = parser.parse_args()
    root = Path.cwd()
    config_path = root / args.config
    output_path = root / args.output
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    split_path = root / config["split_manifest"]
    split = json.loads(split_path.read_text(encoding="utf-8"))
    validate_five_fold_splits(split)
    epsilon = float(config["fusion"]["tie_epsilon"])
    alpha_grid = [float(value) for value in config["fusion"]["cc_alpha_dense"]]
    rrf_k = int(config["fusion"]["rrf_k"])
    h_tie_preference = config["fusion"]["tie_preference"]
    cc_tie_fallback = config["fusion"]["cc_remaining_tie_preference"]
    s_tie_preference = config["fusion"]["s_star_tie_preference"]
    if (
        h_tie_preference != "rrf"
        or cc_tie_fallback != "lower_alpha"
        or s_tie_preference != "candidate_order"
    ):
        raise ValueError("unsupported registered fusion tie policy")
    source_files = (Path("scripts_c/select_fusion.py"), Path("src/pegh/fusion/engines.py"))
    source_hashes = {str(path): file_hash(root / path) for path in source_files}
    report = {
        "schema_version": "1.0",
        "protocol": "C1_fusion_selection_v1",
        "selection_scope": "validation_only",
        "test_qrels_scored": False,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "config_sha256": file_hash(config_path),
        "split_manifest_sha256": file_hash(split_path),
        "split_hash": split["split_hash"],
        "source_sha256": source_hashes,
        "domains": {},
    }

    for domain in config["domains"]:
        manifest_path = root / "data" / "manifests" / f"{domain}.json"
        data_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        raw = root / "data" / "raw" / domain
        for kind, filename in (
            ("corpus", "corpus.jsonl"),
            ("queries", "queries.jsonl"),
            ("qrels", "qrels.tsv"),
        ):
            if file_hash(raw / filename) != data_manifest["files"][kind]["sha256"]:
                raise ValueError(f"{domain}/{kind} differs from its canonical manifest")
        corpus_hash = data_manifest["files"]["corpus"]["sha256"]
        queries = load_queries(raw / "queries.jsonl", domain)
        all_query_ids = {query.query_id for query in queries}
        sparse, sparse_provenance = _rankings(root, domain, "bm25", all_query_ids, corpus_hash)
        dense, dense_provenance = _rankings(root, domain, "dense", all_query_ids, corpus_hash)
        qrels = load_qrels(raw / "qrels.tsv", domain)
        if not all_query_ids <= qrels.keys():
            raise ValueError(f"{domain}: qrels omit canonical queries")
        domain_record = {
            "corpus_sha256": corpus_hash,
            "dataset_manifest_sha256": file_hash(manifest_path),
            "queries_sha256": file_hash(raw / "queries.jsonl"),
            "qrels_sha256": file_hash(raw / "qrels.tsv"),
            "inputs": {"bm25": sparse_provenance, "dense": dense_provenance},
            "folds": {},
        }

        for fold in range(split["fold_count"]):
            fold_data = fold_record(split, fold)["domains"][domain]
            validation_ids = fold_data["validation"]
            validation_qrels = {query_id: qrels[query_id] for query_id in validation_ids}
            candidates: dict[str, dict] = {}
            candidates["bm25"] = _metrics(validation_ids, domain, validation_qrels, sparse)
            candidates["dense"] = _metrics(validation_ids, domain, validation_qrels, dense)
            for alpha in alpha_grid:
                name = f"cc_alpha_{alpha:.1f}"
                fused = {
                    query_id: fuse_cc(sparse[query_id], dense[query_id], alpha_dense=alpha)
                    for query_id in validation_ids
                }
                candidates[name] = _metrics(validation_ids, domain, validation_qrels, fused)
            rrf = {
                query_id: fuse_rrf(sparse[query_id], dense[query_id], rrf_k=rrf_k)
                for query_id in validation_ids
            }
            candidates["rrf"] = _metrics(validation_ids, domain, validation_qrels, rrf)

            hybrid_names = [f"cc_alpha_{alpha:.1f}" for alpha in alpha_grid] + ["rrf"]
            h_star, h_ties = _choose(
                candidates, hybrid_names, epsilon, preferred=[h_tie_preference]
            )
            static_names = list(config["fusion"]["s_star_candidates"])
            candidates["h_star"] = candidates[h_star]
            s_star, s_ties = _choose(candidates, static_names, epsilon)
            inputs = {
                "validation_query_count": len(validation_ids),
                "validation_query_ids_hash": object_hash(validation_ids),
                "split_hash": split["split_hash"],
                "sparse_retriever_hash": sparse_provenance["retriever_hash"],
                "dense_retriever_hash": dense_provenance["retriever_hash"],
                "tie_epsilon": epsilon,
            }
            selection = {
                "validation": inputs,
                "candidates": candidates,
                "h_star": {
                    "method": h_star,
                    "metric": config["fusion"]["h_star_metric"],
                    "tied_within_epsilon": h_ties,
                    "tie_rule": f"prefer_{h_tie_preference}_then_{cc_tie_fallback}",
                },
                "s_star": {
                    "method": s_star,
                    "metric": config["fusion"]["h_star_metric"],
                    "tied_within_epsilon": s_ties,
                    "tie_rule": s_tie_preference,
                },
            }
            selection["selection_hash"] = object_hash(selection)
            domain_record["folds"][str(fold)] = selection
        report["domains"][domain] = domain_record

    report["report_hash"] = object_hash(report)
    atomic_json(output_path, report)
    print(f"Wrote {args.output} ({report['report_hash']})")


if __name__ == "__main__":
    main()
