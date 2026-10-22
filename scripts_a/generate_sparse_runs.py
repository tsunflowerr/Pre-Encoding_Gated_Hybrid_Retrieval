"""Generate offline BM25 quality rankings in the shared ranking-v1 format."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from contracts.io import load_queries
from contracts.ranking import ranking_to_record
from pegh.data.artifacts import atomic_json, file_hash, object_hash, write_jsonl
from pegh.data.splits import fold_record
from pegh.sparse.index import SQLiteBM25


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", required=True)
    parser.add_argument("--queries", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--split", required=True)
    parser.add_argument("--fold", type=int)
    parser.add_argument("--split-manifest")
    parser.add_argument("--run-id")
    parser.add_argument("--k", type=int, default=100)
    args = parser.parse_args()
    output = Path(args.output)
    sidecar = output.with_suffix(output.suffix + ".meta.json")
    if output.exists() or sidecar.exists():
        raise FileExistsError("choose a new sparse run output")
    if args.fold is not None and args.split_manifest is None:
        raise ValueError("--fold requires --split-manifest; a fold label alone is unsafe")
    with SQLiteBM25(args.index) as backend:
        queries = load_queries(args.queries, backend.manifest["domain"])
        split_hash = None
        if args.split_manifest is not None:
            if args.fold is None:
                raise ValueError("--split-manifest requires --fold")
            with Path(args.split_manifest).open(encoding="utf-8") as stream:
                split_manifest = json.load(stream)
            split = fold_record(split_manifest, args.fold)
            split_hash = split["split_hash"]
            try:
                expected_ids = set(split["domains"][backend.manifest["domain"]][args.split])
            except KeyError as exc:
                raise ValueError("unknown domain or split in split manifest") from exc
            query_by_id = {query.query_id: query for query in queries}
            missing = expected_ids - query_by_id.keys()
            if missing:
                raise ValueError(f"split references missing queries: {sorted(missing)[:5]}")
            queries = [query_by_id[query_id] for query_id in sorted(expected_ids)]

        def records():
            for query in queries:
                ranking = backend.search(query, k=args.k)
                metadata = {"method": "bm25", "split": args.split}
                if args.fold is not None:
                    metadata["fold"] = args.fold
                if args.run_id is not None:
                    metadata["run_id"] = args.run_id
                yield ranking_to_record(ranking, **metadata)

        write_jsonl(output, records())
        atomic_json(
            sidecar,
            {
                "schema_version": "1.0",
                "quality_cache": True,
                "latency_benchmark": False,
                "query_count": len(queries),
                "query_ids_hash": object_hash([query.query_id for query in queries]),
                "queries_sha256": file_hash(args.queries),
                "ranking_sha256": file_hash(output),
                "corpus_sha256": backend.manifest["corpus_sha256"],
                "retriever_hash": backend.manifest["retriever_hash"],
                "tokenizer_hash": backend.manifest["tokenizer_hash"],
                "split": args.split,
                "fold": args.fold,
                "run_id": args.run_id,
                "split_hash": split_hash,
                "output_k": args.k,
            },
        )
    print(f"Wrote {len(queries)} BM25 rankings to {output}")


if __name__ == "__main__":
    main()
