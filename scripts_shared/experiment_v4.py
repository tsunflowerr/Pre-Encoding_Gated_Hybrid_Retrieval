"""Drive round v4 (PE-GH v2): encoder choice, BM25-failure gate, preregistered confirmation.

v1 and v3 artifacts are read-only inputs. Every output goes under --root (outside Git).
Development uses only the six seen domains; the six new subforums are fetched only after
the confirmation protocol is registered.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

from pegh.v4.workspace import NEW_DOMAINS, SEEN_DOMAINS, Workspace, vector_key

DEFAULT_ROOT = Path.home() / ".cache/pegh/v4"
DEFAULT_V3_ROOT = Path.home() / ".cache/pegh/v3"
DEFAULT_DEV_ROOT = Path.home() / ".cache/pegh/integration-20261026"
DEFAULT_DEV_DENSE = Path.home() / ".cache/pegh/artifacts/final-v1"
AFFINITY = [0, 2, 4, 6]


def log(**fields) -> None:
    print(json.dumps({"time": time.strftime("%H:%M:%S"), **fields}, ensure_ascii=False), flush=True)


def _domains(args, default=SEEN_DOMAINS) -> tuple[str, ...]:
    return tuple(args.domains) if args.domains else default


def _require_registration(ws: Workspace, domains) -> None:
    if any(d in NEW_DOMAINS for d in domains) and not ws.results("preregistration.json").exists():
        raise PermissionError("register the v4 protocol before touching the new subforums")


def vectors(ws: Workspace, args) -> None:
    """Offline corpus vectors for each encoder's base model."""
    from pegh.v4 import build as b

    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    domains = _domains(args)
    _require_registration(ws, domains)
    for key in dict.fromkeys(vector_key(e) for e in args.encoders):
        for domain in domains:
            started = time.perf_counter()
            b.build_dense(ws, key, domain, args.threads)
            log(
                stage="vectors",
                encoder=key,
                domain=domain,
                seconds=round(time.perf_counter() - started),
            )


def quality(ws: Workspace, args) -> None:
    """Top-100 dense caches (prefix-aware) for every query of each domain."""
    from pegh.v4 import build as b

    domains = _domains(args)
    _require_registration(ws, domains)
    for retriever in args.encoders:
        for domain in domains:
            started = time.perf_counter()
            b.quality_cache(ws, retriever, domain, threads=args.threads)
            log(
                stage="quality",
                retriever=retriever,
                domain=domain,
                seconds=round(time.perf_counter() - started),
            )


def encode_cost(ws: Workspace, args) -> None:
    """Single-query encode latency (with each key's prefix) on the pinned four cores."""
    import statistics

    import psutil

    from contracts.io import load_queries
    from pegh.data.artifacts import atomic_json
    from pegh.v4 import build as b

    psutil.Process().cpu_affinity(AFFINITY)
    queries = load_queries(ws.raw("programmers") / "queries.jsonl", "programmers")[:300]
    path = ws.results("encode_cost.json")
    report = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"encoders": {}}
    report.update(affinity=AFFINITY, torch_threads=4, queries=len(queries))
    for key in args.encoders:
        model = b.prefixed(ws, key, 4)
        for query in queries[:30]:
            model.query(query.text)
        times = []
        for query in queries:
            started = time.perf_counter_ns()
            model.query(query.text)
            times.append((time.perf_counter_ns() - started) / 1e6)
        report["encoders"][key] = {
            "median_ms": statistics.median(times),
            "mean_ms": statistics.fmean(times),
            "p95_ms": sorted(times)[int(0.95 * len(times)) - 1],
        }
        log(stage="encode-cost", encoder=key, **report["encoders"][key])
    atomic_json(path, report)


def _load_group(
    ws: Workspace,
    domains,
    encoder: str,
    *,
    with_tiers: bool = True,
    features_from: str | None = None,
):
    """DomainData for one dense retriever; v1/QPP features are encoder-independent."""
    import numpy as np

    from pegh.v3.pipeline import load_domain

    group = []
    for domain in domains:
        feature_path = ws.features(features_from or encoder, domain)
        if not feature_path.exists():
            feature_path = ws.features("minilm", domain)  # comparison only: v1/QPP columns
        with np.load(feature_path) as stored:
            features = {k: stored[k] for k in stored.files}
        tier_values = None
        if with_tiers and ws.tiers(encoder, domain).exists():
            with np.load(ws.tiers(encoder, domain)) as stored:
                tier_values = {k: stored[k] for k in stored.files}
        group.append(load_domain(ws, domain, encoder, features, tier_values))
    return group


def _oof(data, key: str):
    """Out-of-fold test utility of a validation-selected static choice (e.g. h_star)."""
    import numpy as np

    from pegh.v3.pipeline import select_fusion

    values = np.zeros(len(data.ids))
    for fold in range(5):
        choice = select_fusion(data, fold)
        test = data.folds[fold]["test"]
        values[test] = data.utilities[choice.get(key, key)][test]
    return values


def compare(ws: Workspace, args) -> None:
    """Encoder choice on the development domains: OOF dense-only and H* nDCG@10.

    Rule fixed before running: highest macro H*; within 0.005 the cheaper encoder wins.
    """
    from pegh.data.artifacts import atomic_json
    from pegh.v3.pipeline import bootstrap, macro

    domains = _domains(args, ("programmers", "unix"))
    cost_path = ws.results("encode_cost.json")
    cost = (
        json.loads(cost_path.read_text(encoding="utf-8"))["encoders"] if cost_path.exists() else {}
    )
    report, h_values, groups = {"domains": list(domains), "encoders": {}}, {}, None
    for key in args.encoders:
        group = _load_group(ws, domains, key, with_tiers=False)
        groups = {d.domain: d.groups for d in group}
        dense = {d.domain: _oof(d, "dense") for d in group}
        h_star = {d.domain: _oof(d, "h_star") for d in group}
        h_values[key] = h_star
        report["encoders"][key] = {
            "dense_macro": macro(dense),
            "h_star_macro": macro(h_star),
            "dense_domains": {d: float(v.mean()) for d, v in dense.items()},
            "h_star_domains": {d: float(v.mean()) for d, v in h_star.items()},
            "encode_median_ms": cost.get(key, {}).get("median_ms"),
        }
        log(
            stage="compare",
            encoder=key,
            dense=round(macro(dense), 4),
            h_star=round(macro(h_star), 4),
        )
    best = max(report["encoders"], key=lambda k: report["encoders"][k]["h_star_macro"])
    top = report["encoders"][best]["h_star_macro"]
    close = [k for k, v in report["encoders"].items() if top - v["h_star_macro"] <= 0.005]
    chosen = min(close, key=lambda k: report["encoders"][k]["encode_median_ms"] or float("inf"))
    report["pairwise_h_star_vs_chosen"] = {
        k: bootstrap({d: h_values[chosen][d] - h_values[k][d] for d in domains}, groups)
        for k in report["encoders"]
        if k != chosen
    }
    report["rule"] = "max macro H*; within 0.005 of the best, lowest median encode ms"
    report["chosen"] = chosen
    atomic_json(ws.results("encoder_comparison.json"), report)
    log(stage="compare", chosen=chosen)


