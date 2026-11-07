"""Frozen, validation-only domain-threshold experiment; existing-test reassessment is exploratory."""

from __future__ import annotations

import argparse
import copy
import json
import time
from collections import defaultdict
from dataclasses import replace
from pathlib import Path

import numpy as np

from contracts.io import load_queries
from contracts.ranking import ranking_to_record
from contracts.types import FeatureVector
from pegh.data.artifacts import atomic_json, file_hash, object_hash, write_jsonl
from pegh.data.splits import fold_record
from pegh.evaluation.runs import load_rankings
from pegh.gating.models import load_model
from pegh.gating.selection import select_domain_thresholds
from pegh.profiling.provenance import source_snapshot
from pegh.profiling.report import load_complete_run
from pegh.profiling.runtime import RuntimeSettings
from scripts_c.train_gates import _read_table
from scripts_shared.report_release import paired_speedups
from scripts_shared.reproduce import completed_benchmark, run

DOMAINS = ("programmers", "unix")
METHODS = ("h_star", "pe_v1", "pe_v2")
SCOPE = "exploratory_reassessment_of_previously_observed_test_not_fresh_confirmation"


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def lines(path: Path) -> list[dict]:
    return [json.loads(s) for s in path.read_text(encoding="utf-8").splitlines() if s]


def signed(path: Path, key: str) -> dict:
    value = read(path)
    if object_hash({k: v for k, v in value.items() if k != key}) != value[key]:
        raise ValueError(f"checksum differs: {path}")
    return value


def parity(base: Path, output: Path) -> dict:
    checked, maximum = 0, 0.0
    sample = None
    for domain in DOMAINS:
        features = lines(base / f"results/features/{domain}.jsonl")
        for fold in range(5):
            for path in sorted(
                (base / f"results/models/fold_{fold}/{domain}").glob("*/manifest.json")
            ):
                model = load_model(path)
                general = model.manifest["feature_set"] == "general"
                for row in features:
                    vector = FeatureVector(
                        tuple(row["general_values" if general else "values"]),
                        model.manifest["feature_schema_hash"],
                    )
                    fast, original = (
                        model.predict_score(vector),
                        model.predict_score_reference(vector),
                    )
                    maximum = max(maximum, abs(fast - original))
                    if fast != original:
                        raise ValueError(
                            "linear inference must be bit-exact, including threshold ties"
                        )
                    checked += 1
                    if sample is None and not general:
                        sample = model, vector
    model, vector = sample
    durations = defaultdict(list)
    for repetition in range(5):
        order = ("sklearn", "numpy") if repetition % 2 == 0 else ("numpy", "sklearn")
        for execution in order:
            call = model.predict_score_reference if execution == "sklearn" else model.predict_score
            for _ in range(100):
                call(vector)
            start = time.perf_counter_ns()
            for _ in range(2000):
                call(vector)
            durations[execution].append((time.perf_counter_ns() - start) / 2000 / 1000)
    result = {
        "checked_scores": checked,
        "maximum_absolute_error": maximum,
        "bit_exact": True,
        "inference_only_microseconds_per_call": dict(durations),
        "not_request_latency_benchmark": True,
        "implementation_sha256": file_hash(Path.cwd() / "src/pegh/gating/models.py"),
    }
    atomic_json(output / "parity.json", result)
    return result


