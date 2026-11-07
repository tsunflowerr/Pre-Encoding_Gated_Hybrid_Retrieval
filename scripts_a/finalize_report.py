"""Build A's final tables, figures and routing cases from preserved, verified experiment outputs."""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

from contracts.io import load_queries
from pegh.data.artifacts import atomic_json, file_hash, object_hash, write_jsonl
from pegh.data.qrels import load_qrels, positive_qrels
from pegh.data.splits import fold_record
from pegh.evaluation.failures import outcome, select_cases
from pegh.evaluation.quality_plot import plot_quality
from pegh.evaluation.runs import load_rankings
from pegh.gating.features import FEATURE_NAMES
from pegh.profiling.report import load_complete_run


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def check_hash(path: Path, expected: str) -> None:
    if file_hash(path) != expected:
        raise ValueError(f"input checksum differs: {path}")


def check_object(value: dict, field: str) -> None:
    if object_hash({k: v for k, v in value.items() if k != field}) != value[field]:
        raise ValueError(f"{field} differs from report contents")


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def build_report(root: Path, output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    inputs = {}

    def register(path: Path) -> Path:
        inputs[path.relative_to(root).as_posix()] = file_hash(path)
        return path

    freeze = read(register(root / "results/frozen/c6_manifest.json"))
    release = read(register(root / "results/reports/integration_release.json"))
    facts = read(register(root / "results/reports/c7_report.json"))
    for value, field in ((freeze, "freeze_hash"), (release, "report_hash"), (facts, "report_hash")):
        check_object(value, field)
    if not freeze["freeze_hash"] == release["freeze_hash"] == facts["freeze_hash"]:
        raise ValueError("report/freeze identities differ")
    controls_path = register(root / "results/oof/c6_controls/summary.json")
    primary_path = register(root / "results/oof/c6_final/summary.json")
    per_query_path = register(root / "results/oof/c6_final/per_query.csv")
    for name, path in (
        ("freeze", root / "results/frozen/c6_manifest.json"),
        ("quality_controls", controls_path),
        ("quality_primary", primary_path),
        ("per_query", per_query_path),
    ):
        check_hash(path, facts["input_sha256"][name])
    controls, primary = read(controls_path), read(primary_path)
    registry_path = register(root / "results/frozen/oof_4_methods.json")
    registry = read(registry_path)
    if registry["freeze_hash"] != freeze["freeze_hash"]:
        raise ValueError("OOF registry freeze differs")
    split_path = register(root / "data/splits/manifest.json")
    check_hash(split_path, freeze["split_manifest_sha256"])
    split = read(split_path)
    with per_query_path.open(encoding="utf-8", newline="") as stream:
        metrics = {(r["method"], r["query_id"]): r for r in csv.DictReader(stream)}
    detailed_dir = root / "results/benchmark/c6_programmers_fold_0"
    detailed_manifest, detailed, _ = load_complete_run(detailed_dir)
    register(detailed_dir / "manifest.json")
    if detailed_manifest["source_snapshot"]["combined_sha256"] != freeze["source_snapshot_hash"]:
        raise ValueError("stage sample source differs from frozen experiment")
    stage_samples = {r["query_id"]: r for r in detailed if r["method"] == "pe_gh"}
    all_rows, all_requests = [], []
    domains = sorted(freeze["domains"])
    for domain in domains:
        queries_path = register(root / f"data/raw/{domain}/queries.jsonl")
        qrels_path = register(root / f"data/raw/{domain}/qrels.tsv")
        for label, path in (("queries", queries_path), ("qrels", qrels_path)):
            check_hash(path, primary["input_hashes"][f"{domain}.{label}"])
        queries = {q.query_id: q.text for q in load_queries(queries_path, domain)}
        qrels = load_qrels(qrels_path, domain)
        feature_path = register(root / f"results/features/{domain}.jsonl")
        feature_meta = read(register(feature_path.with_suffix(".jsonl.meta.json")))
        check_hash(feature_path, feature_meta["feature_rows_sha256"])
        check_hash(queries_path, feature_meta["queries_sha256"])
        features = {
            r["query_id"]: r
            for r in (
                json.loads(line) for line in feature_path.read_text(encoding="utf-8").splitlines()
            )
        }
        if set(features) != set(queries):
            raise ValueError("feature/query coverage differs")
        for fold in range(5):
            key = f"{domain}_fold_{fold}"
            directory = root / "results/benchmark/c6_full" / key
            manifest, requests, receipts = load_complete_run(directory)
            register(directory / "manifest.json")
            recorded_run = next(
                r for r in release["runs"] if r["domain"] == domain and r["fold"] == fold
            )
            check_hash(directory / "manifest.json", recorded_run["manifest_sha256"])
            if manifest["source_snapshot"]["combined_sha256"] != freeze["source_snapshot_hash"]:
                raise ValueError("online source differs from frozen experiment")
            for worker in manifest["workers"]:
                for name in ("worker.json", "requests.jsonl", "memory_samples.jsonl"):
                    register(directory / worker["directory"] / name)
            expected = set(fold_record(split, fold)["domains"][domain]["test"])
            rankings = {}
            for method in ("bm25", "h_star", "s_star", "pe_gh"):
                path = Path(registry["domains"][domain]["runs"][method][str(fold)])
                if not path.is_absolute():
                    path = registry_path.parent / path
                path = register(path)
                check_hash(path, primary["input_hashes"][f"{domain}.{method}.fold_{fold}"])
                sidecar = register(path.with_suffix(".jsonl.meta.json"))
                check_hash(
                    sidecar, primary["input_hashes"][f"{domain}.{method}.fold_{fold}.sidecar"]
                )
                rankings[method], _ = load_rankings(path, domain=domain)
                if set(rankings[method]) != expected:
                    raise ValueError("OOF query IDs differ from split")
                if method != "bm25" and read(sidecar)["freeze_hash"] != freeze["freeze_hash"]:
                    raise ValueError("sidecar freeze differs")
            by_query = defaultdict(list)
            for request in requests:
                ids = [h.doc_id for h in rankings[request["method"]][request["query_id"]].hits]
                if object_hash(ids) != request["ranking_hash"]:
                    raise ValueError("online ranking differs from OOF")
                all_requests.append(request)
                if request["method"] == "pe_gh":
                    by_query[request["query_id"]].append(request)
            if set(by_query) != expected:
                raise ValueError("online query set differs from test fold")
            item = freeze["domains"][domain]["folds"][str(fold)]
            check_hash(register(root / item["model_manifest_path"]), item["model_manifest_sha256"])
            for qid in sorted(expected):
                samples = by_query[qid]
                if (
                    len(samples) != 5
                    or len({(r["use_dense"], r["gate_score"]) for r in samples}) != 1
                ):
                    raise ValueError("gate decisions/scores changed across repetitions")
                dense = samples[0]["use_dense"]
                score = samples[0]["gate_score"]
                if not math.isfinite(score) or any(
                    r["encoder_calls"] != int(dense)
                    or r["vector_search_calls"] != int(dense)
                    or r["stage_calls"]["sparse"] != 1
                    for r in samples
                ):
                    raise ValueError("invalid score/encoder/vector/sparse counts")
                vector = features[qid]
                if vector["feature_schema_hash"] != item["feature_schema_hash"]:
                    raise ValueError("feature schema differs from frozen model")
                fallback = samples[0]["fallback_reason"]
                if dense != bool(fallback or score > item["threshold"]):
                    raise ValueError("gate decision differs from frozen threshold")
                utility = {m: float(metrics[(m, qid)]["ndcg_at_10"]) for m in rankings}
                selected = rankings["h_star" if dense else "bm25"][qid]
                if selected.hits != rankings["pe_gh"][qid].hits:
                    raise ValueError("PE-GH hits differ from the selected branch")
                stage = stage_samples.get(qid)
                all_rows.append(
                    {
                        "domain": domain,
                        "fold": fold,
                        "query_id": qid,
                        "query": queries[qid],
                        "use_dense": dense,
                        "gate_score": score,
                        "threshold": item["threshold"],
                        "fallback_reason": fallback,
                        "feature_schema_hash": vector["feature_schema_hash"],
                        "features": dict(zip(FEATURE_NAMES, vector["values"], strict=True)),
                        "u_b": utility["bm25"],
                        "u_h": utility["h_star"],
                        "u_s": utility["s_star"],
                        "u_pe": utility["pe_gh"],
                        "delta_u": utility["h_star"] - utility["bm25"],
                        "top10": {
                            m: [h.doc_id for h in runs[qid].hits[:10]]
                            for m, runs in rankings.items()
                        },
                        "qrels": positive_qrels(qrels, qid),
                        "request_ms": [r["total_ns"] / 1e6 for r in samples],
                        "stage_sample_ns": None
                        if stage is None
                        else {
                            name: stage[f"{name}_ns"]
                            for name in (
                                "sparse",
                                "stats",
                                "features",
                                "gate",
                                "encode",
                                "vector",
                                "fusion",
                            )
                        },
                        "stage_timing_scope": "separate detailed sample, programmers fold 0 only"
                        if stage is not None
                        else "not instrumented in main benchmark",
                    }
                )
            if any(r.get("quality_cache_used") is not False for r in receipts):
                raise ValueError("quality cache used online")
    if len(all_requests) != release["measured_requests"] or len(all_rows) != 1948:
        raise ValueError("unexpected full experiment coverage")
    selected = select_cases(all_rows)
    write_jsonl(output / "gate-cases.jsonl", selected)
    write_csv(
        output / "gate-cases.csv",
        [
            {
                k: row[k]
                for k in (
                    "category",
                    "selection_reason",
                    "domain",
                    "fold",
                    "query_id",
                    "query",
                    "use_dense",
                    "gate_score",
                    "threshold",
                    "u_b",
                    "u_h",
                    "u_s",
                    "u_pe",
                    "delta_u",
                )
            }
            for row in selected
        ],
    )
    case_summary = []
    for domain in domains:
        counts = Counter(
            outcome(r["use_dense"], r["delta_u"]) for r in all_rows if r["domain"] == domain
        )
        for category in ("missed_benefit", "wasted_dense", "useful_dense", "safe_skip"):
            case_summary.append(
                {
                    "domain": domain,
                    "category": category,
                    "query_count": counts[category],
                    "selected_count": sum(
                        r["domain"] == domain and r["category"] == category for r in selected
                    ),
                }
            )
    write_csv(output / "gate-outcomes.csv", case_summary)
    methods = ["bm25", "dense", "h_star", "s_star", "pe_gh"]
    table = []
    ratios = {m["method"]: m["dense_ratio"] for m in facts["methods"]}
    for method, values in controls["summaries"].items():
        table.append(
            {
                "method": method,
                **{f"{d}_ndcg_at_10": values["domains"][d]["ndcg_at_10"] for d in domains},
                **{f"macro_{k}": v for k, v in values["macro"].items() if k != "domain_count"},
                "dense_ratio": ratios[method],
            }
        )
    write_csv(output / "quality-final.csv", table)
    control_rows_path = register(root / "results/oof/c6_controls/per_query.csv")
    with control_rows_path.open(encoding="utf-8", newline="") as stream:
        control_rows = list(csv.DictReader(stream))
    for method in methods:
        for domain in domains:
            current = [r for r in control_rows if r["method"] == method and r["domain"] == domain]
            expected_ids = {q for b in split["domains"][domain]["buckets"] for q in b}
            if (
                len(current) != len(expected_ids)
                or {r["query_id"] for r in current} != expected_ids
            ):
                raise ValueError("plot query coverage differs")
            mean = sum(float(r["ndcg_at_10"]) for r in current) / len(current)
            if not math.isclose(
                mean, controls["summaries"][method]["domains"][domain]["ndcg_at_10"], abs_tol=1e-12
            ):
                raise ValueError("plot metrics differ from verified summary")
    plot_quality(controls, control_rows, output, methods=methods)
    comparison = primary["comparison"]
    import matplotlib.pyplot as plt

    figure, axis = plt.subplots(figsize=(7.2, 3.8))
    labels = [*domains, "macro"]
    ci = [comparison["domains"][d] for d in domains] + [comparison["macro"]]
    for index, value in enumerate(ci):
        axis.plot(value["mean_difference"], index, "o", color="#24648e")
        axis.hlines(index, *value["two_sided_95"], color="#24648e")
        axis.plot(
            value["one_sided_lower_95"],
            index,
            "|",
            color="#d66336",
            markersize=14,
            label="one-sided 95% lower bound" if index == 0 else None,
        )
    axis.axvline(-0.01, color="#b43c32", linestyle="--", label="registered margin -0.01")
    axis.axvline(0, color="grey", linewidth=0.8)
    axis.set_yticks(range(3), labels)
    axis.set_xlabel("PE-GH minus S*: nDCG@10; bars = two-sided 95% CI")
    axis.legend(frameon=False, loc="upper center", bbox_to_anchor=(0.5, 1.24), ncol=2, fontsize=8)
    axis.grid(axis="x", alpha=0.2)
    figure.tight_layout()
    figure.savefig(output / "quality-noninferiority.png", dpi=200)
    plt.close(figure)
    report = {
        "schema_version": "a_final_report_v1",
        "freeze_hash": freeze["freeze_hash"],
        "experiment_source_hash": freeze["source_snapshot_hash"],
        "analysis_script_sha256": file_hash(Path(__file__)),
        "selection_script_sha256": file_hash(root / "src/pegh/evaluation/failures.py"),
        "plot_script_sha256": file_hash(root / "src/pegh/evaluation/quality_plot.py"),
        "query_count": len(all_rows),
        "verified_online_requests": len(all_requests),
        "selected_case_count": len(selected),
        "outcomes": case_summary,
        "case_selection": {
            "limit_per_domain_outcome": 5,
            "safe_skip_seed": 20261019,
            "wasted_dense_order": "largest harm, then query ID",
            "useful_dense_order": "largest gains plus one median",
            "scope": "post-freeze descriptive analysis; no retuning",
        },
        "input_sha256": inputs,
        "output_sha256": {
            p.name: file_hash(p)
            for p in sorted(output.iterdir())
            if p.is_file() and p.name != "report.json"
        },
    }
    report["report_hash"] = object_hash(report)
    atomic_json(output / "report.json", report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    report = build_report(Path.cwd(), Path(args.output))
    print(
        json.dumps(
            {
                k: report[k]
                for k in (
                    "freeze_hash",
                    "query_count",
                    "verified_online_requests",
                    "selected_case_count",
                )
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
