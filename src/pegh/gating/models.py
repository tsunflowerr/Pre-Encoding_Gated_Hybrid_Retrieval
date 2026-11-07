"""Load a frozen C4 scaler/model pair and score one feature vector."""

from __future__ import annotations

import json
import math
import pickle
from pathlib import Path

import numpy as np
import scipy
import sklearn
from scipy.special import expit
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.preprocessing import StandardScaler
from sklearn.svm import LinearSVC

from contracts.types import FeatureVector
from pegh.data.artifacts import file_hash, object_hash


class ModelPredictor:
    def __init__(
        self, manifest: dict, scaler: StandardScaler, model: object, *, execution: str = "numpy"
    ) -> None:
        if execution not in ("numpy", "sklearn"):
            raise ValueError("unsupported linear inference execution")
        self.execution = execution
        self.manifest = manifest
        self.scaler = scaler
        self.model = model
        count = manifest["feature_count"]
        if not scaler.with_mean or not scaler.with_std:
            raise ValueError("linear inference requires the registered standard scaler")
        self._mean = np.asarray(scaler.mean_, dtype=np.float64)
        self._scale = np.asarray(scaler.scale_, dtype=np.float64)
        self._coef = np.asarray(model.coef_, dtype=np.float64)
        self._intercept = np.asarray(model.intercept_, dtype=np.float64)
        shape = (count,) if manifest["family"] == "ridge" else (1, count)
        if (
            self._mean.shape != (count,)
            or self._scale.shape != (count,)
            or self._coef.shape != shape
            or self._intercept.size != 1
            or not all(
                np.isfinite(a).all() for a in (self._mean, self._scale, self._coef, self._intercept)
            )
            or (self._scale <= 0).any()
        ):
            raise ValueError("invalid fitted linear/scaler parameters")

    @property
    def provenance(self) -> dict:
        result = {
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
        result.update(
            inference_execution=self.execution, inference_source_sha256=file_hash(Path(__file__))
        )
        return result

    def predict_score(self, features: FeatureVector) -> float:
        """Keep sklearn's arithmetic order, avoiding its repeated estimator validation."""
        if self.execution == "sklearn":
            return self.predict_score_reference(features)
        self._validate(features)
        scaled = np.asarray([features.values], dtype=np.float64)
        scaled -= self._mean
        scaled /= self._scale
        values = scaled @ self._coef.T + self._intercept
        score = float(values.reshape(-1)[0])
        if self.manifest["family"] == "logistic":
            score = float(expit(score))
        if not math.isfinite(score):
            raise ValueError("model produced a non-finite score")
        return score

    def _validate(self, features: FeatureVector) -> None:
        if features.schema_hash != self.manifest["feature_schema_hash"]:
            raise ValueError("feature schema differs from fitted model")
        if len(features.values) != self.manifest["feature_count"] or not all(
            math.isfinite(value) for value in features.values
        ):
            raise ValueError("feature vector dimension or values are invalid")

    def predict_score_reference(self, features: FeatureVector) -> float:
        """Original sklearn route retained for independent parity and timing checks."""
        self._validate(features)
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


def load_model(manifest_path: str | Path, *, execution: str = "numpy") -> ModelPredictor:
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
    return ModelPredictor(manifest, scaler, model, execution=execution)
