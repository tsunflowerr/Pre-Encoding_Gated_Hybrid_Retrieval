"""Select five-fold online thresholds using validation rows only."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import yaml

from pegh.data.artifacts import atomic_json, file_hash, object_hash
from pegh.data.splits import fold_record

MODEL_METHODS = (
    "ridge_gain_full",
    "logistic_gain_full",
    "logistic_sparse_success_full",
    "linear_svc_gain_general",
    "ridge_gain_general",
)
CONTROL_METHODS = ("identifier_margin_score", "bm25_margin_score", "random_score_seed_0")


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _grid(rows: list[dict], budgets: list[float]) -> list[dict]:
    eligible = sorted((row["score"] for row in rows if not row["force_dense"]), reverse=True)
    forced_count = sum(row["force_dense"] for row in rows)
    result = []
    for budget in budgets:
        target = min(max(round(budget * len(rows)) - forced_count, 0), len(eligible))
        if target == 0:
            threshold = math.nextafter(max(eligible), math.inf) if eligible else 0.0
        elif target == len(eligible):
            threshold = math.nextafter(min(eligible), -math.inf) if eligible else 0.0
        else:
            threshold = eligible[target]
        grouped: dict[str, list[dict]] = {}
        for row in rows:
            grouped.setdefault(row["domain"], []).append(row)
        metrics = {}
        total_dense = 0
        for domain, group in grouped.items():
            dense = [row["force_dense"] or row["score"] > threshold for row in group]
            total_dense += sum(dense)
            quality = sum(
                row["U_H"] if route else row["U_B"] for row, route in zip(group, dense, strict=True)
            ) / len(group)
            baseline = sum(row["U_H"] for row in group) / len(group)
            metrics[domain] = {
                "query_count": len(group),
                "dense_count": sum(dense),
                "dense_ratio": sum(dense) / len(group),
                "ndcg_at_10": quality,
                "s_star_ndcg_at_10": baseline,
                "loss_vs_s_star": baseline - quality,
            }
        macro_loss = sum(value["loss_vs_s_star"] for value in metrics.values()) / len(metrics)
        result.append(
            {
                "desired_dense_budget": budget,
                "threshold": threshold,
                "actual_dense_count": total_dense,
                "actual_dense_ratio": total_dense / len(rows),
                "macro_ndcg_at_10": sum(value["ndcg_at_10"] for value in metrics.values())
                / len(metrics),
                "macro_loss_vs_s_star": macro_loss,
                "domains": metrics,
            }
        )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="results/thresholds/c6_validation.json")
    args = parser.parse_args()
    root = Path.cwd()
    config_path = root / "configs/gating/protocol_v1.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    selection_path = root / "results/fusion/selection_v1.json"
    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    split_path = root / "data/splits/manifest.json"
    split = json.loads(split_path.read_text(encoding="utf-8"))
    if selection["split_hash"] != split["split_hash"]:
        raise ValueError("C1 selection and split differ")
    budgets = config["selection"]["desired_dense_budgets"]
    if budgets != [round(i / 10, 1) for i in range(11)]:
        raise ValueError("expected preregistered 0..1 budget grid")
    output = {
        "schema_version": "c6_validation_thresholds_v1",
        "selection_scope": "validation_only",
        "test_qrels_used": False,
        "split_hash": split["split_hash"],
        "protocol_sha256": file_hash(config_path),
        "selection_sha256": file_hash(selection_path),
        "budgets": budgets,
        "gate_rule": "score_strictly_greater_than_threshold",
        "tie_policy": "skip_equal_score",
        "macro_loss_tolerance": config["selection"]["validation_macro_loss_tolerance"],
        "domain_loss_tolerance": config["selection"]["validation_domain_loss_tolerance"],
        "folds": {},
    }
    for fold in range(5):
        fold_result = {}
        for method in (*MODEL_METHODS, *CONTROL_METHODS):
            rows = []
            inputs = {}
            for domain in config["domains"]:
                if selection["domains"][domain]["folds"][str(fold)]["s_star"]["method"] != "h_star":
                    raise ValueError("C3 U_H can represent S* only when S*=H*")
                table = root / "results/training" / f"fold_{fold}" / domain / "validation.jsonl"
                labels = _jsonl(table)
                expected_ids = set(fold_record(split, fold)["domains"][domain]["validation"])
                if set(row["query_id"] for row in labels) != expected_ids:
                    raise ValueError("validation query IDs differ from split")
                inputs[f"{domain}.labels"] = file_hash(table)
                if method in MODEL_METHODS:
                    prediction = (
                        root
                        / "results/models"
                        / f"fold_{fold}"
                        / domain
                        / method
                        / "validation.jsonl"
                    )
                    predictions = _jsonl(prediction)
                    model_manifest = json.loads(
                        (prediction.parent / "manifest.json").read_text(encoding="utf-8")
                    )
                    if any(
                        row["model_manifest_hash"] != model_manifest["manifest_hash"]
                        for row in predictions
                    ):
                        raise ValueError("prediction/model provenance differs")
                    scores = {row["query_id"]: row["score"] for row in predictions}
                    inputs[f"{domain}.predictions"] = file_hash(prediction)
                    inputs[f"{domain}.model_manifest_hash"] = model_manifest["manifest_hash"]
                else:
                    scores = {row["query_id"]: row[method] for row in labels}
                if set(scores) != {row["query_id"] for row in labels}:
                    raise ValueError("validation score/label query IDs differ")
                for row in labels:
                    score = scores[row["query_id"]]
                    if not math.isfinite(score):
                        raise ValueError("non-finite validation score")
                    rows.append(
                        {
                            "domain": domain,
                            "score": score,
                            "force_dense": row["x_02"] == 0 or row["x_13"] == 1,
                            "U_B": row["U_B"],
                            "U_H": row["U_H"],
                        }
                    )
            grid = _grid(rows, budgets)
            feasible = [
                point
                for point in grid
                if point["desired_dense_budget"] < 1
                and point["macro_loss_vs_s_star"] <= output["macro_loss_tolerance"]
                and all(
                    value["loss_vs_s_star"] <= output["domain_loss_tolerance"]
                    for value in point["domains"].values()
                )
            ]
            chosen = (
                min(
                    feasible,
                    key=lambda point: (
                        point["actual_dense_ratio"],
                        -point["macro_ndcg_at_10"],
                        point["desired_dense_budget"],
                    ),
                )
                if feasible
                else None
            )
            fold_result[method] = {
                "status": "selected" if chosen else "no_feasible_gated_point",
                "selected_mode": "threshold_gate" if chosen else "always_h_star",
                "selected_threshold": chosen["threshold"] if chosen else None,
                "selected_budget": chosen["desired_dense_budget"] if chosen else 1.0,
                "selected_actual_dense_ratio": chosen["actual_dense_ratio"] if chosen else 1.0,
                "selected_macro_ndcg_at_10": chosen["macro_ndcg_at_10"]
                if chosen
                else sum(
                    sum(row["U_H"] for row in rows if row["domain"] == domain)
                    / sum(row["domain"] == domain for row in rows)
                    for domain in config["domains"]
                )
                / len(config["domains"]),
                "inputs": inputs,
                "grid": grid,
            }
        output["folds"][str(fold)] = fold_result
    output["report_hash"] = object_hash(output)
    destination = root / args.output
    if destination.exists():
        raise FileExistsError("threshold report already exists; choose a new output")
    atomic_json(destination, output)
    for fold, methods in output["folds"].items():
        choice = methods["ridge_gain_full"]
        print(f"fold {fold}: {choice['selected_mode']} budget={choice['selected_budget']}")


if __name__ == "__main__":
    main()
