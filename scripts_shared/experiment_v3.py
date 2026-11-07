"""Drive the v3 round: build fresh domains, develop gate features, confirm, benchmark.

Frozen v1 artifacts are read-only inputs. Every output goes under --root (outside Git).
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

from pegh.v3.workspace import DEV_DOMAINS, FRESH_DOMAINS, Workspace

DEFAULT_ROOT = Path.home() / ".cache/pegh/v3"
DEFAULT_DEV_ROOT = Path.home() / ".cache/pegh/integration-20261026"
DEFAULT_DEV_DENSE = Path.home() / ".cache/pegh/artifacts/final-v1"


def log(**fields) -> None:
    print(json.dumps({"time": time.strftime("%H:%M:%S"), **fields}, ensure_ascii=False), flush=True)


def _registration(encoder: str) -> tuple[str, str]:
    """(protocol under configs/v3, receipt under results) of an encoder's fresh confirmation."""
    if encoder == "minilm":
        return "preregistration_fresh.yaml", "preregistration.json"
    return f"preregistration_fresh_{encoder}.yaml", f"preregistration_{encoder}.json"


def _domains(ws: Workspace, encoder: str) -> tuple[str, ...]:
    """Fresh domains are processed for a non-primary encoder only after it is registered."""
    if encoder == "minilm" or ws.results(_registration(encoder)[1]).exists():
        return DEV_DOMAINS + FRESH_DOMAINS
    return DEV_DOMAINS


def build(ws: Workspace, args) -> None:
    from pegh.v3 import build as b

    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    for domain in FRESH_DOMAINS:
        b.fetch_domain(ws, domain)
        log(stage="fetch", domain=domain)
    splits = b.prepare_fresh_splits(ws)
    log(stage="splits", split_hash=splits["split_hash"])
    for domain in FRESH_DOMAINS:
        b.build_sparse(ws, domain)
        b.quality_cache(ws, "bm25", domain)
        log(stage="sparse", domain=domain)
    jobs = [("minilm", d) for d in FRESH_DOMAINS]
    if not args.skip_bge:
        jobs += [("bge_small", d) for d in _domains(ws, "bge_small")]
    for encoder, domain in jobs:
        started = time.perf_counter()
        b.build_dense(ws, encoder, domain, args.threads)
        b.quality_cache(ws, encoder, domain, threads=args.threads)
        log(
            stage="dense",
            encoder=encoder,
            domain=domain,
            seconds=round(time.perf_counter() - started),
        )


def proxy(ws: Workspace, args) -> None:
    """Distill static token tables and audit proxy fidelity against the real encoder.

    Fidelity uses only encoder outputs on fold-0 training queries, never relevance labels.
    """
    import numpy as np

    from contracts.io import iter_corpus, load_queries
    from pegh.data.artifacts import atomic_json
    from pegh.data.splits import fold_record
    from pegh.evaluation.runs import load_rankings
    from pegh.v3 import build as b
    from pegh.v3.proxy import StaticProxy, corpus_token_weights, distill_table, save_proxy

    path = ws.results("proxy_fidelity.json")
    report = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    for encoder in args.encoders:
        model = b._encoder(ws, encoder, args.threads)
        table = distill_table(model.model)
        domains = _domains(ws, encoder)
        for domain in (d for d in domains if not args.domains or d in args.domains):
            target = ws.root / "artifacts/proxy" / encoder / domain
            if not (target / "manifest.json").exists():
                texts = (doc.text for doc in iter_corpus(ws.raw(domain) / "corpus.jsonl", domain))
                weights = corpus_token_weights(model.model.tokenizer, texts)
                save_proxy(
                    target,
                    table,
                    weights,
                    {"encoder": encoder, "domain": domain, "model_revision": model.config.revision},
                )
            vectors, rows, _ = b.load_dense_vectors(ws.dense(encoder, domain))
            split = json.loads(ws.split_manifest(domain).read_text(encoding="utf-8"))
            train_ids = set(fold_record(split, 0)["domains"][domain]["train"])
            queries = [
                q
                for q in load_queries(ws.raw(domain) / "queries.jsonl", domain)
                if q.query_id in train_ids
            ][: args.fidelity_queries]
            sparse, _ = load_rankings(ws.quality("bm25", domain), domain=domain)
            true = model.encode([q.text for q in queries])
            result = {}
            for weighting in ("uniform", "sif"):
                px = StaticProxy(target, model.model.tokenizer, weighting=weighting)
                pearson, overlap, direct = [], [], []
                for query, vector in zip(queries, true, strict=True):
                    hits = sparse[query.query_id].hits
                    if len(hits) < 10:
                        continue
                    candidates = vectors[[rows[h.doc_id] for h in hits]]
                    approx = px.embed(query.text)
                    real_cos, proxy_cos = candidates @ vector, candidates @ approx
                    pearson.append(float(np.corrcoef(real_cos, proxy_cos)[0, 1]))
                    top_real = set(np.argsort(-real_cos)[:10])
                    overlap.append(len(top_real & set(np.argsort(-proxy_cos)[:10])) / 10)
                    direct.append(float(vector @ approx))
                result[weighting] = {
                    "queries": len(pearson),
                    "mean_pearson_candidate_scores": float(np.mean(pearson)),
                    "mean_top10_overlap": float(np.mean(overlap)),
                    "mean_cos_proxy_vs_true_query": float(np.mean(direct)),
                }
            report[f"{encoder}/{domain}"] = result
            log(
                stage="proxy",
                encoder=encoder,
                domain=domain,
                **{k: v["mean_pearson_candidate_scores"] for k, v in result.items()},
            )
    atomic_json(path, report)


