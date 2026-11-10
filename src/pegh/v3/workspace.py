"""Locate v3 inputs/outputs; development domains reuse verified v1 artifacts read-only."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

DEV_DOMAINS = ("programmers", "unix")
FRESH_DOMAINS = ("android", "gis", "mathematica", "webmasters")
ENCODERS = {
    "minilm": "configs/dense/primary.yaml",
    "bge_small": "configs/v3/dense_bge_small.yaml",
}


@dataclass(frozen=True)
class Workspace:
    root: Path
    dev_root: Path
    dev_dense_root: Path
    repo: Path

    @classmethod
    def create(cls, root: str | Path, dev_root: str | Path, dev_dense_root: str | Path):
        repo = Path(__file__).resolve().parents[3]
        return cls(
            Path(root).resolve(), Path(dev_root).resolve(), Path(dev_dense_root).resolve(), repo
        )

    def is_dev(self, domain: str) -> bool:
        if domain not in DEV_DOMAINS + FRESH_DOMAINS:
            raise ValueError(f"unregistered v3 domain: {domain}")
        return domain in DEV_DOMAINS

    def raw(self, domain: str) -> Path:
        return (self.dev_root if self.is_dev(domain) else self.root) / "data/raw" / domain

    def split_manifest(self, domain: str) -> Path:
        if self.is_dev(domain):
            return self.repo / "data/splits/manifest.json"
        return self.root / "data/splits/manifest.json"

    def sparse(self, domain: str) -> Path:
        return (self.dev_root if self.is_dev(domain) else self.root) / "artifacts/sparse" / domain

    def dense(self, encoder: str, domain: str) -> Path:
        if encoder not in ENCODERS:
            raise ValueError(f"unregistered encoder: {encoder}")
        if encoder == "minilm" and self.is_dev(domain):
            return self.dev_dense_root / domain
        return self.root / "artifacts/dense" / encoder / domain

    def quality(self, retriever: str, domain: str) -> Path:
        """Offline top-100 caches for every query; never used by online timing."""
        if retriever == "bm25" and self.is_dev(domain):
            return self.dev_root / "results/quality/bm25" / f"{domain}.jsonl"
        if retriever == "minilm" and self.is_dev(domain):
            return self.dev_root / "results/quality/dense" / f"{domain}.jsonl"
        return self.root / "results/quality" / retriever / f"{domain}.jsonl"

    def results(self, *parts: str) -> Path:
        return self.root.joinpath("results", *parts)
