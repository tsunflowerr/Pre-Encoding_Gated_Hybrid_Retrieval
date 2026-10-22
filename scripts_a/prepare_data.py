"""Audit canonical A inputs and write deterministic grouped five-fold splits."""

from __future__ import annotations

import argparse
from pathlib import Path

import yaml

from contracts.io import load_queries
from pegh.data.artifacts import atomic_json
from pegh.data.manifest import audit_dataset
from pegh.data.qrels import load_qrels
from pegh.data.splits import make_five_fold_splits, write_five_fold_splits


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="configs/data/cqadupstack.yaml")
    args = parser.parse_args()
    with Path(args.config).open(encoding="utf-8") as stream:
        payload = yaml.safe_load(stream)
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict) or not isinstance(data.get("domains"), dict):
        raise ValueError("data config needs data.domains")
    output = Path(data.get("output_dir", "data"))
    queries_by_domain = {}
    qrels_by_domain = {}
    dataset_hashes = {}
    for domain, paths in sorted(data["domains"].items()):
        source_manifest_path = Path(paths["corpus"]).parent / "source_manifest.json"
        manifest = audit_dataset(
            paths["corpus"],
            paths["queries"],
            paths["qrels"],
            domain,
            expected=paths.get("expected"),
            source_manifest_path=source_manifest_path,
        )
        atomic_json(output / "manifests" / f"{domain}.json", manifest)
        dataset_hashes[domain] = manifest["manifest_hash"]
        queries_by_domain[domain] = load_queries(paths["queries"], domain)
        qrels_by_domain[domain] = load_qrels(paths["qrels"], domain)
        print(domain, manifest["counts"], flush=True)
    splits = make_five_fold_splits(
        queries_by_domain,
        qrels_by_domain,
        seed=int(data.get("seed", 42)),
        dataset_hashes=dataset_hashes,
    )
    write_five_fold_splits(output / "splits", splits)
    print(f"Wrote manifests and five folds under {output}", flush=True)


if __name__ == "__main__":
    main()
