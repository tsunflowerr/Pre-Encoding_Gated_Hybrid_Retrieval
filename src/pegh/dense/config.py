from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

import yaml

from pegh.dense.artifacts import object_hash


@dataclass(frozen=True)
class DenseConfig:
    model_id: str = "sentence-transformers/msmarco-MiniLM-L6-cos-v5"
    revision: str = "14ca9be4bbcf1402eac0f43a2e2ccb6e0f994ba3"
    dimension: int = 384
    max_length: int = 256
    batch_size: int = 16
    checkpoint_documents: int = 512
    torch_threads: int = 4
    faiss_threads: int = 4
    device: str = "cpu"
    dtype: str = "float32"
    normalize: bool = True

    def __post_init__(self) -> None:
        if self.device != "cpu" or self.dtype != "float32" or not self.normalize:
            raise ValueError("the registered baseline requires CPU, float32 and L2 normalization")
        if not self.revision:
            raise ValueError("a model revision is required")
        for name in (
            "dimension",
            "max_length",
            "batch_size",
            "checkpoint_documents",
            "torch_threads",
            "faiss_threads",
        ):
            if getattr(self, name) < 1:
                raise ValueError(f"{name} must be positive")

    @property
    def fingerprint(self) -> str:
        return object_hash(asdict(self))

    @property
    def embedding_fingerprint(self) -> str:
        fields = ("model_id", "revision", "dimension", "max_length", "dtype", "normalize")
        return object_hash({name: getattr(self, name) for name in fields})

    @classmethod
    def from_yaml(cls, path: str | Path) -> DenseConfig:
        with Path(path).open(encoding="utf-8") as stream:
            payload = yaml.safe_load(stream)
        return cls(**payload["dense"])
