"""Exploratory, isolated prior-router benchmark (Phase 2); old receipts stay read-only."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from pegh.data.artifacts import atomic_json, file_hash, object_hash
from pegh.v4.workspace import NEW_DOMAINS, SEEN_DOMAINS

DOMAINS = ("programmers", "unix")
BUDGETS = (0.3, 0.5, 0.8)
METHODS = (
    "bm25",
    "p_star",
    "h_star_v2",
    "r_star_v2",
    "pe_gh_v2_b30",
    "pe_gh_v2_b50",
    "pe_gh_v2_b80",
    "litegator_b30",
    "litegator_b50",
    "litegator_b80",
    "bert_b30",
    "bert_b50",
    "bert_b80",
)


def log(**fields):
    print(json.dumps({"time": time.strftime("%H:%M:%S"), **fields}, ensure_ascii=False), flush=True)


def load_group(ws, domains, encoder, *, with_tiers=True):
    from pegh.v3.cache import load_npz_cache
    from pegh.v3.pipeline import load_domain

    group = []
    for domain in domains:
        feature_key = encoder
        feature_path = ws.features(encoder, domain)
        if not feature_path.exists():
            feature_key = "minilm"
            feature_path = ws.features("minilm", domain)
        features = load_npz_cache(ws, feature_key, domain, "features", feature_path)
        tiers = None
        if with_tiers and ws.tiers(encoder, domain).exists():
            from pegh.v4.workspace import query_prefix

            tiers = load_npz_cache(
                ws,
                encoder,
                domain,
                "tiers",
                ws.tiers(encoder, domain),
                prefix=query_prefix(encoder),
            )
        group.append(load_domain(ws, domain, encoder, features, tiers))
    return group


def train_bert(ws, args):
    """Train two seeded heads on the other five topics, never replace the all-six model."""
    from pegh.v4 import prior as p

    frozen = json.loads((ws.repo / "configs/v4/gate_v2.json").read_text(encoding="utf-8"))
    requested = tuple(args.domains) if args.domains else DOMAINS
    if any(d not in DOMAINS for d in requested):
        raise ValueError("LODO BERT targets must be programmers/unix")
    group = None
    for held in requested:
        model_dir = ws.root / "artifacts/prior/bert_lodo" / held
        receipt_path = ws.results("prior_lodo_bert", f"{held}.json")
        recipe = {
            "model": p.BERT_ID,
            "revision": p.BERT_REVISION,
            "held_out": held,
            "trained_on": [d for d in SEEN_DOMAINS if d != held],
            "label": "BM25 nDCG@10 == 0",
            "max_length": p.BERT_MAX_LENGTH,
            "epochs": 1,
            "batch": 8,
            "learning_rate": 2e-5,
            "seed": 42,
            "seed_scope": "classification-head initialization, training shuffle and dropout",
        }
        if receipt_path.exists():
            saved = json.loads(receipt_path.read_text(encoding="utf-8"))
            if (
                saved["recipe"] != recipe
                or file_hash(model_dir / "model.safetensors") != saved["model_sha256"]
            ):
                raise ValueError(f"{held}: saved LODO model/recipe differs")
            log(stage="prior-lodo-bert", held_out=held, reused=True)
            continue
        if (model_dir / "config.json").exists():
            raise ValueError(f"incomplete LODO checkpoint without receipt: {model_dir}")
        if group is None:
            group = load_group(ws, SEEN_DOMAINS, frozen["encoder"], with_tiers=False)
        pairs, labels = [], []
        for data in group:
            if data.domain != held:
                pairs.extend(p.top_document_pairs(ws, data.domain, data.ids))
                labels.extend((data.utilities["bm25"] == 0).astype(int).tolist())
        log(stage="prior-lodo-bert", held_out=held, queries=len(pairs), recipe=recipe)
        router = p.BertRouter(p.bert_path(ws.models), args.threads, seed=42)
        training = router.train(
            pairs,
            labels,
            seed=42,
            log=lambda held_out=held, **f: log(stage="prior-lodo-bert", held_out=held_out, **f),
        )
        model_dir.mkdir(parents=True, exist_ok=True)
        router.model.save_pretrained(model_dir)
        router.tokenizer.save_pretrained(model_dir)
        atomic_json(
            receipt_path,
            {
                "status": "exploratory",
                "recipe": recipe,
                "training": {
                    **training,
                    "queries": len(pairs),
                    "positive_rate": float(np.mean(labels)),
                },
                "model_sha256": file_hash(model_dir / "model.safetensors"),
                "completed_at_utc": datetime.now(UTC).isoformat(),
            },
        )
        log(stage="prior-lodo-bert", held_out=held, training=training, saved=str(model_dir))
        del router


LITE_GRID = tuple({"C": c, "class_weight": w} for c in (0.1, 1.0, 10.0) for w in (None, "balanced"))
AREA_BUDGETS = tuple(i / 10 for i in range(2, 9))


def fit_svm(group, tiers, params):
    from pegh.v4.prior import fit_litegator

    return fit_litegator(
        [d.features["v1"] for d in group],
        [(d.utilities[tiers["h_star"]] > d.utilities[tiers["p_star"]]).astype(int) for d in group],
        c=params["C"],
        class_weight=params["class_weight"],
    )


def select_litegator(group):
    """Identical LODO area criterion to develop(), with only the declared six candidates."""
    from pegh.v4 import gate as g

    curves = [[] for _ in LITE_GRID]
    per_domain = {}
    for held in group:
        train = [d for d in group if d.domain != held.domain]
        tiers = g.fixed_tiers([d.utilities for d in train])
        low, high = held.utilities[tiers["p_star"]], held.utilities[tiers["h_star"]]
        per_domain[held.domain] = []
        for slot, params in enumerate(LITE_GRID):
            model = fit_svm(train, tiers, params)
            score = model.score(held.features["v1"])
            values = [
                float(np.where(g.route_top(score, held.forced, held.ids, b), high, low).mean())
                for b in AREA_BUDGETS
            ]
            curves[slot].append(values)
            per_domain[held.domain].append(values)
    macro_curves = [np.mean(v, axis=0).tolist() for v in curves]
    areas = [float(np.mean(v)) for v in macro_curves]
    chosen = max(range(len(LITE_GRID)), key=lambda i: (areas[i], -i))
    return {
        "trained_on": [d.domain for d in group],
        "budgets": list(AREA_BUDGETS),
        "candidates": [
            {**params, "area_0_2_to_0_8": areas[i], "macro_curve": macro_curves[i]}
            for i, params in enumerate(LITE_GRID)
        ],
        "domain_curves": per_domain,
        "selected_index": chosen,
        "selected": LITE_GRID[chosen],
        "rule": "highest mean LODO macro nDCG@10 over 0.2-0.8; ties keep first grid candidate",
    }


def audit_v2_selection(ws, args):
    """Audit whether the frozen recipe can also be selected without each measured topic."""
    from pegh.v4 import gate as g

    frozen = read_json(ws.repo / "configs/v4/gate_v2.json")
    group = load_group(ws, SEEN_DOMAINS, frozen["encoder"])
    results = {}
    for outer in DOMAINS:
        available = [d for d in group if d.domain != outer]
        totals = {spec.name: [] for spec in g.CANDIDATES}
        for held in available:
            train = [d for d in available if d.domain != held.domain]
            tiers = g.fixed_tiers([d.utilities for d in train])
            for spec in g.CANDIDATES:
                model = g.fit(
                    spec,
                    [d.matrix(spec.groups) for d in train],
                    [d.utilities["bm25"] for d in train],
                )
                x = held.matrix(spec.groups)
                score = model.score(x, g.domain_stats(x))
                values = [
                    np.where(
                        g.route_top(score, held.forced, held.ids, budget),
                        held.utilities[tiers["h_star"]],
                        held.utilities[tiers["p_star"]],
                    ).mean()
                    for budget in AREA_BUDGETS
                ]
                totals[spec.name].append(float(np.mean(values)))
        areas = {name: float(np.mean(values)) for name, values in totals.items()}
        names = [spec.name for spec in g.CANDIDATES]
        chosen = max(names, key=lambda n: (areas[n], -names.index(n)))
        results[outer] = {
            "trained_on": [d.domain for d in available],
            "area": areas,
            "selected": chosen,
            "frozen": g.LinearGate.from_json(frozen["gate"]).spec.name,
        }
        log(
            stage="prior-v2-selection-audit",
            held_out=outer,
            selected=chosen,
            frozen=results[outer]["frozen"],
        )
    atomic_json(ws.results("prior_v2_selection_audit.json"), results)


def tune_litegator(ws, args):
    from sklearn.metrics import roc_auc_score

    from pegh.v3.pipeline import bootstrap, macro
    from pegh.v4 import gate as g

    frozen = json.loads((ws.repo / "configs/v4/gate_v2.json").read_text(encoding="utf-8"))
    seen = load_group(ws, SEEN_DOMAINS, frozen["encoder"])
    selection = select_litegator(seen)
    online = {}
    for held in DOMAINS:
        train = [d for d in seen if d.domain != held]
        nested = select_litegator(train)
        tiers = g.fixed_tiers([d.utilities for d in train])
        model = fit_svm(train, tiers, nested["selected"])
        gate_path = ws.root / "artifacts/gates/litegator_lodo" / f"{held}.json"
        payload = {
            "schema_version": "v4_litegator_lodo_1",
            "domain": held,
            "trained_on": [d.domain for d in train],
            "tiers": tiers,
            "hyperparameters": nested["selected"],
            "selection": nested,
            "gate": model.to_json(),
            "gate_sha256": model.sha256,
        }
        atomic_json(gate_path, payload)
        online[held] = {
            "selection": nested,
            "gate_path": str(gate_path),
            "file_sha256": file_hash(gate_path),
            "gate_sha256": model.sha256,
        }
        log(stage="prior-tune", held_out=held, hyperparameters=nested["selected"])
    selection_report = {
        "status": "exploratory",
        "global": selection,
        "online_nested_lodo": online,
        "no_evaluation_labels_used": True,
        "bert_tuning_limitation": "paper recipe kept fixed; no BERT hyperparameter search because of cost",
    }
    # Save all selections before loading any of the six unseen evaluation topics.
    atomic_json(ws.results("prior_litegator_tuning.json"), selection_report)
    log(stage="prior-tune", global_hyperparameters=selection["selected"])
    new = load_group(ws, NEW_DOMAINS, frozen["encoder"])
    gate = g.LinearGate.from_json(frozen["gate"])
    models = {
        "litegator_default": fit_svm(seen, frozen["tiers"], {"C": 1.0, "class_weight": None}),
        "litegator_tuned": fit_svm(seen, frozen["tiers"], selection["selected"]),
    }
    scores = {
        name: {d.domain: model.score(d.features["v1"]) for d in new}
        for name, model in models.items()
    }
    scores["pe_gh_v2"] = {
        d.domain: gate.score(d.matrix(gate.spec.groups), g.domain_stats(d.matrix(gate.spec.groups)))
        for d in new
    }
    groups = {d.domain: d.groups for d in new}
    matched, comparisons = {}, {}
    original = json.loads(ws.results("prior_comparison.json").read_text(encoding="utf-8"))
    for budget in BUDGETS:
        values = {}
        for name, by_domain in scores.items():
            values[name] = {}
            for d in new:
                low, high = (d.utilities[frozen["tiers"][k]] for k in ("p_star", "h_star"))
                out = np.zeros(len(d.ids))
                for fold in d.folds:
                    test = fold["test"]
                    chosen = g.route_top(
                        by_domain[d.domain][test], d.forced[test], [d.ids[i] for i in test], budget
                    )
                    out[test] = np.where(chosen, high[test], low[test])
                values[name][d.domain] = out
        tag = f"{budget:.1f}"
        matched[tag] = {n: macro(v) for n, v in values.items()}
        if not np.isclose(
            matched[tag]["litegator_default"],
            original["matched_budgets"][tag]["litegator"],
            atol=1e-14,
            rtol=0,
        ):
            raise ValueError("paper-default LiteGator differs from Phase 1")
        for name in models:
            comparisons.setdefault(name, {})[tag] = bootstrap(
                {d: values["pe_gh_v2"][d] - values[name][d] for d in groups}, groups
            )
    atomic_json(
        ws.results("prior_litegator_tuned.json"),
        {
            "status": "exploratory",
            "domains": list(NEW_DOMAINS),
            "selected_on": list(SEEN_DOMAINS),
            "selected_hyperparameters": selection["selected"],
            "matched_budgets": matched,
            "pe_gh_v2_minus": comparisons,
            "auc_bm25_failure": {
                n: float(
                    np.mean([roc_auc_score(d.utilities["bm25"] == 0, sc[d.domain]) for d in new])
                )
                for n, sc in scores.items()
            },
            "selection_sha256": file_hash(ws.results("prior_litegator_tuning.json")),
        },
    )


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def batch1_bert_scores(ws, domain, ids, queries, sparse_cache):
    """Offline expectations use the exact batch-1 request path, never the all-six model."""
    import psutil
    import torch

    from contracts.io import iter_corpus
    from pegh.v4.prior import BertRouter

    receipt = read_json(ws.results("prior_lodo_bert", f"{domain}.json"))
    model_dir = ws.root / "artifacts/prior/bert_lodo" / domain
    if domain in receipt["recipe"]["trained_on"] or receipt["recipe"]["held_out"] != domain:
        raise ValueError("BERT expectations would leak the measured domain")
    if file_hash(model_dir / "model.safetensors") != receipt["model_sha256"]:
        raise ValueError("BERT checkpoint drift")
    identity = {
        "model_sha256": receipt["model_sha256"],
        "batch": 1,
        "torch_threads": 4,
        "torch_interop_threads": 1,
        "max_length": 256,
        "affinity": [0, 2, 4, 6],
        "corpus_sha256": file_hash(ws.raw(domain) / "corpus.jsonl"),
        "queries_sha256": file_hash(ws.raw(domain) / "queries.jsonl"),
        "bm25_run_sha256": file_hash(ws.quality("bm25", domain)),
    }
    path = ws.results("prior_lodo_bert", f"{domain}_batch1.npz")
    metadata = path.with_suffix(".json")
    if path.exists() and metadata.exists():
        saved = read_json(metadata)
        if saved["identity"] != identity or file_hash(path) != saved["scores_sha256"]:
            raise ValueError("BERT batch-1 expectation cache drift")
        with np.load(path) as stored:
            if list(stored["ids"]) != ids:
                raise ValueError("BERT batch-1 query order differs")
            return stored["scores"].copy(), identity
    documents = {
        d.doc_id: f"{d.title} {d.body}".strip()
        for d in iter_corpus(ws.raw(domain) / "corpus.jsonl", domain)
    }
    process = psutil.Process()
    original_affinity = process.cpu_affinity()
    process.cpu_affinity([0, 2, 4, 6])
    try:
        if torch.get_num_interop_threads() != 1:
            torch.set_num_interop_threads(1)
        router = BertRouter(model_dir, 4)
        scores = []
        for i, qid in enumerate(ids):
            ranking = sparse_cache[qid]
            text = documents.get(ranking.hits[0].doc_id, "") if ranking.hits else ""
            scores.append(float(router.score([(queries[qid].text, text)], batch=1)[0]))
            if (i + 1) % 200 == 0:
                log(stage="prior-online-plan", domain=domain, bert_scored=i + 1, queries=len(ids))
    finally:
        process.cpu_affinity(original_affinity)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.stem + ".partial.npz")
    np.savez(temporary, ids=np.array(ids), scores=np.array(scores))
    temporary.replace(path)
    atomic_json(metadata, {"identity": identity, "scores_sha256": file_hash(path)})
    return np.array(scores), identity


def online_plan(ws, args):
    """Clone only read-only shared-tier expectations, then add honest LODO prior scores."""
    import copy

    from contracts.io import load_queries
    from pegh.evaluation.runs import load_rankings
    from pegh.v4 import gate as g
    from pegh.v4.prior import LinearSVM

    if ws.results("prior_online_plan_receipt.json").exists():
        raise ValueError("Phase-2 plan already sealed; do not regenerate after measuring")
    frozen = read_json(ws.repo / "configs/v4/gate_v2.json")
    group = load_group(ws, SEEN_DOMAINS, frozen["encoder"])
    by_name = {d.domain: d for d in group}
    v2_audit = read_json(ws.results("prior_v2_selection_audit.json"))
    for domain in DOMAINS:
        data = by_name[domain]
        train = [d for d in group if d.domain != domain]
        tiers = g.fixed_tiers([d.utilities for d in train])
        if v2_audit[domain]["trained_on"] != [d.domain for d in train]:
            raise ValueError("v2 recipe selection used a different topic set")
        spec = next(s for s in g.CANDIDATES if s.name == v2_audit[domain]["selected"])
        v2_model = g.fit(
            spec, [d.matrix(spec.groups) for d in train], [d.utilities["bm25"] for d in train]
        )
        x = data.matrix(spec.groups)
        v2_stats = g.domain_stats(x) if spec.norm == "domain" else None
        v2_scores = np.array([v2_model.score(row[None, :], v2_stats)[0] for row in x])
        v2_gate_path = ws.root / "artifacts/gates/v2_prior_nested_lodo" / f"{domain}.json"
        atomic_json(
            v2_gate_path,
            {
                "domain": domain,
                "trained_on": [d.domain for d in train],
                "gate": v2_model.to_json(),
                "domain_stats": v2_stats,
                "selection": v2_audit[domain],
            },
        )
        gate_path = ws.root / "artifacts/gates/litegator_lodo" / f"{domain}.json"
        payload = read_json(gate_path)
        if payload["trained_on"] != [d.domain for d in train] or payload["tiers"] != tiers:
            raise ValueError("LiteGator training set or shared LODO tiers differ")
        svm = LinearSVM.from_json(payload["gate"])
        if svm.sha256 != payload["gate_sha256"]:
            raise ValueError("LiteGator exported score differs")
        lite_scores = np.array([svm.score(row[None, :])[0] for row in data.features["v1"]])
        queries = {q.query_id: q for q in load_queries(ws.raw(domain) / "queries.jsonl", domain)}
        sparse_cache, _ = load_rankings(ws.quality("bm25", domain), domain=domain)
        bert_scores, bert_identity = batch1_bert_scores(ws, domain, data.ids, queries, sparse_cache)
        row_of = {qid: i for i, qid in enumerate(data.ids)}
        for fold in range(5):
            old = read_json(ws.results("online_plans", f"{domain}_fold_{fold}.json"))
            if any(old["tiers"][k] != tiers[k] for k in ("p_star", "h_star")):
                raise ValueError("old shared tiers differ from current LODO training")
            base_entries = {
                e["id"]: copy.deepcopy(e) for e in old["registry"] if e["id"] in METHODS
            }
            if set(base_entries) != set(METHODS[:7]):
                raise ValueError("old plan must contain all seven shared reference methods")
            f = data.folds[fold]
            reference = np.concatenate([f["train"], f["validation"]])
            thresholds = {}
            policies = {}
            for budget in BUDGETS:
                name = f"pe_gh_v2_b{int(budget * 100)}"
                policies[name] = g.calibrate_budget(
                    v2_scores[reference],
                    data.forced[reference],
                    [data.ids[i] for i in reference],
                    budget,
                )
                thresholds[name] = policies[name].threshold
                base_entries[name]["kwargs"].update(
                    gate_path=str(v2_gate_path),
                    expected_gate_sha256=file_hash(v2_gate_path),
                    threshold=thresholds[name],
                    budget_policy=policies[name].to_json(),
                )
            for prefix, scores in (("litegator", lite_scores), ("bert", bert_scores)):
                for budget in BUDGETS:
                    name = f"{prefix}_b{int(budget * 100)}"
                    policies[name] = g.calibrate_budget(
                        scores[reference],
                        data.forced[reference],
                        [data.ids[i] for i in reference],
                        budget,
                    )
                    threshold = policies[name].threshold
                    entry = copy.deepcopy(base_entries["pe_gh_v2_b30"])
                    entry["id"] = name
                    kwargs = entry["kwargs"]
                    kwargs.update(
                        threshold=threshold, budget_policy=policies[name].to_json(), torch_threads=4
                    )
                    kwargs.pop("gate_path", None)
                    kwargs.pop("expected_gate_sha256", None)
                    if prefix == "litegator":
                        kwargs.update(
                            scorer="litegator",
                            gate_path=str(gate_path),
                            expected_gate_sha256=file_hash(gate_path),
                        )
                    else:
                        kwargs.update(
                            scorer="arabzadeh_bert",
                            bert_dir=str(ws.root / "artifacts/prior/bert_lodo" / domain),
                            expected_bert_sha256=bert_identity["model_sha256"],
                            corpus_path=str(ws.raw(domain) / "corpus.jsonl"),
                            expected_corpus_sha256=bert_identity["corpus_sha256"],
                            bert_receipt_path=str(ws.results("prior_lodo_bert", f"{domain}.json")),
                        )
                    base_entries[name] = entry
                    thresholds[name] = threshold
            registry = [base_entries[n] for n in METHODS]
            for entry in registry:
                entry["kwargs"]["torch_threads"] = 4
            expected = {}
            quality = {}
            for qid in old["query_ids"]:
                row = row_of[qid]
                record = {k: old["expected"][qid][k] for k in METHODS[:7]}
                for name in METHODS[4:7]:
                    dense = policies[name].use_dense(v2_scores[row], qid, bool(data.forced[row]))
                    record[f"{name}_dense"] = dense
                    record[name] = record["h_star_v2"] if dense else record["p_star"]
                for prefix, scores in (("litegator", lite_scores), ("bert", bert_scores)):
                    for budget in BUDGETS:
                        name = f"{prefix}_b{int(budget * 100)}"
                        dense = policies[name].use_dense(scores[row], qid, bool(data.forced[row]))
                        record[f"{name}_dense"] = dense
                        record[name] = record["h_star_v2"] if dense else record["p_star"]
                # Keep both tier utilities to report actual online quality even if parity fails.
                quality[qid] = {
                    "group": data.groups[row],
                    "bm25": float(data.utilities["bm25"][row]),
                    "p_star": float(data.utilities[tiers["p_star"]][row]),
                    "h_star_v2": float(data.utilities[tiers["h_star"]][row]),
                    "r_star_v2": float(data.utilities[old["tiers"]["r_star"]][row]),
                }
                expected[qid] = record
            plan = {
                "status": "exploratory",
                "domain": domain,
                "fold": fold,
                "registry": registry,
                "query_ids": old["query_ids"],
                "warmup_ids": old["warmup_ids"],
                "expected": expected,
                "quality": quality,
                "thresholds": thresholds,
                "tiers": old["tiers"],
                "reference_plan_sha256": file_hash(
                    ws.results("online_plans", f"{domain}_fold_{fold}.json")
                ),
                "bert_score_identity": bert_identity,
                "litegator_variant": "nested_LODO_tuned_on_other_five",
                "v2_selection": v2_audit[domain],
            }
            atomic_json(ws.results("online_plans_prior", f"{domain}_fold_{fold}.json"), plan)
            log(stage="prior-online-plan", domain=domain, fold=fold, methods=len(registry))


def freeze_plan(ws, args):
    """Seal protocol, inputs and executable source before either smoke or full measurement."""
    import yaml

    from pegh.profiling.provenance import source_snapshot

    paths = sorted(ws.results("online_plans_prior").glob("*.json"))
    if len(paths) != 10:
        raise ValueError("exactly ten domain/fold plans are required")
    config_path = ws.repo / "configs/v4/prior_online_plan.yaml"
    protocol = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if tuple(protocol["methods"]) != METHODS or tuple(protocol["budgets"]) != BUDGETS:
        raise ValueError("declared methods/budgets differ from implemented plan")
    if protocol["training"]["litegator"]["grid_C"] != [0.1, 1.0, 10.0] or protocol["training"][
        "litegator"
    ]["grid_class_weight"] != [None, "balanced"]:
        raise ValueError("declared LiteGator search differs from implemented search")
    atomic_json(
        ws.results("prior_lodo_bert.json"),
        {domain: read_json(ws.results("prior_lodo_bert", f"{domain}.json")) for domain in DOMAINS},
    )
    for path in paths:
        plan = read_json(path)
        if tuple(e["id"] for e in plan["registry"]) != METHODS:
            raise ValueError("registered methods differ from declared Phase-2 methods")
        if len(plan["warmup_ids"]) != 50:
            raise ValueError("fifty disjoint validation warmups required")
        if set(plan["query_ids"]) & set(plan["warmup_ids"]):
            raise ValueError("warmup/test overlap")
        expected_training = [d for d in SEEN_DOMAINS if d != plan["domain"]]
        entries = {e["id"]: e["kwargs"] for e in plan["registry"]}
        shared = entries["pe_gh_v2_b30"]
        for name in METHODS[4:]:
            kwargs = entries[name]
            if any(
                kwargs[k] != shared[k]
                for k in (
                    "domain",
                    "fold",
                    "sparse_dir",
                    "dense_dir",
                    "expected_sparse_sha256",
                    "expected_dense_sha256",
                    "query_prefix",
                    "proxy_dir",
                    "expected_proxy_hash",
                    "p_star",
                    "h_star",
                    "torch_threads",
                )
            ):
                raise ValueError("gated methods differ in more than the decision")
            if name.startswith("bert"):
                trained = read_json(ws.results("prior_lodo_bert", f"{plan['domain']}.json"))[
                    "recipe"
                ]["trained_on"]
            else:
                trained = read_json(Path(kwargs["gate_path"]))["trained_on"]
            if trained != expected_training:
                raise ValueError("a router used labels from the measured topic")
    if sum(len(read_json(p)["query_ids"]) for p in paths) != 1948:
        raise ValueError("the 1,948 OOF queries must be measured")
    payload = {
        "status": "exploratory",
        "protocol_sha256": file_hash(config_path),
        "plans": {p.name: file_hash(p) for p in paths},
        "source_snapshot": source_snapshot(),
        "runtime_profile_sha256": file_hash(
            ws.repo / "configs/runtime/windows-physical4-local.yaml"
        ),
        "training_receipts": {
            d: file_hash(ws.results("prior_lodo_bert", f"{d}.json")) for d in DOMAINS
        },
        "litegator_selection_sha256": file_hash(ws.results("prior_litegator_tuning.json")),
        "v2_selection_sha256": file_hash(ws.results("prior_v2_selection_audit.json")),
        "no_latency_result_selection": True,
        "full_request_count": 1948 * 5 * len(METHODS),
    }
    path = ws.results("prior_online_plan_receipt.json")
    if path.exists():
        existing = read_json(path)
        identity = {
            k: v for k, v in existing.items() if k not in ("registered_at_utc", "receipt_sha256")
        }
        if identity != payload:
            raise ValueError(
                "sealed source/plan drift; preserve receipt and resolve before measuring"
            )
        return
    payload["registered_at_utc"] = datetime.now(UTC).isoformat()
    payload["receipt_sha256"] = object_hash(payload)
    atomic_json(path, payload)
    log(
        stage="prior-online-freeze",
        protocol_sha256=payload["protocol_sha256"],
        receipt_sha256=payload["receipt_sha256"],
        requests=payload["full_request_count"],
    )


def validate_seal(ws):
    from pegh.profiling.provenance import source_snapshot

    receipt = read_json(ws.results("prior_online_plan_receipt.json"))
    if (
        object_hash({k: v for k, v in receipt.items() if k != "receipt_sha256"})
        != receipt["receipt_sha256"]
    ):
        raise ValueError("Phase-2 receipt checksum differs")
    if file_hash(ws.repo / "configs/v4/prior_online_plan.yaml") != receipt["protocol_sha256"]:
        raise ValueError("Phase-2 protocol drift")
    if source_snapshot()["combined_sha256"] != receipt["source_snapshot"]["combined_sha256"]:
        raise ValueError("source/config edited after Phase-2 seal")
    if (
        file_hash(ws.results("prior_litegator_tuning.json"))
        != receipt["litegator_selection_sha256"]
    ):
        raise ValueError("LiteGator model selection changed after seal")
    if file_hash(ws.results("prior_v2_selection_audit.json")) != receipt["v2_selection_sha256"]:
        raise ValueError("v2 model selection changed after seal")
    for name, expected in receipt["plans"].items():
        if file_hash(ws.results("online_plans_prior", name)) != expected:
            raise ValueError(f"Phase-2 input plan drift: {name}")
    for domain, expected in receipt["training_receipts"].items():
        if file_hash(ws.results("prior_lodo_bert", f"{domain}.json")) != expected:
            raise ValueError("LODO BERT training receipt drift")
    return receipt


def run_online(ws, args, *, smoke=False):
    from dataclasses import replace

    from contracts.io import load_queries
    from pegh.profiling.runner import run_benchmark
    from pegh.profiling.runtime import RuntimeSettings

    receipt = validate_seal(ws)
    if not smoke:
        smoke_report = read_json(ws.results("prior_online_smoke.json"))
        if smoke_report["ranking_or_route_mismatches"] or smoke_report["requests_checked"] != 156:
            raise ValueError("full measurement requires a clean, complete 156-request smoke")
        if smoke_report["plan_receipt_sha256"] != receipt["receipt_sha256"]:
            raise ValueError("smoke used a different sealed plan")
    folder = "online_prior_smoke" if smoke else "online_prior"
    session_path = ws.results(folder, "session.json")
    if session_path.exists():
        session = read_json(session_path)
        if session["status"] == "complete":
            log(stage="prior-online", reused_completed_session=True, smoke=smoke)
            return
        raise ValueError(
            "interrupted session retained; do not silently rerun or select better results"
        )
    session = {
        "status": "running",
        "exploratory": True,
        "smoke": smoke,
        "started_at_utc": datetime.now(UTC).isoformat(),
        "plan_receipt_sha256": receipt["receipt_sha256"],
        "runs": [],
    }
    atomic_json(session_path, session)
    settings = RuntimeSettings.from_yaml(ws.repo / "configs/runtime/windows-physical4-local.yaml")
    if smoke:
        settings = replace(settings, repetitions=1)
    try:
        for filename in receipt["plans"]:
            plan = read_json(ws.results("online_plans_prior", filename))
            if smoke and plan["fold"] != 0:
                continue
            queries = {
                q.query_id: q
                for q in load_queries(ws.raw(plan["domain"]) / "queries.jsonl", plan["domain"])
            }
            selected = plan["query_ids"][:6] if smoke else plan["query_ids"]
            output = ws.results(folder, filename.removesuffix(".json"))
            log(stage="prior-online", run=output.name, smoke=smoke, queries=len(selected))
            manifest = run_benchmark(
                plan["registry"],
                [queries[q] for q in selected],
                [queries[q] for q in plan["warmup_ids"]],
                output,
                settings,
                split="test",
                fold=plan["fold"],
                record_ranked_ids=True,
            )
            session["runs"].append(
                {
                    "run": output.name,
                    "manifest_sha256": file_hash(output / "manifest.json"),
                    "status": manifest["status"],
                }
            )
            atomic_json(session_path, session)
        validate_seal(ws)
        session["status"] = "complete"
    except Exception as exc:
        session["status"] = "failed"
        session["error"] = str(exc)
        raise
    finally:
        session["ended_at_utc"] = datetime.now(UTC).isoformat()
        atomic_json(session_path, session)
    if smoke:
        report_online(ws, args, smoke=True)


def latency_comparison(left, right, *, samples=10_000, seed=42):
    """Harness query bootstrap: repetitions stay paired within a query; no requests trimmed."""
    if left.keys() != right.keys():
        raise ValueError("latency comparison query coverage differs")
    pairs = np.array([[np.mean(left[q]), np.mean(right[q])] for q in sorted(left)])
    rng = np.random.default_rng(seed)
    draws = rng.integers(0, len(pairs), size=(samples, len(pairs)))
    deltas = (pairs[draws, 0] - pairs[draws, 1]).mean(axis=1)
    reductions = 1 - pairs[draws, 1].sum(axis=1) / pairs[draws, 0].sum(axis=1)
    return {
        "mean_difference_ms": float((pairs[:, 0] - pairs[:, 1]).mean()),
        "two_sided_95_ms": np.quantile(deltas, [0.025, 0.975]).tolist(),
        "mean_reduction_right_relative_to_left": float(1 - pairs[:, 1].sum() / pairs[:, 0].sum()),
        "reduction_ci95": np.quantile(reductions, [0.025, 0.975]).tolist(),
        "bootstrap_samples": samples,
        "seed": seed,
        "unit": "query with all repetitions paired",
    }


def report_online(ws, args, *, smoke=False):
    from contracts.types import Hit, Ranking
    from pegh.data.qrels import load_qrels
    from pegh.evaluation.metrics import query_metrics
    from pegh.v3.pipeline import bootstrap

    receipt = validate_seal(ws)
    folder = "online_prior_smoke" if smoke else "online_prior"
    session_path = ws.results(folder, "session.json")
    session = read_json(session_path)
    if session["status"] != "complete":
        raise ValueError("cannot present an incomplete measurement session as complete")
    rows = {m: {d: [] for d in DOMAINS} for m in METHODS}
    quality = {m: {d: {} for d in DOMAINS} for m in METHODS}
    latencies = {m: {} for m in METHODS}
    group_of = {d: {} for d in DOMAINS}
    rss = {m: {d: 0 for d in DOMAINS} for m in METHODS}
    mismatch = {m: {"ranking": 0, "route": 0, "either": 0} for m in METHODS}
    details, checked, quality_cache, machines = [], 0, {}, []
    qrels = {d: load_qrels(ws.raw(d) / "qrels.tsv", d) for d in DOMAINS}
    for run in session["runs"]:
        directory = ws.results(folder, run["run"])
        manifest_path = directory / "manifest.json"
        if file_hash(manifest_path) != run["manifest_sha256"]:
            raise ValueError("benchmark manifest drift")
        manifest = read_json(manifest_path)
        if (
            manifest["status"] != "complete"
            or len(manifest["workers"]) != len(METHODS) * manifest["settings"]["repetitions"]
        ):
            raise ValueError("benchmark workers missing or incomplete")
        plan = read_json(ws.results("online_plans_prior", run["run"] + ".json"))
        domain = plan["domain"]
        for worker in manifest["workers"]:
            worker_dir = directory / worker["directory"]
            if file_hash(worker_dir / "worker.json") != worker["receipt_sha256"]:
                raise ValueError("worker receipt drift")
            measured = read_json(worker_dir / "worker.json")
            if (
                measured["status"] != "complete"
                or measured["completed_requests"] != manifest["query_count"]
            ):
                raise ValueError("missing measured requests")
            if file_hash(worker_dir / "requests.jsonl") != measured["requests_sha256"]:
                raise ValueError("measured request bytes drift")
            if measured["source_hash"] != receipt["source_snapshot"]["combined_sha256"]:
                raise ValueError("workers did not use the sealed source")
            if measured["runtime"]["resources"]["effective_affinity"] != [0, 2, 4, 6]:
                raise ValueError("workers did not use the same four cores")
            method = worker["method"]
            if method == "bert_b30":
                machines.append(measured["runtime"])
            memory = measured["memory"]
            rss[method][domain] = max(
                rss[method][domain], memory["os_peak_rss_bytes"] or memory["sampled_peak_rss_bytes"]
            )
            for line in (worker_dir / "requests.jsonl").read_text(encoding="utf-8").splitlines():
                request = json.loads(line)
                qid = request["query_id"]
                expected = plan["expected"][qid]
                ranked_ids = request["ranked_doc_ids"]
                if object_hash(ranked_ids) != request["ranking_hash"]:
                    raise ValueError("recorded ranking IDs/hash disagree")
                checked += 1
                wrong_rank = request["ranking_hash"] != expected[method]
                use_dense = expected.get(f"{method}_dense", method in ("h_star_v2", "r_star_v2"))
                wrong_route = request["use_dense"] != use_dense
                mismatch[method]["ranking"] += int(wrong_rank)
                mismatch[method]["route"] += int(wrong_route)
                mismatch[method]["either"] += int(wrong_rank or wrong_route)
                if wrong_rank or wrong_route:
                    details.append(
                        {
                            "domain": domain,
                            "fold": plan["fold"],
                            "method": method,
                            "query_id": qid,
                            "repetition": worker["repetition"],
                            "expected_hash": expected[method],
                            "actual_hash": request["ranking_hash"],
                            "expected_dense": use_dense,
                            "actual_dense": request["use_dense"],
                        }
                    )
                cache_key = (domain, qid, request["ranking_hash"])
                if cache_key not in quality_cache:
                    ranking = Ranking(
                        qid,
                        domain,
                        tuple(
                            Hit(doc, float(len(ranked_ids) - i), i + 1)
                            for i, doc in enumerate(ranked_ids)
                        ),
                        "measured_online",
                        "ranked_ids",
                    )
                    quality_cache[cache_key] = query_metrics(
                        qid, domain, qrels[domain], ranking
                    ).ndcg_at_10
                quality[method][domain].setdefault(qid, []).append(quality_cache[cache_key])
                group_of[domain][qid] = plan["quality"][qid]["group"]
                ms = request["total_ns"] / 1e6
                latencies[method].setdefault(qid, []).append(ms)
                rows[method][domain].append(
                    (qid, ms, request["process_cpu_ns"] / 1e6, request["use_dense"])
                )
    repetitions = 1 if smoke else 5
    expected_count = 156 if smoke else receipt["full_request_count"]
    if checked != expected_count:
        raise ValueError(f"request count differs: {checked} != {expected_count}")
    summary, q_oof = {}, {}
    for method in METHODS:
        for values in latencies[method].values():
            if len(values) != repetitions:
                raise ValueError("missing or duplicated repetitions for a query")
        summary[method] = {}
        for scope in (*DOMAINS, "all"):
            domains = DOMAINS if scope == "all" else (scope,)
            values = [r for d in domains for r in rows[method][d]]
            ms = np.array([r[1] for r in values])
            summary[method][scope] = {
                "requests": len(values),
                "mean_ms": float(ms.mean()),
                "p50_ms": float(np.percentile(ms, 50)),
                "p95_ms": float(np.percentile(ms, 95)),
                "cpu_mean_ms": float(np.mean([r[2] for r in values])),
                "peak_rss_mib": max(rss[method][d] for d in domains) / 2**20,
                "encode_ratio": float(np.mean([r[3] for r in values])),
            }
        q_oof[method] = float(
            np.mean([np.mean([np.mean(v) for v in quality[method][d].values()]) for d in DOMAINS])
        )
    comparisons, reductions = {}, {}
    if not smoke:
        for prefix in ("litegator", "bert"):
            for budget in BUDGETS:
                tag = f"b{int(budget * 100)}"
                left, right = f"pe_gh_v2_{tag}", f"{prefix}_{tag}"
                differences, groups = {}, {}
                for domain in DOMAINS:
                    ids = sorted(quality[left][domain])
                    if ids != sorted(quality[right][domain]):
                        raise ValueError("quality comparison query coverage differs")
                    differences[domain] = np.array(
                        [
                            np.mean(quality[left][domain][q]) - np.mean(quality[right][domain][q])
                            for q in ids
                        ]
                    )
                    groups[domain] = [group_of[domain][q] for q in ids]
                comparisons[right] = {
                    "quality_v2_minus_router": bootstrap(differences, groups),
                    "latency_v2_minus_router": latency_comparison(
                        latencies[left], latencies[right]
                    ),
                }
        for method in METHODS:
            if method != "h_star_v2":
                reductions[method] = latency_comparison(latencies["h_star_v2"], latencies[method])
    report = {
        "schema_version": "v4_prior_online_report_1",
        "status": "exploratory",
        "smoke": smoke,
        "plan_receipt_sha256": receipt["receipt_sha256"],
        "protocol_sha256": receipt["protocol_sha256"],
        "session": session,
        "session_sha256": file_hash(session_path),
        "requests_checked": checked,
        "ranking_or_route_mismatches": {m: v["either"] for m, v in mismatch.items() if v["either"]},
        "parity": mismatch,
        "mismatch_details": details,
        "summary": summary,
        "quality_oof": q_oof,
        "quality_source": "actual recorded online ranked document IDs, averaged over repetitions then macro topics",
        "comparisons": comparisons,
        "mean_reduction_vs_h_star_v2": reductions,
        "runtime_samples": machines,
        "no_requests_discarded": True,
        "bert_recipe_limitation": "BERT kept at paper recipe for cost; no equal hyperparameter search budget",
    }
    atomic_json(
        ws.results("prior_online_smoke.json" if smoke else "prior_online_report.json"), report
    )
    log(
        stage="prior-online-report",
        smoke=smoke,
        checked=checked,
        mismatches=sum(v["either"] for v in mismatch.values()),
    )
