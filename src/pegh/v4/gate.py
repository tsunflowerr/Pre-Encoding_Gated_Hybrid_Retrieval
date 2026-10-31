"""Gate v2: predict whether BM25 fails, trained once across domains, routed by budget.

The gate sees only the query and its BM25 list, so it is trained on what that evidence can
predict, BM25's own quality, instead of the hybrid gain, which depends on the dense side.
Scores are linear (score = w . z + b on standardized features) and serialized to JSON, so
the same weights drive the confirmation, the online benchmark and the demo.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass

import numpy as np

from pegh.gating.features import FEATURE_NAMES
from pegh.v3.features import QPP_NAMES
from pegh.v3.pipeline import ALPHAS, HYBRIDS, TIE_EPSILON

GROUP_NAMES = {"v1": FEATURE_NAMES, "qpp": QPP_NAMES}
LABELS = ("fail", "low")  # fail: BM25 nDCG@10 == 0 (logistic); low: -BM25 nDCG@10 (ridge)
P_STAR_OPTIONS = ("bm25", *(f"proxy_cc_{a:.1f}" for a in ALPHAS))


@dataclass(frozen=True)
class GateSpec:
    label: str
    groups: tuple[str, ...]
    norm: str  # "global": one scaler; "domain": standardize each domain by its own queries

    @property
    def name(self) -> str:
        return f"{self.label}_{'+'.join(self.groups)}_{self.norm}"


CANDIDATES = tuple(
    GateSpec(label, groups, norm)
    for label in LABELS
    for groups in (("v1",), ("v1", "qpp"))
    for norm in ("global", "domain")
)


def label_values(label: str, bm25_utility: np.ndarray) -> np.ndarray:
    if label == "fail":
        return (bm25_utility == 0).astype(int)
    if label == "low":
        return -np.asarray(bm25_utility, dtype=np.float64)
    raise ValueError(f"unknown gate label {label}")


def domain_stats(x: np.ndarray) -> dict:
    """Unlabeled per-domain feature statistics used by domain normalization."""
    return {"mean": x.mean(axis=0).tolist(), "std": (x.std(axis=0) + 1e-9).tolist()}


def _normalize(x: np.ndarray, stats: dict | None) -> np.ndarray:
    if stats is None:
        return x
    return (x - np.asarray(stats["mean"])) / np.asarray(stats["std"])


@dataclass(frozen=True)
class LinearGate:
    spec: GateSpec
    feature_names: tuple[str, ...]
    mean: tuple[float, ...]
    scale: tuple[float, ...]
    coef: tuple[float, ...]
    intercept: float

    def score(self, x: np.ndarray, stats: dict | None = None) -> np.ndarray:
        """Higher means 'more likely that BM25 fails', i.e. a stronger case to encode."""
        if self.spec.norm == "domain":
            if stats is None:
                raise ValueError("domain-normalized gate needs the domain's feature statistics")
            x = _normalize(x, stats)
        z = (np.atleast_2d(x) - np.asarray(self.mean)) / np.asarray(self.scale)
        return z @ np.asarray(self.coef) + self.intercept

    def to_json(self) -> dict:
        payload = asdict(self)
        payload["spec"] = {**asdict(self.spec), "groups": list(self.spec.groups)}
        return payload

    @classmethod
    def from_json(cls, payload: dict) -> LinearGate:
        spec = payload["spec"]
        return cls(
            GateSpec(spec["label"], tuple(spec["groups"]), spec["norm"]),
            tuple(payload["feature_names"]),
            tuple(payload["mean"]),
            tuple(payload["scale"]),
            tuple(payload["coef"]),
            float(payload["intercept"]),
        )

    @property
    def sha256(self) -> str:
        blob = json.dumps(self.to_json(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode()).hexdigest()


def fit(spec: GateSpec, xs: list[np.ndarray], bm25: list[np.ndarray]) -> LinearGate:
    """Fit on pooled training domains (each x already restricted to spec.groups)."""
    from sklearn.linear_model import LogisticRegression, Ridge
    from sklearn.preprocessing import StandardScaler

    parts = [_normalize(x, domain_stats(x) if spec.norm == "domain" else None) for x in xs]
    x = np.vstack(parts)
    y = np.concatenate([label_values(spec.label, u) for u in bm25])
    scaler = StandardScaler().fit(x)
    z = scaler.transform(x)
    if spec.label == "fail":
        model = LogisticRegression(C=1.0, solver="liblinear", max_iter=2000, random_state=42)
        model.fit(z, y)
        coef, intercept = model.coef_[0], float(model.intercept_[0])
    else:
        model = Ridge(alpha=1.0).fit(z, y)
        coef, intercept = model.coef_, float(model.intercept_)
    names = tuple(n for g in spec.groups for n in GROUP_NAMES[g])
    return LinearGate(
        spec,
        names,
        tuple(scaler.mean_.tolist()),
        tuple(scaler.scale_.tolist()),
        tuple(np.asarray(coef).tolist()),
        intercept,
    )


def route_top(score: np.ndarray, forced: np.ndarray, ids: list[str], budget: float) -> np.ndarray:
    """Exact budget: forced queries plus the highest-scored rest (ties by query ID)."""
    chosen = forced.copy()
    rest = int(round(budget * len(score))) - int(forced.sum())
    if rest > 0:
        order = sorted(
            (i for i in range(len(score)) if not forced[i]), key=lambda i: (-score[i], ids[i])
        )[:rest]
        chosen[order] = True
    return chosen


def quantile_threshold(score: np.ndarray, forced: np.ndarray, budget: float) -> float:
    """Threshold that encodes `budget` of these (unlabeled) queries, forced ones included."""
    eligible = np.sort(score[~forced])[::-1]
    target = min(max(round(budget * len(score)) - int(forced.sum()), 0), len(eligible))
    if target == 0:
        return float(np.nextafter(eligible[0], np.inf)) if len(eligible) else 0.0
    if target == len(eligible):
        return float(np.nextafter(eligible[-1], -np.inf))
    return float(eligible[target])


def best_static(utilities: list[dict], options) -> str:
    """Highest macro mean over the given domains; ties keep the earliest option."""
    means = {o: float(np.mean([u[o].mean() for u in utilities])) for o in options}
    top = max(means.values())
    return next(o for o in options if top - means[o] <= TIE_EPSILON)


def fixed_tiers(utilities: list[dict]) -> dict:
    """Label-free deployment: fusion choices fixed from the training domains."""
    return {
        "h_star": best_static(utilities, HYBRIDS),
        "p_star": best_static(utilities, P_STAR_OPTIONS),
    }
