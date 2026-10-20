from __future__ import annotations

import argparse
from dataclasses import asdict
from pathlib import Path

from pegh.dense.artifacts import atomic_json, file_hash, read_json, write_jsonl
from pegh.dense.config import DenseConfig
from pegh.dense.corpus import load_queries
from pegh.dense.encoder import CPUEncoder
from pegh.dense.retriever import FaissDenseRetriever
from pegh.profiling.provenance import source_snapshot
from pegh.profiling.runtime import RuntimeSettings, configure_resources, runtime_manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Offline quality rankings; never a latency result")
    parser.add_argument("--index", required=True)
    parser.add_argument("--queries", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--split", required=True)
    parser.add_argument("--cache-folder")
    parser.add_argument("--k", type=int, default=100)
    parser.add_argument("--runtime", default="configs/runtime/cpu4.yaml")
    args = parser.parse_args()
    output = Path(args.output)
    if output.exists() or output.with_suffix(output.suffix + ".meta.json").exists():
        raise FileExistsError("choose a new output path")
    if args.k < 1:
        raise ValueError("k must be positive")
    settings = RuntimeSettings.from_yaml(args.runtime)
    resources = configure_resources(settings)
    runtime = runtime_manifest(settings, resources)
    snapshot_before = source_snapshot()
    manifest = read_json(Path(args.index) / "manifest.json")
    encoder = CPUEncoder(DenseConfig(**manifest["config"]), cache_folder=args.cache_folder)
    retriever = FaissDenseRetriever(args.index, encoder)
    queries = load_queries(args.queries, manifest["domain"])
    output.parent.mkdir(parents=True, exist_ok=True)

    def records():
        for query in queries:
            ranking = retriever.search(query, k=args.k)
            yield {
                "schema_version": "1.0",
                "method": "dense",
                "split": args.split,
                **asdict(ranking),
            }

    write_jsonl(output, records())
    atomic_json(
        output.with_suffix(output.suffix + ".meta.json"),
        {
            "schema_version": "1.0",
            "quality_cache": True,
            "latency_benchmark": False,
            "queries_sha256": file_hash(args.queries),
            "query_count": len(queries),
            "retriever_hash": retriever.retriever_hash,
            "model_revision": encoder.config.revision,
            "corpus_sha256": manifest["corpus_sha256"],
            "ranking_sha256": file_hash(output),
            "split": args.split,
            "output_k": args.k,
            "runtime": runtime,
            "source_snapshot_start": snapshot_before,
            "source_snapshot_end": source_snapshot(),
        },
    )
    print(f"Wrote {len(queries)} quality rankings to {output}")


if __name__ == "__main__":
    main()
