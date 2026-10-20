"""Bind a benchmark factory to a complete, checksummed local index."""

from __future__ import annotations

import argparse
from pathlib import Path

from pegh.dense.artifacts import atomic_json, file_hash, read_json


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--cache-folder")
    args = parser.parse_args()
    index = Path(args.index).resolve()
    output = Path(args.output)
    if output.exists():
        raise FileExistsError("choose a new registry output path")
    manifest = read_json(index / "manifest.json")
    if manifest["status"] != "complete":
        raise ValueError("finish the index before registering a benchmark")
    actual = file_hash(index / "index.faiss")
    if actual != manifest["index_sha256"]:
        raise ValueError("index checksum mismatch")
    kwargs = {"index_dir": str(index), "expected_index_sha256": actual}
    if args.cache_folder:
        kwargs["cache_folder"] = str(Path(args.cache_folder).resolve())
    atomic_json(
        output,
        {
            "schema_version": "1.0",
            "methods": [
                {
                    "id": "dense_minilm",
                    "factory": "pegh.dense.factory:create_dense_method",
                    "kwargs": kwargs,
                    "require_dense_warmup": True,
                }
            ],
        },
    )
    print(f"Wrote frozen registry to {output}")


if __name__ == "__main__":
    main()
