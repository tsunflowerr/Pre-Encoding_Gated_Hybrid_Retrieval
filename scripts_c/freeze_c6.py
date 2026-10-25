"""Freeze C6 methods, thresholds, indexes, source, and B benchmark registries."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from pegh.data.artifacts import atomic_json, file_hash, object_hash
from pegh.gating.models import load_model
from pegh.profiling.provenance import source_snapshot


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--thresholds", default="results/thresholds/c6_validation.json")
    parser.add_argument("--output", default="results/frozen/c6_manifest.json")
    args = parser.parse_args()
    root = Path.cwd()
    threshold_path = root / args.thresholds
    threshold_report = json.loads(threshold_path.read_text(encoding="utf-8"))
    if (
        object_hash({k: v for k, v in threshold_report.items() if k != "report_hash"})
        != threshold_report["report_hash"]
    ):
        raise ValueError("threshold report hash differs")
    if (
        threshold_report["selection_scope"] != "validation_only"
        or threshold_report["test_qrels_used"]
    ):
        raise ValueError("threshold selection must use validation only")
    selection_path = root / "results/fusion/selection_v1.json"
    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    split_path = root / "data/splits/manifest.json"
    split = json.loads(split_path.read_text(encoding="utf-8"))
    protocol_path = root / "configs/gating/protocol_v1.yaml"
    if (
        threshold_report["selection_sha256"] != file_hash(selection_path)
        or threshold_report["protocol_sha256"] != file_hash(protocol_path)
        or threshold_report["split_hash"] != split["split_hash"]
    ):
        raise ValueError("threshold input provenance differs")
    script_names = (
        "scripts_c/select_thresholds.py",
        "scripts_c/freeze_c6.py",
        "scripts_c/export_c6_runs.py",
    )
    frozen = {
        "schema_version": "c6_freeze_v1",
        "selection_scope": "validation_only",
        "test_qrels_opened_before_freeze": False,
        "split_hash": split["split_hash"],
        "split_manifest_sha256": file_hash(split_path),
        "protocol_sha256": file_hash(protocol_path),
        "selection_sha256": file_hash(selection_path),
        "threshold_report_sha256": file_hash(threshold_path),
        "threshold_report_hash": threshold_report["report_hash"],
        "source_snapshot_hash": source_snapshot()["combined_sha256"],
        "script_sha256": {name: file_hash(root / name) for name in script_names},
        "domains": {},
    }
    registries = {}
    for domain in ("programmers", "unix"):
        sparse_dir = (root / "artifacts/sparse" / domain).resolve()
        dense_dir = (Path.home() / ".cache/pegh/artifacts/c0-v1" / domain).resolve()
        sparse_manifest = json.loads((sparse_dir / "manifest.json").read_text(encoding="utf-8"))
        dense_manifest = json.loads((dense_dir / "manifest.json").read_text(encoding="utf-8"))
        corpus_hash = selection["domains"][domain]["corpus_sha256"]
        if (
            sparse_manifest["corpus_sha256"] != corpus_hash
            or dense_manifest["corpus_sha256"] != corpus_hash
        ):
            raise ValueError("frozen indexes have different corpora")
        sparse_sha = file_hash(sparse_dir / "index.sqlite3")
        dense_sha = file_hash(dense_dir / "index.faiss")
        if (
            sparse_sha != sparse_manifest["database_sha256"]
            or dense_sha != dense_manifest["index_sha256"]
        ):
            raise ValueError("index checksum differs from manifest")
        domain_record = {
            "corpus_sha256": corpus_hash,
            "sparse_index_sha256": sparse_sha,
            "dense_index_sha256": dense_sha,
            "sparse_run_sha256": file_hash(root / f"results/quality/bm25/{domain}.jsonl"),
            "dense_run_sha256": file_hash(root / f"results/quality/dense/{domain}.jsonl"),
            "folds": {},
        }
        for fold in range(5):
            choice = selection["domains"][domain]["folds"][str(fold)]
            picked = threshold_report["folds"][str(fold)]["ridge_gain_full"]
            if picked["selected_mode"] != "threshold_gate" or picked["selected_threshold"] is None:
                raise ValueError("PE-GH needs a selected gate; use always-H* fallback explicitly")
            model_path = root / f"results/models/fold_{fold}/{domain}/ridge_gain_full/manifest.json"
            model = load_model(model_path)
            if (
                model.manifest["selection_hash"] != choice["selection_hash"]
                or model.manifest["h_star_method"] != choice["h_star"]["method"]
            ):
                raise ValueError("C4 model/H* provenance differs")
            item = {
                "h_star_method": choice["h_star"]["method"],
                "s_star_method": choice["s_star"]["method"],
                "selection_hash": choice["selection_hash"],
                "model_manifest_path": model_path.relative_to(root).as_posix(),
                "model_manifest_sha256": file_hash(model_path),
                "model_manifest_hash": model.manifest["manifest_hash"],
                "feature_schema_hash": model.manifest["feature_schema_hash"],
                "threshold": picked["selected_threshold"],
                "validation_dense_ratio": picked["selected_actual_dense_ratio"],
                "validation_budget": picked["selected_budget"],
            }
            domain_record["folds"][str(fold)] = item
            base = {
                "sparse_dir": str(sparse_dir),
                "dense_dir": str(dense_dir),
                "selection_path": str(selection_path.resolve()),
                "domain": domain,
                "fold": fold,
                "expected_sparse_sha256": sparse_sha,
                "expected_dense_sha256": dense_sha,
                "expected_selection_sha256": file_hash(selection_path),
            }
            gated = {
                **base,
                "protocol_path": str(protocol_path.resolve()),
                "model_manifest_path": str(model_path.resolve()),
                "threshold": item["threshold"],
                "expected_protocol_sha256": file_hash(protocol_path),
                "expected_model_manifest_hash": item["model_manifest_hash"],
            }
            registries[f"{domain}_fold_{fold}"] = {
                "schema_version": "1.0",
                "freeze_status": "frozen_validation_only",
                "methods": [
                    {
                        "id": name,
                        "factory": "pegh.app.factories:create_static_hybrid_method",
                        "kwargs": {**base, "mode": name},
                        "require_dense_warmup": True,
                    }
                    for name in ("h_star", "s_star")
                ]
                + [
                    {
                        "id": "pe_gh",
                        "factory": "pegh.app.factories:create_gated_method",
                        "kwargs": gated,
                        "require_dense_warmup": False,
                    }
                ],
            }
        frozen["domains"][domain] = domain_record
    frozen["benchmark_registry_hashes"] = {
        key: object_hash(value) for key, value in registries.items()
    }
    frozen["freeze_hash"] = object_hash(frozen)
    output_path = root / args.output
    if output_path.exists():
        raise FileExistsError("freeze manifest already exists; choose a new path")
    for key in registries:
        registries[key]["freeze_hash"] = frozen["freeze_hash"]
    for key, registry in registries.items():
        destination = output_path.parent / "benchmark" / f"{key}.json"
        if destination.exists():
            raise FileExistsError(f"benchmark registry already exists: {destination}")
        atomic_json(destination, registry)
    atomic_json(output_path, frozen)
    print(f"C6 frozen: {frozen['freeze_hash']}")


if __name__ == "__main__":
    main()
