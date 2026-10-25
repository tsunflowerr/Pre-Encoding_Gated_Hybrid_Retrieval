"""Export preregistered static and router controls after the primary C6 freeze."""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import replace
from pathlib import Path

import yaml

from contracts.io import load_queries
from contracts.ranking import ranking_to_record
from contracts.types import FeatureVector
from pegh.data.artifacts import atomic_json, file_hash, object_hash, write_jsonl
from pegh.data.splits import fold_record
from pegh.evaluation.runs import load_rankings
from pegh.fusion.engines import CCFusion, RRFFusion
from pegh.gating.features import QueryFeatureExtractor
from pegh.gating.models import load_model
from pegh.profiling.provenance import source_snapshot
from pegh.sparse.index import SQLiteBM25

MODELS = (
    "logistic_gain_full",
    "logistic_sparse_success_full",
    "linear_svc_gain_general",
    "ridge_gain_general",
)
CONTROLS = {
    "identifier_margin": "identifier_margin_score",
    "bm25_margin": "bm25_margin_score",
    "random_seed_0": "random_score_seed_0",
}
METHODS = ("dense", "cc_half", "rrf", *MODELS, *CONTROLS)


def _random_score(query_id: str) -> float:
    digest = hashlib.sha256(f"0\0{query_id}".encode()).digest()
    return 1.0 - int.from_bytes(digest[:8], "big") / 2**64


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", default="results/oof_runs")
    args = parser.parse_args()
    root = Path.cwd()
    frozen = json.loads((root / "results/frozen/c6_manifest.json").read_text(encoding="utf-8"))
    threshold_path = root / "results/thresholds/c6_validation.json"
    thresholds = json.loads(threshold_path.read_text(encoding="utf-8"))
    if (
        source_snapshot()["combined_sha256"] != frozen["source_snapshot_hash"]
        or file_hash(threshold_path) != frozen["threshold_report_sha256"]
    ):
        raise ValueError("source or threshold report differs from C6 freeze")
    split = json.loads((root / "data/splits/manifest.json").read_text(encoding="utf-8"))
    config = yaml.safe_load((root / "configs/gating/protocol_v1.yaml").read_text(encoding="utf-8"))
    output_root = root / args.output_root
    for domain in config["domains"]:
        sparse_runs, sparse_meta = load_rankings(
            root / f"results/quality/bm25/{domain}.jsonl", domain=domain
        )
        dense_runs, dense_meta = load_rankings(
            root / f"results/quality/dense/{domain}.jsonl", domain=domain
        )
        queries = {
            q.query_id: q for q in load_queries(root / f"data/raw/{domain}/queries.jsonl", domain)
        }
        with SQLiteBM25(root / "artifacts/sparse" / domain) as backend:
            extractor = QueryFeatureExtractor(config["features"], backend.tokenizer)
            for fold in range(5):
                ids = fold_record(split, fold)["domains"][domain]["test"]
                primary = frozen["domains"][domain]["folds"][str(fold)]
                selected = thresholds["folds"][str(fold)]
                models = {}
                for method in MODELS:
                    path = root / f"results/models/fold_{fold}/{domain}/{method}/manifest.json"
                    predictor = load_model(path)
                    if (
                        predictor.manifest["manifest_hash"]
                        != selected[method]["inputs"][f"{domain}.model_manifest_hash"]
                    ):
                        raise ValueError("control model differs from validation selection")
                    models[method] = predictor
                records = {method: [] for method in METHODS}
                dense_counts = {method: 0 for method in METHODS}
                hashes = {
                    method: object_hash(
                        {
                            "freeze_hash": frozen["freeze_hash"],
                            "diagnostic_method": method,
                            "domain": domain,
                            "fold": fold,
                            "selection_hash": primary["selection_hash"],
                            "threshold_report_hash": thresholds["report_hash"],
                            "threshold": selected[CONTROLS.get(method, method)][
                                "selected_threshold"
                            ]
                            if method not in ("dense", "cc_half", "rrf")
                            else None,
                        }
                    )
                    for method in METHODS
                }
                for query_id in ids:
                    query = queries[query_id]
                    sparse, dense = sparse_runs[query_id], dense_runs[query_id]
                    if (
                        sparse.retriever_hash != sparse_meta["retriever_hash"]
                        or dense.retriever_hash != dense_meta["retriever_hash"]
                    ):
                        raise ValueError("cached retriever differs")
                    half = CCFusion(0.5).fuse(sparse, dense, k=100)
                    rrf = RRFFusion(60).fuse(sparse, dense, k=100)
                    rankings = {"dense": dense, "cc_half": half, "rrf": rrf}
                    stats = backend.query_stats(query)
                    full = extractor.transform(query, sparse, stats)
                    general = FeatureVector(
                        tuple(full.values[index - 1] for index in extractor.indices),
                        extractor.general_schema_hash,
                    )
                    h_star = (
                        CCFusion(float(primary["h_star_method"].removeprefix("cc_alpha_"))).fuse(
                            sparse, dense, k=100
                        )
                        if primary["h_star_method"].startswith("cc_alpha_")
                        else RRFFusion(60).fuse(sparse, dense, k=100)
                    )
                    scores = {
                        method: predictor.predict_score(
                            general if predictor.manifest["feature_set"] == "general" else full
                        )
                        for method, predictor in models.items()
                    }
                    identifier = float(any(full.values[index] > 0 for index in (6, 7, 8)))
                    scores.update(
                        {
                            "identifier_margin": max(identifier, -full.values[16]),
                            "bm25_margin": -full.values[16],
                            "random_seed_0": _random_score(query_id),
                        }
                    )
                    for method, score in scores.items():
                        choice = selected[CONTROLS.get(method, method)]
                        use_dense = (
                            choice["selected_mode"] == "always_h_star"
                            or stats.token_count == 0
                            or stats.oov_ratio == 1.0
                            or score > choice["selected_threshold"]
                        )
                        dense_counts[method] += use_dense
                        rankings[method] = h_star if use_dense else sparse
                    for method in METHODS:
                        if method in ("dense", "cc_half", "rrf"):
                            dense_counts[method] += 1
                        records[method].append(
                            ranking_to_record(
                                replace(rankings[method], retriever_hash=hashes[method]),
                                method=method,
                                split="test",
                                fold=fold,
                                run_id=f"c6-diag-{frozen['freeze_hash'][:12]}-{method}-{domain}-f{fold}",
                            )
                        )
                for method in METHODS:
                    target = output_root / method / domain / f"fold_{fold}.jsonl"
                    sidecar = target.with_suffix(target.suffix + ".meta.json")
                    if target.exists() or sidecar.exists():
                        raise FileExistsError(f"refusing to overwrite {target}")
                    write_jsonl(target, records[method])
                    atomic_json(
                        sidecar,
                        {
                            "schema_version": "1.0",
                            "ranking_sha256": file_hash(target),
                            "query_ids_hash": object_hash(ids),
                            "query_count": len(ids),
                            "split_hash": split["split_hash"],
                            "domain": domain,
                            "method": method,
                            "fold": fold,
                            "split": "test",
                            "run_id": records[method][0]["run_id"],
                            "corpus_hash": sparse_meta["corpus_hash"],
                            "retriever_hash": hashes[method],
                            "freeze_hash": frozen["freeze_hash"],
                            "threshold_report_hash": thresholds["report_hash"],
                            "selected_mode": selected[CONTROLS.get(method, method)]["selected_mode"]
                            if method not in ("dense", "cc_half", "rrf")
                            else "static",
                            "dense_count": dense_counts[method],
                            "dense_ratio": dense_counts[method] / len(ids),
                            "quality_cache_used": True,
                            "latency_benchmark": False,
                        },
                    )
                print(f"{domain} fold {fold}: exported {len(METHODS)} control runs")


if __name__ == "__main__":
    main()
