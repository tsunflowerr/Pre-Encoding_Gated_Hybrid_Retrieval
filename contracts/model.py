"""Packaged primary-model registry. A/C should load this instead of copying IDs."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from importlib.resources import files


@dataclass(frozen=True)
class ModelSpec:
    model_id: str
    revision: str
    dimension: int
    max_length: int
    device: str
    dtype: str
    normalize: bool

    def __post_init__(self) -> None:
        if re.fullmatch(r"[0-9a-f]{40}", self.revision) is None:
            raise ValueError("primary model revision must be an immutable commit")
        if self.device != "cpu" or self.dtype != "float32" or not self.normalize:
            raise ValueError("registered baseline requires normalized CPU float32")
        if self.dimension < 1 or self.max_length < 1:
            raise ValueError("model dimension/max_length must be positive")


def get_primary_model() -> ModelSpec:
    payload = (
        files("contracts").joinpath("resources/primary_model.json").read_text(encoding="utf-8")
    )
    return ModelSpec(**json.loads(payload))
