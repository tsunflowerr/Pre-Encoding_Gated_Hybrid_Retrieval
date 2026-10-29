"""Fetch fresh CQADupStack domains and build their sparse/dense indexes and quality caches."""

from __future__ import annotations

import json
import os
import time
import urllib.request
from dataclasses import asdict, replace
from pathlib import Path

import pyarrow.parquet as pq

from contracts.io import load_queries
from contracts.ranking import ranking_to_record
from pegh.data.artifacts import atomic_json, file_hash, object_hash, write_jsonl
from pegh.data.manifest import audit_dataset
from pegh.data.qrels import load_qrels
from pegh.data.splits import (
    make_five_fold_splits,
    validate_five_fold_splits,
    write_five_fold_splits,
)
from pegh.v3.workspace import ENCODERS, FRESH_DOMAINS, Workspace

DATASET = "BeIR/cqadupstack"
DATASET_REVISION = "e84b7220ce5a4e6c49aeb568983b0ec5a7584c2c"
QRELS = "BeIR/cqadupstack-qrels"
QRELS_REVISION = "13595a9f221256a9a21e91c8b0fed3563382b6a7"


def _download(url: str, target: Path) -> None:
    if target.exists():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    request = urllib.request.Request(url, headers={"User-Agent": "PE-GH-v3/0.1"})
    with urllib.request.urlopen(request, timeout=300) as response, temporary.open("wb") as output:
        for block in iter(lambda: response.read(1024 * 1024), b""):
            output.write(block)
    temporary.replace(target)


def _parquet_to_jsonl(source: Path, target: Path) -> int:
    """Same canonical conversion as A's fetch_inputs: one source row per JSON line."""
    parquet = pq.ParquetFile(source)

    def records():
        for batch in parquet.iter_batches(batch_size=1024):
            for row in batch.to_pylist():
                if not isinstance(row.get("_id"), str):
                    raise TypeError(f"{source}: source IDs must remain strings")
                yield row

    if not target.exists():
        write_jsonl(target, records())
    return parquet.metadata.num_rows


def fetch_domain(ws: Workspace, domain: str) -> dict:
    if ws.is_dev(domain):
        raise ValueError("development domains are reused from the verified v1 workspace")
    output = ws.raw(domain)
    files = []
    for kind in ("corpus", "queries"):
        url = (
            f"https://huggingface.co/datasets/{DATASET}/resolve/{DATASET_REVISION}/"
            f"{domain}/{kind}/{kind}-00000-of-00001.parquet"
        )
        parquet_path = output / f"{kind}.parquet"
        _download(url, parquet_path)
        rows = _parquet_to_jsonl(parquet_path, output / f"{kind}.jsonl")
        files.append(
            {
                "kind": kind,
                "source_url": url,
                "source_revision": DATASET_REVISION,
                "source_sha256": file_hash(parquet_path),
                "canonical_sha256": file_hash(output / f"{kind}.jsonl"),
                "rows": rows,
            }
        )
    qrels_url = (
        f"https://huggingface.co/datasets/{QRELS}/resolve/{QRELS_REVISION}/{domain}/test.tsv"
    )
    _download(qrels_url, output / "qrels.tsv")
    files.append(
        {
            "kind": "qrels",
            "source_url": qrels_url,
            "source_revision": QRELS_REVISION,
            "canonical_sha256": file_hash(output / "qrels.tsv"),
        }
    )
    manifest = {
        "schema_version": "1.0",
        "domain": domain,
        "dataset_id": DATASET,
        "dataset_revision": DATASET_REVISION,
        "qrels_dataset_id": QRELS,
        "qrels_revision": QRELS_REVISION,
        "license": "cc-by-sa-4.0",
        "files": files,
    }
    atomic_json(output / "source_manifest.json", manifest)
    return manifest


def prepare_fresh_splits(ws: Workspace) -> dict:
    """Same grouping/bucketing recipe and seed as v1, applied only to the fresh domains."""
    queries, qrels, hashes = {}, {}, {}
    for domain in FRESH_DOMAINS:
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
    path = ws.split_manifest(FRESH_DOMAINS[0])
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        validate_five_fold_splits(existing)
        if existing != splits:
            raise FileExistsError("registered fresh-domain split differs; refusing to replace it")
    else:
        write_five_fold_splits(path.parent, splits)
    return splits


