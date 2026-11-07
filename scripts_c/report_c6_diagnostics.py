"""Post-freeze random-30 and oracle exact-budget quality diagnostics."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import statistics
from collections import defaultdict
from pathlib import Path

from pegh.data.artifacts import atomic_json, file_hash, object_hash


def _random_score(query_id: str, seed: int) -> float:
    digest = hashlib.sha256(f"{seed}\0{query_id}".encode()).digest()
    return 1.0 - int.from_bytes(digest[:8], "big") / 2**64


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quality", default="results/oof/c6_final/per_query.csv")
    parser.add_argument("--output", default="results/oof/c6_final/random30_oracle.json")
    args = parser.parse_args()
    root = Path.cwd()
    freeze = json.loads((root / "results/frozen/c6_manifest.json").read_text(encoding="utf-8"))
    quality_path = root / args.quality
    rows = list(csv.DictReader(quality_path.open(encoding="utf-8", newline="")))
    by_method: dict[str, dict[tuple[str, int], dict[str, float]]] = defaultdict(
        lambda: defaultdict(dict)
    )
    for row in rows:
        by_method[row["method"]][(row["domain"], int(row["fold"]))][row["query_id"]] = float(
            row["ndcg_at_10"]
        )
    all_methods = {"bm25", "h_star", "s_star", "pe_gh"}
    if set(by_method) != all_methods:
        raise ValueError("C6 quality table must contain exactly the four registered methods")
    folds = {}
    per_seed_domain: dict[int, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    oracle_domain: dict[str, list[float]] = defaultdict(list)
    pegh_domain: dict[str, list[float]] = defaultdict(list)
    for domain in ("programmers", "unix"):
        for fold in range(5):
            key = (domain, fold)
            sparse = by_method["bm25"][key]
            h_star = by_method["h_star"][key]
            pegh = by_method["pe_gh"][key]
            if sparse.keys() != h_star.keys() or sparse.keys() != pegh.keys():
                raise ValueError("quality query IDs differ across methods")
            sidecar_path = root / f"results/oof_runs/pe_gh/{domain}/fold_{fold}.jsonl.meta.json"
            sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
            if sidecar["freeze_hash"] != freeze["freeze_hash"] or sidecar["query_count"] != len(
                sparse
            ):
                raise ValueError("PE-GH sidecar differs from frozen query set")
            budget = sidecar["dense_count"]
            if not 0 <= budget <= len(sparse):
                raise ValueError("invalid exact dense budget")
            oracle_ids = set(
                sorted(
                    sparse, key=lambda query_id: (-(h_star[query_id] - sparse[query_id]), query_id)
                )[:budget]
            )
            oracle_quality = statistics.fmean(
                h_star[query_id] if query_id in oracle_ids else sparse[query_id]
                for query_id in sparse
            )
            oracle_domain[domain].extend(
                h_star[query_id] if query_id in oracle_ids else sparse[query_id]
                for query_id in sparse
            )
            pegh_domain[domain].extend(pegh.values())
            seeds = {}
            for seed in range(30):
                random_ids = set(
                    sorted(sparse, key=lambda query_id: (-_random_score(query_id, seed), query_id))[
                        :budget
                    ]
                )
                values = [
                    h_star[query_id] if query_id in random_ids else sparse[query_id]
                    for query_id in sparse
                ]
                per_seed_domain[seed][domain].extend(values)
                seeds[str(seed)] = statistics.fmean(values)
            folds[f"{domain}.fold_{fold}"] = {
                "query_count": len(sparse),
                "exact_dense_count": budget,
                "pe_gh_ndcg_at_10": statistics.fmean(pegh.values()),
                "oracle_ndcg_at_10": oracle_quality,
                "random30_fold_ndcg_at_10": seeds,
            }
    per_seed = {}
    for seed in range(30):
        domains = {
            domain: statistics.fmean(per_seed_domain[seed][domain])
            for domain in ("programmers", "unix")
        }
        per_seed[str(seed)] = {
            "domains": domains,
            "macro_ndcg_at_10": statistics.fmean(domains.values()),
        }
    random_macro = [item["macro_ndcg_at_10"] for item in per_seed.values()]
    result = {
        "schema_version": "c6_post_freeze_diagnostics_v1",
        "mode": "batch_exact_budget_not_online_router",
        "selection_scope": "post_freeze_test_diagnostic_only",
        "freeze_hash": freeze["freeze_hash"],
        "quality_csv_sha256": file_hash(quality_path),
        "seed_count": 30,
        "seeds": list(range(30)),
        "budget_source": "frozen_pe_gh_test_dense_count_per_fold_domain",
        "tie_policy": "score_desc_query_id_asc",
        "folds": folds,
        "random30": {
            "per_seed": per_seed,
            "macro_mean_ndcg_at_10": statistics.fmean(random_macro),
            "macro_std_ndcg_at_10": statistics.pstdev(random_macro),
            "macro_min_ndcg_at_10": min(random_macro),
            "macro_max_ndcg_at_10": max(random_macro),
        },
        "oracle": {
            "domains": {
                domain: statistics.fmean(oracle_domain[domain])
                for domain in ("programmers", "unix")
            },
        },
        "pe_gh": {
            "domains": {
                domain: statistics.fmean(pegh_domain[domain]) for domain in ("programmers", "unix")
            },
        },
    }
    result["oracle"]["macro_ndcg_at_10"] = statistics.fmean(result["oracle"]["domains"].values())
    result["pe_gh"]["macro_ndcg_at_10"] = statistics.fmean(result["pe_gh"]["domains"].values())
    result["report_hash"] = object_hash(result)
    target = root / args.output
    if target.exists():
        raise FileExistsError("diagnostic report already exists")
    atomic_json(target, result)
    print(f"random30={result['random30']['macro_mean_ndcg_at_10']:.6f}")
    print(f"oracle={result['oracle']['macro_ndcg_at_10']:.6f}")
    print(f"pe_gh={result['pe_gh']['macro_ndcg_at_10']:.6f}")


if __name__ == "__main__":
    main()
