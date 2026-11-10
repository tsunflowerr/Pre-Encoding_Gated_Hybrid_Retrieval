"""Fit the five registered C4 models per fold/domain using train rows only."""

from __future__ import annotations

import argparse
import json
import os
import pickle
import warnings
from pathlib import Path

import numpy as np
import scipy
import sklearn
import yaml
from sklearn.exceptions import ConvergenceWarning
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.preprocessing import StandardScaler
from sklearn.svm import LinearSVC

from contracts.types import FeatureVector
from pegh.data.artifacts import atomic_json, file_hash, object_hash, write_jsonl
from pegh.data.splits import fold_record, validate_five_fold_splits
from pegh.gating.models import load_model


def _atomic_pickle(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("wb") as stream:
        pickle.dump(value, stream, protocol=pickle.HIGHEST_PROTOCOL)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _read_table(root: Path, entry: dict, expected_ids: list[str]) -> tuple[list[dict], dict]:
    path = root / entry["path"]
    sidecar_path = path.with_suffix(path.suffix + ".meta.json")
    sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    if {"path": entry["path"], **sidecar} != entry:
        raise ValueError(f"{path}: C3 manifest and sidecar differ")
    if sidecar["table_sha256"] != file_hash(path):
        raise ValueError(f"{path}: table checksum differs")
    with path.open(encoding="utf-8") as stream:
        rows = [json.loads(line) for line in stream if line.strip()]
    ids = [row["query_id"] for row in rows]
    if ids != expected_ids or sidecar["query_ids_hash"] != object_hash(ids):
        raise ValueError(f"{path}: query IDs differ from the frozen split")
    if sidecar["query_count"] != len(rows) or sidecar["test_qrels_used"] is not False:
        raise ValueError(f"{path}: invalid C3 query count or qrel scope")
    if any(
        row["fold"] != sidecar["fold"]
        or row["domain"] != sidecar["domain"]
        or row["split_role"] != sidecar["split_role"]
        or row["feature_schema_hash"] != sidecar["feature_schema_hash"]
        or row["reference_hash"] != sidecar["reference_hash"]
        for row in rows
    ):
        raise ValueError(f"{path}: row provenance differs from sidecar")
    return rows, sidecar


def _features(rows: list[dict], indices: list[int]) -> np.ndarray:
    values = np.asarray(
        [[row[f"x_{index:02}"] for index in indices] for row in rows], dtype=np.float64
    )
    if values.shape != (len(rows), len(indices)) or not np.isfinite(values).all():
        raise ValueError("training features contain missing or non-finite values")
    return values


def _model(spec: dict, seed: int):
    family = spec["family"]
    if family == "ridge":
        return Ridge(alpha=float(spec["alpha"]))
    if family == "logistic":
        return LogisticRegression(
            C=float(spec["c"]),
            solver=spec["solver"],
            max_iter=int(spec["max_iter"]),
            random_state=seed,
        )
    if family == "linear_svc":
        return LinearSVC(
            C=float(spec["c"]),
            dual=spec["dual"],
            max_iter=int(spec["max_iter"]),
            random_state=seed,
        )
    raise ValueError(f"unsupported model family: {family}")


def _scores(model, scaled: np.ndarray, family: str) -> np.ndarray:
    if family == "ridge":
        values = model.predict(scaled)
    elif family == "logistic":
        values = model.predict_proba(scaled)[:, 1]
    else:
        values = model.decision_function(scaled)
    result = np.asarray(values, dtype=np.float64)
    if result.ndim != 1 or not np.isfinite(result).all():
        raise ValueError("fitted model produced invalid validation scores")
    return result


def _check_config(config: dict, protocol: dict) -> None:
    if (
        config["scaler"] != "standard_train_only"
        or config["sample_weight_policy"] != "per_domain_no_weights"
    ):
        raise ValueError("unsupported C4 scaler or sample-weight policy")
    expected = {
        "ridge_gain_full": ("ridge", "full", "delta_U", "predicted_ndcg_gain"),
        "logistic_gain_full": (
            "logistic",
            "full",
            "gain_binary_label",
            "probability_gain_positive",
        ),
        "logistic_sparse_success_full": (
            "logistic",
            "full",
            "sparse_success_label",
            "probability_sparse_failure",
        ),
        "linear_svc_gain_general": (
            "linear_svc",
            "general",
            "gain_binary_label",
            "signed_margin_gain_positive",
        ),
        "ridge_gain_general": ("ridge", "general", "delta_U", "predicted_ndcg_gain"),
    }
    if set(config["methods"]) != set(expected):
        raise ValueError("C4 methods differ from the registered five-model menu")
    for method, fields in expected.items():
        spec = config["methods"][method]
        if tuple(spec[key] for key in ("family", "features", "target", "score_unit")) != fields:
            raise ValueError(f"{method}: model recipe differs")
        if spec["family"] == "ridge" and spec["alpha"] != protocol["training"]["ridge_alpha"]:
            raise ValueError(f"{method}: Ridge alpha differs from protocol")
        if spec["family"] == "logistic" and spec["c"] != protocol["training"]["logistic_c"]:
            raise ValueError(f"{method}: Logistic C differs from protocol")
        if spec["family"] == "linear_svc" and spec["c"] != protocol["training"]["linear_svc_c"]:
            raise ValueError(f"{method}: LinearSVC C differs from protocol")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="configs/gating/models_v1.yaml")
    args = parser.parse_args()
    root = Path.cwd()
    config_path = root / args.config
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    protocol_path = root / "configs" / "gating" / "protocol_v1.yaml"
    protocol = yaml.safe_load(protocol_path.read_text(encoding="utf-8"))
    _check_config(config, protocol)
    split_path = root / config["split_manifest"]
    split = json.loads(split_path.read_text(encoding="utf-8"))
    validate_five_fold_splits(split)
    c3_path = root / config["training_manifest"]
    c3 = json.loads(c3_path.read_text(encoding="utf-8"))
    recorded_c3_hash = c3.pop("manifest_hash")
    if object_hash(c3) != recorded_c3_hash or c3["split_hash"] != split["split_hash"]:
        raise ValueError("C3 manifest hash or split differs")
    label_config_path = root / "configs" / "gating" / "labels_v1.yaml"
    if c3["label_config_sha256"] != file_hash(label_config_path):
        raise ValueError("C3 label recipe changed after materialization")
    c3_source_path = root / "scripts_c" / "build_training_tables.py"
    if c3["source_sha256"]["scripts_c/build_training_tables.py"] != file_hash(c3_source_path):
        raise ValueError("C3 builder source changed after materialization")
    schema_path = root / config["feature_schema"]
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    if c3["feature_schema_sha256"] != file_hash(schema_path):
        raise ValueError("C2 feature schema changed after C3 materialization")
    full_hash = schema["full"]["schema_hash"]
    general_hash = schema["general"]["schema_hash"]
    general_indices = schema["general"]["indices_one_based"]
    if general_indices != protocol["features"]["general_indices_one_based"]:
        raise ValueError("general feature indices differ from protocol")
    output_root = root / config["output_dir"]
    entries = {(item["fold"], item["domain"], item["split_role"]): item for item in c3["artifacts"]}
    package_versions = {
        "sklearn": sklearn.__version__,
        "numpy": np.__version__,
        "scipy": scipy.__version__,
    }
    source_hashes = {
        "scripts_c/train_gates.py": file_hash(root / "scripts_c" / "train_gates.py"),
        "src/pegh/gating/models.py": file_hash(root / "src" / "pegh" / "gating" / "models.py"),
    }
    results = []

    for fold in range(split["fold_count"]):
        for domain in sorted(split["domains"]):
            parts = fold_record(split, fold)["domains"][domain]
            train_rows, train_meta = _read_table(
                root, entries[(fold, domain, "train")], parts["train"]
            )
            validation_rows, validation_meta = _read_table(
                root, entries[(fold, domain, "validation")], parts["validation"]
            )
            if (
                train_meta["reference_hash"] != validation_meta["reference_hash"]
                or train_meta["selection_hash"] != validation_meta["selection_hash"]
                or train_meta["feature_schema_hash"] != full_hash
                or validation_meta["feature_schema_hash"] != full_hash
            ):
                raise ValueError(f"{domain}/fold {fold}: C3 train/validation provenance differs")
            matrices = {}
            scaler_paths = {}
            domain_root = output_root / f"fold_{fold}" / domain
            for feature_set, indices in (
                ("full", list(range(1, 22))),
                ("general", general_indices),
            ):
                train_x = _features(train_rows, indices)
                validation_x = _features(validation_rows, indices)
                scaler = StandardScaler().fit(train_x)
                if int(scaler.n_samples_seen_) != len(train_rows):
                    raise ValueError("scaler used rows outside the train split")
                matrices[feature_set] = (scaler.transform(train_x), scaler.transform(validation_x))
                scaler_path = domain_root / "scalers" / f"{feature_set}.pkl"
                _atomic_pickle(scaler_path, scaler)
                scaler_paths[feature_set] = scaler_path

            for method, spec in config["methods"].items():
                feature_set = spec["features"]
                train_x, validation_x = matrices[feature_set]
                target = spec["target"]
                y = np.asarray([row[target] for row in train_rows])
                if spec["family"] != "ridge" and set(y.tolist()) != {0, 1}:
                    raise ValueError(f"{domain}/fold {fold}/{method}: both classes are required")
                model = _model(spec, int(config["seed"]))
                with warnings.catch_warnings():
                    warnings.simplefilter("error", ConvergenceWarning)
                    model.fit(train_x, y)
                direct_scores = _scores(model, validation_x, spec["family"])
                method_root = domain_root / method
                model_path = method_root / "model.pkl"
                _atomic_pickle(model_path, model)
                scaler_path = scaler_paths[feature_set]
                feature_schema_hash = full_hash if feature_set == "full" else general_hash
                manifest = {
                    "schema_version": "c4_model_manifest_v1",
                    "method": method,
                    "fold": fold,
                    "domain": domain,
                    "family": spec["family"],
                    "target": target,
                    "score_unit": spec["score_unit"],
                    "feature_set": feature_set,
                    "feature_indices_one_based": list(range(1, 22))
                    if feature_set == "full"
                    else general_indices,
                    "feature_schema_hash": feature_schema_hash,
                    "feature_count": train_x.shape[1],
                    "hyperparameters": {
                        key: value
                        for key, value in spec.items()
                        if key not in ("family", "features", "target", "score_unit")
                    },
                    "sample_weight_policy": config["sample_weight_policy"],
                    "scaler_policy": config["scaler"],
                    "train_count": len(train_rows),
                    "validation_count": len(validation_rows),
                    "train_ids_hash": train_meta["query_ids_hash"],
                    "validation_ids_hash": validation_meta["query_ids_hash"],
                    "scaler_train_ids_hash": train_meta["query_ids_hash"],
                    "train_table_sha256": train_meta["table_sha256"],
                    "validation_table_sha256": validation_meta["table_sha256"],
                    "split_hash": split["split_hash"],
                    "label_recipe_hash": c3["label_recipe_hash"],
                    "reference_hash": train_meta["reference_hash"],
                    "h_star_method": train_meta["h_star_method"],
                    "selection_hash": train_meta["selection_hash"],
                    "model_file": "model.pkl",
                    "model_sha256": file_hash(model_path),
                    "scaler_file": f"../scalers/{feature_set}.pkl",
                    "scaler_sha256": file_hash(scaler_path),
                    "package_versions": package_versions,
                    "source_sha256": source_hashes,
                    "model_config_sha256": file_hash(config_path),
                    "c3_manifest_sha256": file_hash(c3_path),
                    "uv_lock_sha256": file_hash(root / "uv.lock"),
                    "selected_threshold": None,
                    "threshold_source": "C6_validation_only",
                }
                manifest["manifest_hash"] = object_hash(manifest)
                manifest_path = method_root / "manifest.json"
                atomic_json(manifest_path, manifest)
                predictor = load_model(manifest_path)
                replayed = np.asarray(
                    [
                        predictor.predict_score(
                            FeatureVector(
                                tuple(
                                    row[f"x_{index:02}"]
                                    for index in manifest["feature_indices_one_based"]
                                ),
                                feature_schema_hash,
                            )
                        )
                        for row in validation_rows
                    ],
                    dtype=np.float64,
                )
                maximum_difference = float(np.max(np.abs(replayed - direct_scores)))
                if maximum_difference > 1e-12:
                    raise ValueError(
                        f"{domain}/fold {fold}/{method}: serialized predictions differ"
                    )
                prediction_path = method_root / "validation.jsonl"
                write_jsonl(
                    prediction_path,
                    (
                        {
                            "schema_version": "c4_prediction_v1",
                            "method": method,
                            "fold": fold,
                            "domain": domain,
                            "query_id": row["query_id"],
                            "score": float(score),
                            "score_unit": spec["score_unit"],
                            "feature_schema_hash": feature_schema_hash,
                            "model_manifest_hash": manifest["manifest_hash"],
                        }
                        for row, score in zip(validation_rows, replayed, strict=True)
                    ),
                )
                prediction_sidecar = {
                    "schema_version": "1.0",
                    "method": method,
                    "fold": fold,
                    "domain": domain,
                    "query_count": len(validation_rows),
                    "query_ids_hash": validation_meta["query_ids_hash"],
                    "score_unit": spec["score_unit"],
                    "feature_schema_hash": feature_schema_hash,
                    "model_manifest_hash": manifest["manifest_hash"],
                    "model_manifest_sha256": file_hash(manifest_path),
                    "validation_table_sha256": validation_meta["table_sha256"],
                    "prediction_sha256": file_hash(prediction_path),
                    "reloaded_max_abs_difference": maximum_difference,
                    "score_min": float(replayed.min()),
                    "score_max": float(replayed.max()),
                    "score_mean": float(replayed.mean()),
                }
                atomic_json(
                    prediction_path.with_suffix(prediction_path.suffix + ".meta.json"),
                    prediction_sidecar,
                )
                results.append(
                    {
                        "method": method,
                        "fold": fold,
                        "domain": domain,
                        "model_manifest": str(manifest_path.relative_to(root)),
                        "model_manifest_sha256": file_hash(manifest_path),
                        "prediction": str(prediction_path.relative_to(root)),
                        **prediction_sidecar,
                    }
                )
            print(f"{domain}/fold {fold}: fitted {len(config['methods'])} models", flush=True)

    output = {
        "schema_version": "1.0",
        "protocol": "C4_train_only_models_v1",
        "test_qrels_used": False,
        "model_count": len(results),
        "split_hash": split["split_hash"],
        "c3_manifest_hash": recorded_c3_hash,
        "c3_manifest_sha256": file_hash(c3_path),
        "config_sha256": file_hash(config_path),
        "uv_lock_sha256": file_hash(root / "uv.lock"),
        "source_sha256": source_hashes,
        "package_versions": package_versions,
        "artifacts": results,
    }
    output["manifest_hash"] = object_hash(output)
    atomic_json(output_root / "c4_manifest.json", output)
    print(f"Wrote {len(results)} fitted models and validation predictions")


if __name__ == "__main__":
    main()
