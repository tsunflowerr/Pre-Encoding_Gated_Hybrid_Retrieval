"""Pre-encoding semantic proxy: a static token table distilled from the frozen encoder.

Each vocabulary token is encoded once, alone, through the pinned SentenceTransformer
(model2vec-style). A query proxy is the weighted mean of its WordPiece vectors, so routing
can compare the query with the stored dense vectors of BM25 candidates without running the
transformer. Distillation and weighting use no relevance labels.
"""

from __future__ import annotations

import json
import math
from collections import Counter
from pathlib import Path

import numpy as np

from pegh.data.artifacts import atomic_json, file_hash, object_hash

FORMAT = "static_token_proxy_v1"


def distill_table(sentence_transformer, *, batch_size: int = 512) -> np.ndarray:
    """Return one L2-normalized sentence embedding per vocabulary id, [CLS] t [SEP] input."""
    import torch

    tokenizer = sentence_transformer.tokenizer
    size = len(tokenizer)
    cls, sep = tokenizer.cls_token_id, tokenizer.sep_token_id
    rows = []
    with torch.inference_mode():
        for start in range(0, size, batch_size):
            ids = torch.arange(start, min(start + batch_size, size), dtype=torch.long)
            input_ids = torch.stack(
                [torch.full_like(ids, cls), ids, torch.full_like(ids, sep)], dim=1
            )
            features = {
                "input_ids": input_ids,
                "attention_mask": torch.ones_like(input_ids),
                "token_type_ids": torch.zeros_like(input_ids),
            }
            output = sentence_transformer(features)["sentence_embedding"]
            rows.append(torch.nn.functional.normalize(output, dim=1).numpy().astype(np.float32))
    table = np.concatenate(rows)
    if table.shape[0] != size or not np.isfinite(table).all():
        raise ValueError("distilled token table is incomplete or nonfinite")
    return table


def corpus_token_weights(tokenizer, texts, *, smoothing: float = 1e-3) -> np.ndarray:
    """SIF weights a / (a + p(t)) from corpus WordPiece frequencies (label-free)."""
    counts: Counter[int] = Counter()
    batch: list[str] = []

    def flush() -> None:
        encoded = tokenizer(batch, add_special_tokens=False, truncation=True, max_length=256)
        for ids in encoded["input_ids"]:
            counts.update(ids)
        batch.clear()

    for text in texts:
        batch.append(text)
        if len(batch) == 1024:
            flush()
    if batch:
        flush()
    total = sum(counts.values())
    frequency = np.zeros(len(tokenizer), dtype=np.float64)
    for token, count in counts.items():
        frequency[token] = count / total
    return (smoothing / (smoothing + frequency)).astype(np.float32)


def save_proxy(directory: str | Path, table: np.ndarray, weights: np.ndarray, meta: dict) -> dict:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    np.save(directory / "table.npy", table, allow_pickle=False)
    np.save(directory / "weights.npy", weights, allow_pickle=False)
    manifest = {
        "schema_version": FORMAT,
        **meta,
        "vocab_size": int(table.shape[0]),
        "dimension": int(table.shape[1]),
        "table_sha256": file_hash(directory / "table.npy"),
        "weights_sha256": file_hash(directory / "weights.npy"),
    }
    manifest["manifest_hash"] = object_hash(manifest)
    atomic_json(directory / "manifest.json", manifest)
    return manifest


class StaticProxy:
    """Weighted mean of distilled token vectors; never calls the transformer."""

    def __init__(self, directory: str | Path, tokenizer, *, weighting: str = "sif") -> None:
        directory = Path(directory)
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        unsigned = {key: value for key, value in manifest.items() if key != "manifest_hash"}
        if manifest.get("schema_version") != FORMAT or object_hash(unsigned) != manifest.get(
            "manifest_hash"
        ):
            raise ValueError("proxy manifest checksum or format differs")
        for name in ("table", "weights"):
            if file_hash(directory / f"{name}.npy") != manifest[f"{name}_sha256"]:
                raise ValueError(f"proxy {name} checksum differs")
        if weighting not in ("sif", "uniform"):
            raise ValueError("unsupported proxy weighting")
        self.table = np.load(directory / "table.npy", allow_pickle=False)
        self.weights = (
            np.load(directory / "weights.npy", allow_pickle=False)
            if weighting == "sif"
            else np.ones(self.table.shape[0], dtype=np.float32)
        )
        if self.table.shape[0] != len(tokenizer) or self.weights.shape != (self.table.shape[0],):
            raise ValueError("proxy vocabulary differs from the tokenizer")
        self.tokenizer = tokenizer
        self.weighting = weighting
        self.manifest = manifest
        self.identity = object_hash({"proxy": manifest["manifest_hash"], "weighting": weighting})

    def embed(self, text: str) -> np.ndarray:
        ids = self.tokenizer(text, add_special_tokens=False, truncation=True, max_length=254)[
            "input_ids"
        ]
        if not ids:
            return np.zeros(self.table.shape[1], dtype=np.float32)
        ids = np.asarray(ids, dtype=np.int64)
        vector = self.weights[ids] @ self.table[ids]
        norm = float(np.linalg.norm(vector))
        return vector / norm if norm > 0 and math.isfinite(norm) else np.zeros_like(vector)
