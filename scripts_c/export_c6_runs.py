"""Export frozen H*, S*, and PE-GH test rankings without opening test qrels."""

from __future__ import annotations

import argparse
import json
from dataclasses import replace
from pathlib import Path

import yaml

from contracts.io import load_queries
from contracts.ranking import ranking_to_record
from pegh.data.artifacts import atomic_json, file_hash, object_hash, write_jsonl
from pegh.data.splits import fold_record
from pegh.evaluation.runs import load_rankings
from pegh.fusion.engines import CCFusion, RRFFusion
from pegh.gating.features import QueryFeatureExtractor
from pegh.gating.models import load_model
from pegh.profiling.provenance import source_snapshot
from pegh.sparse.index import SQLiteBM25


def _fusion(name: str):
    if name.startswith("cc_alpha_"):
        return CCFusion(float(name.removeprefix("cc_alpha_")))
    if name in ("rrf", "rrf_k_60"):
        return RRFFusion(60)
    raise ValueError(f"unsupported frozen H*: {name}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--freeze", default="results/frozen/c6_manifest.json")
    parser.add_argument("--output-root", default="results/oof_runs")
    args = parser.parse_args()
    root = Path.cwd()
    freeze_path = root / args.freeze
    frozen = json.loads(freeze_path.read_text(encoding="utf-8"))
    unsigned = {key: value for key, value in frozen.items() if key != "freeze_hash"}
    if object_hash(unsigned) != frozen["freeze_hash"]:
        raise ValueError("freeze manifest hash differs")
    if source_snapshot()["combined_sha256"] != frozen["source_snapshot_hash"]:
        raise ValueError("source/config changed after C6 freeze")
    for name, digest in frozen["script_sha256"].items():
        if file_hash(root / name) != digest:
            raise ValueError(f"{name} changed after C6 freeze")
    split_path = root / "data/splits/manifest.json"
    if file_hash(split_path) != frozen["split_manifest_sha256"]:
        raise ValueError("split manifest changed after C6 freeze")
    split = json.loads(split_path.read_text(encoding="utf-8"))
    protocol_path = root / "configs/gating/protocol_v1.yaml"
    protocol = yaml.safe_load(protocol_path.read_text(encoding="utf-8"))
    output_root = root / args.output_root
    for domain in protocol["domains"]:
        domain_inputs = frozen["domains"][domain]
        sparse_run_path = root / f"results/quality/bm25/{domain}.jsonl"
        dense_run_path = root / f"results/quality/dense/{domain}.jsonl"
        if (
            file_hash(sparse_run_path) != domain_inputs["sparse_run_sha256"]
            or file_hash(dense_run_path) != domain_inputs["dense_run_sha256"]
        ):
            raise ValueError("frozen quality cache changed")
        sparse_runs, sparse_meta = load_rankings(sparse_run_path, domain=domain)
        dense_runs, dense_meta = load_rankings(dense_run_path, domain=domain)
        queries = load_queries(root / f"data/raw/{domain}/queries.jsonl", domain)
        query_by_id = {query.query_id: query for query in queries}
        if set(query_by_id) != set(sparse_runs) or set(query_by_id) != set(dense_runs):
            raise ValueError("quality cache query IDs differ")
        with SQLiteBM25(root / "artifacts/sparse" / domain) as backend:
            if backend.manifest["corpus_sha256"] != domain_inputs["corpus_sha256"]:
                raise ValueError("sparse corpus changed")
            extractor = QueryFeatureExtractor(protocol["features"], backend.tokenizer)
            for fold in range(5):
                item = domain_inputs["folds"][str(fold)]
                ids = fold_record(split, fold)["domains"][domain]["test"]
                if item["s_star_method"] != "h_star":
                    raise ValueError("current C6 S* export requires S*=H*")
                model = load_model(root / item["model_manifest_path"])
                if model.manifest["manifest_hash"] != item["model_manifest_hash"]:
                    raise ValueError("frozen model changed")
                if model.manifest["feature_schema_hash"] != extractor.schema_hash:
                    raise ValueError("frozen feature schema changed")
                engine = _fusion(item["h_star_method"])
                threshold = item["threshold"]
                rankings = {method: [] for method in ("h_star", "s_star", "pe_gh")}
                dense_count = 0
                hashes = {
                    method: object_hash(
                        {
                            "freeze_hash": frozen["freeze_hash"],
                            "method": method,
                            "domain": domain,
                            "fold": fold,
                            "selection_hash": item["selection_hash"],
                            "model_manifest_hash": item["model_manifest_hash"]
                            if method == "pe_gh"
                            else None,
                            "threshold": threshold if method == "pe_gh" else None,
                        }
                    )
                    for method in rankings
                }
                for query_id in ids:
                    query = query_by_id[query_id]
                    sparse = sparse_runs[query_id]
                    dense = dense_runs[query_id]
                    if (
                        sparse.retriever_hash != sparse_meta["retriever_hash"]
                        or dense.retriever_hash != dense_meta["retriever_hash"]
                    ):
                        raise ValueError("quality cache retriever changed")
                    h_star = engine.fuse(sparse, dense, k=100)
                    stats = backend.query_stats(query)
                    features = extractor.transform(query, sparse, stats)
                    score = model.predict_score(features)
                    use_dense = (
                        stats.token_count == 0 or stats.oov_ratio == 1.0 or score > threshold
                    )
                    dense_count += use_dense
                    selected = h_star if use_dense else sparse
                    for method, ranking in (
                        ("h_star", h_star),
                        ("s_star", h_star),
                        ("pe_gh", selected),
                    ):
                        rankings[method].append(
                            ranking_to_record(
                                replace(ranking, retriever_hash=hashes[method]),
                                method=method,
                                split="test",
                                fold=fold,
                                run_id=f"c6-{frozen['freeze_hash'][:12]}-{method}-{domain}-f{fold}",
                            )
                        )
                for method, records in rankings.items():
                    target = output_root / method / domain / f"fold_{fold}.jsonl"
                    sidecar = target.with_suffix(target.suffix + ".meta.json")
                    if target.exists() or sidecar.exists():
                        raise FileExistsError(f"refusing to overwrite {target}")
                    write_jsonl(target, records)
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
                            "run_id": records[0]["run_id"],
                            "corpus_hash": domain_inputs["corpus_sha256"],
                            "retriever_hash": hashes[method],
                            "freeze_hash": frozen["freeze_hash"],
                            "selection_hash": item["selection_hash"],
                            "model_manifest_hash": item["model_manifest_hash"]
                            if method == "pe_gh"
                            else None,
                            "threshold": threshold if method == "pe_gh" else None,
                            "dense_count": dense_count if method == "pe_gh" else len(ids),
                            "dense_ratio": dense_count / len(ids) if method == "pe_gh" else 1.0,
                            "source_sparse_run_sha256": domain_inputs["sparse_run_sha256"],
                            "source_dense_run_sha256": domain_inputs["dense_run_sha256"],
                            "quality_cache_used": True,
                            "latency_benchmark": False,
                        },
                    )
                print(f"{domain} fold {fold}: {len(ids)} queries, PE-GH dense {dense_count}")


if __name__ == "__main__":
    main()
