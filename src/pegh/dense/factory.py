from __future__ import annotations

from pathlib import Path

from pegh.dense.artifacts import read_json
from pegh.dense.config import DenseConfig
from pegh.dense.encoder import CPUEncoder
from pegh.dense.retriever import DenseOnlyMethod, FaissDenseRetriever
from pegh.profiling.trace import TraceSink


def create_dense_method(
    *,
    trace: TraceSink,
    index_dir: str,
    cache_folder: str | None = None,
    torch_threads: int | None = None,
    faiss_threads: int | None = None,
) -> DenseOnlyMethod:
    config = read_json(Path(index_dir) / "manifest.json")["config"]
    if torch_threads is not None:
        config["torch_threads"] = torch_threads
    if faiss_threads is not None:
        config["faiss_threads"] = faiss_threads
    encoder = CPUEncoder(DenseConfig(**config), cache_folder=cache_folder)
    return DenseOnlyMethod(FaissDenseRetriever(index_dir, encoder, trace=trace))
