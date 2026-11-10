"""Fail-closed validation for resumable v3/v4 artifacts; never rewrites old receipts."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import numpy as np

from contracts.io import load_queries
from pegh.data.artifacts import atomic_json, file_hash, object_hash
from pegh.dense.config import DenseConfig
from pegh.dense.index import verify_index
from pegh.evaluation.runs import load_rankings


def checked_dense(directory, corpus, domain: str, config: DenseConfig) -> dict:
    try:
        manifest, ids = verify_index(directory)
    except (KeyError, FileNotFoundError, TypeError) as exc:
        raise ValueError("dense cache is incomplete; rebuild in a new directory") from exc
    if manifest["domain"] != domain or manifest["corpus_sha256"] != file_hash(corpus):
        raise ValueError("dense cache corpus/domain changed; rebuild in a new directory")
    if manifest["embedding_fingerprint"] != config.embedding_fingerprint:
        raise ValueError("dense cache model/revision/config changed; rebuild in a new directory")
    import faiss

    from pegh.dense.artifacts import checked_child

    index = faiss.read_index(str(checked_child(Path(directory), manifest["index_file"])))
    if not isinstance(index, faiss.IndexFlatIP) or index.d != config.dimension:
        raise ValueError("dense cache index type/dimension differs")
    if index.ntotal != len(ids):
        raise ValueError("dense cache index/mapping counts differ")
    return manifest


def retrieval_identity(ws, retriever: str, domain: str, config=None, prefix=None):
    corpus = ws.raw(domain) / "corpus.jsonl"
    if retriever == "bm25":
        from pegh.sparse.config import BM25Config
        from pegh.sparse.index import SQLiteBM25

        with SQLiteBM25(ws.sparse(domain)) as backend:
            manifest = backend.manifest
        expected = BM25Config.from_yaml(ws.repo / "configs/sparse/bm25.yaml")
        if manifest["tokenizer_hash"] != expected.fingerprint:
            raise ValueError("sparse cache config changed; rebuild in a new directory")
        identity = manifest["retriever_hash"]
    else:
        manifest = checked_dense(ws.dense(retriever, domain), corpus, domain, config)
        identity = object_hash(
            {
                "index_sha256": manifest["index_sha256"],
                "embedding": manifest["embedding_fingerprint"],
                "tie_policy": "exact_score_then_doc_id_v1",
            }
        )
    if manifest["corpus_sha256"] != file_hash(corpus) or manifest["domain"] != domain:
        raise ValueError("retrieval cache corpus/domain changed")
    identities = {identity}
    if prefix is not None and retriever != "bm25":
        wrapped = object_hash({"retriever": identity, "query_prefix": prefix})
        identities = {wrapped} if prefix else {identity, wrapped}
    return manifest, identities


def checked_quality(path, ws, retriever: str, domain: str, *, config=None, prefix=None):
    """Validate current inputs, checksum, query coverage and every ranking before reuse."""
    path = Path(path)
    sidecar = path.with_suffix(path.suffix + ".meta.json")
    if not path.exists() and not sidecar.exists():
        return False
    if not path.is_file() or not sidecar.is_file():
        raise ValueError("incomplete quality cache; regenerate in a new output directory")
    meta = json.loads(sidecar.read_text(encoding="utf-8"))
    if meta.get("ranking_sha256") != file_hash(path):
        raise ValueError("quality cache ranking checksum differs")
    query_path = ws.raw(domain) / "queries.jsonl"
    queries = load_queries(query_path, domain)
    if "queries_hash" in meta:
        matches = meta["queries_hash"] == object_hash([asdict(q) for q in queries])
    else:
        matches = meta.get("queries_sha256") == file_hash(query_path)
    if not matches or meta.get("query_count") != len(queries):
        raise ValueError("quality cache queries changed")
    if meta.get("query_prefix", "") != (prefix or ""):
        raise ValueError("quality cache query prefix changed")
    manifest, identities = retrieval_identity(ws, retriever, domain, config, prefix)
    rankings, info = load_rankings(path, domain=domain)
    if set(rankings) != {q.query_id for q in queries}:
        raise ValueError("quality cache query coverage differs")
    if info["retriever_hash"] not in identities or meta.get("retriever_hash") not in identities:
        raise ValueError("quality cache retriever/model identity differs")
    if info["retriever_hash"] != meta["retriever_hash"]:
        raise ValueError("quality cache ranking and sidecar identities differ")
    if info["corpus_hash"] != manifest["corpus_sha256"]:
        raise ValueError("quality cache corpus differs")
    if any(len(r.hits) > 100 for r in rankings.values()):
        raise ValueError("quality cache exceeds top-100")
    return True


def npz_inputs(ws, encoder: str, domain: str, kind: str, *, prefix: str = "") -> dict:
    """Bind derived arrays to their raw inputs, feature schema and implementation."""
    from pegh.gating.features import FEATURE_NAMES
    from pegh.v3.features import PROXY_NAMES, QPP_NAMES

    raw = ws.raw(domain)
    dense = ws.dense(encoder, domain)
    if hasattr(ws, "proxy"):
        proxy = ws.proxy(encoder, domain)
    else:
        proxy = ws.root / "artifacts/proxy" / encoder / domain
    files = {
        "corpus": raw / "corpus.jsonl",
        "queries": raw / "queries.jsonl",
        "sparse_manifest": ws.sparse(domain) / "manifest.json",
        "sparse_index": ws.sparse(domain) / "index.sqlite3",
        "sparse_rankings": ws.quality("bm25", domain),
        "sparse_ranking_metadata": ws.quality("bm25", domain).with_suffix(".jsonl.meta.json"),
        "dense_manifest": dense / "manifest.json",
        "proxy_manifest": proxy / "manifest.json",
        "proxy_table": proxy / "table.npy",
        "proxy_weights": proxy / "weights.npy",
        "protocol": ws.repo / "configs/gating/protocol_v1.yaml",
        "sparse_config": ws.repo / "configs/sparse/bm25.yaml",
    }
    manifest = json.loads((dense / "manifest.json").read_text(encoding="utf-8"))
    from pegh.dense.artifacts import checked_child

    files["dense_index"] = checked_child(dense, manifest["index_file"])
    files["dense_ids"] = checked_child(dense, manifest["ids_file"])
    if kind == "tiers":
        files["qrels"] = raw / "qrels.tsv"
    elif kind != "features":
        raise ValueError("unknown derived cache kind")
    for name in (
        "v3/features.py",
        "v3/proxy.py",
        "v3/rescore.py",
        "gating/features.py",
        "fusion/engines.py",
        "evaluation/metrics.py",
    ):
        files[name] = ws.repo / "src/pegh" / name
    # Config revisions are inputs even if the stored corpus index has not been rebuilt.
    from pegh.v4.workspace import ENCODERS

    files["encoder_config"] = ws.repo / ENCODERS[encoder][0]
    checked_dense(
        dense, raw / "corpus.jsonl", domain, DenseConfig.from_yaml(files["encoder_config"])
    )
    if not checked_quality(ws.quality("bm25", domain), ws, "bm25", domain):
        raise FileNotFoundError("BM25 quality cache is required before derived arrays")
    for name in ("experiment_v3.py", "experiment_v4.py"):
        files[name] = ws.repo / "scripts_shared" / name
    return {
        "kind": kind,
        "domain": domain,
        "query_prefix": prefix if kind == "tiers" else "",
        "feature_schema": [list(FEATURE_NAMES), list(QPP_NAMES), list(PROXY_NAMES)],
        "files": {name: file_hash(path) for name, path in files.items()},
    }


def npz_ready(path, inputs: dict) -> bool:
    path = Path(path)
    sidecar = path.with_suffix(path.suffix + ".meta.json")
    if not path.exists() and not sidecar.exists():
        return False
    if not path.is_file() or not sidecar.is_file():
        raise ValueError(f"{path}: legacy/incomplete NPZ cache; regenerate in a new workspace")
    receipt = json.loads(sidecar.read_text(encoding="utf-8"))
    unsigned = {k: v for k, v in receipt.items() if k != "receipt_hash"}
    if receipt.get("receipt_hash") != object_hash(unsigned):
        raise ValueError(f"{path}: NPZ cache receipt checksum differs")
    if receipt.get("inputs") != inputs or receipt.get("sha256") != file_hash(path):
        raise ValueError(f"{path}: NPZ cache inputs/checksum changed; use a new workspace")
    with np.load(path, allow_pickle=False) as stored:
        ids = stored["ids"]
        if ids.ndim != 1 or len(ids) != len(set(ids.tolist())):
            raise ValueError("NPZ cache has invalid query IDs")
        for name in stored.files:
            if name != "ids" and (
                len(stored[name]) != len(ids) or not np.isfinite(stored[name]).all()
            ):
                raise ValueError("NPZ cache arrays are not finite/aligned")
    return True


def seal_npz(path, inputs: dict) -> None:
    path = Path(path)
    receipt = {
        "schema_version": "pegh_derived_cache_1",
        "inputs": inputs,
        "sha256": file_hash(path),
    }
    receipt["receipt_hash"] = object_hash(receipt)
    atomic_json(path.with_suffix(path.suffix + ".meta.json"), receipt)


def load_npz_cache(ws, encoder, domain, kind, path, *, prefix="") -> dict:
    if not npz_ready(path, npz_inputs(ws, encoder, domain, kind, prefix=prefix)):
        raise FileNotFoundError(f"{path}: derived cache has not been generated")
    with np.load(path, allow_pickle=False) as stored:
        return {key: stored[key] for key in stored.files}
