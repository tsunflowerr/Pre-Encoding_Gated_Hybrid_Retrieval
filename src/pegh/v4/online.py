"""Online PE-GH v2 methods for the isolated benchmark worker and the demo.

Routes: `bm25`; `p_star` (BM25 re-scored with the static proxy, no encoder); `r_star`
(encode once with the query prefix, re-score BM25 candidates); `h_star` (encode, exact FAISS
search, fusion); `gated` (gate v2 or the BM25-margin rule picks P* or H* by threshold).
All loading and checksum verification happens in the factory.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import yaml

from contracts.types import Query, Ranking, SearchResponse
from pegh.data.artifacts import file_hash
from pegh.dense.config import DenseConfig
from pegh.dense.encoder import CPUEncoder, checked_vectors
from pegh.fusion import fuse_cc, fuse_rrf
from pegh.gating.features import QueryFeatureExtractor
from pegh.profiling.trace import NullTraceSink
from pegh.sparse.fast import open_backend
from pegh.v3.features import ExtendedFeatureExtractor
from pegh.v3.proxy import StaticProxy
from pegh.v3.rescore import candidate_fusion, rescore_identity, rescored_ranking
from pegh.v4.gate import LinearGate

ROUTES = ("bm25", "p_star", "r_star", "h_star", "gated")
SCORERS = ("gate_v2", "bm25_margin")
MARGIN_COLUMN = 16  # bm25_rel_gap12 in the v1 feature vector


def fuse_high(sparse: Ranking, dense: Ranking, h_star: str) -> Ranking:
    if h_star == "rrf":
        return fuse_rrf(sparse, dense, rrf_k=60)
    return fuse_cc(sparse, dense, alpha_dense=float(h_star.removeprefix("cc_alpha_")))


def proxy_alpha(p_star: str) -> float | None:
    return None if p_star == "bm25" else float(p_star.removeprefix("proxy_cc_"))


class V2SearchMethod:
    def __init__(self, route, sparse, *, trace, provenance, **parts):
        self.route, self.sparse = route, sparse
        self.trace = trace if trace is not None else NullTraceSink()
        self.provenance = provenance
        self.p_alpha = parts.get("p_alpha")
        self.h_star = parts.get("h_star")
        self.r_alpha = parts.get("r_alpha")
        self.prefix = parts.get("prefix", "")
        for name in ("proxy", "encoder", "dense", "vectors", "rows", "extractor", "gate", "stats"):
            setattr(self, name, parts.get(name))
        self.scorer, self.threshold = parts.get("scorer"), parts.get("threshold")
        self.identities = parts.get("identities", {})

    def _empty(self, query: Query) -> SearchResponse:
        manifest = self.sparse.manifest
        empty = Ranking(
            query.query_id, query.domain, (), manifest["corpus_sha256"], manifest["retriever_hash"]
        )
        empty.validate()
        return SearchResponse(empty, False, None, 0, "empty_query")

    def _encode(self, query: Query) -> np.ndarray:
        with self.trace.stage("encode"):
            self.trace.increment("encoder_calls")
            vectors = self.encoder.encode([self.prefix + query.text])
            return checked_vectors(vectors, 1, self.encoder.config.dimension)

    def cheap(self, query: Query, sparse: Ranking) -> Ranking:
        if self.p_alpha is None:
            return sparse
        with self.trace.stage("fusion"):
            other = rescored_ranking(
                sparse,
                self.proxy.embed(query.text),
                self.vectors,
                self.rows,
                self.identities["proxy"],
            )
            return candidate_fusion(sparse, other, self.p_alpha)

    def rescore(self, query: Query, sparse: Ranking) -> Ranking:
        vector = self._encode(query)[0]
        with self.trace.stage("fusion"):
            other = rescored_ranking(
                sparse, vector, self.vectors, self.rows, self.identities["query"]
            )
            return candidate_fusion(sparse, other, self.r_alpha)

    def full(self, query: Query, sparse: Ranking) -> Ranking:
        vector = self._encode(query)
        dense = self.dense.search_vector(query, vector, k=100)  # traced as "vector"
        with self.trace.stage("fusion"):
            return fuse_high(sparse, dense, self.h_star)

    def gate_score(self, query: Query, sparse: Ranking, stats) -> float:
        with self.trace.stage("features"):
            values = np.asarray(
                self.extractor.transform(query, sparse, stats).values, dtype=np.float64
            )
        with self.trace.stage("gate"):
            if self.scorer == "bm25_margin":
                return float(-values[MARGIN_COLUMN])
            return float(self.gate.score(values[None, :], self.stats)[0])

    def search(self, query: Query, k: int = 100) -> SearchResponse:
        if type(k) is not int or k != 100:
            raise ValueError("v4 tiers are defined on the registered BM25 top-100")
        if query.domain != self.sparse.manifest["domain"]:
            raise ValueError("query domain differs from method domain")
        if not query.text.strip():
            return self._empty(query)
        sparse = self.sparse.search(query, k=k)
        if self.route == "bm25":
            return SearchResponse(sparse, False, None, 0, None)
        if self.route == "p_star":
            return SearchResponse(self.cheap(query, sparse), False, None, 0, None)
        if self.route == "r_star":
            return SearchResponse(self.rescore(query, sparse), True, None, 1, None)
        if self.route == "h_star":
            return SearchResponse(self.full(query, sparse), True, None, 1, None)
        stats = self.sparse.query_stats(query)
        score = self.gate_score(query, sparse, stats)
        if stats.token_count == 0 or stats.oov_ratio == 1.0 or score > self.threshold:
            return SearchResponse(self.full(query, sparse), True, score, 1, None)
        return SearchResponse(self.cheap(query, sparse), False, score, 0, None)

    def close(self) -> None:
        self.sparse.close()


def create_v2_method(
    *,
    trace,
    route: str,
    domain: str,
    fold: int,
    sparse_dir: str,
    dense_dir: str,
    expected_sparse_sha256: str,
    expected_dense_sha256: str,
    query_prefix: str = "",
    proxy_dir: str | None = None,
    expected_proxy_hash: str | None = None,
    p_star: str = "bm25",
    h_star: str | None = None,
    r_star: str | None = None,
    scorer: str | None = None,
    gate_path: str | None = None,
    expected_gate_sha256: str | None = None,
    threshold: float | None = None,
    protocol_path: str | None = None,
    cache_folder: str | None = None,
    torch_threads: int | None = None,
) -> V2SearchMethod:
    from pegh.dense.retriever import FaissDenseRetriever
    from pegh.v3.online import load_vectors

    if route not in ROUTES:
        raise ValueError(f"unsupported v4 route {route}")
    sparse_path, dense_path = Path(sparse_dir), Path(dense_dir)
    if file_hash(sparse_path / "index.sqlite3") != expected_sparse_sha256:
        raise ValueError("sparse registry checksum differs")
    if file_hash(dense_path / "index.faiss") != expected_dense_sha256:
        raise ValueError("dense registry checksum differs")
    sparse = open_backend(sparse_path, trace=trace, execution="numpy")
    provenance = {
        "schema_version": "v4_online_method_1",
        "route": route,
        "domain": domain,
        "fold": fold,
        "p_star": p_star,
        "h_star": h_star,
        "r_star": r_star,
        "query_prefix": query_prefix,
        "sparse_index_sha256": expected_sparse_sha256,
        "sparse_execution": sparse.execution_provenance,
        "dense_index_sha256": expected_dense_sha256,
        "query_embedding_cache": False,
        "quality_cache_used": False,
    }
    if route == "bm25":
        return V2SearchMethod(route, sparse, trace=trace, provenance=provenance)
    vectors, rows, manifest = load_vectors(dense_path)
    if manifest["corpus_sha256"] != sparse.manifest["corpus_sha256"]:
        raise ValueError("dense/sparse corpus differs")
    config = dict(manifest["config"])
    if torch_threads is not None:
        config["torch_threads"] = torch_threads
    parts = {"vectors": vectors, "rows": rows, "prefix": query_prefix}
    if route == "p_star":
        from transformers import AutoTokenizer

        tokenizer = AutoTokenizer.from_pretrained(
            config["model_id"], revision=config["revision"], cache_dir=cache_folder
        )
    else:
        encoder = CPUEncoder(DenseConfig(**config), cache_folder=cache_folder)
        tokenizer = encoder.model.tokenizer
        parts["encoder"] = encoder
        provenance["dense_config"] = config
    identities = {
        "query": rescore_identity(
            "query_encoder", f"{manifest['embedding_fingerprint']}|{query_prefix}"
        )
    }
    if route in ("p_star", "gated") and p_star != "bm25":
        proxy = StaticProxy(proxy_dir, tokenizer)
        if proxy.manifest["manifest_hash"] != expected_proxy_hash:
            raise ValueError("proxy registry hash differs")
        identities["proxy"] = rescore_identity("static_proxy", proxy.identity)
        parts.update(proxy=proxy, p_alpha=proxy_alpha(p_star))
        provenance["proxy_manifest_hash"] = expected_proxy_hash
    if route == "r_star":
        parts["r_alpha"] = float(r_star.removeprefix("rescore_cc_"))
    if route in ("h_star", "gated"):
        faiss_threads = config.get("faiss_threads")
        parts["dense"] = FaissDenseRetriever(dense_path, parts["encoder"], trace=trace)
        parts["h_star"] = h_star
        provenance["faiss_threads"] = faiss_threads
    if route == "gated":
        if scorer not in SCORERS:
            raise ValueError(f"unsupported scorer {scorer}")
        protocol = yaml.safe_load(Path(protocol_path).read_text(encoding="utf-8"))
        base = QueryFeatureExtractor(protocol["features"], sparse.tokenizer)
        if scorer == "gate_v2":
            if file_hash(Path(gate_path)) != expected_gate_sha256:
                raise ValueError("gate file checksum differs")
            payload = json.loads(Path(gate_path).read_text(encoding="utf-8"))
            if payload["domain"] != domain:
                raise ValueError("gate was not exported for this domain")
            gate = LinearGate.from_json(payload["gate"])
            parts.update(
                gate=gate,
                stats=payload.get("domain_stats"),
                extractor=ExtendedFeatureExtractor(base, sparse, gate.spec.groups),
            )
            provenance.update(gate_sha256=expected_gate_sha256, gate=gate.spec.name)
        else:
            parts["extractor"] = ExtendedFeatureExtractor(base, sparse, ("v1",))
        parts.update(scorer=scorer, threshold=float(threshold))
        provenance.update(scorer=scorer, threshold=float(threshold))
    parts["identities"] = identities
    json.dumps(provenance, allow_nan=False)
    return V2SearchMethod(route, sparse, trace=trace, provenance=provenance, **parts)
