"""Freeze C6 methods, thresholds, indexes, source, and B benchmark registries."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from contracts.io import load_queries
from pegh.data.artifacts import atomic_json, file_hash, object_hash, write_jsonl
from pegh.data.splits import fold_record
from pegh.gating.models import load_model
from pegh.profiling.provenance import source_snapshot
from pegh.profiling.report import load_complete_run
from pegh.sparse.fast import open_backend


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--thresholds", default="results/thresholds/c6_validation.json")
    parser.add_argument("--output", default="results/frozen/c6_manifest.json")
    parser.add_argument("--dense-root", default=str(Path.home() / ".cache/pegh/artifacts/c0-v1"))
    parser.add_argument("--cache-folder", default="artifacts/models")
    parser.add_argument("--sparse-execution", choices=("numpy", "sqlite"), default="numpy")
    parser.add_argument(
        "--execution-selection",
        help="Validation-only sequential/parallel baseline timing selection",
    )
    args = parser.parse_args()
    root = Path.cwd()
    output_path = root / args.output
    if output_path.exists():
        raise FileExistsError("freeze manifest already exists; choose a new path")
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
        "benchmark_inputs": {},
    }
    execution_selection = None
    if args.execution_selection:
        selection_file = Path(args.execution_selection)
        execution_selection = json.loads(selection_file.read_text(encoding="utf-8"))
        if (
            execution_selection["selection_scope"] != "validation_timing_only"
            or execution_selection["source_snapshot_hash"] != source_snapshot()["combined_sha256"]
        ):
            raise ValueError(
                "execution profile must be selected on validation with the current source"
            )
        if (
            execution_selection["test_qrels_used"]
            or object_hash({k: v for k, v in execution_selection.items() if k != "report_hash"})
            != execution_selection["report_hash"]
        ):
            raise ValueError("execution selection checksum/scope differs")
        frozen["execution_selection_sha256"] = file_hash(selection_file)
    registries = {}
    for domain in ("programmers", "unix"):
        queries = {
            q.query_id: q for q in load_queries(root / f"data/raw/{domain}/queries.jsonl", domain)
        }
        sparse_dir = (root / "artifacts/sparse" / domain).resolve()
        dense_dir = (Path(args.dense_root) / domain).resolve()
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
        with open_backend(sparse_dir, execution=args.sparse_execution) as sparse_backend:
            sparse_execution = sparse_backend.execution_provenance
        if (
            sparse_sha != sparse_manifest["database_sha256"]
            or dense_sha != dense_manifest["index_sha256"]
        ):
            raise ValueError("index checksum differs from manifest")
        domain_record = {
            "corpus_sha256": corpus_hash,
            "sparse_index_sha256": sparse_sha,
            "dense_index_sha256": dense_sha,
            "sparse_execution": sparse_execution,
            "sparse_run_sha256": file_hash(root / f"results/quality/bm25/{domain}.jsonl"),
            "dense_run_sha256": file_hash(root / f"results/quality/dense/{domain}.jsonl"),
            "folds": {},
        }
        for fold in range(5):
            parts = fold_record(split, fold)["domains"][domain]
            if execution_selection:
                key = f"{domain}_fold_{fold}"
                record = execution_selection["folds"][key]
                run_dir = root / "results/execution_profiles" / key
                profile_manifest, rows, _ = load_complete_run(run_dir)
                if (
                    file_hash(run_dir / "manifest.json") != record["run_manifest_sha256"]
                    or profile_manifest["split"] != "validation"
                    or {r["query_id"] for r in rows} != set(parts["validation"])
                ):
                    raise ValueError(
                        "execution profile must cover exactly this fold's validation queries"
                    )
                means = {
                    name: sum(r["total_ns"] / 1e6 for r in rows if r["method"] == name)
                    / sum(r["method"] == name for r in rows)
                    for name in ("sequential", "parallel")
                }
                allowed = [name for name in means if record["ranking_identity_passed"][name]]
                if record["selected"] != min(allowed, key=means.__getitem__):
                    raise ValueError("execution profile did not select the faster valid baseline")
            inputs = {}
            for role, name in (("test", "test"), ("validation", "warmup")):
                destination = (
                    output_path.parent / "benchmark_inputs" / f"{domain}_fold_{fold}_{name}.jsonl"
                )
                if destination.exists():
                    raise FileExistsError(f"benchmark input already exists: {destination}")
                selected_queries = [queries[qid] for qid in parts[role]]
                write_jsonl(
                    destination, ({"_id": q.query_id, "text": q.text} for q in selected_queries)
                )
                inputs[name] = {
                    "sha256": file_hash(destination),
                    "queries_hash": object_hash([asdict(q) for q in selected_queries]),
                }
            frozen["benchmark_inputs"][f"{domain}_fold_{fold}"] = inputs
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
                "static_execution": execution_selection["folds"][f"{domain}_fold_{fold}"][
                    "selected"
                ]
                if execution_selection
                else "sequential",
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
                "sparse_execution": args.sparse_execution,
                "expected_sparse_execution_hash": object_hash(sparse_execution),
                "cache_folder": str(Path(args.cache_folder).resolve()),
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
                        "kwargs": {
                            **base,
                            "mode": name,
                            "parallel_branches": item["static_execution"] == "parallel",
                        },
                        "require_dense_warmup": True,
                    }
                    for name in ("h_star", "s_star")
                ]
                + [
                    {
                        "id": "pe_gh",
                        "factory": "pegh.app.factories:create_gated_method",
                        "kwargs": gated,
                        "require_dense_warmup": picked["selected_actual_dense_ratio"] > 0,
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