def proxy(ws: Workspace, args) -> None:
    """Static token tables (v3 recipe) and their label-free fidelity audit."""
    import numpy as np

    from contracts.io import iter_corpus, load_queries
    from pegh.data.artifacts import atomic_json
    from pegh.data.splits import fold_record
    from pegh.evaluation.runs import load_rankings
    from pegh.v3.build import load_dense_vectors
    from pegh.v3.proxy import StaticProxy, corpus_token_weights, distill_table, save_proxy
    from pegh.v4 import build as b

    domains = _domains(args)
    _require_registration(ws, domains)
    path = ws.results("proxy_fidelity.json")
    report = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    for key in args.encoders:
        model = b.prefixed(ws, key, args.threads)
        st, table = model.model.model, None
        for domain in domains:
            target = ws.proxy(key, domain)
            if not (target / "manifest.json").exists():
                table = table if table is not None else distill_table(st)
                texts = (doc.text for doc in iter_corpus(ws.raw(domain) / "corpus.jsonl", domain))
                save_proxy(
                    target,
                    table,
                    corpus_token_weights(st.tokenizer, texts),
                    {
                        "encoder": vector_key(key),
                        "domain": domain,
                        "model_revision": model.model.config.revision,
                    },
                )
            vectors_, rows, _ = load_dense_vectors(ws.dense(key, domain))
            split = json.loads(ws.split_manifest(domain).read_text(encoding="utf-8"))
            train_ids = set(fold_record(split, 0)["domains"][domain]["train"])
            queries = [
                q
                for q in load_queries(ws.raw(domain) / "queries.jsonl", domain)
                if q.query_id in train_ids
            ][:300]
            sparse, _ = load_rankings(ws.quality("bm25", domain), domain=domain)
            true = model.model.encode([model.text(q.text) for q in queries])
            px = StaticProxy(target, st.tokenizer)
            pearson = []
            for query, vector in zip(queries, true, strict=True):
                hits = sparse[query.query_id].hits
                if len(hits) >= 10:
                    candidates = vectors_[[rows[h.doc_id] for h in hits]]
                    pearson.append(
                        float(
                            np.corrcoef(candidates @ vector, candidates @ px.embed(query.text))[
                                0, 1
                            ]
                        )
                    )
            report[f"{key}/{domain}"] = {
                "queries": len(pearson),
                "mean_pearson": float(np.mean(pearson)),
            }
            log(
                stage="proxy", encoder=key, domain=domain, pearson=round(float(np.mean(pearson)), 3)
            )
    atomic_json(path, report)


