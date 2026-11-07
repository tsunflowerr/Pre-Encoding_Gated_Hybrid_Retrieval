"""Online v3 methods for the isolated benchmark worker.

Routes: `bm25` (sparse only), `proxy` (P*: BM25 re-scored with the static proxy, no
encoder), `rescore` (R*: encode once, re-score BM25 candidates; no vector-index search) and
`cascade` (Ridge gate on v1 features picks P* or R*). All loading happens in the factory.
"""

from __future__ import annotations

import json
import pickle
from pathlib import Path

import numpy as np
import yaml

from contracts.types import Query, Ranking, SearchResponse
from pegh.data.artifacts import atomic_json, file_hash, object_hash
from pegh.dense.config import DenseConfig
from pegh.dense.encoder import CPUEncoder, checked_vectors
from pegh.gating.features import QueryFeatureExtractor
from pegh.gating.models import ModelPredictor
from pegh.profiling.trace import NullTraceSink
from pegh.sparse.fast import open_backend
from pegh.v3.proxy import StaticProxy
from pegh.v3.rescore import candidate_fusion, rescore_identity, rescored_ranking

ROUTES = ("bm25", "proxy", "rescore", "cascade")


def export_gate(directory: Path, scaler, model, manifest: dict) -> dict:
    """Persist a fitted Ridge gate in the layout ModelPredictor expects."""
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "scaler.pkl").open("wb") as stream:
        pickle.dump(scaler, stream)
    with (directory / "model.pkl").open("wb") as stream:
        pickle.dump(model, stream)
    record = {
        **manifest,
        "family": "ridge",
        "scaler_sha256": file_hash(directory / "scaler.pkl"),
        "model_sha256": file_hash(directory / "model.pkl"),
    }
    record["manifest_hash"] = object_hash(record)
    atomic_json(directory / "manifest.json", record)
    return record


def load_gate(directory: str | Path, expected_hash: str) -> tuple[ModelPredictor, dict]:
    directory = Path(directory)
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    unsigned = {k: v for k, v in manifest.items() if k != "manifest_hash"}
    if (
        object_hash(unsigned) != manifest["manifest_hash"]
        or manifest["manifest_hash"] != expected_hash
    ):
        raise ValueError("cascade gate manifest differs from the registry")
    for name in ("scaler", "model"):
        if file_hash(directory / f"{name}.pkl") != manifest[f"{name}_sha256"]:
            raise ValueError(f"cascade gate {name} checksum differs")
    with (directory / "scaler.pkl").open("rb") as stream:
        scaler = pickle.load(stream)
    with (directory / "model.pkl").open("rb") as stream:
        model = pickle.load(stream)
    return ModelPredictor(manifest, scaler, model, execution="numpy"), manifest


def load_vectors(dense_dir: Path) -> tuple[np.ndarray, dict[str, int], dict]:
    """Stored corpus vectors without keeping a vector index: re-scoring needs rows only."""
    from pegh.v3.build import load_dense_vectors

    vectors, rows, manifest = load_dense_vectors(dense_dir)
    return np.ascontiguousarray(vectors), rows, manifest


class TierSearchMethod:
    def __init__(
        self,
        route,
        sparse,
        *,
        trace,
        provenance,
        low_alpha=None,
        high_alpha=None,
        proxy=None,
        encoder=None,
        vectors=None,
        rows=None,
        extractor=None,
        predictor=None,
        threshold=None,
        identities=None,
    ):
        self.route = route
        self.sparse = sparse
        self.trace = trace if trace is not None else NullTraceSink()
        self.provenance = provenance
        self.low_alpha, self.high_alpha = low_alpha, high_alpha
        self.proxy, self.encoder = proxy, encoder
        self.vectors, self.rows = vectors, rows
        self.extractor, self.predictor, self.threshold = extractor, predictor, threshold
        self.identities = identities or {}

    def _empty(self, query: Query) -> SearchResponse:
        empty = Ranking(
            query.query_id,
            query.domain,
            (),
            self.sparse.manifest["corpus_sha256"],
            self.sparse.manifest["retriever_hash"],
        )
        empty.validate()
        return SearchResponse(empty, False, None, 0, "empty_query")

    def _cheap(self, query: Query, sparse: Ranking) -> Ranking:
        if self.low_alpha is None:
            return sparse
        with self.trace.stage("fusion"):
            other = rescored_ranking(
                sparse,
                self.proxy.embed(query.text),
                self.vectors,
                self.rows,
                self.identities["proxy"],
            )
            return candidate_fusion(sparse, other, self.low_alpha)

    def _expensive(self, query: Query, sparse: Ranking) -> Ranking:
        with self.trace.stage("encode"):
            self.trace.increment("encoder_calls")
            vector = checked_vectors(self.encoder.encode([query.text]), 1, self.vectors.shape[1])[0]
        with self.trace.stage("fusion"):
            other = rescored_ranking(
                sparse, vector, self.vectors, self.rows, self.identities["query"]
            )
            return candidate_fusion(sparse, other, self.high_alpha)

    def search(self, query: Query, k: int = 100) -> SearchResponse:
        if type(k) is not int or k != 100:
            raise ValueError("v3 tiers are defined on the registered BM25 top-100")
        if query.domain != self.sparse.manifest["domain"]:
            raise ValueError("query domain differs from method domain")
        if not query.text.strip():
            return self._empty(query)
        sparse = self.sparse.search(query, k=k)
        if self.route in ("bm25", "proxy"):
            return SearchResponse(self._cheap(query, sparse), False, None, 0, None)
        if self.route == "rescore":
            return SearchResponse(self._expensive(query, sparse), True, None, 1, None)
        stats = self.sparse.query_stats(query)
        with self.trace.stage("features"):
            features = self.extractor.transform(query, sparse, stats)
        with self.trace.stage("gate"):
            score = self.predictor.predict_score(features)
            use_dense = stats.token_count == 0 or stats.oov_ratio == 1.0 or score > self.threshold
        if use_dense:
            return SearchResponse(self._expensive(query, sparse), True, score, 1, None)
        return SearchResponse(self._cheap(query, sparse), False, score, 0, None)

    def close(self) -> None:
        self.sparse.close()


