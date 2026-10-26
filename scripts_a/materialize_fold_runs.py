"""Slice a complete quality cache into the exact five OOF test-query runs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from contracts.ranking import ranking_to_record
from pegh.data.artifacts import atomic_json, file_hash, object_hash, write_jsonl
from pegh.data.splits import fold_record, validate_five_fold_splits
from pegh.evaluation.runs import load_rankings


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True)
    parser.add_argument("--split-manifest", required=True)
    parser.add_argument("--domain", required=True)
    parser.add_argument("--method", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--run-id-prefix", required=True)
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    with Path(args.split_manifest).open(encoding="utf-8") as stream:
        manifest = json.load(stream)
    validate_five_fold_splits(manifest)
    rankings, source_metadata = load_rankings(args.run, domain=args.domain)
    expected_all = {
        query_id
        for fold in range(5)
        for query_id in fold_record(manifest, fold)["domains"][args.domain]["test"]
    }
    if set(rankings) != expected_all:
        missing = sorted(expected_all - rankings.keys())[:5]
        extra = sorted(rankings.keys() - expected_all)[:5]
        raise ValueError(f"complete run query set differs: missing={missing}, extra={extra}")
    for fold in range(5):
        query_ids = fold_record(manifest, fold)["domains"][args.domain]["test"]
        target = output / f"fold_{fold}.jsonl"
        sidecar = target.with_suffix(target.suffix + ".meta.json")
        if target.exists() or sidecar.exists():
            raise FileExistsError(f"refusing to replace {target}")
        run_id = f"{args.run_id_prefix}-fold-{fold}"
        write_jsonl(
            target,
            (
                ranking_to_record(
                    rankings[query_id],
                    method=args.method,
                    split="test",
                    fold=fold,
                    run_id=run_id,
                )
                for query_id in query_ids
            ),
        )
        atomic_json(
            sidecar,
            {
                "schema_version": "1.0",
                "source_run_sha256": file_hash(args.run),
                "ranking_sha256": file_hash(target),
                "split_hash": manifest["split_hash"],
                "query_ids_hash": object_hash(query_ids),
                "query_count": len(query_ids),
                "domain": args.domain,
                "method": args.method,
                "fold": fold,
                "split": "test",
                "run_id": run_id,
                "corpus_hash": source_metadata["corpus_hash"],
                "retriever_hash": source_metadata["retriever_hash"],
            },
        )
    print(f"Wrote five exact OOF runs under {output}")


if __name__ == "__main__":
    main()
