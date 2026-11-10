"""Build C3 train/validation labels without reading held-out test judgments."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

import yaml

from contracts.ids import canonical_id
from pegh.data.artifacts import atomic_json, file_hash, object_hash, write_jsonl
from pegh.data.qrels import Qrel, positive_qrels
from pegh.data.splits import fold_record, validate_five_fold_splits
from pegh.evaluation.metrics import evaluate_rankings
from pegh.evaluation.runs import load_rankings
from pegh.fusion import fuse_cc, fuse_rrf


def _scoped_qrels(path: Path, domain: str, query_ids: set[str]) -> dict[str, dict[str, float]]:
    """Parse relevance values only for the requested train/validation IDs."""
    result: dict[str, dict[str, float]] = {}
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream, delimiter="\t")
        if reader.fieldnames is None or not {"query-id", "corpus-id", "score"} <= set(
            reader.fieldnames
        ):
            raise ValueError(f"{path}: unsupported canonical qrels header")
        for line_number, row in enumerate(reader, 2):
            query_id = canonical_id(row["query-id"], domain)
            if query_id not in query_ids:
                continue
            doc_id = canonical_id(row["corpus-id"], domain)
            try:
                relevance = float(row["score"])
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{path}:{line_number}: invalid relevance") from exc
            qrel = Qrel(query_id, doc_id, relevance)
            documents = result.setdefault(qrel.query_id, {})
            if qrel.doc_id in documents:
                raise ValueError(f"{path}:{line_number}: duplicate qrel pair")
            documents[qrel.doc_id] = qrel.relevance
    return result


def _load_run(root: Path, domain: str, method: str, expected: dict):
    path = root / "results" / "quality" / method / f"{domain}.jsonl"
    sidecar_path = path.with_suffix(path.suffix + ".meta.json")
    rankings, metadata = load_rankings(path, domain=domain)
    sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    if (
        file_hash(path) != expected["ranking_sha256"]
        or file_hash(sidecar_path) != expected["sidecar_sha256"]
        or metadata["retriever_hash"] != expected["retriever_hash"]
        or sidecar.get("ranking_sha256") != file_hash(path)
    ):
        raise ValueError(f"{method}/{domain}: source ranking differs from C1 provenance")
    return rankings, {
        "ranking_sha256": file_hash(path),
        "sidecar_sha256": file_hash(sidecar_path),
        "retriever_hash": metadata["retriever_hash"],
    }


def _h_star_rankings(
    method: str, query_ids: list[str], sparse: dict, dense: dict, rrf_k: int
) -> dict:
    if method == "rrf":
        return {
            query_id: fuse_rrf(sparse[query_id], dense[query_id], rrf_k=rrf_k)
            for query_id in query_ids
        }
    prefix = "cc_alpha_"
    if method.startswith(prefix):
        alpha = float(method.removeprefix(prefix))
        return {
            query_id: fuse_cc(sparse[query_id], dense[query_id], alpha_dense=alpha)
            for query_id in query_ids
        }
    raise ValueError(f"unsupported C1 H* method: {method}")


def _random_score(query_id: str, seed: int) -> float:
    digest = hashlib.sha256(f"{seed}\0{query_id}".encode()).digest()
    uniform = int.from_bytes(digest[:8], "big") / 2**64
    return 1.0 - uniform


def _group_ids(split_domain: dict, domain: str) -> dict[str, str]:
    return {
        query_id: f"{domain}:group:{group_index}"
        for group_index, group in enumerate(split_domain["groups"])
        for query_id in group
    }


def _validate_recipe(config: dict) -> None:
    targets, controls = config["targets"], config["controls"]
    if (
        targets["utility_metric"] != "ndcg_at_10"
        or targets["gain"] != "h_star_minus_bm25"
        or targets["gain_binary"] != "delta_u_strictly_greater_than_zero"
        or targets["sparse_success"] != "0_if_bm25_top10_has_positive_qrel_else_1"
        or targets["remove_self_qrel"] is not True
        or targets["retain_zero_utility_queries"] is not True
        or controls["threshold_source"] != "validation_only"
    ):
        raise ValueError("unsupported registered C3 label recipe")
    expected_controls = {
        "identifier_margin": "max(identifier_present, -bm25_rel_gap12)",
        "bm25_margin": "-bm25_rel_gap12",
    }
    if any(controls[name]["dense_score"] != recipe for name, recipe in expected_controls.items()):
        raise ValueError("unsupported registered C3 control recipe")
    expected_decision = "dense_if_score_strictly_greater_than_validation_threshold"
    if any(controls[name]["decision"] != expected_decision for name in expected_controls):
        raise ValueError("control thresholds must be selected on validation only")
    if (
        controls["random"]["hash"]
        != "sha256(seed_utf8 + NUL + canonical_query_id_utf8), first_64_bits_big_endian"
        or controls["random"]["dense_score"] != "1_minus_first_64_hash_bits_divided_by_2_pow_64"
        or controls["random"]["decision"] != expected_decision
    ):
        raise ValueError("unsupported registered random control recipe")
    seeds = controls["random"]["seeds"]
    if (
        len(seeds) != 30
        or len(set(seeds)) != 30
        or any(type(seed) is not int or seed < 0 for seed in seeds)
    ):
        raise ValueError("random control needs 30 unique integer seeds")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="configs/gating/labels_v1.yaml")
    parser.add_argument("--output-dir", default="results/training")
    args = parser.parse_args()
    root = Path.cwd()
    config_path = root / args.config
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    split_path = root / config["split_manifest"]
    fusion_path = root / config["fusion_selection"]
    feature_schema_path = root / config["features_manifest"]
    protocol_path = root / "configs" / "gating" / "protocol_v1.yaml"
    split = json.loads(split_path.read_text(encoding="utf-8"))
    fusion_report = json.loads(fusion_path.read_text(encoding="utf-8"))
    features_schema = json.loads(feature_schema_path.read_text(encoding="utf-8"))
    protocol = yaml.safe_load(protocol_path.read_text(encoding="utf-8"))
    _validate_recipe(config)
    recorded_report_hash = fusion_report.pop("report_hash")
    if object_hash(fusion_report) != recorded_report_hash:
        raise ValueError("C1 selection report hash differs")
    validate_five_fold_splits(split)
    feature_hash = features_schema["full"]["schema_hash"]
    general_hash = features_schema["general"]["schema_hash"]
    labels = config["targets"]
    controls = config["controls"]
    label_recipe_hash = object_hash({"targets": labels, "controls": controls})
    output_root = root / args.output_dir
    builder_hash = file_hash(root / "scripts_c" / "build_training_tables.py")
    artifacts: list[dict] = []

    for domain in sorted(split["domains"]):
        data_manifest_path = root / "data" / "manifests" / f"{domain}.json"
        data_manifest = json.loads(data_manifest_path.read_text(encoding="utf-8"))
        raw = root / "data" / "raw" / domain
        qrels_path = raw / "qrels.tsv"
        qrels_hash = file_hash(qrels_path)
        if qrels_hash != data_manifest["files"]["qrels"]["sha256"]:
            raise ValueError(f"{domain}: qrels differ from canonical manifest")

        feature_path = root / "results" / "features" / f"{domain}.jsonl"
        feature_sidecar_path = feature_path.with_suffix(feature_path.suffix + ".meta.json")
        feature_sidecar = json.loads(feature_sidecar_path.read_text(encoding="utf-8"))
        if (
            feature_sidecar.get("feature_schema_hash") != feature_hash
            or feature_sidecar.get("general_schema_hash") != general_hash
            or feature_sidecar.get("feature_rows_sha256") != file_hash(feature_path)
            or feature_sidecar.get("queries_sha256") != data_manifest["files"]["queries"]["sha256"]
            or feature_sidecar.get("dataset_manifest_sha256") != file_hash(data_manifest_path)
            or feature_sidecar.get("protocol_config_sha256") != file_hash(protocol_path)
            or feature_sidecar.get("extractor_sha256")
            != file_hash(root / "src" / "pegh" / "gating" / "features.py")
        ):
            raise ValueError(f"{domain}: C2 feature sidecar differs")
        feature_rows = {}
        with feature_path.open(encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, 1):
                row = json.loads(line)
                if row["domain"] != domain or row["query_id"] in feature_rows:
                    raise ValueError(f"{feature_path}:{line_number}: duplicate or wrong-domain row")
                if (
                    row["feature_schema_hash"] != feature_hash
                    or row["general_schema_hash"] != general_hash
                    or len(row["values"]) != 21
                ):
                    raise ValueError(f"{feature_path}:{line_number}: feature schema differs")
                feature_rows[row["query_id"]] = row["values"]

        sparse, sparse_meta = _load_run(
            root, domain, "bm25", fusion_report["domains"][domain]["inputs"]["bm25"]
        )
        dense, dense_meta = _load_run(
            root, domain, "dense", fusion_report["domains"][domain]["inputs"]["dense"]
        )
        if fusion_report["config_sha256"] != file_hash(protocol_path):
            raise ValueError("C1 report refers to a different fusion protocol config")
        engine_hash = file_hash(root / "src" / "pegh" / "fusion" / "engines.py")
        engine_key = str(Path("src") / "pegh" / "fusion" / "engines.py")
        if fusion_report["source_sha256"][engine_key] != engine_hash:
            raise ValueError("C1 report refers to a different fusion implementation")
        selector_hash = file_hash(root / "scripts_c" / "select_fusion.py")
        selector_key = str(Path("scripts_c") / "select_fusion.py")
        if fusion_report["source_sha256"][selector_key] != selector_hash:
            raise ValueError("C1 report refers to a different fusion selector")
        all_ids = set(split["domains"][domain]["buckets"][0])
        all_ids.update(
            query_id for bucket in split["domains"][domain]["buckets"][1:] for query_id in bucket
        )
        if set(feature_rows) != all_ids or set(sparse) != all_ids or set(dense) != all_ids:
            raise ValueError(f"{domain}: features or runs do not cover canonical split IDs")
        groups = _group_ids(split["domains"][domain], domain)

        for fold in range(split["fold_count"]):
            fold_data = fold_record(split, fold)["domains"][domain]
            train_ids, validation_ids = fold_data["train"], fold_data["validation"]
            allowed_ids = set(train_ids) | set(validation_ids)
            qrels = _scoped_qrels(qrels_path, domain, allowed_ids)
            selection = fusion_report["domains"][domain]["folds"][str(fold)]
            selection_hash = selection["selection_hash"]
            unsigned_selection = {
                key: value for key, value in selection.items() if key != "selection_hash"
            }
            if object_hash(unsigned_selection) != selection_hash:
                raise ValueError(f"{domain}/fold {fold}: C1 selection hash differs")
            h_star_method = selection["h_star"]["method"]
            h_star_ids = train_ids + validation_ids
            h_star = _h_star_rankings(
                h_star_method,
                h_star_ids,
                sparse,
                dense,
                int(protocol["fusion"]["rrf_k"]),
            )
            reference_hash = object_hash(
                {
                    "schema_version": "h_star_apply_v1",
                    "selection_hash": selection_hash,
                    "h_star_method": h_star_method,
                    "bm25_ranking_sha256": sparse_meta["ranking_sha256"],
                    "dense_ranking_sha256": dense_meta["ranking_sha256"],
                    "sparse_retriever_hash": sparse_meta["retriever_hash"],
                    "dense_retriever_hash": dense_meta["retriever_hash"],
                    "fusion_engine_sha256": engine_hash,
                }
            )

            for role, query_ids in (("train", train_ids), ("validation", validation_ids)):
                scoped_qrels = {query_id: qrels.get(query_id, {}) for query_id in query_ids}
                sparse_scope = {query_id: sparse[query_id] for query_id in query_ids}
                h_star_scope = {query_id: h_star[query_id] for query_id in query_ids}
                sparse_metrics = evaluate_rankings(query_ids, domain, scoped_qrels, sparse_scope)
                h_star_metrics = evaluate_rankings(query_ids, domain, scoped_qrels, h_star_scope)
                sparse_by_id = {row.query_id: row for row in sparse_metrics}
                h_star_by_id = {row.query_id: row for row in h_star_metrics}
                rows = []
                gain_positive_count = sparse_success_count = both_zero_count = 0
                for query_id in query_ids:
                    x = feature_rows[query_id]
                    utility_b = sparse_by_id[query_id].ndcg_at_10
                    utility_h = h_star_by_id[query_id].ndcg_at_10
                    delta = utility_h - utility_b
                    if not -1.0 <= delta <= 1.0:
                        raise ValueError(f"{domain}/{query_id}: delta utility outside [-1, 1]")
                    relevant = positive_qrels(scoped_qrels, query_id)
                    sparse_success = any(
                        hit.doc_id in relevant for hit in sparse[query_id].hits[:10]
                    )
                    identifier_present = float(any(x[index] > 0 for index in (6, 7, 8)))
                    row = {
                        "schema_version": "c3_labeled_row_v1",
                        "fold": fold,
                        "split_role": role,
                        "domain": domain,
                        "query_id": query_id,
                        "group_id": groups[query_id],
                        "feature_schema_hash": feature_hash,
                        **{f"x_{index:02}": value for index, value in enumerate(x, 1)},
                        "U_B": utility_b,
                        "U_H": utility_h,
                        "delta_U": delta,
                        "gain_binary_label": int(delta > 0),
                        "sparse_success_label": int(not sparse_success),
                        "identifier_margin_score": max(identifier_present, -x[16]),
                        "bm25_margin_score": -x[16],
                        "reference_hash": reference_hash,
                    }
                    for seed in controls["random"]["seeds"]:
                        row[f"random_score_seed_{seed}"] = _random_score(query_id, int(seed))
                    rows.append(row)
                    gain_positive_count += int(delta > 0)
                    sparse_success_count += int(sparse_success)
                    both_zero_count += int(utility_b == 0 and utility_h == 0)

                target = output_root / f"fold_{fold}" / domain / f"{role}.jsonl"
                write_jsonl(target, rows)
                sidecar = {
                    "schema_version": "1.0",
                    "fold": fold,
                    "domain": domain,
                    "split_role": role,
                    "query_count": len(rows),
                    "query_ids_hash": object_hash(query_ids),
                    "split_hash": split["split_hash"],
                    "dataset_manifest_sha256": file_hash(data_manifest_path),
                    "qrels_sha256": qrels_hash,
                    "qrels_scope": role,
                    "test_qrels_used": False,
                    "feature_rows_sha256": file_hash(feature_path),
                    "feature_schema_hash": feature_hash,
                    "general_schema_hash": general_hash,
                    "h_star_method": h_star_method,
                    "selection_hash": selection_hash,
                    "reference_hash": reference_hash,
                    "bm25_ranking_sha256": sparse_meta["ranking_sha256"],
                    "dense_ranking_sha256": dense_meta["ranking_sha256"],
                    "label_recipe_hash": label_recipe_hash,
                    "control_policy_hash": object_hash(controls),
                    "control_policy_names": ["identifier_margin", "bm25_margin", "random"],
                    "builder_sha256": builder_hash,
                    "positive_gain_count": gain_positive_count,
                    "sparse_success_count": sparse_success_count,
                    "both_zero_utility_count": both_zero_count,
                    "table_sha256": file_hash(target),
                }
                atomic_json(target.with_suffix(target.suffix + ".meta.json"), sidecar)
                artifacts.append({"path": str(target.relative_to(root)), **sidecar})

    manifest = {
        "schema_version": "1.0",
        "protocol": "C3_labels_and_controls_v1",
        "test_qrels_used": False,
        "split_manifest_sha256": file_hash(split_path),
        "split_hash": split["split_hash"],
        "fusion_report_sha256": file_hash(fusion_path),
        "fusion_report_hash": recorded_report_hash,
        "feature_schema_sha256": file_hash(feature_schema_path),
        "label_config_sha256": file_hash(config_path),
        "source_sha256": {"scripts_c/build_training_tables.py": builder_hash},
        "label_recipe": labels,
        "control_policies": controls,
        "label_recipe_hash": label_recipe_hash,
        "artifacts": artifacts,
    }
    manifest["manifest_hash"] = object_hash(manifest)
    atomic_json(output_root / "c3_manifest.json", manifest)
    print(f"Wrote {len(artifacts)} train/validation tables; test qrels were not used")


if __name__ == "__main__":
    main()
