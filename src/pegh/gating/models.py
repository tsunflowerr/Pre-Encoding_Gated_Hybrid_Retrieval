"""Load a frozen C4 scaler/model pair and score one feature vector."""

from __future__ import annotations

import json
import math
import pickle
from pathlib import Path

import numpy as np
import scipy
import sklearn
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.preprocessing import StandardScaler
from sklearn.svm import LinearSVC

from contracts.types import FeatureVector
from pegh.data.artifacts import file_hash, object_hash


class ModelPredictor:
    def __init__(self, manifest: dict, scaler: StandardScaler, model: object) -> None:
        self.manifest = manifest
        self.scaler = scaler
        self.model = model

    @property
    def provenance(self) -> dict:
        return {
            key: self.manifest[key]
            for key in (
                "method",
                "fold",
                "domain",
                "manifest_hash",
                "feature_schema_hash",
                "reference_hash",
                "model_sha256",
                "scaler_sha256",
            )
        }

    def predict_score(self, features: FeatureVector) -> float:
        if features.schema_hash != self.manifest["feature_schema_hash"]:
            raise ValueError("feature schema differs from fitted model")
        if len(features.values) != self.manifest["feature_count"] or not all(
            math.isfinite(value) for value in features.values
        ):
            raise ValueError("feature vector dimension or values are invalid")
        scaled = self.scaler.transform(np.asarray([features.values], dtype=np.float64))
        family = self.manifest["family"]
        if family == "ridge":
            score = float(self.model.predict(scaled)[0])
        elif family == "logistic":
            score = float(self.model.predict_proba(scaled)[0, 1])
        elif family == "linear_svc":
            score = float(self.model.decision_function(scaled)[0])
        else:
            raise ValueError(f"unsupported fitted model family: {family}")
        if not math.isfinite(score):
            raise ValueError("model produced a non-finite score")
        return score


def load_model(manifest_path: str | Path) -> ModelPredictor:
    path = Path(manifest_path).resolve()
    manifest = json.loads(path.read_text(encoding="utf-8"))
    recorded_hash = manifest.get("manifest_hash")
    unsigned = {key: value for key, value in manifest.items() if key != "manifest_hash"}
    if (
        manifest.get("schema_version") != "c4_model_manifest_v1"
        or object_hash(unsigned) != recorded_hash
    ):
        raise ValueError("model manifest hash or version differs")
    versions = manifest["package_versions"]
    if versions != {
        "sklearn": sklearn.__version__,
        "numpy": np.__version__,
        "scipy": scipy.__version__,
    }:
        raise ValueError("model package versions differ from fitted environment")
    artifact_root = path.parent.parent.resolve()
    model_path = (path.parent / manifest["model_file"]).resolve()
    scaler_path = (path.parent / manifest["scaler_file"]).resolve()
    if not model_path.is_relative_to(artifact_root) or not scaler_path.is_relative_to(
        artifact_root
    ):
        raise ValueError("model artifact escapes its fold/domain directory")
    if (
        file_hash(model_path) != manifest["model_sha256"]
        or file_hash(scaler_path) != manifest["scaler_sha256"]
    ):
        raise ValueError("model or scaler checksum differs")
    with scaler_path.open("rb") as stream:
        scaler = pickle.load(stream)
    with model_path.open("rb") as stream:
        model = pickle.load(stream)
    expected = {"ridge": Ridge, "logistic": LogisticRegression, "linear_svc": LinearSVC}
    if manifest["family"] not in expected:
        raise ValueError("unsupported model family")
    if not isinstance(scaler, StandardScaler) or not isinstance(
        model, expected[manifest["family"]]
    ):
        raise ValueError("serialized scaler/model type differs from manifest")
    if (
        scaler.n_features_in_ != manifest["feature_count"]
        or model.n_features_in_ != manifest["feature_count"]
    ):
        raise ValueError("serialized feature count differs from manifest")
    if int(scaler.n_samples_seen_) != manifest["train_count"]:
        raise ValueError("scaler sample count differs from train table")
    if manifest["family"] != "ridge" and model.classes_.tolist() != [0, 1]:
        raise ValueError("binary model classes must be [0, 1]")
    return ModelPredictor(manifest, scaler, model)