def features(ws: Workspace, args) -> None:
    """Materialize v1 + QPP + proxy features for every query; check v1 parity on dev data."""
    import numpy as np
    import yaml

    from contracts.io import load_queries
    from pegh.data.artifacts import atomic_json
    from pegh.evaluation.runs import load_rankings
    from pegh.gating.features import QueryFeatureExtractor
    from pegh.sparse.fast import open_backend
    from pegh.v3 import build as b
    from pegh.v3.features import PROXY_NAMES, QPP_NAMES, ExtendedFeatureExtractor
    from pegh.v3.pipeline import save_npz
    from pegh.v3.proxy import StaticProxy

    protocol = yaml.safe_load(
        (ws.repo / "configs/gating/protocol_v1.yaml").read_text(encoding="utf-8")
    )
    parity = {}
    for encoder in args.encoders:
        model = b._encoder(ws, encoder, 1)
        domains = _domains(ws, encoder)
        for domain in (d for d in domains if not args.domains or d in args.domains):
            output = ws.results("features", encoder, f"{domain}.npz")
            backend = open_backend(ws.sparse(domain), execution="numpy")
            base = QueryFeatureExtractor(protocol["features"], backend.tokenizer)
            vectors, rows, _ = b.load_dense_vectors(ws.dense(encoder, domain))
            extractor = ExtendedFeatureExtractor(
                base,
                backend,
                ("v1", "qpp", "proxy"),
                proxy=StaticProxy(
                    ws.root / "artifacts/proxy" / encoder / domain, model.model.tokenizer
                ),
                doc_vectors=vectors,
                doc_rows=rows,
            )
            sparse, _ = load_rankings(ws.quality("bm25", domain), domain=domain)
            queries = sorted(
                load_queries(ws.raw(domain) / "queries.jsonl", domain), key=lambda q: q.query_id
            )
            x = np.array(
                [
                    extractor.transform(q, sparse[q.query_id], backend.query_stats(q)).values
                    for q in queries
                ]
            )
            ids = np.array([q.query_id for q in queries])
            v1, qpp = x[:, :21], x[:, 21 : 21 + len(QPP_NAMES)]
            save_npz(output, ids=ids, v1=v1, qpp=qpp, proxy=x[:, 21 + len(QPP_NAMES) :])
            if ws.is_dev(domain):
                frozen = {}
                for line in (
                    (ws.dev_root / "results/features" / f"{domain}.jsonl")
                    .read_text(encoding="utf-8")
                    .splitlines()
                ):
                    record = json.loads(line)
                    frozen[record["query_id"]] = record["values"]
                reference = np.array([frozen[q] for q in ids])
                parity[f"{encoder}/{domain}"] = float(np.abs(reference - v1).max())
            log(
                stage="features",
                encoder=encoder,
                domain=domain,
                queries=len(ids),
                proxy_columns=len(PROXY_NAMES),
            )
    if parity:
        path = ws.results("features", "v1_parity.json")
        if path.exists():
            parity = {**json.loads(path.read_text(encoding="utf-8")), **parity}
        atomic_json(path, parity)
        log(stage="features", v1_parity_max_abs=parity)


def tiers(ws: Workspace, args) -> None:
    """Per-query nDCG@10 of the cascade tiers at every alpha (offline; labels by fold later).

    Queries are encoded one at a time exactly as online, so online rankings must match.
    """
    import numpy as np

    from contracts.io import load_queries
    from pegh.data.qrels import load_qrels
    from pegh.evaluation.metrics import query_metrics
    from pegh.evaluation.runs import load_rankings
    from pegh.v3 import build as b
    from pegh.v3.pipeline import ALPHAS, save_npz
    from pegh.v3.proxy import StaticProxy
    from pegh.v3.rescore import candidate_fusion, rescore_identity, rescored_ranking

    for encoder in args.encoders:
        model = b._encoder(ws, encoder, args.threads)
        domains = _domains(ws, encoder)
        for domain in (d for d in domains if not args.domains or d in args.domains):
            output = ws.results("tiers", encoder, f"{domain}.npz")
            if output.exists():
                continue
            queries = sorted(
                load_queries(ws.raw(domain) / "queries.jsonl", domain), key=lambda q: q.query_id
            )
            qrels = load_qrels(ws.raw(domain) / "qrels.tsv", domain)
            sparse, _ = load_rankings(ws.quality("bm25", domain), domain=domain)
            vectors, rows, manifest = b.load_dense_vectors(ws.dense(encoder, domain))
            proxy_model = StaticProxy(
                ws.root / "artifacts/proxy" / encoder / domain, model.model.tokenizer
            )
            proxy_id = rescore_identity("static_proxy", proxy_model.identity)
            true_id = rescore_identity("query_encoder", manifest["embedding_fingerprint"])
            arrays = {f"{kind}_cc_{a:.1f}": [] for kind in ("proxy", "rescore") for a in ALPHAS}
            started = time.perf_counter()
            for query in queries:
                ranking = sparse[query.query_id]
                vector = model.encode([query.text])[0] if query.text.strip() else None
                cheap = rescored_ranking(
                    ranking, proxy_model.embed(query.text), vectors, rows, proxy_id
                )
                full = (
                    rescored_ranking(ranking, vector, vectors, rows, true_id)
                    if vector is not None
                    else ranking
                )
                for alpha in ALPHAS:
                    for kind, other in (("proxy", cheap), ("rescore", full)):
                        fused = candidate_fusion(ranking, other, alpha)
                        arrays[f"{kind}_cc_{alpha:.1f}"].append(
                            query_metrics(query.query_id, domain, qrels, fused).ndcg_at_10
                        )
            save_npz(
                output,
                ids=np.array([q.query_id for q in queries]),
                **{k: np.array(v) for k, v in arrays.items()},
            )
            log(
                stage="tiers",
                encoder=encoder,
                domain=domain,
                seconds=round(time.perf_counter() - started),
                **{
                    k: round(float(np.mean(v)), 4)
                    for k, v in arrays.items()
                    if k.endswith(("0.3", "0.5", "0.7"))
                },
            )


def _load_group(ws: Workspace, domains, encoder: str):
    import numpy as np

    from pegh.v3.pipeline import load_domain

    group = []
    for domain in domains:
        with np.load(ws.results("features", encoder, f"{domain}.npz")) as stored:
            features = {k: stored[k] for k in stored.files}
        tier_path = ws.results("tiers", encoder, f"{domain}.npz")
        tier_values = None
        if tier_path.exists():
            with np.load(tier_path) as stored:
                tier_values = {k: stored[k] for k in stored.files}
        group.append(load_domain(ws, domain, encoder, features, tier_values))
    return group


CASCADE_CANDIDATES = (
    "v1_ridge",
    "v1_logistic",
    "v3_ridge_qpp",
    "v3_ridge_proxy",
    "v3_ridge_all",
    "v3_logistic_qpp",
    "v3_logistic_proxy",
    "v3_logistic_all",
)


def _choose(areas: dict, candidates) -> str:
    """Pre-declared rule: within 0.0005 of the best, fewer feature groups, then Ridge, then name."""
    from pegh.v3.pipeline import GATES

    best = max(areas[m] for m in candidates)
    tied = [m for m in candidates if best - areas[m] <= 0.0005]
    return min(tied, key=lambda m: (len(GATES[m][1]), GATES[m][0] != "ridge", m))


