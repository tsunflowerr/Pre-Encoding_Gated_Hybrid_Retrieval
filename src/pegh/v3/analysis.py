"""Test-time analysis after every threshold is fixed: quality, matched budgets, curves."""

from __future__ import annotations

import numpy as np
from scipy.stats import spearmanr
from sklearn.metrics import roc_auc_score

from pegh.v3.pipeline import (
    CURVE_BUDGETS,
    MARGIN,
    RANDOM_SEEDS,
    DomainData,
    _test_frame,
    assemble,
    at_budget,
    bootstrap,
    macro,
)


def _summary(values: dict[str, np.ndarray], dense: dict[str, np.ndarray] | None = None) -> dict:
    result = {
        "macro_ndcg_at_10": macro(values),
        "domains": {d: float(v.mean()) for d, v in values.items()},
    }
    if dense is not None:
        total = sum(int(m.sum()) for m in dense.values())
        count = sum(len(m) for m in dense.values())
        result["dense_ratio"] = total / count
        result["dense_count"] = total
        result["domain_dense_ratio"] = {d: float(m.mean()) for d, m in dense.items()}
    return result


def static_test(group: list[DomainData], scored: dict, key: str) -> dict[str, np.ndarray]:
    """OOF test utilities of a static choice: a fixed method or a per-fold selection key."""
    result = {}
    for data in group:
        values = np.zeros(len(data.ids))
        for fold, fs in enumerate(scored[data.domain]):
            test = data.folds[fold]["test"]
            name = fs.choice.get(key, key) if key in fs.choice else key
            values[test] = data.utilities[name][test]
        result[data.domain] = values
    return result


def _counts(group: list[DomainData], outcome) -> dict:
    return {
        d.domain: [int(outcome.dense[d.domain][d.folds[f]["test"]].sum()) for f in range(5)]
        for d in group
    }


def analyze_group(group: list[DomainData], scored: dict, *, primary: str, gates: list[str]) -> dict:
    groups = {d.domain: d.groups for d in group}
    frames = {d.domain: _test_frame(d, scored) for d in group}
    u_b = {d: f[0] for d, f in frames.items()}
    u_h = {d: f[1] for d, f in frames.items()}
    u_s = {d: f[2] for d, f in frames.items()}
    keys = ["bm25", "dense", "h_star", "s_star", "p_star", "r_star", "s_star_all"]
    available = [
        k for k in keys if k in ("bm25", "dense") or k in scored[group[0].domain][0].choice
    ]
    statics = {k: static_test(group, scored, k) for k in available}
    references = {k: statics[k] for k in ("h_star", "s_star", "s_star_all") if k in statics}
    report = {
        "static": {k: _summary(v) for k, v in statics.items()},
        "routes": {
            "cheap": "per-fold " + scored[group[0].domain][0].low,
            "expensive": "per-fold high tier",
        },
        "fusion_choices": {
            d.domain: [
                {k: v for k, v in fs.choice.items() if k != "validation"} for fs in scored[d.domain]
            ]
            for d in group
        },
        "gain_distribution": {
            d: {
                "positive": float(np.mean(u_h[d] - u_b[d] > 0)),
                "zero": float(np.mean(u_h[d] == u_b[d])),
                "negative": float(np.mean(u_h[d] - u_b[d] < 0)),
                "mean_gain": float(np.mean(u_h[d] - u_b[d])),
            }
            for d in u_b
        },
        "operating_points": {},
    }
    routers = [*gates, "bm25_margin", "random_0"]
    outcomes = {m: assemble(group, scored, m) for m in routers}
    for method, outcome in outcomes.items():
        diff = {d: outcome.utility[d] - u_s[d] for d in u_s}
        test = bootstrap(diff, groups)
        report["operating_points"][method] = {
            **_summary(outcome.utility, outcome.dense),
            "vs_s_star": test,
            "noninferior_margin_0_01": test["one_sided_lower_95"] > -MARGIN,
            "domain_vs_s_star": {d: bootstrap({d: diff[d]}, groups) for d in diff},
            "vs_references": {
                k: bootstrap({d: outcome.utility[d] - ref[d] for d in ref}, groups)
                for k, ref in references.items()
            },
            "fold_status": [t["status"] for t in outcome.thresholds],
            "fold_budgets": [t.get("budget") for t in outcome.thresholds],
            "dense_counts": _counts(group, outcome),
        }
    counts = _counts(group, outcomes[primary])
    matched = {m: at_budget(group, scored, m, counts) for m in [*gates, "bm25_margin", "oracle"]}
    random_runs = [at_budget(group, scored, f"random_{s}", counts) for s in RANDOM_SEEDS]
    random_mean = {d: np.mean([r[d] for r in random_runs], axis=0) for d in u_b}
    base = matched[primary]
    report["matched_budget"] = {
        "reference": primary,
        "dense_counts": counts,
        "methods": {
            m: {"macro_ndcg_at_10": macro(v), "domains": {d: float(x.mean()) for d, x in v.items()}}
            for m, v in matched.items()
        },
        "random30": {
            "macro_mean": float(np.mean([macro(r) for r in random_runs])),
            "macro_sd": float(np.std([macro(r) for r in random_runs], ddof=1)),
        },
        "primary_minus": {
            m: bootstrap({d: base[d] - v[d] for d in base}, groups)
            for m, v in {**matched, "random30_mean": random_mean}.items()
            if m != primary
        },
    }
    curves = {}
    for method in [*gates, "bm25_margin", "oracle"]:
        curves[method] = [
            macro(at_budget(group, scored, method, {d.domain: [b] * 5 for d in group}))
            for b in CURVE_BUDGETS
        ]
    curves["random30"] = [
        float(
            np.mean(
                [
                    macro(
                        at_budget(group, scored, f"random_{s}", {d.domain: [b] * 5 for d in group})
                    )
                    for s in RANDOM_SEEDS
                ]
            )
        )
        for b in CURVE_BUDGETS
    ]
    report["curves"] = {"budgets": list(CURVE_BUDGETS), "macro_ndcg_at_10": curves}
    report["curve_area"] = {m: float(np.mean(v)) for m, v in curves.items()}
    ranking = {}
    for method in [*gates, "bm25_margin"]:
        rho, auc = [], []
        for d in group:
            for fold, fs in enumerate(scored[d.domain]):
                test = d.folds[fold]["test"]
                gain = d.utilities[fs.high][test] - d.utilities[fs.low][test]
                score = fs.scores[method][test]
                rho.append(float(spearmanr(score, gain).statistic))
                if 0 < (gain > 0).sum() < len(gain):
                    auc.append(float(roc_auc_score(gain > 0, score)))
        ranking[method] = {
            "spearman_gain": float(np.nanmean(rho)),
            "auc_gain_positive": float(np.mean(auc)),
        }
    report["score_quality"] = ranking
    errors = {}
    for d in u_b:
        gain = u_h[d] - u_b[d]
        dense = outcomes[primary].dense[d]
        positive = np.maximum(gain, 0)
        errors[d] = {
            "dense_ratio": float(dense.mean()),
            "missed_gain_per_query": float(np.sum(~dense * positive) / len(gain)),
            "harmful_dense_per_query": float(np.sum(dense * np.maximum(-gain, 0)) / len(gain)),
            "captured_positive_gain": float(np.sum(dense * positive) / max(positive.sum(), 1e-12)),
            "dense_calls_without_gain": int(np.sum(dense & (gain <= 0))),
        }
    report["routing_errors"] = {"method": primary, "domains": errors}
    return report
