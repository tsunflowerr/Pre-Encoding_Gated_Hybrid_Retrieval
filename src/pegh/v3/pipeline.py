"""The v1 gate protocol generalized to any domain group, plus matched-budget analysis.

Rules kept from v1: five group-separated folds; H*/S* chosen on validation with the same
grid and tie policy; train-only scaler/model per fold and domain; one numeric threshold per
fold chosen on pooled validation with 0.005 macro / 0.01 per-domain loss vs S*; score ties
skip dense; sparse OOV forces dense and counts in the ratio. Test labels are only read
after all of these are fixed, by `assemble`.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from contracts.io import load_queries
from pegh.data.qrels import load_qrels
from pegh.data.splits import fold_record
from pegh.evaluation.metrics import query_metrics
from pegh.evaluation.runs import load_rankings
from pegh.fusion import fuse_cc, fuse_rrf
from pegh.v3.workspace import Workspace

ALPHAS = tuple(round(0.1 * i, 1) for i in range(1, 10))
HYBRIDS = tuple(f"cc_alpha_{a:.1f}" for a in ALPHAS) + ("rrf",)
TIE_EPSILON = 1e-6
BUDGETS = tuple(round(i / 10, 1) for i in range(11))
CURVE_BUDGETS = tuple(round(i / 10, 1) for i in range(1, 10))
MACRO_TOLERANCE, DOMAIN_TOLERANCE, MARGIN = 0.005, 0.01, 0.01
GENERAL = (4, 10, 11, 12, 15, 16, 19, 20)
RANDOM_SEEDS = tuple(range(30))

# name -> (family, feature groups, target); feature group "general" = LiteGator-style 8.
GATES = {
    "v1_ridge": ("ridge", ("v1",), "gain"),
    "v1_logistic": ("logistic", ("v1",), "gain_positive"),
    "v1_sparse_success": ("logistic", ("v1",), "sparse_failure"),
    "v1_ridge_general": ("ridge", ("general",), "gain"),
    "litegator_svc": ("svc", ("general",), "gain_positive"),
    "v3_ridge_qpp": ("ridge", ("v1", "qpp"), "gain"),
    "v3_ridge_proxy": ("ridge", ("v1", "proxy"), "gain"),
    "v3_ridge_all": ("ridge", ("v1", "qpp", "proxy"), "gain"),
    "v3_logistic_qpp": ("logistic", ("v1", "qpp"), "gain_positive"),
    "v3_logistic_proxy": ("logistic", ("v1", "proxy"), "gain_positive"),
    "v3_logistic_all": ("logistic", ("v1", "qpp", "proxy"), "gain_positive"),
}
V3_CANDIDATES = tuple(name for name in GATES if name.startswith("v3_"))


@dataclass
class DomainData:
    domain: str
    ids: list[str]
    utilities: dict[str, np.ndarray]
    folds: list[dict[str, np.ndarray]]
    groups: list[str]
    features: dict[str, np.ndarray]

    @property
    def forced(self) -> np.ndarray:
        v1 = self.features["v1"]
        return (v1[:, 1] == 0) | (v1[:, 12] == 1)

    def matrix(self, groups: tuple[str, ...]) -> np.ndarray:
        parts = [
            self.features["v1"][:, [i - 1 for i in GENERAL]] if g == "general" else self.features[g]
            for g in groups
        ]
        return np.hstack(parts)


def _ndcg(domain: str, ids: list[str], qrels: dict, rankings: dict) -> np.ndarray:
    return np.array([query_metrics(q, domain, qrels, rankings[q]).ndcg_at_10 for q in ids])


def load_domain(
    ws: Workspace, domain: str, encoder: str, features: dict, tiers: dict | None = None
) -> DomainData:
    queries = load_queries(ws.raw(domain) / "queries.jsonl", domain)
    qrels = load_qrels(ws.raw(domain) / "qrels.tsv", domain)
    sparse, _ = load_rankings(ws.quality("bm25", domain), domain=domain)
    dense, _ = load_rankings(ws.quality(encoder, domain), domain=domain)
    ids = sorted(q.query_id for q in queries)
    if set(sparse) != set(ids) or set(dense) != set(ids) or list(features["ids"]) != ids:
        raise ValueError(f"{domain}: cached rankings/features do not cover the query set")
    utilities = {
        "bm25": _ndcg(domain, ids, qrels, sparse),
        "dense": _ndcg(domain, ids, qrels, dense),
    }
    for alpha in ALPHAS:
        fused = {q: fuse_cc(sparse[q], dense[q], alpha_dense=alpha) for q in ids}
        utilities[f"cc_alpha_{alpha:.1f}"] = _ndcg(domain, ids, qrels, fused)
    utilities["rrf"] = _ndcg(
        domain, ids, qrels, {q: fuse_rrf(sparse[q], dense[q], rrf_k=60) for q in ids}
    )
    if tiers is not None:
        if list(tiers["ids"]) != ids:
            raise ValueError(f"{domain}: tier utilities are not aligned with the query set")
        utilities.update(
            {k: np.asarray(v, dtype=np.float64) for k, v in tiers.items() if k != "ids"}
        )
    split = json.loads(ws.split_manifest(domain).read_text(encoding="utf-8"))
    row = {q: n for n, q in enumerate(ids)}
    folds = []
    for fold in range(5):
        record = fold_record(split, fold)["domains"][domain]
        folds.append(
            {
                role: np.array([row[q] for q in record[role]])
                for role in ("train", "validation", "test")
            }
        )
    group_of = {}
    for number, members in enumerate(split["domains"][domain]["groups"]):
        for q in members:
            group_of[q] = f"{domain}:g{number}"
    return DomainData(
        domain,
        ids,
        utilities,
        folds,
        [group_of[q] for q in ids],
        {k: np.asarray(v, dtype=np.float64) for k, v in features.items() if k != "ids"},
    )


def _best(means: dict, names: list[str]) -> str:
    """Highest validation mean; ties within epsilon keep the earliest (cheaper/lower alpha)."""
    best = max(means[n] for n in names)
    return next(n for n in names if best - means[n] <= TIE_EPSILON)


def select_fusion(data: DomainData, fold: int) -> dict:
    """v1 C1 rule: best validation nDCG@10; ties prefer RRF, then lower alpha; S* in order.

    With cascade tiers loaded, also choose the cheap tier P* (BM25 or BM25+proxy) and the
    encode tier R* (BM25 candidates re-scored by the query vector), and S*_all over every
    static option, ordered cheapest first for ties.
    """
    validation = data.folds[fold]["validation"]
    means = {m: float(u[validation].mean()) for m, u in data.utilities.items()}
    best = max(means[m] for m in HYBRIDS)
    tied = [m for m in HYBRIDS if best - means[m] <= TIE_EPSILON]
    h_star = "rrf" if "rrf" in tied else tied[0]
    static = {"bm25": means["bm25"], "dense": means["dense"], "h_star": means[h_star]}
    s_name = _best(static, ["bm25", "dense", "h_star"])
    choice = {"h_star": h_star, "s_star": h_star if s_name == "h_star" else s_name}
    if "rescore_cc_0.5" in data.utilities:
        p_star = _best(means, ["bm25", *(f"proxy_cc_{a:.1f}" for a in ALPHAS)])
        r_star = _best(means, [f"rescore_cc_{a:.1f}" for a in ALPHAS])
        choice.update(
            p_star=p_star,
            r_star=r_star,
            s_star_all=_best(means, ["bm25", p_star, "dense", h_star, r_star]),
        )
    choice["validation"] = means
    return choice


MODES = {
    # mode -> (cheap tier key, expensive tier key, S* key) in the select_fusion record
    "v1": ("bm25", "h_star", "s_star"),
    "cascade": ("p_star", "r_star", "s_star_all"),
}


def _random_score(seed: int, query_id: str) -> float:
    digest = hashlib.sha256(f"{seed}\0{query_id}".encode()).digest()
    return 1.0 - int.from_bytes(digest[:8], "big") / 2**64


def _fit_scores(family: str, x_train, y_train, x_eval) -> np.ndarray:
    from sklearn.linear_model import LogisticRegression, Ridge
    from sklearn.preprocessing import StandardScaler
    from sklearn.svm import LinearSVC

    scaler = StandardScaler().fit(x_train)
    z_train, z_eval = scaler.transform(x_train), scaler.transform(x_eval)
    if family == "ridge":
        return Ridge(alpha=1.0).fit(z_train, y_train).predict(z_eval)
    if len(set(y_train.tolist())) < 2:
        return np.zeros(len(x_eval))
    if family == "logistic":
        model = LogisticRegression(C=1.0, solver="liblinear", max_iter=2000, random_state=42)
        return model.fit(z_train, y_train).predict_proba(z_eval)[:, 1]
    if family == "svc":
        model = LinearSVC(C=1.0, dual=False, max_iter=5000, random_state=42)
        return model.fit(z_train, y_train).decision_function(z_eval)
    raise ValueError(f"unknown model family {family}")


def fit_gate(data: DomainData, fold: int, mode: str, gate: str):
    """Refit one Ridge gate exactly as `score_group` does, returning the fitted objects."""
    from sklearn.linear_model import Ridge
    from sklearn.preprocessing import StandardScaler

    family, feature_groups, target = GATES[gate]
    if family != "ridge" or target != "gain":
        raise ValueError("only Ridge gain gates are exported for online use")
    low_key, high_key, _ = MODES[mode]
    choice = select_fusion(data, fold)
    low = "bm25" if low_key == "bm25" else choice[low_key]
    gain = data.utilities[choice[high_key]] - data.utilities[low]
    train = data.folds[fold]["train"]
    x = data.matrix(feature_groups)
    scaler = StandardScaler().fit(x[train])
    model = Ridge(alpha=1.0).fit(scaler.transform(x[train]), gain[train])
    return scaler, model, {**{k: v for k, v in choice.items() if k != "validation"}, "low": low}


@dataclass
class FoldScores:
    """Scores for every query of one fold/domain; only validation+test rows are filled.

    `low` is the route taken on skip, `high` the route after encoding the query.
    """

    low: str
    high: str
    s_star: str
    choice: dict
    scores: dict[str, np.ndarray]


def score_group(
    group: list[DomainData], gates: tuple[str, ...], mode: str = "v1"
) -> dict[str, list[FoldScores]]:
    """Fit train-only models per fold/domain and score validation and test rows."""
    low_key, high_key, s_key = MODES[mode]
    result = {}
    for data in group:
        folds = []
        for fold in range(5):
            choice = select_fusion(data, fold)
            low = "bm25" if low_key == "bm25" else choice[low_key]
            u_b, u_h = data.utilities[low], data.utilities[choice[high_key]]
            train, evaluate = (
                data.folds[fold]["train"],
                np.concatenate([data.folds[fold]["validation"], data.folds[fold]["test"]]),
            )
            targets = {
                "gain": u_h - u_b,
                "gain_positive": (u_h - u_b > 0).astype(int),
                "sparse_failure": (u_b == 0).astype(int),
            }
            scores = {}
            for name in gates:
                family, feature_groups, target = GATES[name]
                x = data.matrix(feature_groups)
                values = np.full(len(data.ids), np.nan)
                values[evaluate] = _fit_scores(
                    family, x[train], targets[target][train], x[evaluate]
                )
                scores[name] = values
            scores["bm25_margin"] = -data.features["v1"][:, 16]
            for seed in RANDOM_SEEDS:
                scores[f"random_{seed}"] = np.array([_random_score(seed, q) for q in data.ids])
            scores["oracle"] = u_h - u_b
            folds.append(FoldScores(low, choice[high_key], choice[s_key], choice, scores))
        result[data.domain] = folds
    return result


def _route(score, forced, threshold):
    return forced | (score > threshold)


def select_threshold(group: list[DomainData], scored: dict, method: str, fold: int) -> dict:
    """v1 C6 rule on pooled validation rows of the whole domain group."""
    rows = []
    for data in group:
        fs = scored[data.domain][fold]
        v = data.folds[fold]["validation"]
        rows.append(
            (
                data.domain,
                fs.scores[method][v],
                data.forced[v],
                data.utilities[fs.low][v],
                data.utilities[fs.high][v],
                data.utilities[fs.s_star][v],
            )
        )
    scores = np.concatenate([r[1] for r in rows])
    forced = np.concatenate([r[2] for r in rows])
    eligible = np.sort(scores[~forced])[::-1]
    total = len(scores)
    points = []
    for budget in BUDGETS:
        target = min(max(round(budget * total) - int(forced.sum()), 0), len(eligible))
        if target == 0:
            threshold = math.nextafter(float(eligible[0]), math.inf) if len(eligible) else 0.0
        elif target == len(eligible):
            threshold = math.nextafter(float(eligible[-1]), -math.inf)
        else:
            threshold = float(eligible[target])
        domains, dense_count = {}, 0
        for domain, s, f, u_b, u_h, u_s in rows:
            dense = _route(s, f, threshold)
            dense_count += int(dense.sum())
            quality = float(np.where(dense, u_h, u_b).mean())
            domains[domain] = {
                "ndcg": quality,
                "loss": float(u_s.mean()) - quality,
                "dense": int(dense.sum()),
            }
        points.append(
            {
                "budget": budget,
                "threshold": threshold,
                "dense_ratio": dense_count / total,
                "macro_ndcg": float(np.mean([d["ndcg"] for d in domains.values()])),
                "macro_loss": float(np.mean([d["loss"] for d in domains.values()])),
                "domains": domains,
            }
        )
    feasible = [
        p
        for p in points
        if p["budget"] < 1
        and p["macro_loss"] <= MACRO_TOLERANCE
        and all(d["loss"] <= DOMAIN_TOLERANCE for d in p["domains"].values())
    ]
    if not feasible:
        return {"status": "no_feasible_gated_point", "threshold": -math.inf, "grid": points}
    chosen = min(feasible, key=lambda p: (p["dense_ratio"], -p["macro_ndcg"], p["budget"]))
    return {
        "status": "selected",
        "threshold": chosen["threshold"],
        "budget": chosen["budget"],
        "grid": points,
    }


@dataclass
class Outcome:
    """Out-of-fold test outcome of one routing method across a domain group."""

    method: str
    dense: dict[str, np.ndarray]
    utility: dict[str, np.ndarray]
    thresholds: list[dict]


def _test_frame(data: DomainData, scored: dict):
    """Per-query test reference utilities and fold IDs assembled across five folds."""
    n = len(data.ids)
    u_b, u_h, u_s, fold_of = np.zeros(n), np.zeros(n), np.zeros(n), np.zeros(n, dtype=int)
    for fold, fs in enumerate(scored[data.domain]):
        test = data.folds[fold]["test"]
        u_b[test] = data.utilities[fs.low][test]
        u_h[test] = data.utilities[fs.high][test]
        u_s[test] = data.utilities[fs.s_star][test]
        fold_of[test] = fold
    return u_b, u_h, u_s, fold_of


def assemble(group: list[DomainData], scored: dict, method: str) -> Outcome:
    """Apply the validation-selected threshold of each fold to its test rows."""
    thresholds = [select_threshold(group, scored, method, fold) for fold in range(5)]
    dense, utility = {}, {}
    for data in group:
        u_b, u_h, _, _ = _test_frame(data, scored)
        mask = np.zeros(len(data.ids), dtype=bool)
        for fold, fs in enumerate(scored[data.domain]):
            test = data.folds[fold]["test"]
            mask[test] = _route(
                fs.scores[method][test], data.forced[test], thresholds[fold]["threshold"]
            )
        dense[data.domain] = mask
        utility[data.domain] = np.where(mask, u_h, u_b)
    return Outcome(method, dense, utility, thresholds)


def at_budget(
    group: list[DomainData], scored: dict, method: str, counts: dict
) -> dict[str, np.ndarray]:
    """Batch diagnostic: per fold/domain, route forced queries plus the top-scored rest.

    counts[domain][fold] gives the dense count; a float in [0, 1] means a ratio of the fold.
    The oracle only spends budget on strictly positive gains.
    """
    result = {}
    for data in group:
        u_b, u_h, _, _ = _test_frame(data, scored)
        mask = np.zeros(len(data.ids), dtype=bool)
        for fold, fs in enumerate(scored[data.domain]):
            test = data.folds[fold]["test"]
            k = counts[data.domain][fold]
            k = int(round(k * len(test))) if isinstance(k, float) else int(k)
            forced = data.forced[test]
            chosen = forced.copy()
            rest = k - int(forced.sum())
            if rest > 0:
                score = fs.scores[method][test]
                order = sorted(
                    (i for i in range(len(test)) if not forced[i]),
                    key=lambda i: (-score[i], data.ids[test[i]]),
                )[:rest]
                if method == "oracle":
                    order = [i for i in order if score[i] > 0]
                chosen[order] = True
            mask[test] = chosen
        result[data.domain] = np.where(mask, u_h, u_b)
    return result


def macro(values: dict[str, np.ndarray]) -> float:
    return float(np.mean([v.mean() for v in values.values()]))


def bootstrap(
    diff: dict[str, np.ndarray],
    groups: dict[str, list[str]],
    *,
    samples: int = 10_000,
    seed: int = 20_261_019,
) -> dict:
    """Group bootstrap inside each domain, macro-averaged; same semantics as v1, vectorized."""
    rng = np.random.default_rng(seed)
    estimates = np.zeros(samples)
    for domain, values in diff.items():
        labels = groups[domain]
        unique = sorted(set(labels))
        index = {g: i for i, g in enumerate(unique)}
        gid = np.array([index[g] for g in labels])
        sums = np.bincount(gid, weights=values, minlength=len(unique))
        sizes = np.bincount(gid, minlength=len(unique)).astype(float)
        draws = rng.integers(0, len(unique), size=(samples, len(unique)))
        estimates += sums[draws].sum(axis=1) / sizes[draws].sum(axis=1)
    estimates /= len(diff)
    return {
        "p_superiority": float(np.mean(estimates <= 0)),
        "p_noninferiority_0_01": float(np.mean(estimates <= -MARGIN)),
        "mean_difference": float(np.mean([v.mean() for v in diff.values()])),
        "one_sided_lower_95": float(np.quantile(estimates, 0.05)),
        "one_sided_upper_95": float(np.quantile(estimates, 0.95)),
        "two_sided_95": [
            float(np.quantile(estimates, 0.025)),
            float(np.quantile(estimates, 0.975)),
        ],
        "samples": samples,
        "seed": seed,
    }


def validation_area(group: list[DomainData], scored: dict, method: str) -> float:
    """Validation-only design criterion: mean exact-budget nDCG over budgets 0.1..0.9."""
    values = []
    for fold in range(5):
        per_budget = []
        for budget in CURVE_BUDGETS:
            domain_quality = []
            for data in group:
                fs = scored[data.domain][fold]
                v = data.folds[fold]["validation"]
                u_b, u_h = data.utilities[fs.low][v], data.utilities[fs.high][v]
                forced, score = data.forced[v], fs.scores[method][v]
                chosen = forced.copy()
                rest = int(round(budget * len(v))) - int(forced.sum())
                if rest > 0:
                    order = sorted(
                        (i for i in range(len(v)) if not forced[i]),
                        key=lambda i: (-score[i], data.ids[v[i]]),
                    )[:rest]
                    chosen[order] = True
                domain_quality.append(float(np.where(chosen, u_h, u_b).mean()))
            per_budget.append(np.mean(domain_quality))
        values.append(np.mean(per_budget))
    return float(np.mean(values))


def save_npz(path: Path, **arrays) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(path, **arrays)
