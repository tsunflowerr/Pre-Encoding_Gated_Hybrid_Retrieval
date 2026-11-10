"""Reproduce the fixed protocol with exact sparse acceleration and validation-only execution selection."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path

import yaml

from contracts.io import load_queries
from pegh.data.artifacts import atomic_json, file_hash, object_hash
from pegh.data.splits import fold_record
from pegh.evaluation.runs import load_rankings
from pegh.fusion.engines import CCFusion, RRFFusion
from pegh.profiling.provenance import source_snapshot
from pegh.profiling.report import load_complete_run, summarize_run
from pegh.profiling.runner import run_benchmark
from pegh.profiling.runtime import RuntimeSettings
from pegh.sparse.fast import FORMAT, NumpyBM25, compile_index


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def run(root: Path, script: str, *arguments: str) -> None:
    print(f"Running {script}", flush=True)
    completed = subprocess.run(
        [sys.executable, "-X", "utf8", str(root / script), *map(str, arguments)],
        cwd=root,
        check=False,
    )
    if completed.returncode:
        raise SystemExit(completed.returncode)


def step(root: Path, name: str, script: str, arguments: list[str], outputs: list[Path]) -> None:
    marker = root / "results/completed_steps" / f"{name}.json"
    source_hash = source_snapshot()["combined_sha256"]
    if marker.exists():
        saved = read(marker)
        if saved["source_hash"] != source_hash or any(
            file_hash(root / p) != digest for p, digest in saved["outputs"].items()
        ):
            raise ValueError(f"completed step changed: {name}")
        print(f"Verified completed step {name}", flush=True)
        return
    run(root, script, *arguments)
    if source_snapshot()["combined_sha256"] != source_hash:
        raise ValueError("executable source changed during reproduction")
    atomic_json(
        marker,
        {
            "source_hash": source_hash,
            "outputs": {p.relative_to(root).as_posix(): file_hash(p) for p in outputs},
        },
    )


def copy_checked(source: Path, target: Path, expected: str) -> None:
    if not source.is_file():
        return
    if file_hash(source) != expected:
        raise ValueError(f"cached source checksum differs: {source}")
    if target.is_file():
        if file_hash(target) != expected:
            raise ValueError(f"existing input checksum differs: {target}")
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)


def prepare(root: Path, args) -> None:
    config = yaml.safe_load((root / "configs/data/cqadupstack.yaml").read_text(encoding="utf-8"))[
        "data"
    ]
    for domain, settings in config["domains"].items():
        registered = read(root / "data/manifests" / f"{domain}.json")
        if args.source_cache:
            source = Path(args.source_cache) / domain
            raw = root / "data/raw" / domain
            for name in ("corpus", "queries"):
                copy_checked(
                    source / f"{name}.jsonl",
                    raw / f"{name}.jsonl",
                    settings["expected"][f"{name}_sha256"],
                )
                original = next(f for f in registered["source"]["files"] if f["kind"] == name)
                copy_checked(
                    source / f"{name}.parquet", raw / f"{name}.parquet", original["source_sha256"]
                )
        if args.qrels_root:
            copy_checked(
                Path(args.qrels_root) / domain / "qrels.tsv",
                root / "data/raw" / domain / "qrels.tsv",
                settings["expected"]["qrels_sha256"],
            )
    run(root, "scripts_a/fetch_inputs.py")
    run(root, "scripts_a/prepare_data.py")
    for domain, settings in config["domains"].items():
        sparse = root / "artifacts/sparse" / domain
        if not (sparse / "manifest.json").exists():
            source = Path(args.sparse_root) / domain if args.sparse_root else None
            if source is not None and (source / "manifest.json").is_file():
                source_manifest = read(source / "manifest.json")
                if source_manifest["corpus_sha256"] != settings["expected"]["corpus_sha256"]:
                    raise ValueError("cached sparse corpus differs")
                for name in ("manifest.json", "index.sqlite3"):
                    expected = (
                        source_manifest["database_sha256"]
                        if name.endswith("sqlite3")
                        else file_hash(source / name)
                    )
                    copy_checked(source / name, sparse / name, expected)
            else:
                run(
                    root,
                    "scripts_a/build_sparse.py",
                    "--corpus",
                    f"data/raw/{domain}/corpus.jsonl",
                    "--domain",
                    domain,
                    "--output",
                    str(sparse),
                )
        if not (sparse / FORMAT / "manifest.json").exists():
            compile_index(sparse, sparse / FORMAT)
        with NumpyBM25(sparse):
            pass
        dense = Path(args.dense_root) / domain
        verification = root / f"results/prepare/{domain}-vectors.json"
        if not verification.exists():
            run(
                root,
                "scripts_b/verify_dense_index.py",
                "--index",
                str(dense),
                "--expected-count",
                str(settings["expected"]["documents"]),
                "--output",
                str(verification),
            )
        else:
            receipt = read(verification)
            if receipt["manifest_sha256"] != file_hash(dense / "manifest.json"):
                raise ValueError("saved dense verification is stale")
        for method in ("bm25", "dense"):
            output = root / f"results/quality/{method}/{domain}.jsonl"
            if output.exists():
                meta = read(output.with_suffix(".jsonl.meta.json"))
                if meta["ranking_sha256"] != file_hash(output):
                    raise ValueError("quality cache checksum differs")
                continue
            common = (
                "--queries",
                f"data/raw/{domain}/queries.jsonl",
                "--output",
                str(output),
                "--split",
                "development_validation",
            )
            if method == "bm25":
                run(
                    root,
                    "scripts_a/generate_sparse_runs.py",
                    "--index",
                    str(sparse),
                    "--execution",
                    "numpy",
                    *common,
                )
            else:
                run(
                    root,
                    "scripts_b/generate_dense_runs.py",
                    "--index",
                    str(dense),
                    "--cache-folder",
                    args.cache_folder,
                    "--runtime",
                    args.runtime,
                    *common,
                )


def completed_benchmark(
    root: Path,
    registry: dict,
    queries,
    warmup,
    output: Path,
    settings: RuntimeSettings,
    *,
    split: str,
    fold: int,
    stop_file: str | None,
    restart_incomplete: bool = False,
) -> tuple[dict, list, list]:
    if (output / "manifest.json").is_file():
        recorded = read(output / "manifest.json")
        if recorded["status"] != "complete":
            if not restart_incomplete:
                raise RuntimeError(
                    f"Incomplete run preserved at {output}; use --restart-incomplete to archive and rerun"
                )
            source = output.resolve()
            archive = source.with_name(
                source.name + ".interrupted." + datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
            )
            boundary = (root / "results").resolve()
            if not source.is_relative_to(boundary) or not archive.is_relative_to(boundary):
                raise ValueError("benchmark archive escapes reproduction results")
            source.rename(archive)
            return completed_benchmark(
                root,
                registry,
                queries,
                warmup,
                output,
                settings,
                split=split,
                fold=fold,
                stop_file=stop_file,
            )
        if (
            recorded["registry_hash"] != object_hash(registry["methods"])
            or recorded["settings"] != json.loads(json.dumps(asdict(settings)))
            or recorded["queries_hash"] != object_hash([asdict(q) for q in queries])
            or recorded["source_snapshot"]["combined_sha256"]
            != source_snapshot()["combined_sha256"]
        ):
            raise ValueError("refusing to reuse a benchmark with a different configuration/source")
    else:
        manifest = run_benchmark(
            registry["methods"],
            queries,
            warmup,
            output,
            settings,
            split=split,
            fold=fold,
            stop_file=stop_file,
        )
        if manifest["status"] != "complete":
            raise SystemExit(75)
    summarize_run(output)
    return load_complete_run(output)


def select_execution(root: Path, args) -> Path:
    destination = root / "results/execution_profiles/selection.json"
    if destination.exists():
        report = read(destination)
        if report["source_snapshot_hash"] != source_snapshot()["combined_sha256"]:
            raise ValueError("execution selection source changed")
        if (
            object_hash({k: v for k, v in report.items() if k != "report_hash"})
            != report["report_hash"]
        ):
            raise ValueError("execution selection checksum differs")
        return destination
    split = read(root / "data/splits/manifest.json")
    selection = read(root / "results/fusion/selection_v1.json")
    report = {
        "selection_scope": "validation_timing_only",
        "test_qrels_used": False,
        "source_snapshot_hash": source_snapshot()["combined_sha256"],
        "folds": {},
    }
    settings = replace(
        RuntimeSettings.from_yaml(args.runtime),
        repetitions=args.pilot_repetitions,
        detailed_stages=False,
    )
    for domain in ("programmers", "unix"):
        queries = {
            q.query_id: q for q in load_queries(root / f"data/raw/{domain}/queries.jsonl", domain)
        }
        sparse_rankings, _ = load_rankings(
            root / f"results/quality/bm25/{domain}.jsonl", domain=domain
        )
        dense_rankings, _ = load_rankings(
            root / f"results/quality/dense/{domain}.jsonl", domain=domain
        )
        sparse, dense = root / f"artifacts/sparse/{domain}", Path(args.dense_root) / domain
        with NumpyBM25(sparse) as backend:
            execution_hash = object_hash(backend.execution_provenance)
        for fold in range(5):
            key = f"{domain}_fold_{fold}"
            parts = fold_record(split, fold)["domains"][domain]
            base = {
                "sparse_dir": str(sparse.resolve()),
                "dense_dir": str(dense.resolve()),
                "selection_path": str((root / "results/fusion/selection_v1.json").resolve()),
                "domain": domain,
                "fold": fold,
                "mode": "h_star",
                "expected_sparse_sha256": file_hash(sparse / "index.sqlite3"),
                "expected_dense_sha256": file_hash(dense / "index.faiss"),
                "expected_selection_sha256": file_hash(root / "results/fusion/selection_v1.json"),
                "cache_folder": args.cache_folder,
                "sparse_execution": "numpy",
                "expected_sparse_execution_hash": execution_hash,
            }
            registry = {
                "methods": [
                    {
                        "id": mode,
                        "factory": "pegh.app.factories:create_static_hybrid_method",
                        "kwargs": {**base, "parallel_branches": mode == "parallel"},
                        "require_dense_warmup": True,
                    }
                    for mode in ("sequential", "parallel")
                ]
            }
            output = root / "results/execution_profiles" / key
            _, rows, _ = completed_benchmark(
                root,
                registry,
                [queries[q] for q in parts["validation"]],
                [queries[q] for q in parts["train"]],
                output,
                settings,
                split="validation",
                fold=fold,
                stop_file=args.stop_file,
                restart_incomplete=args.restart_incomplete,
            )
            choice = selection["domains"][domain]["folds"][str(fold)]["h_star"]["method"]
            fusion = (
                CCFusion(float(choice.removeprefix("cc_alpha_")))
                if choice.startswith("cc_alpha_")
                else RRFFusion(60)
            )
            expected = {
                qid: object_hash(
                    [
                        h.doc_id
                        for h in fusion.fuse(sparse_rankings[qid], dense_rankings[qid], k=100).hits
                    ]
                )
                for qid in parts["validation"]
            }
            verified = {
                mode: all(
                    r["ranking_hash"] == expected[r["query_id"]]
                    for r in rows
                    if r["method"] == mode
                )
                for mode in ("sequential", "parallel")
            }
            if not verified["sequential"]:
                raise ValueError("validation sequential baseline differs from frozen quality cache")
            summary = read(output / "summary.json")
            means = {s["method"]: s["mean_ms"] for s in summary["summaries"]}
            selected = min((m for m in means if verified[m]), key=means.__getitem__)
            report["folds"][key] = {
                "selected": selected,
                "mean_ms": means,
                "ranking_identity_passed": verified,
                "run_manifest_sha256": file_hash(output / "manifest.json"),
            }
            print(f"Validation execution {key}: {selected} {means}", flush=True)
    report["report_hash"] = object_hash(report)
    atomic_json(destination, report)
    return destination


def train(root: Path, args) -> None:
    outputs = {
        "select_fusion": "results/fusion/selection_v1.json",
        "materialize_features": "results/features/schema_v1.json",
        "build_training_tables": "results/training/c3_manifest.json",
        "train_gates": "results/models/c4_manifest.json",
        "select_thresholds": "results/thresholds/c6_validation.json",
    }
    for script, output in outputs.items():
        step(root, script, f"scripts_c/{script}.py", [], [root / output])
    execution = select_execution(root, args)
    step(
        root,
        "freeze",
        "scripts_c/freeze_c6.py",
        [
            "--dense-root",
            args.dense_root,
            "--cache-folder",
            args.cache_folder,
            "--sparse-execution",
            "numpy",
            "--execution-selection",
            str(execution),
        ],
        [root / "results/frozen/c6_manifest.json"],
    )


def quality_registry(root: Path, methods: list[str]) -> Path:
    freeze = read(root / "results/frozen/c6_manifest.json")
    registry = {
        "schema_version": "1.0",
        "freeze_hash": freeze["freeze_hash"],
        "split_manifest": str(root / "data/splits/manifest.json"),
        "domains": {},
        "utilities": [
            {"name": "h_star_gain", "baseline": "bm25", "candidate": "h_star"},
            {"name": "pe_gh_vs_s_star", "baseline": "s_star", "candidate": "pe_gh"},
        ],
        "comparison": {"baseline": "s_star", "candidate": "pe_gh", "metric": "ndcg_at_10"},
    }
    for domain in ("programmers", "unix"):
        registry["domains"][domain] = {
            "dataset_manifest": str(root / f"data/manifests/{domain}.json"),
            "queries": str(root / f"data/raw/{domain}/queries.jsonl"),
            "qrels": str(root / f"data/raw/{domain}/qrels.tsv"),
            "runs": {
                method: {
                    str(fold): str(
                        root
                        / "results/oof_runs"
                        / ("release_bm25" if method == "bm25" else method)
                        / domain
                        / f"fold_{fold}.jsonl"
                    )
                    for fold in range(5)
                }
                for method in methods
            },
        }
    output = root / f"results/frozen/oof_{len(methods)}_methods.json"
    atomic_json(output, registry)
    return output


def quality(root: Path, args) -> None:
    step(
        root,
        "export_primary",
        "scripts_c/export_c6_runs.py",
        [],
        [
            root / f"results/oof_runs/{method}/{domain}/fold_{fold}.jsonl.meta.json"
            for method in ("h_star", "s_star", "pe_gh")
            for domain in ("programmers", "unix")
            for fold in range(5)
        ],
    )
    for domain in ("programmers", "unix"):
        step(
            root,
            f"materialize_bm25_{domain}",
            "scripts_a/materialize_fold_runs.py",
            [
                "--run",
                f"results/quality/bm25/{domain}.jsonl",
                "--split-manifest",
                "data/splits/manifest.json",
                "--domain",
                domain,
                "--method",
                "bm25",
                "--output",
                f"results/oof_runs/release_bm25/{domain}",
                "--run-id-prefix",
                f"release-bm25-{domain}",
                "--reuse-identical",
            ],
            [
                root / f"results/oof_runs/release_bm25/{domain}/fold_{fold}.jsonl.meta.json"
                for fold in range(5)
            ],
        )
    primary = ["bm25", "h_star", "s_star", "pe_gh"]
    step(
        root,
        "evaluate_primary",
        "scripts_a/run_final_oof.py",
        ["--registry", str(quality_registry(root, primary)), "--output", "results/oof/c6_final"],
        [root / "results/oof/c6_final/summary.json", root / "results/oof/c6_final/per_query.csv"],
    )
    step(
        root,
        "export_controls",
        "scripts_c/export_c6_controls.py",
        [],
        [
            root / f"results/oof_runs/dense/{domain}/fold_{fold}.jsonl.meta.json"
            for domain in ("programmers", "unix")
            for fold in range(5)
        ],
    )
    controls = sorted(p.name for p in (root / "results/oof_runs").iterdir() if p.is_dir())
    if len(controls) != 14:
        raise ValueError("all fourteen registered methods are required")
    step(
        root,
        "evaluate_controls",
        "scripts_a/run_final_oof.py",
        [
            "--registry",
            str(quality_registry(root, controls)),
            "--output",
            "results/oof/c6_controls",
        ],
        [root / "results/oof/c6_controls/summary.json"],
    )
    step(
        root,
        "quality_diagnostics",
        "scripts_c/report_c6_diagnostics.py",
        [],
        [root / "results/oof/c6_final/random30_oracle.json"],
    )


def online(root: Path, args) -> None:
    frozen = read(root / "results/frozen/c6_manifest.json")
    if frozen["source_snapshot_hash"] != source_snapshot()["combined_sha256"]:
        raise ValueError("source changed after freeze")
    settings = RuntimeSettings.from_yaml(args.runtime)
    for domain in ("programmers", "unix"):
        for fold in range(5):
            key = f"{domain}_fold_{fold}"
            registry = read(root / f"results/frozen/benchmark/{key}.json")
            if (
                object_hash({k: v for k, v in registry.items() if k != "freeze_hash"})
                != frozen["benchmark_registry_hashes"][key]
            ):
                raise ValueError("frozen benchmark registry changed")
            paths = {
                name: root / f"results/frozen/benchmark_inputs/{key}_{name}.jsonl"
                for name in ("test", "warmup")
            }
            for name, path in paths.items():
                if file_hash(path) != frozen["benchmark_inputs"][key][name]["sha256"]:
                    raise ValueError("frozen benchmark query inputs changed")
            queries, warmup = (load_queries(paths[name], domain) for name in ("test", "warmup"))
            if domain == "programmers" and fold == 0:
                completed_benchmark(
                    root,
                    registry,
                    queries,
                    warmup,
                    root / "results/benchmark/c6_programmers_fold_0",
                    replace(settings, repetitions=1, detailed_stages=True),
                    split="test",
                    fold=fold,
                    stop_file=args.stop_file,
                    restart_incomplete=args.restart_incomplete,
                )
            completed_benchmark(
                root,
                registry,
                queries,
                warmup,
                root / f"results/benchmark/c6_full/{key}",
                replace(settings, repetitions=5, detailed_stages=False),
                split="test",
                fold=fold,
                stop_file=args.stop_file,
                restart_incomplete=args.restart_incomplete,
            )
            print(f"Complete final benchmark {key}", flush=True)


def report(root: Path, args) -> None:
    run(
        root,
        "scripts_c/report_gating.py",
        "--figure-dir",
        "results/reports/figures",
        "--facts-output",
        "results/reports/release-facts.json",
    )
    run(root, "scripts_shared/report_release.py")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--stage", choices=("prepare", "train", "quality", "online", "report", "all"), default="all"
    )
    parser.add_argument("--dense-root", required=True)
    parser.add_argument("--cache-folder", required=True)
    parser.add_argument("--source-cache")
    parser.add_argument("--qrels-root")
    parser.add_argument("--sparse-root")
    parser.add_argument("--runtime", default="configs/runtime/cpu4.yaml")
    parser.add_argument("--pilot-repetitions", type=int, default=2)
    parser.add_argument("--stop-file")
    parser.add_argument("--restart-incomplete", action="store_true")
    args = parser.parse_args()
    if args.pilot_repetitions < 1:
        raise ValueError("pilot repetitions must be positive")
    root = Path.cwd().resolve()
    identity = {
        "source_snapshot_hash": source_snapshot()["combined_sha256"],
        "runtime_sha256": file_hash(root / args.runtime),
        "dense_manifest_sha256": {
            domain: file_hash(Path(args.dense_root) / domain / "manifest.json")
            for domain in ("programmers", "unix")
        },
        "pilot_repetitions": args.pilot_repetitions,
    }
    identity_path = root / "results/reproduction_identity.json"
    if identity_path.exists() and read(identity_path) != identity:
        raise ValueError(
            "reproduction source/config/artifacts changed; choose a fresh workspace/results directory"
        )
    if not identity_path.exists():
        atomic_json(identity_path, identity)
    actions = {
        "prepare": prepare,
        "train": train,
        "quality": quality,
        "online": online,
        "report": report,
    }
    stages = actions if args.stage == "all" else [args.stage]
    for stage in stages:
        atomic_json(
            root / "results/pipeline_status.json",
            {
                "phase": stage,
                "status": "running",
                "updated_at_utc": datetime.now(UTC).isoformat(),
                "source_snapshot_hash": source_snapshot()["combined_sha256"],
            },
        )
        try:
            actions[stage](root, args)
        except BaseException as error:
            atomic_json(
                root / "results/pipeline_status.json",
                {
                    "phase": stage,
                    "status": "paused"
                    if isinstance(error, SystemExit) and error.code == 75
                    else "failed",
                    "error": str(error),
                    "updated_at_utc": datetime.now(UTC).isoformat(),
                    "source_snapshot_hash": source_snapshot()["combined_sha256"],
                },
            )
            raise
        atomic_json(
            root / "results/pipeline_status.json",
            {
                "phase": stage,
                "status": "complete",
                "updated_at_utc": datetime.now(UTC).isoformat(),
                "source_snapshot_hash": source_snapshot()["combined_sha256"],
            },
        )


if __name__ == "__main__":
    main()