def develop(ws: Workspace, args) -> None:
    """Choose v3 configurations on development VALIDATION rows only (no test labels)."""
    import numpy as np

    from pegh.data.artifacts import atomic_json, object_hash
    from pegh.v3.pipeline import GATES, V3_CANDIDATES, score_group, select_fusion, validation_area

    encoder = args.encoders[0]
    group = _load_group(ws, DEV_DOMAINS, encoder)
    report = {
        "schema_version": "v3_development_selection_2",
        "selection_scope": "development_validation_only",
        "test_labels_used": False,
        "encoder": encoder,
        "criterion": "mean exact-budget validation nDCG@10 over budgets 0.1..0.9, macro, 5 folds",
        "tie_rule": "within 0.0005: fewer feature groups, then ridge, then name",
        "modes": {},
    }
    for mode, candidates in (("v1", V3_CANDIDATES), ("cascade", CASCADE_CANDIDATES)):
        scored = score_group(group, tuple(GATES), mode=mode)
        areas = {m: validation_area(group, scored, m) for m in (*GATES, "bm25_margin", "oracle")}
        areas["random30"] = float(
            np.mean([validation_area(group, scored, f"random_{s}") for s in range(30)])
        )
        report["modes"][mode] = {"validation_area": areas, "chosen": _choose(areas, candidates)}
        for name, value in sorted(areas.items(), key=lambda item: -item[1]):
            log(stage="develop", mode=mode, method=name, validation_area=round(value, 6))
    statics = {}
    for key in ("bm25", "h_star", "p_star", "r_star", "s_star", "s_star_all"):
        per_fold = []
        for fold in range(5):
            means = []
            for data in group:
                choice = select_fusion(data, fold)
                name = choice.get(key, key)
                means.append(float(data.utilities[name][data.folds[fold]["validation"]].mean()))
            per_fold.append(float(np.mean(means)))
        statics[key] = float(np.mean(per_fold))
    report["static_validation_macro"] = statics
    report["fold_choices"] = {
        data.domain: [
            {k: v for k, v in select_fusion(data, f).items() if k != "validation"} for f in range(5)
        ]
        for data in group
    }
    report["report_hash"] = object_hash(report)
    atomic_json(ws.results(f"develop_{encoder}.json"), report)
    log(
        stage="develop",
        statics=statics,
        chosen={m: r["chosen"] for m, r in report["modes"].items()},
    )


def evaluate(ws: Workspace, args) -> None:
    """Score all routers OOF on a domain group; dev results are exploratory reassessment."""
    from pegh.data.artifacts import atomic_json, object_hash
    from pegh.v3.analysis import analyze_group
    from pegh.v3.pipeline import GATES, score_group

    encoder = args.encoders[0]
    domains = DEV_DOMAINS if args.group == "dev" else FRESH_DOMAINS
    registered_tests = None
    if args.group == "fresh":
        prereg = ws.results(_registration(encoder)[1])
        if not prereg.exists():
            raise FileNotFoundError(
                "register the confirmation protocol before scoring fresh test labels"
            )
        receipt = json.loads(prereg.read_text(encoding="utf-8"))
        primaries = receipt["primary_gates"]
        registered_tests = receipt["spec"].get("hypothesis_tests")
    else:
        selection = json.loads(ws.results(f"develop_{encoder}.json").read_text(encoding="utf-8"))
        primaries = {"v1": "v1_ridge", "cascade": selection["modes"]["cascade"]["chosen"]}
    group = _load_group(ws, domains, encoder)
    report = {
        "schema_version": "v3_evaluation_2",
        "group": args.group,
        "domains": list(domains),
        "encoder": encoder,
        "primaries": primaries,
        "inference_scope": (
            "preregistered_confirmation_on_unseen_domains"
            if args.group == "fresh"
            else "exploratory_reassessment_of_previously_observed_test_not_fresh_confirmation"
        ),
        "modes": {},
    }
    scored_by_mode = {}
    for mode, primary in primaries.items():
        scored = scored_by_mode[mode] = score_group(group, tuple(GATES), mode=mode)
        report["modes"][mode] = analyze_group(group, scored, primary=primary, gates=list(GATES))
        ops = report["modes"][mode]["operating_points"]
        for method, op in sorted(ops.items(), key=lambda item: -item[1]["macro_ndcg_at_10"]):
            log(
                stage="evaluate",
                mode=mode,
                method=method,
                ndcg=round(op["macro_ndcg_at_10"], 6),
                dense=round(op["dense_ratio"], 4),
                lower_vs_s=round(op["vs_s_star"]["one_sided_lower_95"], 5),
            )
    report["hypotheses"] = hypotheses(group, scored_by_mode["v1"], report, registered_tests)
    for name, result in report["hypotheses"]["tests"].items():
        log(
            stage="hypothesis",
            name=name,
            estimate=round(result["estimate"], 5),
            p=result["p_value"],
            holm_reject=result["holm_reject"],
        )
    report["report_hash"] = object_hash(report)
    atomic_json(ws.results(f"evaluation_{args.group}_{encoder}.json"), report)


def hypotheses(group, scored, report: dict, names=None, alpha: float = 0.05) -> dict:
    """Registered tests (default H1-H5) with one-sided bootstrap p-values and Holm's rule."""
    from pegh.v3.analysis import static_test
    from pegh.v3.pipeline import bootstrap

    groups = {d.domain: d.groups for d in group}
    static = {k: static_test(group, scored, k) for k in ("bm25", "h_star", "p_star", "r_star")}

    def diff(a, b):
        return bootstrap({d: static[a][d] - static[b][d] for d in static[a]}, groups)

    v1 = report["modes"]["v1"]

    def vs_s_star():
        return v1["operating_points"][v1["matched_budget"]["reference"]]["vs_s_star"]

    def vs_random(mode):
        return lambda: report["modes"][mode]["matched_budget"]["primary_minus"]["random30_mean"]

    available = {
        "H1_r_star_noninferior_to_h_star": (
            lambda: diff("r_star", "h_star"),
            "p_noninferiority_0_01",
        ),
        "H2_p_star_superior_to_bm25": (lambda: diff("p_star", "bm25"), "p_superiority"),
        "H3_pe_gh_v1_noninferior_to_s_star": (vs_s_star, "p_noninferiority_0_01"),
        "H4_pe_gh_v1_beats_random_matched": (vs_random("v1"), "p_superiority"),
        "H5_cascade_gate_beats_random_matched": (vs_random("cascade"), "p_superiority"),
        "B1_h_star_superior_to_r_star": (lambda: diff("h_star", "r_star"), "p_superiority"),
        "B2_p_star_superior_to_bm25": (lambda: diff("p_star", "bm25"), "p_superiority"),
        "B3_pe_gh_v1_noninferior_to_s_star": (vs_s_star, "p_noninferiority_0_01"),
        "B4_pe_gh_v1_beats_random_matched": (vs_random("v1"), "p_superiority"),
    }
    names = list(names or [n for n in available if n.startswith("H")])
    tests = {name: (available[name][0](), available[name][1]) for name in names}
    result = {
        name: {
            "estimate": t["mean_difference"],
            "two_sided_95": t["two_sided_95"],
            "one_sided_lower_95": t["one_sided_lower_95"],
            "p_value": t[key],
            "p_kind": key,
        }
        for name, (t, key) in tests.items()
    }
    ordered = sorted(result, key=lambda n: result[n]["p_value"])
    still = True
    for rank, name in enumerate(ordered):
        threshold = alpha / (len(ordered) - rank)
        still = still and result[name]["p_value"] <= threshold
        result[name]["holm_threshold"] = threshold
        result[name]["holm_reject"] = still
    return {"family_alpha": alpha, "procedure": "holm_step_down", "tests": result}


