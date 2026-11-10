from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from pegh.data.artifacts import object_hash

DEFAULT_PATTERN = r"(?u)--?[\w-]+|[\w]+(?:[./:+#-][\w]+)*"


@dataclass(frozen=True)
class BM25Config:
    implementation: str = "sqlite_bm25_v1"
    k1: float = 1.2
    b: float = 0.75
    lowercase: bool = True
    token_pattern: str = DEFAULT_PATTERN
    output_k: int = 100

    def __post_init__(self) -> None:
        if self.implementation != "sqlite_bm25_v1":
            raise ValueError("unsupported sparse implementation")
        if self.k1 <= 0 or not 0 <= self.b <= 1 or self.output_k < 1:
            raise ValueError("invalid BM25 parameters")

    @property
    def fingerprint(self) -> str:
        return object_hash(
            {
                "implementation": self.implementation,
                "k1": self.k1,
                "b": self.b,
                "lowercase": self.lowercase,
                "token_pattern": self.token_pattern,
            }
        )

    @classmethod
    def from_yaml(cls, path: str | Path) -> BM25Config:
        with Path(path).open(encoding="utf-8") as stream:
            payload = yaml.safe_load(stream)
        if not isinstance(payload, dict) or not isinstance(payload.get("sparse"), dict):
            raise ValueError("sparse config must contain a sparse mapping")
        return cls(**payload["sparse"])