def freeze(base: Path, output: Path, runtime: Path, policy: str) -> None:
    destination = output / "freeze.json"
    if destination.exists():
        raise FileExistsError("choose a fresh refinement directory")
    baseline = signed(base / "results/frozen/c6_manifest.json", "freeze_hash")
    original = signed(base / "results/thresholds/c6_validation.json", "report_hash")
    split = read(Path.cwd() / "data/splits/manifest.json")
    if file_hash(Path.cwd() / "data/splits/manifest.json") != baseline["split_manifest_sha256"]:
        raise ValueError("base split changed")
    c3 = signed(base / "results/training/c3_manifest.json", "manifest_hash")
    entries = {(r["fold"], r["domain"], r["split_role"]): r for r in c3["artifacts"]}
    result = {
        "schema_version": "domain_refinement_v2",
        "policy": policy,
        "selection_scope": "validation_only",
        "test_qrels_used_for_selection": False,
        "evaluation_scope": SCOPE,
        "source_snapshot_hash": source_snapshot()["combined_sha256"],
        "base_freeze_hash": baseline["freeze_hash"],
        "base_freeze_sha256": file_hash(base / "results/frozen/c6_manifest.json"),
        "runtime_sha256": file_hash(runtime),
        "folds": {},
        "inputs": {},
    }
    for fold in range(5):
        old = original["folds"][str(fold)]["ridge_gain_full"]
        groups, diagnostics = {}, {}
        for domain in DOMAINS:
            parts = fold_record(split, fold)["domains"][domain]
            labels, _ = _read_table(
                base, entries[(fold, domain, "validation")], parts["validation"]
            )
            path = base / f"results/models/fold_{fold}/{domain}/ridge_gain_full/validation.jsonl"
            meta = read(path.with_suffix(".jsonl.meta.json"))
            model = signed(path.parent / "manifest.json", "manifest_hash")
            predictions = lines(path)
            scores = {r["query_id"]: r["score"] for r in predictions}
            if (
                file_hash(path) != meta["prediction_sha256"]
                or len(scores) != len(predictions)
                or set(scores) != set(parts["validation"])
                or any(r["model_manifest_hash"] != model["manifest_hash"] for r in predictions)
            ):
                raise ValueError("validation prediction provenance differs")
            groups[domain] = [
                {
                    "score": scores[r["query_id"]],
                    "force_dense": r["x_02"] == 0 or r["x_13"] == 1,
                    "U_B": r["U_B"],
                    "U_H": r["U_H"],
                }
                for r in labels
            ]
            s = np.array([scores[r["query_id"]] for r in labels])
            gain = np.array([r["delta_U"] for r in labels])
            diagnostics[domain] = {
                "mean_score": float(s.mean()),
                "std_score": float(s.std()),
                "score_gain_correlation": float(np.corrcoef(s, gain)[0, 1]),
                "zero_gain_ratio": float(np.mean(gain == 0)),
                "error_identifier_ratio": sum(r["x_07"] > 0 for r in labels) / len(labels),
                "path_flag_ratio": sum(r["x_08"] > 0 for r in labels) / len(labels),
            }
            for source in (
                path,
                path.with_suffix(".jsonl.meta.json"),
                path.parent / "manifest.json",
                base / entries[(fold, domain, "validation")]["path"],
            ):
                result["inputs"][str(source)] = file_hash(source)
        selection = select_domain_thresholds(groups, old["selected_threshold"])
        result["folds"][str(fold)] = {
            "selection": selection,
            "diagnostics": diagnostics,
            "old_shared_threshold": old["selected_threshold"],
            "registries": {},
            "query_files": {},
        }
        for domain in DOMAINS:
            key = f"{domain}_fold_{fold}"
            path = base / f"results/frozen/benchmark/{key}.json"
            registry = read(path)
            if (
                object_hash({k: v for k, v in registry.items() if k != "freeze_hash"})
                != baseline["benchmark_registry_hashes"][key]
            ):
                raise ValueError("base online registry changed")
            reference = copy.deepcopy(next(m for m in registry["methods"] if m["id"] == "pe_gh"))
            reference["id"] = "pe_v1"
            reference["kwargs"]["score_execution"] = "sklearn"
            candidate = copy.deepcopy(reference)
            candidate["id"] = "pe_v2"
            candidate["kwargs"].update(
                score_execution="numpy",
                threshold=selection["domains"][domain]["threshold"]
                if policy == "domain_threshold"
                else old["selected_threshold"],
            )
            methods = [
                next(m for m in registry["methods"] if m["id"] == "h_star"),
                reference,
                candidate,
            ]
            result["folds"][str(fold)]["registries"][domain] = {"methods": methods}
            inputs = {}
            for role in ("test", "warmup"):
                source = base / f"results/frozen/benchmark_inputs/{key}_{role}.jsonl"
                if file_hash(source) != baseline["benchmark_inputs"][key][role]["sha256"]:
                    raise ValueError("base benchmark queries changed")
                inputs[role] = {"path": str(source), "sha256": file_hash(source)}
            result["folds"][str(fold)]["query_files"][domain] = inputs
    for domain in DOMAINS:
        consumed = [
            base / f"data/raw/{domain}/queries.jsonl",
            base / f"data/raw/{domain}/qrels.tsv",
            base / f"results/features/{domain}.jsonl",
            base / f"results/features/{domain}.jsonl.meta.json",
            Path.cwd() / f"data/manifests/{domain}.json",
        ]
        for fold in range(5):
            for method in ("bm25", "h_star", "pe_gh"):
                path = base / f"results/oof_runs/{method}/{domain}/fold_{fold}.jsonl"
                consumed.extend((path, path.with_suffix(".jsonl.meta.json")))
        result["inputs"].update({str(p): file_hash(p) for p in consumed})
    result["inputs"][str(Path.cwd() / "data/splits/manifest.json")] = file_hash(
        Path.cwd() / "data/splits/manifest.json"
    )
    parity(base, output)
    if source_snapshot()["combined_sha256"] != result["source_snapshot_hash"]:
        raise ValueError("source changed during selection/parity")
    result["parity_sha256"] = file_hash(output / "parity.json")
    result["freeze_hash"] = object_hash(result)
    atomic_json(destination, result)
    print("Frozen validation-only refinement", result["freeze_hash"], flush=True)