ONLINE_METHODS = ("h_star", "pe_gh", "bm25", "proxy", "rescore", "cascade")


def online_plan(ws: Workspace, args) -> None:
    """Export cascade gates, bind them to offline scores, and write benchmark registries."""
    import numpy as np
    import yaml

    from contracts.io import load_queries
    from pegh.data.artifacts import atomic_json, file_hash, object_hash
    from pegh.evaluation.runs import load_rankings
    from pegh.v3 import build as b
    from pegh.v3.online import export_gate
    from pegh.v3.pipeline import fit_gate, score_group, select_threshold
    from pegh.v3.proxy import StaticProxy
    from pegh.v3.rescore import candidate_fusion, rescore_identity, rescored_ranking

    protocol_path = ws.repo / "configs/gating/protocol_v1.yaml"
    protocol = yaml.safe_load(protocol_path.read_text(encoding="utf-8"))
    group = _load_group(ws, DEV_DOMAINS, "minilm")
    scored = score_group(group, ("v1_ridge",), mode="cascade")
    thresholds = [select_threshold(group, scored, "v1_ridge", f)["threshold"] for f in range(5)]
    model = b._encoder(ws, "minilm", args.threads)
    for data in group:
        domain = data.domain
        queries = {q.query_id: q for q in load_queries(ws.raw(domain) / "queries.jsonl", domain)}
        sparse_cache, _ = load_rankings(ws.quality("bm25", domain), domain=domain)
        vectors, rows, dense_manifest = b.load_dense_vectors(ws.dense("minilm", domain))
        proxy_dir = ws.root / "artifacts/proxy/minilm" / domain
        proxy = StaticProxy(proxy_dir, model.model.tokenizer)
        ids = {
            "proxy": rescore_identity("static_proxy", proxy.identity),
            "query": rescore_identity("query_encoder", dense_manifest["embedding_fingerprint"]),
        }
        sparse_sha = file_hash(ws.sparse(domain) / "index.sqlite3")
        dense_sha = file_hash(ws.dense("minilm", domain) / "index.faiss")
        row_of = {q: n for n, q in enumerate(data.ids)}
        for fold in range(5):
            scaler, gate_model, choice = fit_gate(data, fold, "cascade", "v1_ridge")
            evaluate = np.concatenate([data.folds[fold]["validation"], data.folds[fold]["test"]])
            refit = gate_model.predict(scaler.transform(data.matrix(("v1",))[evaluate]))
            if not np.array_equal(refit, scored[domain][fold].scores["v1_ridge"][evaluate]):
                raise ValueError("exported gate does not reproduce the evaluated scores")
            gate_dir = ws.root / "artifacts/gates/cascade_v1_ridge" / f"{domain}_fold_{fold}"
            gate = export_gate(
                gate_dir,
                scaler,
                gate_model,
                {
                    "schema_version": "v3_cascade_gate_1",
                    "method": "cascade_v1_ridge",
                    "fold": fold,
                    "domain": domain,
                    "feature_count": 21,
                    "feature_schema_hash": protocol["features"]["schema_hashes"]["full"],
                    "reference_hash": object_hash(choice),
                    "threshold": thresholds[fold],
                    "low": choice["low"],
                    "high": choice["r_star"],
                    "train_count": len(data.folds[fold]["train"]),
                },
            )
            v1_path = (
                ws.repo / f"docs/integration/2026-10-26/online-manifests/{domain}_fold_{fold}.json"
            )
            registry = []
            for entry in json.loads(v1_path.read_text(encoding="utf-8"))["registry"]:
                if entry["id"] in ("h_star", "pe_gh"):
                    if "protocol_path" in entry["kwargs"]:
                        entry["kwargs"]["protocol_path"] = str(protocol_path)
                    registry.append(entry)
            common = {
                "domain": domain,
                "fold": fold,
                "sparse_dir": str(ws.sparse(domain)),
                "dense_dir": str(ws.dense("minilm", domain)),
                "expected_sparse_sha256": sparse_sha,
                "expected_dense_sha256": dense_sha,
                "cache_folder": str(ws.root.parent / "models"),
            }
            proxy_args = {
                "proxy_dir": str(proxy_dir),
                "expected_proxy_hash": proxy.manifest["manifest_hash"],
                "low": choice["low"],
            }
            factory = "pegh.v3.online:create_tier_method"
            cascade_args = {
                **common,
                **proxy_args,
                "route": "cascade",
                "high": choice["r_star"],
                "gate_dir": str(gate_dir),
                "expected_gate_hash": gate["manifest_hash"],
                "threshold": thresholds[fold],
                "protocol_path": str(protocol_path),
            }
            registry += [
                {"id": "bm25", "factory": factory, "kwargs": {**common, "route": "bm25"}},
                {
                    "id": "proxy",
                    "factory": factory,
                    "kwargs": {**common, **proxy_args, "route": "proxy"},
                },
                {
                    "id": "rescore",
                    "factory": factory,
                    "kwargs": {**common, "route": "rescore", "high": choice["r_star"]},
                    "require_dense_warmup": True,
                },
                {
                    "id": "cascade",
                    "factory": factory,
                    "kwargs": cascade_args,
                    "require_dense_warmup": True,
                },
            ]
            test_ids = [data.ids[i] for i in data.folds[fold]["test"]]
            warmup_ids = sorted(data.ids[i] for i in data.folds[fold]["validation"])[:50]
            low_alpha = None if choice["low"] == "bm25" else float(choice["low"].split("_")[-1])
            high_alpha = float(choice["r_star"].split("_")[-1])
            scores = scored[domain][fold].scores["v1_ridge"]
            expected = {}
            for qid in test_ids:
                query, sparse = queries[qid], sparse_cache[qid]
                cheap = sparse
                if low_alpha is not None:
                    other = rescored_ranking(
                        sparse, proxy.embed(query.text), vectors, rows, ids["proxy"]
                    )
                    cheap = candidate_fusion(sparse, other, low_alpha)
                vector = model.encode([query.text])[0]
                full = candidate_fusion(
                    sparse,
                    rescored_ranking(sparse, vector, vectors, rows, ids["query"]),
                    high_alpha,
                )
                row = row_of[qid]
                use_dense = bool(data.forced[row] or scores[row] > thresholds[fold])
                expected[qid] = {
                    "bm25": object_hash([h.doc_id for h in sparse.hits]),
                    "proxy": object_hash([h.doc_id for h in cheap.hits]),
                    "rescore": object_hash([h.doc_id for h in full.hits]),
                    "cascade": object_hash([h.doc_id for h in (full if use_dense else cheap).hits]),
                    "cascade_dense": use_dense,
                }
            for method in ("h_star", "pe_gh"):
                runs, _ = load_rankings(
                    ws.dev_root / f"results/oof_runs/{method}/{domain}/fold_{fold}.jsonl",
                    domain=domain,
                )
                for qid in test_ids:
                    expected[qid][method] = object_hash([h.doc_id for h in runs[qid].hits])
            atomic_json(
                ws.results("online_plans", f"{domain}_fold_{fold}.json"),
                {
                    "registry": registry,
                    "query_ids": test_ids,
                    "warmup_ids": warmup_ids,
                    "expected": expected,
                    "choice": choice,
                    "threshold": thresholds[fold],
                },
            )
            dense_share = float(np.mean([e["cascade_dense"] for e in expected.values()]))
            log(
                stage="online-plan",
                domain=domain,
                fold=fold,
                low=choice["low"],
                high=choice["r_star"],
                cascade_dense=round(dense_share, 3),
            )


