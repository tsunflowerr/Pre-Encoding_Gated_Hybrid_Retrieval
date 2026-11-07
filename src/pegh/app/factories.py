"""Construct benchmark methods and verify C1/C4/index provenance before timing."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from pegh.app.methods import HybridSearchMethod, ScoreThresholdGate, StaticHybridMethod
from pegh.dense.artifacts import file_hash, object_hash, read_json
from pegh.dense.config import DenseConfig
from pegh.dense.encoder import CPUEncoder
from pegh.dense.retriever import FaissDenseRetriever
from pegh.fusion.engines import CCFusion, RRFFusion
from pegh.gating.features import QueryFeatureExtractor
from pegh.gating.models import load_model
from pegh.sparse.fast import open_backend


def create_gated_method(
    *,
    trace,
    sparse_dir: str,
    dense_dir: str,
    protocol_path: str,
    selection_path: str,
    model_manifest_path: str,
    domain: str,
    fold: int,
    threshold: float,
    expected_sparse_sha256: str,
    expected_dense_sha256: str,
    expected_protocol_sha256: str,
    expected_selection_sha256: str,
    expected_model_manifest_hash: str,
    cache_folder: str | None = None,
    torch_threads: int | None = None,
    faiss_threads: int | None = None,
    sparse_execution: str = "numpy",
    expected_sparse_execution_hash: str | None = None,
    score_execution: str = "numpy",
) -> HybridSearchMethod:
    """All artifact loading and model setup occurs outside search()."""
    if type(fold) is not int or fold not in range(5) or domain not in ("programmers", "unix"):
        raise ValueError("unsupported fold or domain")
    sparse_path, dense_path = Path(sparse_dir), Path(dense_dir)
    if file_hash(sparse_path / "index.sqlite3") != expected_sparse_sha256:
        raise ValueError("sparse registry checksum differs")
    if file_hash(dense_path / "index.faiss") != expected_dense_sha256:
        raise ValueError("dense registry checksum differs")
    if file_hash(protocol_path) != expected_protocol_sha256:
        raise ValueError("feature protocol checksum differs")
    if file_hash(selection_path) != expected_selection_sha256:
        raise ValueError("fusion selection checksum differs")
    sparse = open_backend(sparse_path, trace=trace, execution=sparse_execution)
    try:
        if (
            expected_sparse_execution_hash is not None
            and object_hash(sparse.execution_provenance) != expected_sparse_execution_hash
        ):
            raise ValueError("sparse execution artifact differs from registry")
        protocol = yaml.safe_load(Path(protocol_path).read_text(encoding="utf-8"))
        extractor = QueryFeatureExtractor(protocol["features"], sparse.tokenizer)
        selection = read_json(selection_path)
        fold_choice = selection["domains"][domain]["folds"][str(fold)]
        if selection["domains"][domain]["corpus_sha256"] != sparse.manifest["corpus_sha256"]:
            raise ValueError("selection/sparse corpus differs")
        if fold_choice["validation"]["sparse_retriever_hash"] != sparse.manifest["retriever_hash"]:
            raise ValueError("selection/sparse retriever differs")
        method = fold_choice["h_star"]["method"]
        if method.startswith("cc_alpha_"):
            fusion = CCFusion(float(method.removeprefix("cc_alpha_")))
        elif method == "rrf":
            fusion = RRFFusion(protocol["fusion"]["rrf_k"])
        else:
            raise ValueError(f"unsupported H* method: {method}")
        predictor = load_model(model_manifest_path, execution=score_execution)
        manifest = predictor.manifest
        if manifest["manifest_hash"] != expected_model_manifest_hash:
            raise ValueError("model registry hash differs")
        if (manifest["fold"], manifest["domain"]) != (fold, domain):
            raise ValueError("model fold/domain differs")
        if (
            manifest["selection_hash"] != fold_choice["selection_hash"]
            or manifest["h_star_method"] != method
        ):
            raise ValueError("model H* reference differs")
        expected_schema = (
            extractor.general_schema_hash
            if manifest["feature_set"] == "general"
            else extractor.schema_hash
        )
        if manifest["feature_schema_hash"] != expected_schema:
            raise ValueError("model feature schema differs")
        dense_manifest = read_json(dense_path / "manifest.json")
        if dense_manifest["corpus_sha256"] != sparse.manifest["corpus_sha256"]:
            raise ValueError("dense/sparse corpus differs")
        config = dict(dense_manifest["config"])
        if torch_threads is not None:
            config["torch_threads"] = torch_threads
        if faiss_threads is not None:
            config["faiss_threads"] = faiss_threads
        dense = FaissDenseRetriever(
            dense_path, CPUEncoder(DenseConfig(**config), cache_folder=cache_folder), trace=trace
        )
        if dense.retriever_hash != fold_choice["validation"]["dense_retriever_hash"]:
            raise ValueError("selection/dense retriever differs")
        gate = ScoreThresholdGate(predictor, threshold)
        provenance = {
            "schema_version": "c5_online_method_v1",
            "domain": domain,
            "fold": fold,
            "corpus_sha256": sparse.manifest["corpus_sha256"],
            "sparse_index_sha256": expected_sparse_sha256,
            "sparse_retriever_hash": sparse.manifest["retriever_hash"],
            "sparse_execution": sparse.execution_provenance,
            "dense_index_sha256": expected_dense_sha256,
            "dense_retriever_hash": dense.retriever_hash,
            "dense_config": config,
            "protocol_sha256": expected_protocol_sha256,
            "selection_sha256": expected_selection_sha256,
            "selection_hash": fold_choice["selection_hash"],
            "h_star_method": method,
            "feature_schema_hash": expected_schema,
            "model": predictor.provenance,
            "threshold": gate.threshold,
            "gate_rule": "score_strictly_greater_than_threshold",
            "oov_policy": "force_dense_counted_in_ratio",
            "query_embedding_cache": False,
            "quality_cache_used": False,
        }
        json.dumps(provenance, allow_nan=False)
        return HybridSearchMethod(
            sparse, dense, extractor, gate, fusion, trace=trace, provenance=provenance
        )
    except Exception:
        sparse.close()
        raise


def create_static_hybrid_method(
    *,
    trace,
    sparse_dir: str,
    dense_dir: str,
    selection_path: str,
    domain: str,
    fold: int,
    mode: str,
    expected_sparse_sha256: str,
    expected_dense_sha256: str,
    expected_selection_sha256: str,
    cache_folder: str | None = None,
    torch_threads: int | None = None,
    faiss_threads: int | None = None,
    sparse_execution: str = "numpy",
    expected_sparse_execution_hash: str | None = None,
    parallel_branches: bool = False,
) -> StaticHybridMethod:
    if type(fold) is not int or fold not in range(5) or domain not in ("programmers", "unix"):
        raise ValueError("unsupported fold or domain")
    if mode not in ("h_star", "s_star", "cc_half", "rrf"):
        raise ValueError("unsupported static hybrid mode")
    if parallel_branches and sparse_execution != "numpy":
        raise ValueError("parallel baseline requires the thread-safe in-memory sparse backend")
    if parallel_branches:
        torch_threads = 3 if torch_threads is None else torch_threads
        faiss_threads = 3 if faiss_threads is None else faiss_threads
        if max(torch_threads, faiss_threads) > 3:
            raise ValueError(
                "parallel baseline reserves one of four CPU threads for sparse retrieval"
            )
    sparse_path, dense_path = Path(sparse_dir), Path(dense_dir)
    if file_hash(sparse_path / "index.sqlite3") != expected_sparse_sha256:
        raise ValueError("sparse registry checksum differs")
    if file_hash(dense_path / "index.faiss") != expected_dense_sha256:
        raise ValueError("dense registry checksum differs")
    if file_hash(selection_path) != expected_selection_sha256:
        raise ValueError("fusion selection checksum differs")
    sparse = open_backend(sparse_path, trace=trace, execution=sparse_execution)
    try:
        if (
            expected_sparse_execution_hash is not None
            and object_hash(sparse.execution_provenance) != expected_sparse_execution_hash
        ):
            raise ValueError("sparse execution artifact differs from registry")
        selection = read_json(selection_path)
        selected = selection["domains"][domain]["folds"][str(fold)]
        if selection["domains"][domain]["corpus_sha256"] != sparse.manifest["corpus_sha256"]:
            raise ValueError("selection/sparse corpus differs")
        if selected["validation"]["sparse_retriever_hash"] != sparse.manifest["retriever_hash"]:
            raise ValueError("selection/sparse retriever differs")
        if mode == "s_star" and selected["s_star"]["method"] != "h_star":
            raise ValueError("current static S* adapter requires S*=H*")
        fusion_name = selected["h_star"]["method"] if mode in ("h_star", "s_star") else mode
        if fusion_name.startswith("cc_alpha_"):
            fusion = CCFusion(float(fusion_name.removeprefix("cc_alpha_")))
        elif fusion_name == "cc_half":
            fusion = CCFusion(0.5)
        elif fusion_name in ("rrf", "rrf_k_60"):
            fusion = RRFFusion(60)
        else:
            raise ValueError("unsupported static fusion selection")
        dense_manifest = read_json(dense_path / "manifest.json")
        if dense_manifest["corpus_sha256"] != sparse.manifest["corpus_sha256"]:
            raise ValueError("dense/sparse corpus differs")
        config = dict(dense_manifest["config"])
        if torch_threads is not None:
            config["torch_threads"] = torch_threads
        if faiss_threads is not None:
            config["faiss_threads"] = faiss_threads
        dense = FaissDenseRetriever(
            dense_path, CPUEncoder(DenseConfig(**config), cache_folder=cache_folder), trace=trace
        )
        if dense.retriever_hash != selected["validation"]["dense_retriever_hash"]:
            raise ValueError("selection/dense retriever differs")
        provenance = {
            "schema_version": "c6_static_method_v1",
            "parallel_branches": parallel_branches,
            "mode": mode,
            "fold": fold,
            "domain": domain,
            "fusion_method": fusion_name,
            "selection_hash": selected["selection_hash"],
            "selection_sha256": expected_selection_sha256,
            "corpus_sha256": sparse.manifest["corpus_sha256"],
            "sparse_index_sha256": expected_sparse_sha256,
            "dense_index_sha256": expected_dense_sha256,
            "sparse_retriever_hash": sparse.manifest["retriever_hash"],
            "sparse_execution": sparse.execution_provenance,
            "dense_retriever_hash": dense.retriever_hash,
            "dense_config": config,
            "query_embedding_cache": False,
            "quality_cache_used": False,
        }
        json.dumps(provenance, allow_nan=False)
        return StaticHybridMethod(
            sparse, dense, fusion, trace=trace, provenance=provenance, parallel=parallel_branches
        )
    except Exception:
        sparse.close()
        raise