def quality(base: Path, output: Path, frozen: dict) -> None:
    split = read(Path.cwd() / "data/splits/manifest.json")
    registry = {
        "schema_version": "1.0",
        "freeze_hash": frozen["freeze_hash"],
        "split_manifest": str(Path.cwd() / "data/splits/manifest.json"),
        "domains": {},
        "comparison": {"baseline": "h_star", "candidate": "pe_v2", "metric": "ndcg_at_10"},
    }
    for domain in DOMAINS:
        features = {r["query_id"]: r for r in lines(base / f"results/features/{domain}.jsonl")}
        registry["domains"][domain] = {
            "dataset_manifest": str(Path.cwd() / f"data/manifests/{domain}.json"),
            "queries": str(base / f"data/raw/{domain}/queries.jsonl"),
            "qrels": str(base / f"data/raw/{domain}/qrels.tsv"),
            "runs": {m: {} for m in (*METHODS, "bm25")},
        }
        for fold in range(5):
            ids = fold_record(split, fold)["domains"][domain]["test"]
            reference, _ = load_rankings(
                base / f"results/oof_runs/pe_gh/{domain}/fold_{fold}.jsonl", domain=domain
            )
            h_star, _ = load_rankings(
                base / f"results/oof_runs/h_star/{domain}/fold_{fold}.jsonl", domain=domain
            )
            sparse, _ = load_rankings(
                base / f"results/oof_runs/bm25/{domain}/fold_{fold}.jsonl", domain=domain
            )
            kwargs = frozen["folds"][str(fold)]["registries"][domain]["methods"][2]["kwargs"]
            model = load_model(kwargs["model_manifest_path"])
            scores = {
                qid: model.predict_score(
                    FeatureVector(
                        tuple(features[qid]["values"]), features[qid]["feature_schema_hash"]
                    )
                )
                for qid in ids
            }
            decisions = {
                qid: features[qid]["values"][1] == 0
                or features[qid]["values"][12] == 1
                or scores[qid] > kwargs["threshold"]
                for qid in ids
            }
            if frozen["policy"] == "score_only" and any(
                (h_star[qid] if decisions[qid] else sparse[qid]).hits != reference[qid].hits
                for qid in ids
            ):
                raise ValueError("score-only optimization changed a frozen ranking")
            for method in (*METHODS, "bm25"):
                rankings = (
                    h_star if method == "h_star" else reference if method == "pe_v1" else sparse
                )
                digest = object_hash(
                    {
                        "freeze": frozen["freeze_hash"],
                        "method": method,
                        "domain": domain,
                        "fold": fold,
                    }
                )
                records = [
                    ranking_to_record(
                        replace(
                            (h_star[qid] if decisions[qid] else sparse[qid])
                            if method == "pe_v2"
                            else rankings[qid],
                            retriever_hash=digest,
                        ),
                        method=method,
                        split="test",
                        fold=fold,
                        run_id=f"refine-{method}-{domain}-{fold}",
                    )
                    for qid in ids
                ]
                path = output / f"oof_runs/{method}/{domain}/fold_{fold}.jsonl"
                if path.exists():
                    raise FileExistsError(
                        "quality exports already exist; use a fresh output directory"
                    )
                write_jsonl(path, records)
                dense_count = (
                    sum(decisions.values())
                    if method == "pe_v2"
                    else read(
                        base / f"results/oof_runs/pe_gh/{domain}/fold_{fold}.jsonl.meta.json"
                    )["dense_count"]
                    if method == "pe_v1"
                    else len(ids)
                    if method == "h_star"
                    else 0
                )
                atomic_json(
                    path.with_suffix(".jsonl.meta.json"),
                    {
                        "schema_version": "1.0",
                        "ranking_sha256": file_hash(path),
                        "query_ids_hash": object_hash(ids),
                        "query_count": len(ids),
                        "split_hash": split["split_hash"],
                        "domain": domain,
                        "method": method,
                        "fold": fold,
                        "split": "test",
                        "run_id": records[0]["run_id"],
                        "corpus_hash": records[0]["corpus_hash"],
                        "retriever_hash": digest,
                        "freeze_hash": frozen["freeze_hash"],
                        "dense_count": dense_count,
                        "dense_ratio": dense_count / len(ids),
                        "evaluation_scope": SCOPE,
                    },
                )
                registry["domains"][domain]["runs"][method][str(fold)] = str(path)
    path = output / "quality_registry.json"
    atomic_json(path, registry)
    run(
        Path.cwd(),
        "scripts_a/run_final_oof.py",
        "--registry",
        str(path),
        "--output",
        str(output / "quality"),
    )
    registry["comparison"]["baseline"] = "pe_v1"
    path = output / "quality_registry_v1_comparison.json"
    atomic_json(path, registry)
    run(
        Path.cwd(),
        "scripts_a/run_final_oof.py",
        "--registry",
        str(path),
        "--output",
        str(output / "quality_vs_v1"),
    )


