"""Deterministic sparse retrieval owned by person A."""

from pegh.sparse.config import BM25Config
from pegh.sparse.index import SQLiteBM25, build_index

__all__ = ["BM25Config", "SQLiteBM25", "build_index"]
