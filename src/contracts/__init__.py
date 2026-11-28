"""Common public API for A/B/C; contains no Torch/FAISS imports."""

from contracts.types import Document, Hit, Query, Ranking, SearchHit

__all__ = ["Document", "Hit", "Query", "Ranking", "SearchHit"]