def online(output: Path, frozen: dict, runtime: Path, args) -> None:
    if file_hash(runtime) != frozen["runtime_sha256"]:
        raise ValueError("runtime changed after freeze")
    settings = replace(RuntimeSettings.from_yaml(runtime), detailed_stages=False, repetitions=5)
    for domain in DOMAINS:
        for fold in range(5):
            info = frozen["folds"][str(fold)]
            paths = info["query_files"][domain]
            for item in paths.values():
                if file_hash(item["path"]) != item["sha256"]:
                    raise ValueError("frozen query file changed")
            completed_benchmark(
                output,
                info["registries"][domain],
                load_queries(paths["test"]["path"], domain),
                load_queries(paths["warmup"]["path"], domain),
                output / f"results/benchmark/{domain}_fold_{fold}",
                settings,
                split="test",
                fold=fold,
                stop_file=args.stop_file,
                restart_incomplete=args.restart_incomplete,
            )
            print("Completed refinement", domain, fold, flush=True)


def report(output: Path, frozen: dict) -> None:
    quality_report = read(output / "quality/summary.json")
    grouped = defaultdict(list)
    peaks = defaultdict(list)
    conditions = set()
    for domain in DOMAINS:
        for fold in range(5):
            directory = output / f"results/benchmark/{domain}_fold_{fold}"
            manifest, rows, receipts = load_complete_run(directory)
            if manifest["source_snapshot"]["combined_sha256"] != frozen["source_snapshot_hash"]:
                raise ValueError("online source differs from freeze")
            if manifest["registry_hash"] != object_hash(
                frozen["folds"][str(fold)]["registries"][domain]["methods"]
            ):
                raise ValueError("online registry differs")
            for method in METHODS:
                offline = lines(output / f"oof_runs/{method}/{domain}/fold_{fold}.jsonl")
                expected = {
                    r["query_id"]: object_hash([h["doc_id"] for h in r["hits"]]) for r in offline
                }
                measured = [r for r in rows if r["method"] == method]
                meta = read(output / f"oof_runs/{method}/{domain}/fold_{fold}.jsonl.meta.json")
                if (
                    any(
                        r["ranking_hash"] != expected[r["query_id"]]
                        or r["stage_calls"]["sparse"] != 1
                        for r in measured
                    )
                    or sum(r["encoder_calls"] for r in measured) != meta["dense_count"] * 5
                ):
                    raise ValueError("online rankings/counters differ from frozen quality")
                grouped[(domain, method)].extend(measured)
                peaks[(domain, method)].extend(
                    r["memory"]["os_peak_rss_bytes"] or r["memory"]["sampled_peak_rss_bytes"]
                    for r in receipts
                    if r["method"] == method
                )
            for receipt in receipts:
                conditions.add(
                    object_hash(
                        {
                            k: receipt["runtime"][k]
                            for k in ("platform", "processor", "resources", "package_versions")
                        }
                    )
                )
    if len(conditions) != 1:
        raise ValueError("hardware/resource/package conditions differed across runs")
    summaries, arrays = {}, {}
    for domain in (*DOMAINS, "all"):
        summaries[domain] = {}
        for method in METHODS:
            rows = (
                grouped[(domain, method)]
                if domain != "all"
                else [r for d in DOMAINS for r in grouped[(d, method)]]
            )
            latencies = np.array([r["total_ns"] / 1e6 for r in rows])
            summaries[domain][method] = {
                "mean_ms": float(latencies.mean()),
                "p95_ms": float(np.quantile(latencies, 0.95)),
                "dense_ratio": sum(r["encoder_calls"] for r in rows) / len(rows),
                "requests": len(rows),
                "peak_rss_bytes": max(peaks[(domain, method)])
                if domain != "all"
                else max(v for d in DOMAINS for v in peaks[(d, method)]),
            }
        if domain != "all":
            per_query = {}
            for method in METHODS:
                values = defaultdict(list)
                for row in grouped[(domain, method)]:
                    values[row["query_id"]].append(row["total_ns"] / 1e6)
                if any(len(v) != 5 for v in values.values()):
                    raise ValueError("missing query timing repeats")
                per_query[method] = {q: np.mean(v) for q, v in values.items()}
            ids = sorted(per_query["h_star"])
            arrays[domain] = np.array([[per_query[m][q] for m in METHODS] for q in ids])
    result = {
        "evaluation_scope": SCOPE,
        "freeze_hash": frozen["freeze_hash"],
        "source_snapshot_hash": frozen["source_snapshot_hash"],
        "online_rankings_verified": sum(len(v) for v in grouped.values()),
        "policy": frozen["policy"],
        "summaries": summaries,
        "paired_speedup_v2_vs_h_star_and_v1": paired_speedups(
            arrays, baseline_names=("h_star", "pe_v1")
        ),
        "quality": quality_report["summaries"],
        "quality_vs_h_star": quality_report["comparison"],
        "quality_vs_v1": read(output / "quality_vs_v1/comparison.json"),
    }
    result["report_hash"] = object_hash(result)
    atomic_json(output / "report.json", result)
    print(json.dumps(result["summaries"]["all"], indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", required=True, choices=("freeze", "quality", "online", "report"))
    parser.add_argument("--base-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--runtime", type=Path, default=Path("configs/runtime/cpu4.yaml"))
    parser.add_argument("--stop-file")
    parser.add_argument("--restart-incomplete", action="store_true")
    parser.add_argument(
        "--policy", choices=("score_only", "domain_threshold"), default="score_only"
    )
    args = parser.parse_args()
    base, output = args.base_root.resolve(), args.output_root.resolve()
    if output == base or output.is_relative_to(base / "results"):
        raise ValueError("refinement must use a separate output directory")
    output.mkdir(parents=True, exist_ok=True)
    if args.stage == "freeze":
        freeze(base, output, args.runtime, args.policy)
        return
    frozen = signed(output / "freeze.json", "freeze_hash")
    if frozen["policy"] != args.policy:
        raise ValueError("policy differs from the frozen experiment")
    if source_snapshot()["combined_sha256"] != frozen["source_snapshot_hash"]:
        raise ValueError("source changed after refinement freeze")
    if any(file_hash(path) != digest for path, digest in frozen["inputs"].items()):
        raise ValueError("validation inputs changed after freeze")
    {
        "quality": lambda: quality(base, output, frozen),
        "online": lambda: online(output, frozen, args.runtime, args),
        "report": lambda: report(output, frozen),
    }[args.stage]()


if __name__ == "__main__":
    main()
