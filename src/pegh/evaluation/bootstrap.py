from __future__ import annotations

import random
from collections import defaultdict


def _quantile(values: list[float], probability: float) -> float:
    if not values or not 0 <= probability <= 1:
        raise ValueError("quantile needs samples and a probability in [0,1]")
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def paired_group_bootstrap(
    differences: dict[str, float],
    groups: dict[str, str] | None = None,
    *,
    samples: int = 10_000,
    seed: int = 20_261_019,
) -> dict:
    if samples < 1 or not differences:
        raise ValueError("bootstrap needs differences and at least one sample")
    groups = groups or {query_id: query_id for query_id in differences}
    if differences.keys() - groups.keys():
        raise ValueError("every query difference needs a group")
    grouped: dict[str, list[float]] = defaultdict(list)
    for query_id, difference in differences.items():
        grouped[groups[query_id]].append(difference)
    group_ids = sorted(grouped)
    generator = random.Random(seed)
    estimates = []
    for _ in range(samples):
        selected = [generator.choice(group_ids) for _ in group_ids]
        values = [value for group_id in selected for value in grouped[group_id]]
        estimates.append(sum(values) / len(values))
    point = sum(differences.values()) / len(differences)
    return {
        "query_count": len(differences),
        "group_count": len(group_ids),
        "samples": samples,
        "seed": seed,
        "mean_difference": point,
        "one_sided_lower_95": _quantile(estimates, 0.05),
        "two_sided_95": [_quantile(estimates, 0.025), _quantile(estimates, 0.975)],
    }


def macro_group_bootstrap(
    differences_by_domain: dict[str, dict[str, float]],
    groups_by_domain: dict[str, dict[str, str]],
    *,
    samples: int = 10_000,
    seed: int = 20_261_019,
) -> dict:
    """Bootstrap groups inside each domain, then macro-average domain estimates."""
    if samples < 1 or not differences_by_domain:
        raise ValueError("bootstrap needs domains and at least one sample")
    grouped_by_domain: dict[str, dict[str, list[float]]] = {}
    for domain, differences in sorted(differences_by_domain.items()):
        if not differences:
            raise ValueError(f"{domain}: bootstrap differences are empty")
        groups = groups_by_domain.get(domain, {})
        if differences.keys() - groups.keys():
            raise ValueError(f"{domain}: every query difference needs a group")
        grouped: dict[str, list[float]] = defaultdict(list)
        for query_id, difference in differences.items():
            grouped[groups[query_id]].append(difference)
        grouped_by_domain[domain] = dict(grouped)
    generator = random.Random(seed)
    estimates = []
    for _ in range(samples):
        domain_means = []
        for grouped in grouped_by_domain.values():
            group_ids = sorted(grouped)
            selected = [generator.choice(group_ids) for _ in group_ids]
            values = [value for group_id in selected for value in grouped[group_id]]
            domain_means.append(sum(values) / len(values))
        estimates.append(sum(domain_means) / len(domain_means))
    domain_points = [
        sum(values.values()) / len(values) for values in differences_by_domain.values()
    ]
    return {
        "domain_count": len(differences_by_domain),
        "query_count": sum(len(values) for values in differences_by_domain.values()),
        "group_count": sum(len(values) for values in grouped_by_domain.values()),
        "samples": samples,
        "seed": seed,
        "mean_difference": sum(domain_points) / len(domain_points),
        "one_sided_lower_95": _quantile(estimates, 0.05),
        "two_sided_95": [_quantile(estimates, 0.025), _quantile(estimates, 0.975)],
    }