def create_tier_method(
    *,
    trace,
    route: str,
    domain: str,
    fold: int,
    sparse_dir: str,
    dense_dir: str,
    proxy_dir: str | None = None,
    low: str = "bm25",
    high: str | None = None,
    gate_dir: str | None = None,
    expected_gate_hash: str | None = None,
    threshold: float | None = None,
    protocol_path: str | None = None,
    expected_sparse_sha256: str,
    expected_dense_sha256: str,
    expected_proxy_hash: str | None = None,
    cache_folder: str | None = None,
    torch_threads: int | None = None,
) -> TierSearchMethod:
    if route not in ROUTES:
        raise ValueError(f"unsupported v3 route {route}")
    sparse_path, dense_path = Path(sparse_dir), Path(dense_dir)
    if file_hash(sparse_path / "index.sqlite3") != expected_sparse_sha256:
        raise ValueError("sparse registry checksum differs")
    if file_hash(dense_path / "index.faiss") != expected_dense_sha256:
        raise ValueError("dense registry checksum differs")
    sparse = open_backend(sparse_path, trace=trace, execution="numpy")
    provenance = {
        "schema_version": "v3_online_method_1",
        "route": route,
        "domain": domain,
        "fold": fold,
        "low": low,
        "high": high,
        "sparse_index_sha256": expected_sparse_sha256,
        "sparse_execution": sparse.execution_provenance,
        "dense_index_sha256": expected_dense_sha256,
        "vector_index_search": False,
        "query_embedding_cache": False,
        "quality_cache_used": False,
    }
    if route == "bm25":
        return TierSearchMethod(route, sparse, trace=trace, provenance=provenance)
    vectors, rows, dense_manifest = load_vectors(dense_path)
    if dense_manifest["corpus_sha256"] != sparse.manifest["corpus_sha256"]:
        raise ValueError("dense/sparse corpus differs")
    config = dict(dense_manifest["config"])
    if torch_threads is not None:
        config["torch_threads"] = torch_threads
    kwargs = {"vectors": vectors, "rows": rows}
    if route == "proxy":
        # The cheap tier never loads encoder weights; only the pinned tokenizer.
        from transformers import AutoTokenizer

        encoder = None
        tokenizer = AutoTokenizer.from_pretrained(
            config["model_id"], revision=config["revision"], cache_dir=cache_folder
        )
    else:
        encoder = CPUEncoder(DenseConfig(**config), cache_folder=cache_folder)
        tokenizer = encoder.model.tokenizer
    identities = {
        "query": rescore_identity("query_encoder", dense_manifest["embedding_fingerprint"])
    }
    low_alpha = None
    if low != "bm25" and route in ("proxy", "cascade"):
        proxy = StaticProxy(proxy_dir, tokenizer)
        if proxy.manifest["manifest_hash"] != expected_proxy_hash:
            raise ValueError("proxy registry hash differs")
        identities["proxy"] = rescore_identity("static_proxy", proxy.identity)
        kwargs["proxy"] = proxy
        low_alpha = float(low.removeprefix("proxy_cc_"))
        provenance["proxy_manifest_hash"] = expected_proxy_hash
    high_alpha = float(high.removeprefix("rescore_cc_")) if high else None
    if route in ("rescore", "cascade"):
        kwargs["encoder"] = encoder
        provenance["dense_config"] = config
    if route == "cascade":
        protocol = yaml.safe_load(Path(protocol_path).read_text(encoding="utf-8"))
        kwargs["extractor"] = QueryFeatureExtractor(protocol["features"], sparse.tokenizer)
        predictor, gate_manifest = load_gate(gate_dir, expected_gate_hash)
        if (gate_manifest["fold"], gate_manifest["domain"]) != (fold, domain):
            raise ValueError("gate fold/domain differs")
        if gate_manifest["threshold"] != threshold:
            raise ValueError("registry threshold differs from the exported gate")
        kwargs.update(predictor=predictor, threshold=float(threshold))
        provenance.update(gate=predictor.provenance, threshold=threshold)
    json.dumps(provenance, allow_nan=False)
    return TierSearchMethod(
        route,
        sparse,
        trace=trace,
        provenance=provenance,
        low_alpha=low_alpha if route != "rescore" else None,
        high_alpha=high_alpha,
        identities=identities,
        **kwargs,
    )