def build_sparse(ws: Workspace, domain: str) -> Path:
    from pegh.sparse.config import BM25Config
    from pegh.sparse.fast import FORMAT, compile_index
    from pegh.sparse.index import build_index

    output = ws.sparse(domain)
    if not (output / "manifest.json").exists():
        build_index(
            ws.raw(domain) / "corpus.jsonl",
            output,
            domain,
            BM25Config.from_yaml(ws.repo / "configs/sparse/bm25.yaml"),
        )
    if not (output / FORMAT / "manifest.json").exists():
        compile_index(output, output / FORMAT)
    return output


def _encoder(ws: Workspace, encoder: str, threads: int):
    from pegh.dense.config import DenseConfig
    from pegh.dense.encoder import CPUEncoder

    config = DenseConfig.from_yaml(ws.repo / ENCODERS[encoder])
    config = replace(config, torch_threads=threads, faiss_threads=threads)
    return CPUEncoder(config, cache_folder=str(ws.root.parent / "models"))


def build_dense(ws: Workspace, encoder: str, domain: str, threads: int) -> Path:
    """Offline indexing; thread count only affects build time, never online timing."""
    from pegh.dense.index import build_index

    output = ws.dense(encoder, domain)
    manifest_path = output / "manifest.json"
    if manifest_path.exists() and json.loads(manifest_path.read_text())["status"] == "complete":
        return output
    model = _encoder(ws, encoder, threads)
    started = time.perf_counter()
    manifest = build_index(
        ws.raw(domain) / "corpus.jsonl",
        output,
        domain,
        model,
        resume=manifest_path.exists(),
        recover_stale_lock=True,  # refuses if the lock PID is still alive
        progress=lambda row: print(
            json.dumps({"domain": domain, "encoder": encoder, **row}), flush=True
        ),
    )
    if manifest["status"] != "complete":
        raise RuntimeError(f"dense build for {encoder}/{domain} did not complete")
    atomic_json(
        output / "v3_build.json",
        {"threads": threads, "wall_seconds": time.perf_counter() - started, "pid": os.getpid()},
    )
    return output


def load_dense_vectors(directory: str | Path):
    """Verified stored corpus vectors in index row order, plus the doc-ID row map."""
    import faiss

    from pegh.dense.artifacts import checked_child
    from pegh.dense.index import verify_index

    manifest, doc_ids = verify_index(directory)
    index = faiss.read_index(str(checked_child(Path(directory), manifest["index_file"])))
    vectors = index.reconstruct_n(0, index.ntotal)
    return vectors, {doc_id: row for row, doc_id in enumerate(doc_ids)}, manifest


def quality_cache(ws: Workspace, retriever: str, domain: str, threads: int = 4) -> Path:
    """Top-100 for every query, for offline quality/label work only."""
    output = ws.quality(retriever, domain)
    sidecar = output.with_suffix(output.suffix + ".meta.json")
    if output.exists() and sidecar.exists():
        return output
    queries = load_queries(ws.raw(domain) / "queries.jsonl", domain)
    if retriever == "bm25":
        from pegh.sparse.fast import open_backend

        backend = open_backend(ws.sparse(domain), execution="numpy")
        search, identity = backend.search, backend.manifest["retriever_hash"]
    else:
        from pegh.dense.retriever import FaissDenseRetriever

        dense = FaissDenseRetriever(ws.dense(retriever, domain), _encoder(ws, retriever, threads))
        search, identity = dense.search, dense.retriever_hash
    output.parent.mkdir(parents=True, exist_ok=True)
    write_jsonl(
        output,
        (ranking_to_record(search(q, k=100), method=retriever, split="all") for q in queries),
    )
    atomic_json(
        sidecar,
        {
            "schema_version": "1.0",
            "quality_cache": True,
            "latency_benchmark": False,
            "retriever": retriever,
            "retriever_hash": identity,
            "query_count": len(queries),
            "queries_hash": object_hash([asdict(q) for q in queries]),
            "ranking_sha256": file_hash(output),
        },
    )
    return output