def online(ws: Workspace, args) -> None:
    """Run the isolated-worker benchmark for every planned fold/domain (resumable)."""
    from contracts.io import load_queries
    from pegh.profiling.runner import run_benchmark
    from pegh.profiling.runtime import RuntimeSettings

    settings = RuntimeSettings.from_yaml(ws.repo / "configs/runtime/windows-physical4-local.yaml")
    if args.repetitions:
        settings = RuntimeSettings(**{**settings.__dict__, "repetitions": args.repetitions})
    plans = sorted(ws.results("online_plans").glob("*.json"))
    folder = "online"
    if args.detailed:
        # Separate instrumented sample (fold 0, one repeat); never pooled with main timing.
        settings = RuntimeSettings(
            **{**settings.__dict__, "repetitions": 1, "detailed_stages": True}
        )
        plans = [p for p in plans if p.stem.endswith("_fold_0")]
        folder = "online_stages"
    for plan_path in plans:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        output = ws.results(folder, plan_path.stem)
        manifest = output / "manifest.json"
        if manifest.exists() and json.loads(manifest.read_text())["status"] == "complete":
            continue
        if output.exists():
            output.rename(output.with_name(output.name + f".interrupted.{int(time.time())}"))
        domain = plan_path.stem.rsplit("_fold_", 1)[0]
        queries = {q.query_id: q for q in load_queries(ws.raw(domain) / "queries.jsonl", domain)}
        started = time.perf_counter()
        run_benchmark(
            plan["registry"],
            [queries[q] for q in plan["query_ids"]],
            [queries[q] for q in plan["warmup_ids"]],
            output,
            settings,
            split="test",
            fold=int(plan_path.stem.rsplit("_", 1)[1]),
        )
        log(
            stage="online",
            run=plan_path.stem,
            minutes=round((time.perf_counter() - started) / 60, 1),
        )


def online_report(ws: Workspace, args) -> None:
    """Aggregate raw requests: latency, CPU, RSS, dense ratio, and ranking parity."""
    import numpy as np

    from pegh.data.artifacts import atomic_json

    rows = {m: {d: [] for d in DEV_DOMAINS} for m in ONLINE_METHODS}
    rss = {m: dict.fromkeys(DEV_DOMAINS, 0) for m in ONLINE_METHODS}
    mismatches, checked = 0, 0
    for plan_path in sorted(ws.results("online_plans").glob("*.json")):
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        domain = plan_path.stem.rsplit("_fold_", 1)[0]
        run = ws.results("online", plan_path.stem)
        manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
        if manifest["status"] != "complete":
            raise ValueError(f"{run} is not complete")
        for worker in manifest["workers"]:
            folder = run / worker["directory"]
            receipt = json.loads((folder / "worker.json").read_text(encoding="utf-8"))
            method = worker["method"]
            rss[method][domain] = max(rss[method][domain], receipt["memory"]["os_peak_rss_bytes"])
            for line in (folder / "requests.jsonl").read_text(encoding="utf-8").splitlines():
                request = json.loads(line)
                expected = plan["expected"][request["query_id"]]
                checked += 1
                if request["ranking_hash"] != expected[method] or (
                    method == "cascade" and request["use_dense"] != expected["cascade_dense"]
                ):
                    mismatches += 1
                rows[method][domain].append(
                    (
                        request["query_id"],
                        request["total_ns"] / 1e6,
                        request["process_cpu_ns"] / 1e6,
                        request["use_dense"],
                    )
                )
    summary = {}
    for method in ONLINE_METHODS:
        for scope in (*DEV_DOMAINS, "all"):
            scoped = DEV_DOMAINS if scope == "all" else (scope,)
            data = [r for d in scoped for r in rows[method][d]]
            latency = np.array([r[1] for r in data])
            summary.setdefault(method, {})[scope] = {
                "requests": len(data),
                "mean_ms": float(latency.mean()),
                "p50_ms": float(np.percentile(latency, 50)),
                "p95_ms": float(np.percentile(latency, 95)),
                "cpu_mean_ms": float(np.mean([r[2] for r in data])),
                "dense_ratio": float(np.mean([r[3] for r in data])),
                "peak_rss_mib": max(rss[method][d] for d in scoped) / 2**20,
            }
    rng = np.random.default_rng(42)
    reductions = {}
    for method in ONLINE_METHODS[1:]:
        pairs = []
        for domain in DEV_DOMAINS:
            base, cand = {}, {}
            for qid, ms, _, _ in rows["h_star"][domain]:
                base[qid] = base.get(qid, 0.0) + ms
            for qid, ms, _, _ in rows[method][domain]:
                cand[qid] = cand.get(qid, 0.0) + ms
            pairs += [(base[q], cand[q]) for q in base]
        pairs = np.array(pairs)
        draws = rng.integers(0, len(pairs), size=(10_000, len(pairs)))
        ratio = 1 - pairs[draws, 1].sum(axis=1) / pairs[draws, 0].sum(axis=1)
        reductions[method] = {
            "mean_reduction_vs_h_star": float(1 - pairs[:, 1].sum() / pairs[:, 0].sum()),
            "ci95_query_bootstrap": [
                float(np.quantile(ratio, 0.025)),
                float(np.quantile(ratio, 0.975)),
            ],
        }
    stages = {}
    for run in sorted(ws.results("online_stages").glob("*_fold_0")):
        manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
        for worker in manifest["workers"]:
            for line in (run / worker["directory"] / "requests.jsonl").read_text().splitlines():
                request = json.loads(line)
                branch = "dense" if request["use_dense"] else "skip"
                bucket = stages.setdefault(worker["method"], {}).setdefault(branch, [])
                bucket.append(
                    {
                        k.removesuffix("_ns"): (request[k] or 0) / 1e6
                        for k in request
                        if k.endswith("_ns")
                    }
                )
    stage_means = {
        method: {
            branch: {
                "requests": len(items),
                **{k: float(np.mean([i[k] for i in items])) for k in items[0]},
            }
            for branch, items in branches.items()
        }
        for method, branches in stages.items()
    }
    report = {
        "schema_version": "v3_online_report_1",
        "stage_sample_fold0_one_repeat": stage_means,
        "requests_checked": checked,
        "ranking_or_route_mismatches": mismatches,
        "summary": summary,
        "mean_reduction_vs_h_star": reductions,
    }
    atomic_json(ws.results("online_report.json"), report)
    log(stage="online-report", checked=checked, mismatches=mismatches)
    for method in ONLINE_METHODS:
        s = summary[method]["all"]
        log(
            method=method,
            mean=round(s["mean_ms"], 3),
            p95=round(s["p95_ms"], 3),
            cpu=round(s["cpu_mean_ms"], 2),
            dense=round(s["dense_ratio"], 4),
            rss=round(s["peak_rss_mib"], 1),
        )


