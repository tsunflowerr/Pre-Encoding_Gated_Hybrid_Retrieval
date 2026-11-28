"""Slice a complete quality cache into the exact five OOF test-query runs."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from contracts.ranking import ranking_to_record
from pegh.data.artifacts import atomic_json, canonical_json, file_hash, object_hash, write_jsonl
from pegh.data.splits import fold_record, validate_five_fold_splits
from pegh.evaluation.runs import load_rankings


def materialize_fold_runs(
    run: str | Path,
    split_manifest: str | Path,
    domain: str,
    method: str,
    output: str | Path,
    run_id_prefix: str,
    *,
    reuse_identical: bool = False,
) -> dict[str, int]:
    output = Path(output)
    with Path(split_manifest).open(encoding="utf-8") as stream:
        manifest = json.load(stream)
    validate_five_fold_splits(manifest)
    rankings, source_metadata = load_rankings(run, domain=domain)
    expected_all = {
        query_id
        for fold in range(5)
        for query_id in fold_record(manifest, fold)["domains"][domain]["test"]
    }
    if set(rankings) != expected_all:
        missing = sorted(expected_all - rankings.keys())[:5]
        extra = sorted(rankings.keys() - expected_all)[:5]
        raise ValueError(f"complete run query set differs: missing={missing}, extra={extra}")
    pending = []
    reused = 0
    source_hash = file_hash(run)
    for fold in range(5):
        query_ids = fold_record(manifest, fold)["domains"][domain]["test"]
        target = output / f"fold_{fold}.jsonl"
        sidecar = target.with_suffix(target.suffix + ".meta.json")
        run_id = f"{run_id_prefix}-fold-{fold}"
        records = [
            ranking_to_record(
                rankings[query_id],
                method=method,
                split="test",
                fold=fold,
                run_id=run_id,
            )
            for query_id in query_ids
        ]
        digest = hashlib.sha256(
            "".join(canonical_json(record) + "\n" for record in records).encode("utf-8")
        ).hexdigest()
        metadata = {
            "schema_version": "1.0",
            "source_run_sha256": source_hash,
            "ranking_sha256": digest,
            "split_hash": manifest["split_hash"],
            "query_ids_hash": object_hash(query_ids),
            "query_count": len(query_ids),
            "domain": domain,
            "method": method,
            "fold": fold,
            "split": "test",
            "run_id": run_id,
            "corpus_hash": source_metadata["corpus_hash"],
            "retriever_hash": source_metadata["retriever_hash"],
        }
        if target.exists() or sidecar.exists():
            if (
                not reuse_identical
                or not target.is_file()
                or not sidecar.is_file()
                or file_hash(target) != digest
                or json.loads(sidecar.read_text(encoding="utf-8")) != metadata
            ):
                raise FileExistsError(
                    f"refusing to replace {target}: existing run/sidecar must match exactly; "
                    "choose a new output directory or archive the old output"
                )
            reused += 1
        else:
            pending.append((target, sidecar, records, metadata))
    # Check all five folds before writing any output; a conflict never leaves a new partial set.
    for target, sidecar, records, metadata in pending:
        write_jsonl(target, records)
        atomic_json(sidecar, metadata)
    return {"written": len(pending), "reused": reused}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True)
    parser.add_argument("--split-manifest", required=True)
    parser.add_argument("--domain", required=True)
    parser.add_argument("--method", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--run-id-prefix", required=True)
    parser.add_argument("--reuse-identical", action="store_true")
    args = parser.parse_args()
    counts = materialize_fold_runs(
        args.run,
        args.split_manifest,
        args.domain,
        args.method,
        args.output,
        args.run_id_prefix,
        reuse_identical=args.reuse_identical,
    )
    print(f"Verified five exact OOF runs under {args.output}: {counts}")


if __name__ == "__main__":
    main()
