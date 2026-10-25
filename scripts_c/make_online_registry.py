"""Write a checksummed B benchmark registry for one C5 gate and fold/domain."""

from __future__ import annotations

import argparse
import math
from pathlib import Path

from pegh.dense.artifacts import atomic_json, file_hash, read_json


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--domain", choices=("programmers", "unix"), required=True)
    parser.add_argument("--fold", type=int, choices=range(5), required=True)
    parser.add_argument("--method", required=True)
    parser.add_argument("--threshold", type=float, required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--dense-dir")
    parser.add_argument("--cache-folder")
    args = parser.parse_args()
    if not math.isfinite(args.threshold):
        raise ValueError("threshold must be finite")
    root = Path.cwd()
    sparse = (root / "artifacts" / "sparse" / args.domain).resolve()
    dense = (
        Path(args.dense_dir)
        if args.dense_dir
        else Path.home() / ".cache" / "pegh" / "artifacts" / "c0-v1" / args.domain
    ).resolve()
    model = (
        root
        / "results"
        / "models"
        / f"fold_{args.fold}"
        / args.domain
        / args.method
        / "manifest.json"
    ).resolve()
    selection = (root / "results" / "fusion" / "selection_v1.json").resolve()
    protocol = (root / "configs" / "gating" / "protocol_v1.yaml").resolve()
    manifest = read_json(model)
    if manifest["method"] != args.method or (manifest["domain"], manifest["fold"]) != (
        args.domain,
        args.fold,
    ):
        raise ValueError("model manifest identity differs")
    output = Path(args.output).resolve()
    if output.exists():
        raise FileExistsError("choose a new registry path")
    kwargs = {
        "sparse_dir": str(sparse),
        "dense_dir": str(dense),
        "protocol_path": str(protocol),
        "selection_path": str(selection),
        "model_manifest_path": str(model),
        "domain": args.domain,
        "fold": args.fold,
        "threshold": args.threshold,
        "expected_sparse_sha256": file_hash(sparse / "index.sqlite3"),
        "expected_dense_sha256": file_hash(dense / "index.faiss"),
        "expected_protocol_sha256": file_hash(protocol),
        "expected_selection_sha256": file_hash(selection),
        "expected_model_manifest_hash": manifest["manifest_hash"],
    }
    if args.cache_folder:
        kwargs["cache_folder"] = str(Path(args.cache_folder).resolve())
    atomic_json(
        output,
        {
            "schema_version": "1.0",
            "selection_status": "c5_integration_only_threshold_supplied_by_caller",
            "methods": [
                {
                    "id": f"pegh_{args.method}_f{args.fold}_{args.domain}",
                    "factory": "pegh.app.factories:create_gated_method",
                    "kwargs": kwargs,
                    "require_dense_warmup": False,
                }
            ],
        },
    )
    print(f"Wrote registry: {output.name}")


if __name__ == "__main__":
    main()