def throughput(ws: Workspace, args) -> None:
    """Queries/second with four single-thread server processes on the four pinned cores."""
    from contracts.io import load_queries
    from pegh.data.artifacts import atomic_json
    from pegh.v3.throughput import measure

    report = {"processes": 4, "affinity": [0, 2, 4, 6], "folds": [0, 1], "methods": {}}
    for method in ONLINE_METHODS:
        runs = []
        for domain in DEV_DOMAINS:
            queries = {
                q.query_id: q for q in load_queries(ws.raw(domain) / "queries.jsonl", domain)
            }
            for fold in (0, 1):
                plan = json.loads(
                    ws.results("online_plans", f"{domain}_fold_{fold}.json").read_text(
                        encoding="utf-8"
                    )
                )
                entry = next(e for e in plan["registry"] if e["id"] == method)
                stream = [queries[q].__dict__ for q in plan["query_ids"]]
                runs.append(measure(entry, stream, processes=4, affinity=[0, 2, 4, 6]))
        total = sum(r["queries"] for r in runs)
        wall = sum(r["wall_seconds"] for r in runs)
        report["methods"][method] = {
            "runs": runs,
            "qps": total / wall,
            "cpu_ms_per_query": sum(r["cpu_ms_per_query"] * r["queries"] for r in runs) / total,
            "dense_ratio": sum(r["dense_ratio"] * r["queries"] for r in runs) / total,
        }
        log(
            stage="throughput",
            method=method,
            qps=round(total / wall, 1),
            cpu=round(report["methods"][method]["cpu_ms_per_query"], 2),
        )
    atomic_json(ws.results("throughput.json"), report)


FACT_FILES = (
    "proxy_fidelity.json",
    "develop_minilm.json",
    "evaluation_dev_minilm.json",
    "preregistration.json",
    "evaluation_fresh_minilm.json",
    "online_report.json",
    "throughput.json",
    "develop_bge_small.json",
    "evaluation_dev_bge_small.json",
    "preregistration_bge_small.json",
    "evaluation_fresh_bge_small.json",
    "ann.json",
    "encode_cost.json",
)


def encode_cost(ws: Workspace, args) -> None:
    """Single-query encode latency per encoder on the pinned four cores (quiet machine)."""
    import statistics

    import psutil

    from contracts.io import load_queries
    from pegh.data.artifacts import atomic_json
    from pegh.v3 import build as b

    psutil.Process().cpu_affinity([0, 2, 4, 6])
    queries = load_queries(ws.raw("programmers") / "queries.jsonl", "programmers")[:300]
    report = {"affinity": [0, 2, 4, 6], "torch_threads": 4, "queries": len(queries), "encoders": {}}
    for encoder in args.encoders:
        model = b._encoder(ws, encoder, 4)
        for query in queries[:30]:
            model.encode([query.text])
        times = []
        for query in queries:
            started = time.perf_counter_ns()
            model.encode([query.text])
            times.append((time.perf_counter_ns() - started) / 1e6)
        report["encoders"][encoder] = {
            "median_ms": statistics.median(times),
            "mean_ms": statistics.fmean(times),
            "p95_ms": sorted(times)[int(0.95 * len(times)) - 1],
        }
        log(stage="encode-cost", encoder=encoder, **report["encoders"][encoder])
    atomic_json(ws.results("encode_cost.json"), report)


EF_SEARCH = (128, 256, 512)