def features(ws: Workspace, args) -> None:
    """v1 + QPP + proxy features for every query (v3 extractor); v1 parity on dev data."""
    import numpy as np
    import yaml

    from contracts.io import load_queries
    from pegh.evaluation.runs import load_rankings
    from pegh.gating.features import QueryFeatureExtractor
    from pegh.sparse.fast import open_backend
    from pegh.v3.build import load_dense_vectors
    from pegh.v3.features import QPP_NAMES, ExtendedFeatureExtractor
    from pegh.v3.pipeline import save_npz
    from pegh.v3.proxy import StaticProxy
    from pegh.v4 import build as b

    domains = _domains(args)
    _require_registration(ws, domains)
    protocol = yaml.safe_load(
        (ws.repo / "configs/gating/protocol_v1.yaml").read_text(encoding="utf-8")
    )
    for key in args.encoders:
        tokenizer = b.encoder(ws, vector_key(key), 1).model.tokenizer
        for domain in domains:
            output = ws.features(key, domain)
            if output.exists():
                continue
            backend = open_backend(ws.sparse(domain), execution="numpy")
            vectors_, rows, _ = load_dense_vectors(ws.dense(key, domain))
            extractor = ExtendedFeatureExtractor(
                QueryFeatureExtractor(protocol["features"], backend.tokenizer),
                backend,
                ("v1", "qpp", "proxy"),
                proxy=StaticProxy(ws.proxy(key, domain), tokenizer),
                doc_vectors=vectors_,
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
            parity = None
            if ws.is_dev(domain):
                frozen = {}
                for line in (
                    (ws.dev_root / "results/features" / f"{domain}.jsonl")
                    .read_text(encoding="utf-8")
                    .splitlines()
                ):
                    record = json.loads(line)
                    frozen[record["query_id"]] = record["values"]
                parity = float(np.abs(np.array([frozen[q] for q in ids]) - x[:, :21]).max())
            save_npz(
                output,
                ids=ids,
                v1=x[:, :21],
                qpp=x[:, 21 : 21 + len(QPP_NAMES)],
                proxy=x[:, 21 + len(QPP_NAMES) :],
            )
            log(
                stage="features",
                encoder=key,
                domain=domain,
                queries=len(ids),
                v1_parity_max_abs=parity,
            )


def tiers(ws: Workspace, args) -> None:
    """Per-query nDCG@10 of P* (proxy) and R* (true, prefixed query vector) at every alpha."""
    import numpy as np

    from contracts.io import load_queries
    from pegh.data.qrels import load_qrels
    from pegh.evaluation.metrics import query_metrics
    from pegh.evaluation.runs import load_rankings
    from pegh.v3.build import load_dense_vectors
    from pegh.v3.pipeline import ALPHAS, save_npz
    from pegh.v3.proxy import StaticProxy
    from pegh.v3.rescore import candidate_fusion, rescore_identity, rescored_ranking
    from pegh.v4 import build as b

    domains = _domains(args)
    _require_registration(ws, domains)
    for key in args.encoders:
        model = b.prefixed(ws, key, args.threads)
        for domain in domains:
            output = ws.tiers(key, domain)
            if output.exists():
                continue
            queries = sorted(
                load_queries(ws.raw(domain) / "queries.jsonl", domain), key=lambda q: q.query_id
            )
            qrels = load_qrels(ws.raw(domain) / "qrels.tsv", domain)
            sparse, _ = load_rankings(ws.quality("bm25", domain), domain=domain)
            vectors_, rows, manifest = load_dense_vectors(ws.dense(key, domain))
            px = StaticProxy(ws.proxy(key, domain), model.model.model.tokenizer)
            proxy_id = rescore_identity("static_proxy", px.identity)
            true_id = rescore_identity(
                "query_encoder", f"{manifest['embedding_fingerprint']}|{model.prefix}"
            )
            arrays = {f"{kind}_cc_{a:.1f}": [] for kind in ("proxy", "rescore") for a in ALPHAS}
            started = time.perf_counter()
            for query in queries:
                ranking = sparse[query.query_id]
                cheap = rescored_ranking(ranking, px.embed(query.text), vectors_, rows, proxy_id)
                full = (
                    rescored_ranking(ranking, model.query(query.text), vectors_, rows, true_id)
                    if query.text.strip()
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
                encoder=key,
                domain=domain,
                seconds=round(time.perf_counter() - started),
            )


DEV_BUDGETS = tuple(round(i / 10, 1) for i in range(1, 10))


def _routed(score, forced, ids, u_low, u_high, budget):
    import numpy as np

    from pegh.v4.gate import route_top

    return np.where(route_top(score, forced, ids, budget), u_high, u_low)


def _random_mean(data, u_low, u_high, budget, seeds):
    import numpy as np

    from pegh.v3.pipeline import _random_score

    runs = [
        _routed(
            np.array([_random_score(s, q) for q in data.ids]),
            data.forced,
            data.ids,
            u_low,
            u_high,
            budget,
        )
        for s in seeds
    ]
    return np.mean(runs, axis=0)


def _oracle(u_low, u_high, forced, budget):
    import numpy as np

    gain = u_high - u_low
    chosen = forced.copy()
    rest = int(round(budget * len(gain))) - int(forced.sum())
    order = [i for i in np.argsort(-gain, kind="stable") if not forced[i] and gain[i] > 0][
        : max(rest, 0)
    ]
    chosen[order] = True
    return np.where(chosen, u_high, u_low)


def develop(ws: Workspace, args) -> None:
    """Choose gate v2 on the six seen domains by leave-one-domain-out (LODO) routing.

    Each held-out domain gets fusion choices and a gate fitted on the other five, and is
    routed with no labels of its own (P* -> H*). Rule fixed before running: the candidate
    with the largest mean LODO macro nDCG@10 over budgets 0.2-0.8 wins; the operating
    budget is the smallest of 0.3-0.9 whose LODO macro is within 0.005 of always-H*.
    """
    import numpy as np

    from pegh.data.artifacts import atomic_json
    from pegh.v3.pipeline import RANDOM_SEEDS, bootstrap, macro
    from pegh.v4 import gate as g

    key = args.encoders[0]
    group = _load_group(ws, SEEN_DOMAINS, key)
    groups = {d.domain: d.groups for d in group}
    methods = [s.name for s in g.CANDIDATES] + ["bm25_margin", "random30", "oracle"]
    curves = {m: {} for m in methods}
    per_query = {m: {} for m in [s.name for s in g.CANDIDATES] + ["bm25_margin", "random30"]}
    references, choices = {}, {}
    for held in group:
        train = [d for d in group if d is not held]
        tiers_ = choices[held.domain] = g.fixed_tiers([d.utilities for d in train])
        u_p, u_h = held.utilities[tiers_["p_star"]], held.utilities[tiers_["h_star"]]
        references[held.domain] = {"p_star": u_p, "h_star": u_h}
        scores = {}
        for spec in g.CANDIDATES:
            gate = g.fit(
                spec, [d.matrix(spec.groups) for d in train], [d.utilities["bm25"] for d in train]
            )
            x = held.matrix(spec.groups)
            scores[spec.name] = gate.score(x, g.domain_stats(x))
        scores["bm25_margin"] = -held.features["v1"][:, 16]
        for m in methods:
            curves[m][held.domain] = []
            for budget in DEV_BUDGETS:
                if m == "random30":
                    values = _random_mean(held, u_p, u_h, budget, RANDOM_SEEDS)
                elif m == "oracle":
                    values = _oracle(u_p, u_h, held.forced, budget)
                else:
                    values = _routed(scores[m], held.forced, held.ids, u_p, u_h, budget)
                curves[m][held.domain].append(float(values.mean()))
                if m in per_query and budget in (0.3, 0.5, 0.7):
                    per_query[m].setdefault(budget, {})[held.domain] = values
        log(stage="develop", held_out=held.domain, tiers=tiers_)
    macro_curves = {
        m: [float(np.mean([curves[m][d][i] for d in curves[m]])) for i in range(len(DEV_BUDGETS))]
        for m in methods
    }
    area = {m: float(np.mean(v[1:8])) for m, v in macro_curves.items()}
    names = [s.name for s in g.CANDIDATES]
    chosen = max(names, key=lambda n: (area[n], -names.index(n)))
    h_macro = macro({d: r["h_star"] for d, r in references.items()})
    p_macro = macro({d: r["p_star"] for d, r in references.items()})
    operating = next(
        (
            b
            for i, b in enumerate(DEV_BUDGETS)
            if b >= 0.3 and macro_curves[chosen][i] >= h_macro - 0.005
        ),
        0.9,
    )
    vs = {
        f"{m}@{b}": bootstrap(
            {d: per_query[chosen][b][d] - per_query[m][b][d] for d in groups}, groups
        )
        for m in ("bm25_margin", "random30", *(n for n in names if n != chosen))
        for b in (0.3, 0.5, 0.7)
    }
    spec = next(s for s in g.CANDIDATES if s.name == chosen)
    report = {
        "schema_version": "v4_develop_1",
        "encoder": key,
        "domains": list(SEEN_DOMAINS),
        "protocol": "leave-one-domain-out; fusion choices and gate fitted on the other five domains",
        "rule": "max mean LODO macro over budgets 0.2-0.8; operating budget = smallest b>=0.3 within 0.005 of H*",
        "budgets": list(DEV_BUDGETS),
        "macro_curves": macro_curves,
        "domain_curves": curves,
        "area_0_2_to_0_8": area,
        "h_star_macro": h_macro,
        "p_star_macro": p_macro,
        "lodo_tier_choices": choices,
        "chosen": {
            "label": spec.label,
            "groups": list(spec.groups),
            "norm": spec.norm,
            "name": chosen,
        },
        "operating_budget": operating,
        "chosen_minus": vs,
    }
    atomic_json(ws.results("develop.json"), report)
    log(
        stage="develop",
        chosen=chosen,
        area=round(area[chosen], 4),
        margin_area=round(area["bm25_margin"], 4),
        operating_budget=operating,
        h_star=round(h_macro, 4),
    )


def freeze(ws: Workspace, args) -> None:
    """Fit the chosen gate on all six seen domains and fix the fusion choices; write to configs."""
    from pegh.data.artifacts import atomic_json, file_hash
    from pegh.v4 import gate as g
    from pegh.v4.workspace import ENCODERS, query_prefix

    dev_path = ws.results("develop.json")
    dev = json.loads(dev_path.read_text(encoding="utf-8"))
    key, chosen = dev["encoder"], dev["chosen"]
    spec = g.GateSpec(chosen["label"], tuple(chosen["groups"]), chosen["norm"])
    group = _load_group(ws, SEEN_DOMAINS, key)
    gate = g.fit(spec, [d.matrix(spec.groups) for d in group], [d.utilities["bm25"] for d in group])
    payload = {
        "schema_version": "pegh_gate_v2_1",
        "encoder": key,
        "encoder_config": ENCODERS[key][0],
        "query_prefix": query_prefix(key),
        "tiers": g.fixed_tiers([d.utilities for d in group]),
        "operating_budget": dev["operating_budget"],
        "trained_on": list(SEEN_DOMAINS),
        "development_sha256": file_hash(dev_path),
        "gate": gate.to_json(),
        "gate_sha256": gate.sha256,
    }
    atomic_json(ws.repo / "configs/v4/gate_v2.json", payload)
    log(
        stage="freeze", encoder=key, gate=spec.name, tiers=payload["tiers"], gate_sha256=gate.sha256
    )


def preregister(ws: Workspace, args) -> None:
    """Hash the protocol and frozen gate before any new-subforum file exists."""
    import datetime

    import yaml

    from pegh.data.artifacts import atomic_json, file_hash, object_hash

    receipt_path = ws.results("preregistration.json")
    if receipt_path.exists():
        raise FileExistsError("the v4 protocol is already registered")
    if any((ws.root / "data/raw" / d).exists() for d in NEW_DOMAINS):
        raise PermissionError("new-subforum data already exists; registration would not be prior")
    protocol_path = ws.repo / "configs/v4/preregistration.yaml"
    gate_path = ws.repo / "configs/v4/gate_v2.json"
    spec = yaml.safe_load(protocol_path.read_text(encoding="utf-8"))
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    if spec["gate_sha256"] != gate["gate_sha256"] or spec["encoder"] != gate["encoder"]:
        raise ValueError("protocol and frozen gate disagree")
    receipt = {
        "schema_version": "v4_preregistration_receipt_1",
        "registered_at_utc": datetime.datetime.now(datetime.UTC).isoformat(),
        "protocol_sha256": file_hash(protocol_path),
        "gate_file_sha256": file_hash(gate_path),
        "development_sha256": file_hash(ws.results("develop.json")),
        "spec": spec,
    }
    receipt["receipt_hash"] = object_hash(receipt)
    atomic_json(receipt_path, receipt)
    log(
        stage="preregister",
        **{k: receipt[k] for k in ("registered_at_utc", "protocol_sha256", "gate_file_sha256")},
    )


def fetch(ws: Workspace, args) -> None:
    """Download the six new subforums, split them (seed 42) and build BM25 (after registration)."""
    from pegh.v3 import build as b3
    from pegh.v4 import build as b

    _require_registration(ws, NEW_DOMAINS)
    for domain in NEW_DOMAINS:
        b3.fetch_domain(ws, domain)
        log(stage="fetch", domain=domain)
    log(stage="splits", split_hash=b.prepare_new_splits(ws)["split_hash"])
    for domain in NEW_DOMAINS:
        b3.build_sparse(ws, domain)
        b.quality_cache(ws, "bm25", domain)
        log(stage="sparse", domain=domain)


def _holm(tests: dict, alpha: float = 0.05) -> None:
    order = sorted(tests, key=lambda n: (tests[n]["p_value"], n))
    stopped = False
    for i, name in enumerate(order):
        threshold = alpha / (len(order) - i)
        reject = not stopped and tests[name]["p_value"] <= threshold
        stopped = stopped or not reject
        tests[name].update(holm_threshold=threshold, holm_reject=reject)


def evaluate(ws: Workspace, args) -> None:
    """Registered confirmation on the six new subforums (K1-K4, Holm), plus descriptives.

    PE-GH v2 uses no label of a new domain: frozen gate, fusion choices fixed on the seen
    domains, thresholds from the gate scores of each fold's non-test queries.
    """
    import numpy as np
    from sklearn.metrics import roc_auc_score

    from pegh.data.artifacts import atomic_json, file_hash, object_hash
    from pegh.v3.pipeline import (
        RANDOM_SEEDS,
        _random_score,
        assemble,
        bootstrap,
        macro,
        score_group,
    )
    from pegh.v4 import gate as g

    receipt = json.loads(ws.results("preregistration.json").read_text(encoding="utf-8"))
    gate_path = ws.repo / "configs/v4/gate_v2.json"
    if file_hash(gate_path) != receipt["gate_file_sha256"]:
        raise ValueError("frozen gate changed after registration")
    spec, frozen = receipt["spec"], json.loads(gate_path.read_text(encoding="utf-8"))
    key, gate, tiers_ = frozen["encoder"], g.LinearGate.from_json(frozen["gate"]), frozen["tiers"]
    b_match, b_op = spec["matched_budget"], spec["operating_budget"]
    group = _load_group(ws, NEW_DOMAINS, key)
    groups = {d.domain: d.groups for d in group}
    keys = ("v2_operating", "v2_matched", "margin_matched", "random_matched", "p_star", "h_star")
    arrays = {k: {} for k in keys}
    routes, curves, auc, statics = {}, {}, {}, {}
    for d in group:
        u_p, u_h = d.utilities[tiers_["p_star"]], d.utilities[tiers_["h_star"]]
        x = d.matrix(gate.spec.groups)
        score = gate.score(x, g.domain_stats(x))
        margin = -d.features["v1"][:, 16]
        random = [np.array([_random_score(s, q) for q in d.ids]) for s in RANDOM_SEEDS]
        n = len(d.ids)
        operating, matched, margin_m, random_m = (np.zeros(n) for _ in range(4))
        route = np.zeros(n, dtype=bool)
        for fold in range(5):
            test = d.folds[fold]["test"]
            reference = np.concatenate([d.folds[fold]["train"], d.folds[fold]["validation"]])
            threshold = g.quantile_threshold(score[reference], d.forced[reference], b_op)
            route[test] = d.forced[test] | (score[test] > threshold)
            operating[test] = np.where(route[test], u_h[test], u_p[test])
            ids, f, lo, hi = [d.ids[i] for i in test], d.forced[test], u_p[test], u_h[test]
            matched[test] = _routed(score[test], f, ids, lo, hi, b_match)
            margin_m[test] = _routed(margin[test], f, ids, lo, hi, b_match)
            random_m[test] = np.mean(
                [_routed(r[test], f, ids, lo, hi, b_match) for r in random], axis=0
            )
        for k, v in zip(keys, (operating, matched, margin_m, random_m, u_p, u_h), strict=True):
            arrays[k][d.domain] = v
        routes[d.domain] = {
            "realized_encode_ratio": float(route.mean()),
            "forced": int(d.forced.sum()),
            "queries": n,
        }
        curves[d.domain] = {
            "v2": [float(_routed(score, d.forced, d.ids, u_p, u_h, b).mean()) for b in DEV_BUDGETS],
            "bm25_margin": [
                float(_routed(margin, d.forced, d.ids, u_p, u_h, b).mean()) for b in DEV_BUDGETS
            ],
            "random30": [
                float(np.mean([_routed(r, d.forced, d.ids, u_p, u_h, b).mean() for r in random]))
                for b in DEV_BUDGETS
            ],
            "oracle": [float(_oracle(u_p, u_h, d.forced, b).mean()) for b in DEV_BUDGETS],
        }
        fail = d.utilities["bm25"] == 0
        auc[d.domain] = {
            "bm25_fail_rate": float(fail.mean()),
            "auc_bm25_fail_v2": float(roc_auc_score(fail, score)),
            "auc_bm25_fail_margin": float(roc_auc_score(fail, margin)),
        }
        statics[d.domain] = {
            k: float(d.utilities[k].mean())
            for k in ("bm25", "dense", tiers_["p_star"], tiers_["h_star"])
        }
        log(
            stage="evaluate",
            domain=d.domain,
            **routes[d.domain],
            v2=round(float(operating.mean()), 4),
            h_star=round(float(u_h.mean()), 4),
        )
    minilm = _load_group(ws, NEW_DOMAINS, "minilm", with_tiers=False, features_from=key)
    scored = score_group(minilm, ("v1_ridge",), mode="v1")
    v1 = assemble(minilm, scored, "v1_ridge")
    v1_static = {
        d.domain: {
            "h_star": float(_oof(d, "h_star").mean()),
            "dense": float(_oof(d, "dense").mean()),
        }
        for d in minilm
    }

    def diff(a, b):
        return {dom: a[dom] - b[dom] for dom in a}

    tests = {
        "K1_gate_v2_beats_bm25_margin_matched": (
            diff(arrays["v2_matched"], arrays["margin_matched"]),
            "p_superiority",
        ),
        "K2_pe_gh_v2_noninferior_to_h_star": (
            diff(arrays["v2_operating"], arrays["h_star"]),
            "p_noninferiority_0_01",
        ),
        "K3_pe_gh_v2_superior_to_pe_gh_v1": (
            diff(arrays["v2_operating"], v1.utility),
            "p_superiority",
        ),
        "K4_gate_v2_beats_random_matched": (
            diff(arrays["v2_matched"], arrays["random_matched"]),
            "p_superiority",
        ),
    }
    results = {}
    for name, (values, kind) in tests.items():
        stats = bootstrap(values, groups)
        results[name] = {
            "estimate": stats["mean_difference"],
            "two_sided_95": stats["two_sided_95"],
            "one_sided_lower_95": stats["one_sided_lower_95"],
            "p_value": stats[kind],
            "p_kind": kind,
        }
    _holm(results)
    report = {
        "schema_version": "v4_evaluation_1",
        "domains": list(NEW_DOMAINS),
        "encoder": key,
        "tiers": tiers_,
        "gate": gate.spec.name,
        "matched_budget": b_match,
        "operating_budget": b_op,
        "registration_receipt_hash": receipt["receipt_hash"],
        "macro": {k: macro(v) for k, v in arrays.items()} | {"pe_gh_v1": macro(v1.utility)},
        "pe_gh_v1_encode_ratio": {dom: float(m.mean()) for dom, m in v1.dense.items()},
        "pe_gh_v1_fold_status": [t["status"] for t in v1.thresholds],
        "v2_routes": routes,
        "domain_means": {
            k: {dom: float(x.mean()) for dom, x in v.items()} for k, v in arrays.items()
        },
        "statics": statics,
        "minilm_statics": v1_static,
        "budgets": list(DEV_BUDGETS),
        "domain_curves": curves,
        "macro_curves": {
            m: [
                float(np.mean([curves[dom][m][i] for dom in curves]))
                for i in range(len(DEV_BUDGETS))
            ]
            for m in ("v2", "bm25_margin", "random30", "oracle")
        },
        "auc": auc,
        "hypotheses": {"family_alpha": 0.05, "procedure": "holm_step_down", "tests": results},
    }
    report["report_hash"] = object_hash(report)
    atomic_json(ws.results("evaluation_new.json"), report)
    for name, r in results.items():
        log(
            stage="hypothesis",
            name=name,
            estimate=round(r["estimate"], 5),
            p=r["p_value"],
            reject=r["holm_reject"],
        )


ONLINE_DOMAINS = ("programmers", "unix")
ONLINE_BUDGETS = (0.3, 0.5)


def _hash_hits(ranking) -> str:
    from pegh.data.artifacts import object_hash

    return object_hash([h.doc_id for h in ranking.hits])


def online_plan(ws: Workspace, args) -> None:
    """Registries for the dev-domain benchmark: LODO gate v2 and tier choices per domain.

    Gate scores are recomputed one query at a time exactly as online, and every expected
    ranking hash/route is derived offline from the caches.
    """
    import numpy as np

    from contracts.io import load_queries
    from pegh.data.artifacts import atomic_json, file_hash
    from pegh.evaluation.runs import load_rankings
    from pegh.v3.build import load_dense_vectors
    from pegh.v3.pipeline import ALPHAS
    from pegh.v3.proxy import StaticProxy
    from pegh.v3.rescore import candidate_fusion, rescore_identity, rescored_ranking
    from pegh.v4 import build as b
    from pegh.v4 import gate as g
    from pegh.v4.online import fuse_high, proxy_alpha

    frozen = json.loads((ws.repo / "configs/v4/gate_v2.json").read_text(encoding="utf-8"))
    dev = json.loads(ws.results("develop.json").read_text(encoding="utf-8"))
    key, operating = frozen["encoder"], frozen["operating_budget"]
    spec = g.GateSpec(dev["chosen"]["label"], tuple(dev["chosen"]["groups"]), dev["chosen"]["norm"])
    budgets = tuple(sorted({*ONLINE_BUDGETS, operating}))
    seen = _load_group(ws, SEEN_DOMAINS, key)
    by_name = {d.domain: d for d in seen}
    protocol_path = ws.repo / "configs/gating/protocol_v1.yaml"
    model = b.prefixed(ws, key, args.threads)
    factory = "pegh.v4.online:create_v2_method"
    for domain in ONLINE_DOMAINS:
        data = by_name[domain]
        train = [d for d in seen if d.domain != domain]
        tiers_ = g.fixed_tiers([d.utilities for d in train])
        r_star = g.best_static(
            [d.utilities for d in train], [f"rescore_cc_{a:.1f}" for a in ALPHAS]
        )
        gate = g.fit(
            spec, [d.matrix(spec.groups) for d in train], [d.utilities["bm25"] for d in train]
        )
        x = data.matrix(spec.groups)
        stats = g.domain_stats(x) if spec.norm == "domain" else None
        gate_path = ws.root / "artifacts/gates/v2_lodo" / f"{domain}.json"
        atomic_json(
            gate_path,
            {
                "domain": domain,
                "trained_on": [d.domain for d in train],
                "gate": gate.to_json(),
                "domain_stats": stats,
            },
        )
        score = np.array([gate.score(row[None, :], stats)[0] for row in x])
        margin = -data.features["v1"][:, 16]
        queries = {q.query_id: q for q in load_queries(ws.raw(domain) / "queries.jsonl", domain)}
        sparse_cache, _ = load_rankings(ws.quality("bm25", domain), domain=domain)
        dense_cache, _ = load_rankings(ws.quality(key, domain), domain=domain)
        vectors_, rows, manifest = load_dense_vectors(ws.dense(key, domain))
        proxy = StaticProxy(ws.proxy(key, domain), model.model.model.tokenizer)
        ids = {
            "proxy": rescore_identity("static_proxy", proxy.identity),
            "query": rescore_identity(
                "query_encoder", f"{manifest['embedding_fingerprint']}|{model.prefix}"
            ),
        }
        common = {
            "domain": domain,
            "sparse_dir": str(ws.sparse(domain)),
            "dense_dir": str(ws.dense(key, domain)),
            "expected_sparse_sha256": file_hash(ws.sparse(domain) / "index.sqlite3"),
            "expected_dense_sha256": file_hash(ws.dense(key, domain) / "index.faiss"),
            "query_prefix": model.prefix,
            "cache_folder": str(ws.models),
        }
        proxy_args = {
            "proxy_dir": str(ws.proxy(key, domain)),
            "expected_proxy_hash": proxy.manifest["manifest_hash"],
            "p_star": tiers_["p_star"],
        }
        row_of = {q: n for n, q in enumerate(data.ids)}
        cheap, full, rescore = {}, {}, {}
        for qid in data.ids:
            query, sparse = queries[qid], sparse_cache[qid]
            low = sparse
            if proxy_alpha(tiers_["p_star"]) is not None:
                other = rescored_ranking(
                    sparse, proxy.embed(query.text), vectors_, rows, ids["proxy"]
                )
                low = candidate_fusion(sparse, other, proxy_alpha(tiers_["p_star"]))
            cheap[qid] = _hash_hits(low)
            full[qid] = _hash_hits(fuse_high(sparse, dense_cache[qid], tiers_["h_star"]))
            if query.text.strip():
                other = rescored_ranking(
                    sparse, model.query(query.text), vectors_, rows, ids["query"]
                )
                rescore[qid] = _hash_hits(
                    candidate_fusion(sparse, other, float(r_star.removeprefix("rescore_cc_")))
                )
            else:
                rescore[qid] = _hash_hits(sparse)
        for fold in range(5):
            f = data.folds[fold]
            reference = np.concatenate([f["train"], f["validation"]])
            thresholds = {
                f"pe_gh_v2_b{int(round(bb * 100))}": float(
                    g.quantile_threshold(score[reference], data.forced[reference], bb)
                )
                for bb in budgets
            }
            thresholds["margin_op"] = float(
                g.quantile_threshold(margin[reference], data.forced[reference], operating)
            )
            registry = []
            v1_path = (
                ws.repo / f"docs/integration/2026-10-26/online-manifests/{domain}_fold_{fold}.json"
            )
            for entry in json.loads(v1_path.read_text(encoding="utf-8"))["registry"]:
                if entry["id"] in ("h_star", "pe_gh"):
                    if "protocol_path" in entry["kwargs"]:
                        entry["kwargs"]["protocol_path"] = str(protocol_path)
                    registry.append({**entry, "id": f"{entry['id']}_v1"})
            base = {**common, "fold": fold}
            registry += [
                {"id": "bm25", "factory": factory, "kwargs": {**base, "route": "bm25"}},
                {
                    "id": "p_star",
                    "factory": factory,
                    "kwargs": {**base, **proxy_args, "route": "p_star"},
                },
                {
                    "id": "r_star_v2",
                    "factory": factory,
                    "kwargs": {**base, "route": "r_star", "r_star": r_star},
                    "require_dense_warmup": True,
                },
                {
                    "id": "h_star_v2",
                    "factory": factory,
                    "kwargs": {**base, "route": "h_star", "h_star": tiers_["h_star"]},
                    "require_dense_warmup": True,
                },
            ]
            for method, threshold in thresholds.items():
                scorer = "bm25_margin" if method == "margin_op" else "gate_v2"
                kwargs = {
                    **base,
                    **proxy_args,
                    "route": "gated",
                    "h_star": tiers_["h_star"],
                    "scorer": scorer,
                    "threshold": threshold,
                    "protocol_path": str(protocol_path),
                }
                if scorer == "gate_v2":
                    kwargs.update(
                        gate_path=str(gate_path), expected_gate_sha256=file_hash(gate_path)
                    )
                registry.append(
                    {
                        "id": method,
                        "factory": factory,
                        "kwargs": kwargs,
                        "require_dense_warmup": True,
                    }
                )
            test_ids = [data.ids[i] for i in f["test"]]
            expected = {}
            for qid in test_ids:
                row = row_of[qid]
                record = {
                    "bm25": _hash_hits(sparse_cache[qid]),
                    "p_star": cheap[qid],
                    "r_star_v2": rescore[qid],
                    "h_star_v2": full[qid],
                }
                for method, threshold in thresholds.items():
                    s = margin[row] if method == "margin_op" else score[row]
                    use_dense = bool(data.forced[row] or s > threshold)
                    record[method] = full[qid] if use_dense else cheap[qid]
                    record[f"{method}_dense"] = use_dense
                expected[qid] = record
            for method in ("h_star", "pe_gh"):
                runs, _ = load_rankings(
                    ws.dev_root / f"results/oof_runs/{method}/{domain}/fold_{fold}.jsonl",
                    domain=domain,
                )
                for qid in test_ids:
                    expected[qid][f"{method}_v1"] = _hash_hits(runs[qid])
            atomic_json(
                ws.results("online_plans", f"{domain}_fold_{fold}.json"),
                {
                    "registry": registry,
                    "query_ids": test_ids,
                    "warmup_ids": sorted(data.ids[i] for i in f["validation"])[:50],
                    "expected": expected,
                    "tiers": {**tiers_, "r_star": r_star},
                    "thresholds": thresholds,
                },
            )
            log(
                stage="online-plan",
                domain=domain,
                fold=fold,
                tiers=tiers_,
                **{
                    k: round(float(np.mean([expected[q][f"{k}_dense"] for q in test_ids])), 3)
                    for k in thresholds
                },
            )


def online(ws: Workspace, args) -> None:
    """Isolated-worker benchmark for every planned fold/domain (resumable); same harness as v3."""
    from contracts.io import load_queries
    from pegh.profiling.runner import run_benchmark
    from pegh.profiling.runtime import RuntimeSettings

    settings = RuntimeSettings.from_yaml(ws.repo / "configs/runtime/windows-physical4-local.yaml")
    plans, folder = sorted(ws.results("online_plans").glob("*.json")), "online"
    if args.detailed:
        settings = RuntimeSettings(
            **{**settings.__dict__, "repetitions": 1, "detailed_stages": True}
        )
        plans, folder = [p for p in plans if p.stem.endswith("_fold_0")], "online_stages"
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
    """Latency, CPU, RSS, encode ratio, ranking/route parity, and OOF quality per method."""
    import numpy as np

    from pegh.data.artifacts import atomic_json

    plans = sorted(ws.results("online_plans").glob("*.json"))
    methods = [e["id"] for e in json.loads(plans[0].read_text(encoding="utf-8"))["registry"]]
    rows = {m: {d: [] for d in ONLINE_DOMAINS} for m in methods}
    rss = {m: dict.fromkeys(ONLINE_DOMAINS, 0) for m in methods}
    mismatches, checked = {}, 0
    for plan_path in plans:
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
                route_key = f"{method}_dense"
                if request["ranking_hash"] != expected[method] or (
                    route_key in expected and request["use_dense"] != expected[route_key]
                ):
                    mismatches[method] = mismatches.get(method, 0) + 1
                rows[method][domain].append(
                    (
                        request["query_id"],
                        request["total_ns"] / 1e6,
                        request["process_cpu_ns"] / 1e6,
                        request["use_dense"],
                    )
                )
    summary = {}
    for method in methods:
        for scope in (*ONLINE_DOMAINS, "all"):
            scoped = ONLINE_DOMAINS if scope == "all" else (scope,)
            data = [r for d in scoped for r in rows[method][d]]
            latency = np.array([r[1] for r in data])
            summary.setdefault(method, {})[scope] = {
                "requests": len(data),
                "mean_ms": float(latency.mean()),
                "p50_ms": float(np.percentile(latency, 50)),
                "p95_ms": float(np.percentile(latency, 95)),
                "cpu_mean_ms": float(np.mean([r[2] for r in data])),
                "encode_ratio": float(np.mean([r[3] for r in data])),
                "peak_rss_mib": max(rss[method][d] for d in scoped) / 2**20,
            }
    rng = np.random.default_rng(42)
    reductions = {}
    for reference in ("h_star_v2", "h_star_v1"):
        for method in methods:
            if method == reference:
                continue
            pairs = []
            for domain in ONLINE_DOMAINS:
                base, cand = {}, {}
                for qid, ms, _, _ in rows[reference][domain]:
                    base[qid] = base.get(qid, 0.0) + ms
                for qid, ms, _, _ in rows[method][domain]:
                    cand[qid] = cand.get(qid, 0.0) + ms
                pairs += [(base[q], cand[q]) for q in base]
            pairs = np.array(pairs)
            draws = rng.integers(0, len(pairs), size=(10_000, len(pairs)))
            ratio = 1 - pairs[draws, 1].sum(axis=1) / pairs[draws, 0].sum(axis=1)
            reductions.setdefault(reference, {})[method] = {
                "mean_reduction": float(1 - pairs[:, 1].sum() / pairs[:, 0].sum()),
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
                branch = "encode" if request["use_dense"] else "skip"
                stages.setdefault(worker["method"], {}).setdefault(branch, []).append(
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
        "schema_version": "v4_online_report_1",
        "requests_checked": checked,
        "ranking_or_route_mismatches": mismatches,
        "summary": summary,
        "mean_reduction": reductions,
        "stage_sample_fold0_one_repeat": stage_means,
        "quality_oof": _online_quality(ws),
    }
    atomic_json(ws.results("online_report.json"), report)
    log(stage="online-report", checked=checked, mismatches=mismatches)
    for method in methods:
        s = summary[method]["all"]
        log(
            method=method,
            mean=round(s["mean_ms"], 2),
            p95=round(s["p95_ms"], 2),
            cpu=round(s["cpu_mean_ms"], 1),
            encode=round(s["encode_ratio"], 3),
            ndcg=report["quality_oof"].get(method),
        )


def _online_quality(ws: Workspace) -> dict:
    """OOF macro nDCG@10 of each benchmarked method on the dev domains (same routes as online)."""
    import numpy as np

    from pegh.v3.pipeline import macro

    frozen = json.loads((ws.repo / "configs/v4/gate_v2.json").read_text(encoding="utf-8"))
    key = frozen["encoder"]
    plans = {
        p.stem: json.loads(p.read_text(encoding="utf-8"))
        for p in ws.results("online_plans").glob("*.json")
    }
    group = {d.domain: d for d in _load_group(ws, ONLINE_DOMAINS, key)}
    out = {}
    for domain in ONLINE_DOMAINS:
        data, row_of = group[domain], {q: n for n, q in enumerate(group[domain].ids)}
        values = {}
        for fold in range(5):
            plan = plans[f"{domain}_fold_{fold}"]
            t = plan["tiers"]
            for qid in plan["query_ids"]:
                r = row_of[qid]
                u = {
                    "bm25": data.utilities["bm25"][r],
                    "p_star": data.utilities[t["p_star"]][r],
                    "h_star_v2": data.utilities[t["h_star"]][r],
                    "r_star_v2": data.utilities[t["r_star"]][r],
                }
                for method in plan["thresholds"]:
                    u[method] = (
                        u["h_star_v2"] if plan["expected"][qid][f"{method}_dense"] else u["p_star"]
                    )
                for method, value in u.items():
                    values.setdefault(method, {}).setdefault(qid, value)
        out[domain] = values
    result = {}
    for method in out[ONLINE_DOMAINS[0]]:
        result[method] = macro({d: np.array(list(out[d][method].values())) for d in ONLINE_DOMAINS})
    for method in ("h_star", "pe_gh"):
        result[f"{method}_v1"] = {"h_star": 0.314625, "pe_gh": 0.312163}[
            method
        ]  # frozen v1 receipts
    return result


FACT_FILES = (
    "encoder_comparison.json",
    "encode_cost.json",
    "develop.json",
    "preregistration.json",
    "evaluation_new.json",
    "online_report.json",
    "proxy_fidelity.json",
)
ONLINE_LABELS = {
    "bm25": ("BM25", "v1"),
    "h_star_v1": ("H* v1 (MiniLM)", "v1"),
    "pe_gh_v1": ("PE-GH v1", "v1"),
    "p_star": ("P*", "v2"),
    "r_star_v2": ("R*", "v2"),
    "h_star_v2": ("H*", "v2"),
    "margin_op": ("Margin cùng ngân sách", "v2"),
}
ONLINE_LABEL_PLACEMENT = {  # points crowded near H* get their labels on the left
    "pe_gh_v2_b80": {"offset": (-8, 5), "ha": "right"},
    "margin_op": {"offset": (-8, -12), "ha": "right"},
}


def report(ws: Workspace, args) -> None:
    """Copy fact files and draw the v4 figures into docs/v4."""
    import shutil

    from pegh.v4 import figures

    docs = ws.repo / "docs/v4"
    (docs / "facts").mkdir(parents=True, exist_ok=True)
    (docs / "figures").mkdir(parents=True, exist_ok=True)
    copied = []
    for name in FACT_FILES:
        if ws.results(name).exists():
            shutil.copy2(ws.results(name), docs / "facts" / name)
            copied.append(name)
    drawn = []
    dev_path, new_path = ws.results("develop.json"), ws.results("evaluation_new.json")
    panels = []
    if dev_path.exists():
        dev = json.loads(dev_path.read_text(encoding="utf-8"))
        name = dev["chosen"]["name"]
        panels.append(
            {
                "title": "6 domain đã dùng, để riêng từng domain (phát triển)",
                "budgets": dev["budgets"],
                "series": {
                    "Gate v2 (BM25 thất bại)": dev["macro_curves"][name],
                    "BM25-margin": dev["macro_curves"]["bm25_margin"],
                    "Ngẫu nhiên": dev["macro_curves"]["random30"],
                },
                "references": {
                    "H* (luôn encode)": dev["h_star_macro"],
                    "P* (không encode)": dev["p_star_macro"],
                },
            }
        )
    if new_path.exists():
        new = json.loads(new_path.read_text(encoding="utf-8"))
        panels.append(
            {
                "title": "6 subforum mới (xác nhận đăng ký trước)",
                "budgets": new["budgets"],
                "series": {
                    "Gate v2 (BM25 thất bại)": new["macro_curves"]["v2"],
                    "BM25-margin": new["macro_curves"]["bm25_margin"],
                    "Ngẫu nhiên": new["macro_curves"]["random30"],
                },
                "references": {
                    "H* (luôn encode)": new["macro"]["h_star"],
                    "P* (không encode)": new["macro"]["p_star"],
                },
            }
        )
        labels = {
            "K1_gate_v2_beats_bm25_margin_matched": "K1: Gate v2 > BM25-margin (50%)",
            "K2_pe_gh_v2_noninferior_to_h_star": "K2: PE-GH v2 không kém H*",
            "K3_pe_gh_v2_superior_to_pe_gh_v1": "K3: PE-GH v2 > PE-GH v1",
            "K4_gate_v2_beats_random_matched": "K4: Gate v2 > ngẫu nhiên (50%)",
        }
        rows = [
            {
                "label": labels[k],
                "estimate": t["estimate"],
                "low": t["two_sided_95"][0],
                "high": t["two_sided_95"][1],
                "verdict": "đạt" if t["holm_reject"] else "không đạt",
            }
            for k, t in new["hypotheses"]["tests"].items()
        ]
        figures.forest(
            rows,
            docs / "figures/v4_hypotheses.png",
            "Giả thuyết đăng ký trước (6 subforum mới): ước lượng và CI 95%",
        )
        drawn.append("v4_hypotheses.png")
    if panels:
        figures.budget_curves(panels, docs / "figures/v4_budget_curves.png")
        drawn.append("v4_budget_curves.png")
    online_path = ws.results("online_report.json")
    if online_path.exists():
        online_ = json.loads(online_path.read_text(encoding="utf-8"))
        points = []
        for method, s in online_["summary"].items():
            label, family = ONLINE_LABELS.get(method, (method, "v2"))
            if method.startswith("pe_gh_v2_b"):
                label = f"PE-GH v2 ({method.removeprefix('pe_gh_v2_b')}% encode)"
            points.append(
                {
                    "name": label,
                    "family": family,
                    "latency_ms": s["all"]["mean_ms"],
                    "ndcg": online_["quality_oof"][method],
                    **ONLINE_LABEL_PLACEMENT.get(method, {}),
                }
            )
        figures.pareto(
            points,
            docs / "figures/v4_pareto_online.png",
            "Chất lượng và độ trễ (programmers + unix, đo online)",
        )
        drawn.append("v4_pareto_online.png")
    log(stage="report", copied=copied, figures=drawn)


STAGES = {
    "report": report,
    "online-plan": online_plan,
    "online": online,
    "online-report": online_report,
    "evaluate": evaluate,
    "vectors": vectors,
    "quality": quality,
    "encode-cost": encode_cost,
    "compare": compare,
    "proxy": proxy,
    "features": features,
    "tiers": tiers,
    "develop": develop,
    "freeze": freeze,
    "preregister": preregister,
    "fetch": fetch,
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=tuple(STAGES))
    parser.add_argument("--encoders", nargs="+", default=["bge_small_q"])
    parser.add_argument("--domains", nargs="+")
    parser.add_argument("--threads", type=int, default=6)
    parser.add_argument("--detailed", action="store_true")
    parser.add_argument("--root", default=str(DEFAULT_ROOT))
    parser.add_argument("--v3-root", default=str(DEFAULT_V3_ROOT))
    parser.add_argument("--dev-root", default=str(DEFAULT_DEV_ROOT))
    parser.add_argument("--dev-dense-root", default=str(DEFAULT_DEV_DENSE))
    args = parser.parse_args()
    ws = Workspace.create(args.root, args.v3_root, args.dev_root, args.dev_dense_root)
    STAGES[args.stage](ws, args)


if __name__ == "__main__":
    main()
