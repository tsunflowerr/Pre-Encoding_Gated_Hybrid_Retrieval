"""Materialize C2 features from canonical queries, SQLiteBM25 stats, and cached runs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

from contracts.io import load_queries
from pegh.data.artifacts import atomic_json, file_hash, write_jsonl
from pegh.evaluation.runs import load_rankings
from pegh.gating.features import QueryFeatureExtractor
from pegh.sparse.index import SQLiteBM25


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="configs/gating/protocol_v1.yaml")
    parser.add_argument("--output-dir", default="results/features")
    args = parser.parse_args()
    root = Path.cwd()
    config_path = root / args.config
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    output = root / args.output_dir
    schema_manifest = None

    for domain in config["domains"]:
        raw = root / "data" / "raw" / domain
        data_manifest_path = root / "data" / "manifests" / f"{domain}.json"
        data_manifest = json.loads(data_manifest_path.read_text(encoding="utf-8"))
        corpus_hash = data_manifest["files"]["corpus"]["sha256"]
        if file_hash(raw / "corpus.jsonl") != corpus_hash:
            raise ValueError(f"{domain}: canonical corpus hash differs")

        queries = load_queries(raw / "queries.jsonl", domain)
        query_ids = {query.query_id for query in queries}
        run_path = root / "results" / "quality" / "bm25" / f"{domain}.jsonl"
        run_sidecar = run_path.with_suffix(run_path.suffix + ".meta.json")
        rankings, run_metadata = load_rankings(run_path, domain=domain)
        sidecar = json.loads(run_sidecar.read_text(encoding="utf-8"))
        if set(rankings) != query_ids:
            raise ValueError(f"{domain}: cached BM25 query set differs")
        if (
            sidecar.get("ranking_sha256") != file_hash(run_path)
            or sidecar.get("corpus_sha256") != corpus_hash
            or sidecar.get("queries_sha256") != file_hash(raw / "queries.jsonl")
            or sidecar.get("retriever_hash") != run_metadata["retriever_hash"]
            or run_metadata["method"] != "bm25"
            or run_metadata["split"] != "development_validation"
        ):
            raise ValueError(f"{domain}: cached BM25 provenance differs")

        with SQLiteBM25(root / "artifacts" / "sparse" / domain) as backend:
            if backend.manifest["corpus_sha256"] != corpus_hash:
                raise ValueError(f"{domain}: sparse index corpus differs")
            extractor = QueryFeatureExtractor(config["features"], backend.tokenizer)
            current_schema = extractor.schema_manifest()
            if schema_manifest is None:
                schema_manifest = current_schema
            elif schema_manifest != current_schema:
                raise ValueError("feature schema differs across domains")
            records = []
            for query in queries:
                sparse_ranking = rankings[query.query_id]
                if (
                    sparse_ranking.corpus_hash != corpus_hash
                    or sparse_ranking.retriever_hash != backend.manifest["retriever_hash"]
                ):
                    raise ValueError(f"{domain}/{query.query_id}: ranking provenance differs")
                stats = backend.query_stats(query)
                full = extractor.transform(query, sparse_ranking, stats)
                general = extractor.transform_general(query, sparse_ranking, stats)
                records.append(
                    {
                        "query_id": query.query_id,
                        "domain": domain,
                        "feature_schema_hash": full.schema_hash,
                        "general_schema_hash": general.schema_hash,
                        "values": list(full.values),
                        "general_values": list(general.values),
                    }
                )

        run_output = output / f"{domain}.jsonl"
        write_jsonl(run_output, records)
        atomic_json(
            run_output.with_suffix(run_output.suffix + ".meta.json"),
            {
                "schema_version": "1.0",
                "domain": domain,
                "query_count": len(records),
                "feature_count": 21,
                "general_feature_count": 8,
                "feature_schema_hash": extractor.schema_hash,
                "general_schema_hash": extractor.general_schema_hash,
                "queries_sha256": file_hash(raw / "queries.jsonl"),
                "dataset_manifest_sha256": file_hash(data_manifest_path),
                "sparse_retriever_hash": backend.manifest["retriever_hash"],
                "bm25_ranking_sha256": file_hash(run_path),
                "bm25_sidecar_sha256": file_hash(run_sidecar),
                "feature_rows_sha256": file_hash(run_output),
                "protocol_config_sha256": file_hash(config_path),
                "extractor_sha256": file_hash(root / "src" / "pegh" / "gating" / "features.py"),
                "materializer_sha256": file_hash(root / "scripts_c" / "materialize_features.py"),
            },
        )
        print(f"{domain}: materialized {len(records)} feature vectors")

    if schema_manifest is None:
        raise ValueError("no domains configured")
    atomic_json(output / "schema_v1.json", schema_manifest)


if __name__ == "__main__":
    main()