def ann(ws: Workspace, args) -> None:
    """HNSW in place of exact FlatIP for the dense branch (dev domains, quiet machine).

    Times single-query searches on the pinned four cores, measures top-k overlap with the
    exact lists, and re-runs the v1 H* validation rule on the approximate lists.
    """
    import statistics
    from dataclasses import replace

    import faiss
    import numpy as np
    import psutil

    from contracts.io import load_queries
    from contracts.ranking import ranking_to_record
    from contracts.types import SearchHit
    from pegh.data.artifacts import atomic_json, object_hash, write_jsonl
    from pegh.evaluation.runs import load_rankings
    from pegh.v3 import build as b
    from pegh.v3.pipeline import load_domain, select_fusion

    psutil.Process().cpu_affinity([0, 2, 4, 6])
    faiss.omp_set_num_threads(4)
    variants = ("flat", *(f"hnsw_ef{ef}" for ef in EF_SEARCH))
    report = {
        "affinity": [0, 2, 4, 6],
        "faiss_threads": 4,
        "hnsw": {"M": 32, "ef_construction": 200, "ef_search": list(EF_SEARCH)},
        "encoders": {},
    }
    for encoder in args.encoders:
        model = b._encoder(ws, encoder, 4)
        result = report["encoders"][encoder] = {"domains": {}, "h_star_macro": {}}
        h_star = {v: [] for v in variants}
        for domain in DEV_DOMAINS:
            vectors, rows, _ = b.load_dense_vectors(ws.dense(encoder, domain))
            doc_of = {row: doc for doc, row in rows.items()}
            flat = faiss.IndexFlatIP(vectors.shape[1])
            flat.add(vectors)
            started = time.perf_counter()
            hnsw = faiss.IndexHNSWFlat(vectors.shape[1], 32, faiss.METRIC_INNER_PRODUCT)
            hnsw.hnsw.efConstruction = 200
            faiss.omp_set_num_threads(1)  # a multi-threaded HNSW build is not deterministic
            hnsw.add(vectors)
            faiss.omp_set_num_threads(4)
            build_seconds = time.perf_counter() - started
            exact, _ = load_rankings(ws.quality(encoder, domain), domain=domain)
            queries = sorted(
                load_queries(ws.raw(domain) / "queries.jsonl", domain), key=lambda q: q.query_id
            )
            encoded = {
                q.query_id: model.encode([q.text])[0].reshape(1, -1)
                for q in queries
                if exact[q.query_id].hits
            }
            indexes = {"flat": (flat, None), **{f"hnsw_ef{ef}": (hnsw, ef) for ef in EF_SEARCH}}
            found = {v: {} for v in variants}
            for _ in range(2):  # first pass warms caches; the second is timed
                times = {v: [] for v in variants}
                for qid, vector in encoded.items():
                    for name, (index, ef) in indexes.items():
                        if ef is not None:
                            index.hnsw.efSearch = ef
                        begin = time.perf_counter_ns()
                        scores, ids = index.search(vector, 101)
                        times[name].append((time.perf_counter_ns() - begin) / 1e6)
                        # same contract as FaissDenseRetriever: no self-hit, (-score, doc_id)
                        found[name][qid] = sorted(
                            (
                                (doc_of[int(i)], float(s))
                                for s, i in zip(scores[0], ids[0], strict=True)
                                if i >= 0 and doc_of[int(i)] != qid
                            ),
                            key=lambda hit: (-hit[1], hit[0]),
                        )[:100]
            reference = {qid: [d for d, _ in hits] for qid, hits in found["flat"].items()}
            parity = np.mean([reference[q] == [h.doc_id for h in exact[q].hits] for q in reference])
            stats = {"build_seconds": build_seconds, "flat_matches_cache": float(parity)}
            for name in variants:
                overlap = {
                    k: float(
                        np.mean(
                            [
                                len({d for d, _ in found[name][q][:k]} & set(reference[q][:k])) / k
                                for q in reference
                            ]
                        )
                    )
                    for k in (10, 100)
                }
                stats[name] = {
                    "median_ms": statistics.median(times[name]),
                    "mean_ms": statistics.fmean(times[name]),
                    "overlap_at_10": overlap[10],
                    "overlap_at_100": overlap[100],
                }
                if name == "flat":
                    continue
                identity = object_hash(
                    {"index": "hnsw_flat_ip", "M": 32, "ef": name, "of": encoder}
                )
                rankings = (
                    replace(
                        exact[q.query_id],
                        hits=tuple(
                            SearchHit(doc, score, rank)
                            for rank, (doc, score) in enumerate(found[name].get(q.query_id, []), 1)
                        ),
                        retriever_hash=identity,
                    )
                    for q in queries
                )
                path = ws.quality(f"{encoder}_{name}", domain)
                path.parent.mkdir(parents=True, exist_ok=True)
                write_jsonl(
                    path, (ranking_to_record(r, method=name, split="all") for r in rankings)
                )
            result["domains"][domain] = stats
            with np.load(ws.results("features", encoder, f"{domain}.npz")) as stored:
                features = {k: stored[k] for k in stored.files}
            for name in variants:
                retriever = encoder if name == "flat" else f"{encoder}_{name}"
                data = load_domain(ws, domain, retriever, features)
                test = [
                    data.utilities[select_fusion(data, fold)["h_star"]][data.folds[fold]["test"]]
                    for fold in range(5)
                ]
                h_star[name].append(float(np.concatenate(test).mean()))
            log(
                stage="ann",
                encoder=encoder,
                domain=domain,
                **{v: round(stats[v]["median_ms"], 3) for v in variants},
            )
        result["h_star_macro"] = {v: float(np.mean(h_star[v])) for v in variants}
        log(stage="ann", encoder=encoder, h_star=result["h_star_macro"])
    atomic_json(ws.results("ann.json"), report)


