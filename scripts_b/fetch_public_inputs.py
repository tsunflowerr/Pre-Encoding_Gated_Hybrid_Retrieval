"""Fetch pinned public corpus/query files for standalone B validation only.

No qrels, split generation, training or evaluation is performed here. Person A's
validated corpus adapter/manifest can replace these files without changing B APIs.
"""

from __future__ import annotations

import argparse
import urllib.request
from pathlib import Path

import pyarrow.parquet as pq

from pegh.dense.artifacts import atomic_json, file_hash, read_json, write_jsonl

REVISION = "e84b7220ce5a4e6c49aeb568983b0ec5a7584c2c"
COUNTS = {
    "programmers": {"corpus": 32176, "queries": 876},
    "unix": {"corpus": 47382, "queries": 1072},
}


def fetch_domain(domain: str, output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    metadata = output / "source_manifest.json"
    if metadata.exists():
        existing = read_json(metadata)
        if existing["revision"] != REVISION or existing["domain"] != domain:
            raise ValueError("existing input manifest has an incompatible source")
        for item in existing["files"]:
            if file_hash(output / item["jsonl"]) != item["jsonl_sha256"]:
                raise ValueError("existing converted input was modified")
        return existing
    files = []
    for split in ("corpus", "queries"):
        relative = f"{domain}/{split}/{split}-00000-of-00001.parquet"
        url = f"https://huggingface.co/datasets/BeIR/cqadupstack/resolve/{REVISION}/{relative}"
        binary = output / f"{split}.parquet"
        if not binary.exists():
            temporary = binary.with_suffix(".parquet.tmp")
            request = urllib.request.Request(url, headers={"User-Agent": "PE-GH-part-B/0.1"})
            with (
                urllib.request.urlopen(request, timeout=90) as response,
                temporary.open("wb") as dest,
            ):
                for block in iter(lambda: response.read(1024 * 1024), b""):
                    dest.write(block)
            temporary.replace(binary)
        parquet = pq.ParquetFile(binary)
        if parquet.metadata.num_rows != COUNTS[domain][split]:
            raise ValueError("unexpected source row count")

        def records(parquet_file=parquet):
            for batch in parquet_file.iter_batches(batch_size=1024):
                for row in batch.to_pylist():
                    if not isinstance(row["_id"], str):
                        raise TypeError("source IDs must be strings")
                    yield row

        converted = output / f"{split}.jsonl"
        write_jsonl(converted, records())
        files.append(
            {
                "kind": split,
                "source_url": url,
                "parquet": binary.name,
                "parquet_sha256": file_hash(binary),
                "jsonl": converted.name,
                "jsonl_sha256": file_hash(converted),
                "rows": parquet.metadata.num_rows,
            }
        )
    manifest = {
        "schema_version": "1.0",
        "domain": domain,
        "revision": REVISION,
        "scope": "public corpus/query input only; no qrels or study splits",
        "files": files,
    }
    atomic_json(metadata, manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--domains", choices=tuple(COUNTS), nargs="+", default=list(COUNTS))
    args = parser.parse_args()
    for domain in args.domains:
        metadata = fetch_domain(domain, args.output / domain)
        print(domain, [(f["kind"], f["rows"]) for f in metadata["files"]], flush=True)


if __name__ == "__main__":
    main()
