"""Locate v4 inputs/outputs across the v1, v3 and v4 workspaces.

Seen domains (v1 development + v3 fresh) reuse their verified artifacts read-only; the six
new subforums and every new encoder live under the v4 root. The interface mirrors the v3
Workspace so v3 library functions (fetch, sparse build, load_domain) can be reused as is.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

DEV_DOMAINS = ("programmers", "unix")
FRESH_DOMAINS = ("android", "gis", "mathematica", "webmasters")
SEEN_DOMAINS = DEV_DOMAINS + FRESH_DOMAINS
NEW_DOMAINS = ("english", "gaming", "physics", "stats", "tex", "wordpress")
QUERY_INSTRUCTION = "Represent this sentence for searching relevant passages: "

# encoder key -> (dense config, query prefix, document-vector key). Prefixes only change the
# query side, so prefixed variants share the stored corpus vectors of their base model.
ENCODERS = {
    "minilm": ("configs/dense/primary.yaml", "", "minilm"),
    "bge_small": ("configs/v3/dense_bge_small.yaml", "", "bge_small"),
    "bge_small_q": ("configs/v3/dense_bge_small.yaml", QUERY_INSTRUCTION, "bge_small"),
    "arctic_xs": ("configs/v4/dense_arctic_xs.yaml", "", "arctic_xs"),
    "arctic_xs_q": ("configs/v4/dense_arctic_xs.yaml", QUERY_INSTRUCTION, "arctic_xs"),
}
V3_KEYS = ("minilm", "bge_small")  # keys whose seen-domain artifacts already exist in v3


def vector_key(encoder: str) -> str:
    if encoder not in ENCODERS:
        raise ValueError(f"unregistered encoder: {encoder}")
    return ENCODERS[encoder][2]


def query_prefix(encoder: str) -> str:
    if encoder not in ENCODERS:
        raise ValueError(f"unregistered encoder: {encoder}")
    return ENCODERS[encoder][1]


@dataclass(frozen=True)
class Workspace:
    root: Path
    v3_root: Path
    dev_root: Path
    dev_dense_root: Path
    repo: Path

    @classmethod
    def create(cls, root, v3_root, dev_root, dev_dense_root):
        repo = Path(__file__).resolve().parents[3]
        paths = (Path(p).resolve() for p in (root, v3_root, dev_root, dev_dense_root))
        return cls(*paths, repo)

    @property
    def models(self) -> Path:
        return self.v3_root.parent / "models"

    def kind(self, domain: str) -> str:
        if domain in DEV_DOMAINS:
            return "dev"
        if domain in FRESH_DOMAINS:
            return "fresh"
        if domain in NEW_DOMAINS:
            return "new"
        raise ValueError(f"unregistered v4 domain: {domain}")

    def is_dev(self, domain: str) -> bool:
        return self.kind(domain) == "dev"

    def _base(self, domain: str) -> Path:
        return {"dev": self.dev_root, "fresh": self.v3_root, "new": self.root}[self.kind(domain)]

    def raw(self, domain: str) -> Path:
        return self._base(domain) / "data/raw" / domain

    def split_manifest(self, domain: str) -> Path:
        if self.kind(domain) == "dev":
            return self.repo / "data/splits/manifest.json"
        return self._base(domain) / "data/splits/manifest.json"

    def sparse(self, domain: str) -> Path:
        return self._base(domain) / "artifacts/sparse" / domain

    def _reuse_v3(self, key: str, domain: str) -> bool:
        return key in V3_KEYS and self.kind(domain) != "new"

    def dense(self, encoder: str, domain: str) -> Path:
        key = vector_key(encoder)
        if key == "minilm" and self.kind(domain) == "dev":
            return self.dev_dense_root / domain
        base = self.v3_root if self._reuse_v3(key, domain) else self.root
        return base / "artifacts/dense" / key / domain

    def proxy(self, encoder: str, domain: str) -> Path:
        key = vector_key(encoder)
        base = self.v3_root if self._reuse_v3(key, domain) else self.root
        return base / "artifacts/proxy" / key / domain

    def quality(self, retriever: str, domain: str) -> Path:
        """Offline top-100 caches for every query; never used by online timing."""
        kind = self.kind(domain)
        if kind == "dev" and retriever in ("bm25", "minilm"):
            name = "bm25" if retriever == "bm25" else "dense"
            return self.dev_root / "results/quality" / name / f"{domain}.jsonl"
        if (kind == "fresh" and retriever in ("bm25", *V3_KEYS)) or (
            kind == "dev" and retriever == "bge_small"
        ):
            return self.v3_root / "results/quality" / retriever / f"{domain}.jsonl"
        return self.root / "results/quality" / retriever / f"{domain}.jsonl"

    def features(self, encoder: str, domain: str) -> Path:
        key = vector_key(encoder)
        base = self.v3_root if self._reuse_v3(key, domain) else self.root
        return base / "results/features" / key / f"{domain}.npz"

    def tiers(self, encoder: str, domain: str) -> Path:
        base = self.v3_root if self._reuse_v3(encoder, domain) else self.root
        return base / "results/tiers" / encoder / f"{domain}.npz"

    def results(self, *parts: str) -> Path:
        return self.root.joinpath("results", *parts)