def report(ws: Workspace, args) -> None:
    """Copy small machine-readable facts into docs/v3 and draw the report figures."""
    import shutil

    from pegh.data.artifacts import file_hash
    from pegh.v3 import figures

    docs = ws.repo / "docs/v3"
    (docs / "facts").mkdir(parents=True, exist_ok=True)
    (docs / "figures").mkdir(parents=True, exist_ok=True)
    copied = {}
    for name in FACT_FILES:
        source = ws.results(name)
        if source.exists():
            shutil.copyfile(source, docs / "facts" / name)
            copied[name] = file_hash(docs / "facts" / name)

    def load(name):
        path = ws.results(name)
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    dev, fresh, online_facts = (
        load("evaluation_dev_minilm.json"),
        load("evaluation_fresh_minilm.json"),
        load("online_report.json"),
    )
    if dev and online_facts:
        v1, cascade = dev["modes"]["v1"], dev["modes"]["cascade"]
        quality = {
            "BM25": v1["static"]["bm25"]["macro_ndcg_at_10"],
            "H* (FAISS)": v1["static"]["h_star"]["macro_ndcg_at_10"],
            "PE-GH v1": v1["operating_points"]["v1_ridge"]["macro_ndcg_at_10"],
            "P* (proxy)": v1["static"]["p_star"]["macro_ndcg_at_10"],
            "R* (re-score)": v1["static"]["r_star"]["macro_ndcg_at_10"],
            "Cascade": cascade["operating_points"]["v1_ridge"]["macro_ndcg_at_10"],
        }
        methods = {
            "BM25": "bm25",
            "H* (FAISS)": "h_star",
            "PE-GH v1": "pe_gh",
            "P* (proxy)": "proxy",
            "R* (re-score)": "rescore",
            "Cascade": "cascade",
        }
        figures.pareto(
            [
                {
                    "name": name,
                    "latency_ms": online_facts["summary"][method]["all"]["mean_ms"],
                    "ndcg": quality[name],
                    "family": "v1" if method in ("bm25", "h_star", "pe_gh") else "v3",
                }
                for name, method in methods.items()
            ],
            docs / "figures/v3_pareto_dev.png",
        )
    panels = []
    for title, evaluation in (
        ("programmers + unix (thăm dò)", dev),
        ("4 domain mới (xác nhận)", fresh),
    ):
        if not evaluation:
            continue
        v1, cascade = evaluation["modes"]["v1"], evaluation["modes"]["cascade"]
        panels.append(
            {
                "title": title,
                "budgets": v1["curves"]["budgets"],
                "series": {
                    "v1: gate Ridge": v1["curves"]["macro_ndcg_at_10"]["v1_ridge"],
                    "v1: random": v1["curves"]["macro_ndcg_at_10"]["random30"],
                    "cascade: gate Ridge": cascade["curves"]["macro_ndcg_at_10"]["v1_ridge"],
                    "cascade: random": cascade["curves"]["macro_ndcg_at_10"]["random30"],
                },
                "references": {
                    "H*": v1["static"]["h_star"]["macro_ndcg_at_10"],
                    "R*": v1["static"]["r_star"]["macro_ndcg_at_10"],
                },
            }
        )
    if panels:
        figures.budget_curves(panels, docs / "figures/v3_budget_curves.png")
    bge_panels = []
    for title, name in (
        ("bge-small: programmers + unix (thăm dò)", "evaluation_dev_bge_small.json"),
        ("bge-small: 4 domain mới (xác nhận lần 2)", "evaluation_fresh_bge_small.json"),
    ):
        evaluation = load(name)
        if not evaluation:
            continue
        v1 = evaluation["modes"]["v1"]
        curves = v1["curves"]["macro_ndcg_at_10"]
        bge_panels.append(
            {
                "title": title,
                "budgets": v1["curves"]["budgets"],
                "series": {
                    "gate Ridge v1": curves["v1_ridge"],
                    "BM25-margin": curves["bm25_margin"],
                    "random": curves["random30"],
                },
                "references": {
                    "H*": v1["static"]["h_star"]["macro_ndcg_at_10"],
                    "R*": v1["static"]["r_star"]["macro_ndcg_at_10"],
                },
            }
        )
    if bge_panels:
        figures.budget_curves(bge_panels, docs / "figures/v3_budget_curves_bge.png")
    if fresh:
        labels = {
            "H1_r_star_noninferior_to_h_star": "H1  R* − H*",
            "H2_p_star_superior_to_bm25": "H2  P* − BM25",
            "H3_pe_gh_v1_noninferior_to_s_star": "H3  PE-GH v1 − S*",
            "H4_pe_gh_v1_beats_random_matched": "H4  PE-GH v1 − random (cùng ngân sách)",
            "H5_cascade_gate_beats_random_matched": "H5  gate cascade − random (cùng ngân sách)",
        }
        rows = []
        for key, label in labels.items():
            test = fresh["hypotheses"]["tests"][key]
            rows.append(
                {
                    "label": label,
                    "estimate": test["estimate"],
                    "low": test["two_sided_95"][0],
                    "high": test["two_sided_95"][1],
                    "verdict": "đạt (Holm)" if test["holm_reject"] else "chưa đạt",
                }
            )
        figures.forest(rows, docs / "figures/v3_hypotheses_fresh.png")
    log(
        stage="report",
        copied=sorted(copied),
        figures=sorted(p.name for p in (docs / "figures").glob("*.png")),
    )


def preregister(ws: Workspace, args) -> None:
    """Freeze the confirmation protocol before any fresh-domain label is scored."""
    from datetime import UTC, datetime

    import yaml

    from pegh.data.artifacts import atomic_json, file_hash, object_hash

    encoder = args.encoders[0]
    protocol, receipt = _registration(encoder)
    scored = [ws.results(f"evaluation_fresh_{encoder}.json")] + [
        ws.results("tiers", encoder, f"{d}.npz") for d in FRESH_DOMAINS
    ]
    if ws.results(receipt).exists() or any(path.exists() for path in scored):
        raise FileExistsError(
            f"fresh {encoder} rankings were already scored; a registration now is not prospective"
        )
    path = ws.repo / "configs/v3" / protocol
    spec = yaml.safe_load(path.read_text(encoding="utf-8"))
    record = {
        "schema_version": "v3_preregistration_receipt_1",
        "encoder": encoder,
        "registration_sha256": file_hash(path),
        "registered_at_utc": datetime.now(UTC).isoformat(),
        "development_selection_sha256": file_hash(ws.results(f"develop_{encoder}.json")),
        "development_evaluation_sha256": file_hash(ws.results(f"evaluation_dev_{encoder}.json")),
        # the primary (MiniLM) confirmation already scored these labels once
        "fresh_labels_scored_before_with": [] if encoder == "minilm" else ["minilm"],
        "primary_gates": spec["primary_gates"],
        "spec": spec,
    }
    record["receipt_hash"] = object_hash(record)
    atomic_json(ws.results(receipt), record)
    log(stage="preregister", sha256=record["registration_sha256"], at=record["registered_at_utc"])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "stage",
        choices=(
            "build",
            "proxy",
            "features",
            "tiers",
            "develop",
            "preregister",
            "evaluate",
            "online-plan",
            "online",
            "online-report",
            "throughput",
            "report",
            "encode-cost",
            "ann",
        ),
    )
    parser.add_argument("--group", choices=("dev", "fresh"), default="dev")
    parser.add_argument("--primary", default="v1_ridge")
    parser.add_argument("--encoders", nargs="+", default=["minilm"])
    parser.add_argument("--fidelity-queries", type=int, default=300)
    parser.add_argument("--domains", nargs="+")
    parser.add_argument("--repetitions", type=int)
    parser.add_argument("--detailed", action="store_true")
    parser.add_argument("--root", default=str(DEFAULT_ROOT))
    parser.add_argument("--dev-root", default=str(DEFAULT_DEV_ROOT))
    parser.add_argument("--dev-dense-root", default=str(DEFAULT_DEV_DENSE))
    parser.add_argument("--threads", type=int, default=6)
    parser.add_argument("--skip-bge", action="store_true")
    args = parser.parse_args()
    ws = Workspace.create(args.root, args.dev_root, args.dev_dense_root)
    stages = {
        "build": build,
        "proxy": proxy,
        "features": features,
        "tiers": tiers,
        "develop": develop,
        "preregister": preregister,
        "online-plan": online_plan,
        "online": online,
        "online-report": online_report,
        "throughput": throughput,
        "report": report,
        "encode-cost": encode_cost,
        "ann": ann,
        "evaluate": evaluate,
    }
    stages[args.stage](ws, args)


if __name__ == "__main__":
    main()
