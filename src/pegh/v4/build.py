"""Encoders with query prefixes, dense builds, quality caches and splits for the new domains."""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, replace

from contracts.io import load_queries
from contracts.ranking import ranking_to_record
from contracts.types import Query
from pegh.data.artifacts import atomic_json, file_hash, object_hash, write_jsonl
from pegh.v4.workspace import ENCODERS, NEW_DOMAINS, Workspace, query_prefix, vector_key


class PrefixedEncoder:
    """Applies an encoder's query instruction; documents are always encoded without it."""

    def __init__(self, model, prefix: str):
        self.model, self.prefix = model, prefix

    def text(self, query_text: str) -> str:
        return self.prefix + query_text if query_text.strip() else query_text

    def query(self, query_text: str):
        return self.model.encode([self.text(query_text)])[0]


def encoder(ws: Workspace, key: str, threads: int):
    from pegh.dense.config import DenseConfig
    from pegh.dense.encoder import CPUEncoder

    config = DenseConfig.from_yaml(ws.repo / ENCODERS[key][0])
    config = replace(config, torch_threads=threads, faiss_threads=threads)
    return CPUEncoder(config, cache_folder=str(ws.models))


def prefixed(ws: Workspace, key: str, threads: int) -> PrefixedEncoder:
    return PrefixedEncoder(encoder(ws, key, threads), query_prefix(key))


def build_dense(ws: Workspace, key: str, domain: str, threads: int):
    """Offline corpus indexing (no prefix); thread count only affects build time."""
    from pegh.dense.index import build_index

    output = ws.dense(key, domain)
    manifest_path = output / "manifest.json"
    if manifest_path.exists() and json.loads(manifest_path.read_text())["status"] == "complete":
        return output
    model = encoder(ws, vector_key(key), threads)
    started = time.perf_counter()
    manifest = build_index(
        ws.raw(domain) / "corpus.jsonl",
        output,
        domain,
        model,
        resume=manifest_path.exists(),
        recover_stale_lock=True,
        progress=lambda row: print(
            json.dumps({"domain": domain, "encoder": key, **row}), flush=True
        ),
    )
    if manifest["status"] != "complete":
        raise RuntimeError(f"dense build for {key}/{domain} did not complete")
    atomic_json(
        output / "v4_build.json",
        {"threads": threads, "wall_seconds": time.perf_counter() - started, "pid": os.getpid()},
    )
    return output


def quality_cache(ws: Workspace, retriever: str, domain: str, threads: int = 4):
    """Top-100 for every query (offline quality/label work only), prefix-aware."""
    output = ws.quality(retriever, domain)
    sidecar = output.with_suffix(output.suffix + ".meta.json")
    if output.exists() and sidecar.exists():
        return output
    queries = load_queries(ws.raw(domain) / "queries.jsonl", domain)
    if retriever == "bm25":
        from pegh.sparse.fast import open_backend

        backend = open_backend(ws.sparse(domain), execution="numpy")
        search, identity = backend.search, backend.manifest["retriever_hash"]
        prefix = ""
    else:
        from pegh.dense.retriever import FaissDenseRetriever

        dense = FaissDenseRetriever(ws.dense(retriever, domain), encoder(ws, retriever, threads))
        search, prefix = dense.search, query_prefix(retriever)
        identity = object_hash({"retriever": dense.retriever_hash, "query_prefix": prefix})

    def ranked(q: Query):
        text = prefix + q.text if prefix and q.text.strip() else q.text
        ranking = search(replace(q, text=text), k=100)
        return ranking_to_record(
            replace(ranking, retriever_hash=identity), method=retriever, split="all"
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    write_jsonl(output, (ranked(q) for q in queries))
    atomic_json(
        sidecar,
        {
            "schema_version": "1.0",
            "quality_cache": True,
            "latency_benchmark": False,
            "retriever": retriever,
            "retriever_hash": identity,
            "query_prefix": prefix,
            "query_count": len(queries),
            "queries_hash": object_hash([asdict(q) for q in queries]),
            "ranking_sha256": file_hash(output),
        },
    )
    return output


def prepare_new_splits(ws: Workspace) -> dict:
    """Same grouping recipe and seed as v1/v3, applied only to the six new domains."""
    from pegh.data.manifest import audit_dataset
    from pegh.data.qrels import load_qrels
    from pegh.data.splits import (
        make_five_fold_splits,
        validate_five_fold_splits,
        write_five_fold_splits,
    )

    queries, qrels, hashes = {}, {}, {}
    for domain in NEW_DOMAINS:
        raw = ws.raw(domain)
        manifest = audit_dataset(
            raw / "corpus.jsonl",
            raw / "queries.jsonl",
            raw / "qrels.tsv",
            domain,
            source_manifest_path=raw / "source_manifest.json",
        )
        atomic_json(ws.root / "data/manifests" / f"{domain}.json", manifest)
        hashes[domain] = manifest["manifest_hash"]
        queries[domain] = load_queries(raw / "queries.jsonl", domain)
        qrels[domain] = load_qrels(raw / "qrels.tsv", domain)
    splits = make_five_fold_splits(queries, qrels, seed=42, dataset_hashes=hashes)
    path = ws.split_manifest(NEW_DOMAINS[0])
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        validate_five_fold_splits(existing)
        if existing != splits:
            raise FileExistsError("registered new-domain split differs; refusing to replace it")
    else:
        write_five_fold_splits(path.parent, splits)
    return splits
