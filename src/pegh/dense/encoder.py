from __future__ import annotations

import inspect
import os
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

import numpy as np

from pegh.dense.artifacts import file_hash, object_hash
from pegh.dense.config import DenseConfig


class TextEncoder(Protocol):
    config: DenseConfig

    def encode(self, texts: Sequence[str]) -> np.ndarray: ...
    def token_lengths(self, texts: Sequence[str]) -> list[int]: ...


def implementation_fingerprint(encoder: TextEncoder) -> str:
    directory = Path(__file__).parent
    paths = {directory / name for name in ("encoder.py", "config.py", "corpus.py", "index.py")}
    encoder_path = Path(inspect.getfile(type(encoder)))
    return object_hash(
        {
            "encoder_class": type(encoder).__qualname__,
            "encoder_class_source": file_hash(encoder_path),
            "pipeline_files": {path.name: file_hash(path) for path in sorted(paths)},
        }
    )


def checked_vectors(vectors: np.ndarray, count: int, dimension: int) -> np.ndarray:
    if vectors.dtype != np.float32 or vectors.shape != (count, dimension):
        raise ValueError(f"expected float32 vectors with shape {(count, dimension)}")
    if not np.isfinite(vectors).all():
        raise ValueError("nonfinite embedding")
    if count and not np.allclose(np.linalg.norm(vectors, axis=1), 1.0, atol=1e-4):
        raise ValueError("embeddings must be L2-normalized and nonzero")
    return np.ascontiguousarray(vectors)


class CPUEncoder:
    """Frozen, pinned SentenceTransformer. No query/vector cache is maintained."""

    def __init__(self, config: DenseConfig, *, cache_folder: str | None = None):
        os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
        os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
        import torch
        from sentence_transformers import SentenceTransformer

        torch.set_num_threads(config.torch_threads)
        if torch.get_num_interop_threads() != 1:
            torch.set_num_interop_threads(1)
        self.config = config
        self.model = SentenceTransformer(
            config.model_id,
            revision=config.revision,
            device="cpu",
            cache_folder=cache_folder,
            trust_remote_code=False,
            model_kwargs={"torch_dtype": torch.float32},
        )
        self.model.max_seq_length = config.max_length
        self.model.eval()
        get_dimension = (
            getattr(self.model, "get_embedding_dimension", None)
            or self.model.get_sentence_embedding_dimension
        )
        if get_dimension() != config.dimension:
            raise ValueError("model dimension differs from registered configuration")
        if any(parameter.device.type != "cpu" for parameter in self.model.parameters()):
            raise RuntimeError("non-CPU model parameter detected")
        self.encode_calls = 0

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        if not texts:
            return np.empty((0, self.config.dimension), dtype=np.float32)
        self.encode_calls += 1
        vectors = self.model.encode(
            list(texts),
            batch_size=self.config.batch_size,
            device="cpu",
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return checked_vectors(vectors, len(texts), self.config.dimension)

    def token_lengths(self, texts: Sequence[str]) -> list[int]:
        # Offline-only audit: counting untruncated tokens is included in indexing time.
        encoded = self.model.tokenizer(
            list(texts),
            add_special_tokens=True,
            truncation=False,
            padding=False,
            return_length=True,
            verbose=False,
        )
        return [int(length) for length in encoded["length"]]
