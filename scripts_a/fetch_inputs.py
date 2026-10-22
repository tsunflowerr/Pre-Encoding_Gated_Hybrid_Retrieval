"""Fetch pinned CQADupStack inputs and reject any byte/count drift."""

from __future__ import annotations

import argparse
import urllib.request
from pathlib import Path

import pyarrow.parquet as pq
import yaml

from pegh.data.artifacts import atomic_json, file_hash, write_jsonl


def _download(url: str, target: Path) -> None:
    if target.exists():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    request = urllib.request.Request(url, headers={"User-Agent": "PE-GH-part-A/0.1"})
    with urllib.request.urlopen(request, timeout=120) as response, temporary.open("wb") as output:
        for block in iter(lambda: response.read(1024 * 1024), b""):
            output.write(block)
    temporary.replace(target)


def _convert_parquet(source: Path, target: Path, expected_rows: int) -> None:
    parquet = pq.ParquetFile(source)
    if parquet.metadata.num_rows != expected_rows:
        raise ValueError(
            f"{source}: expected {expected_rows} rows, got {parquet.metadata.num_rows}"
        )

    def records():
        for batch in parquet.iter_batches(batch_size=1024):
            for row in batch.to_pylist():
                if not isinstance(row.get("_id"), str):
                    raise TypeError(f"{source}: source IDs must remain strings")
                yield row

    write_jsonl(target, records())


def fetch_domain(domain: str, paths: dict, source: dict) -> dict:
    expected = paths["expected"]
    output = Path(paths["corpus"]).parent
    output.mkdir(parents=True, exist_ok=True)
    dataset_revision = source["dataset_revision"]
    qrels_revision = source["qrels_revision"]
    files = []
    for kind, count_key, hash_key in (
        ("corpus", "documents", "corpus_sha256"),
        ("queries", "queries", "queries_sha256"),
    ):
        url = (
            "https://huggingface.co/datasets/BeIR/cqadupstack/resolve/"
            f"{dataset_revision}/{domain}/{kind}/{kind}-00000-of-00001.parquet"
        )
        parquet_path = output / f"{kind}.parquet"
        jsonl_path = Path(paths[kind])
        _download(url, parquet_path)
        if not jsonl_path.exists():
            _convert_parquet(parquet_path, jsonl_path, int(expected[count_key]))
        actual_hash = file_hash(jsonl_path)
        if actual_hash != expected[hash_key]:
            raise ValueError(f"{jsonl_path}: canonical JSONL hash mismatch")
        files.append(
            {
                "kind": kind,
                "source_url": url,
                "source_revision": dataset_revision,
                "source_sha256": file_hash(parquet_path),
                "canonical_path": str(jsonl_path),
                "canonical_sha256": actual_hash,
                "rows": int(expected[count_key]),
            }
        )
    qrels_url = (
        "https://huggingface.co/datasets/BeIR/cqadupstack-qrels/resolve/"
        f"{qrels_revision}/{domain}/test.tsv"
    )
    qrels_path = Path(paths["qrels"])
    _download(qrels_url, qrels_path)
    qrels_hash = file_hash(qrels_path)
    if qrels_hash != expected["qrels_sha256"]:
        raise ValueError(f"{qrels_path}: pinned qrels hash mismatch")
    files.append(
        {
            "kind": "qrels",
            "source_url": qrels_url,
            "source_revision": qrels_revision,
            "canonical_path": str(qrels_path),
            "canonical_sha256": qrels_hash,
            "rows": int(expected["qrel_pairs"]),
        }
    )
    manifest = {
        "schema_version": "1.0",
        "domain": domain,
        "dataset_id": source["dataset_id"],
        "dataset_revision": dataset_revision,
        "qrels_dataset_id": source["qrels_dataset_id"],
        "qrels_revision": qrels_revision,
        "license": source["license"],
        "files": files,
    }
    atomic_json(output / "source_manifest.json", manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="configs/data/cqadupstack.yaml")
    parser.add_argument("--domains", nargs="+", choices=("programmers", "unix"))
    args = parser.parse_args()
    with Path(args.config).open(encoding="utf-8") as stream:
        payload = yaml.safe_load(stream)["data"]
    selected = args.domains or sorted(payload["domains"])
    for domain in selected:
        manifest = fetch_domain(domain, payload["domains"][domain], payload["source"])
        print(domain, [(item["kind"], item["rows"]) for item in manifest["files"]])


if __name__ == "__main__":
    main()
