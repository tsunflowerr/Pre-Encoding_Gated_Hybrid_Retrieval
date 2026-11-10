import numpy as np
import pytest
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.preprocessing import StandardScaler
from sklearn.svm import LinearSVC

from contracts.types import FeatureVector
from pegh.gating.models import ModelPredictor


@pytest.mark.parametrize("family", ["ridge", "logistic", "linear_svc"])
def test_fast_linear_scores_and_threshold_decisions_match_sklearn(family):
    rng = np.random.default_rng(42)
    x = rng.normal(size=(120, 21))
    x[:, 0] = 1
    scaler = StandardScaler().fit(x)
    y = x[:, 1] - x[:, 2]
    model = {"ridge": Ridge(), "logistic": LogisticRegression(), "linear_svc": LinearSVC()}[family]
    model.fit(scaler.transform(x), y if family == "ridge" else y > 0)
    predictor = ModelPredictor(
        {"family": family, "feature_count": 21, "feature_schema_hash": "schema"}, scaler, model
    )
    for values in np.concatenate([x, rng.normal(size=(250, 21)) * 100]):
        features = FeatureVector(tuple(values), "schema")
        actual = predictor.predict_score(features)
        expected = predictor.predict_score_reference(features)
        assert actual == expected
        for threshold in (
            expected,
            np.nextafter(expected, -np.inf),
            np.nextafter(expected, np.inf),
        ):
            assert (actual > threshold) == (expected > threshold)
    with pytest.raises(ValueError, match="schema"):
        predictor.predict_score(FeatureVector(tuple(x[0]), "other"))
    with pytest.raises(ValueError, match="dimension or values"):
        predictor.predict_score(FeatureVector((float("nan"),) * 21, "schema"))


def test_bad_scaler_parameters_are_rejected_at_load():
    x = np.arange(30, dtype=float).reshape(10, 3)
    scaler = StandardScaler().fit(x)
    model = Ridge().fit(scaler.transform(x), x[:, 0])
    scaler.scale_[0] = 0
    with pytest.raises(ValueError, match="invalid fitted"):
        ModelPredictor({"family": "ridge", "feature_count": 3}, scaler, model)
