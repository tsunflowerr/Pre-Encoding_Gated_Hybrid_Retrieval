from __future__ import annotations

import json
import os
from dataclasses import replace

import numpy as np
import pytest

from contracts.types import Query
from pegh.dense.config import DenseConfig
from pegh.dense.encoder import CPUEncoder
from pegh.dense.index import build_index
from pegh.dense.retriever import FaissDenseRetriever


@pytest.mark.model
def test_real_pinned_cpu_encoder_index_and_query(tmp_path):
    config = replace(DenseConfig(), batch_size=2, checkpoint_documents=4)
    encoder = CPUEncoder(config, cache_folder=os.environ.get("PE_GH_MODEL_CACHE"))
    texts = [
        "How do I change Unix file permissions?",
        "A Python module import failed.",
        "Configure a reverse proxy for a web server.",
        "token " * 600,
        "Find duplicate questions about shell commands.",
    ]
    vectors = encoder.encode(texts)
    assert vectors.shape == (5, 384) and vectors.dtype == np.float32
    np.testing.assert_allclose(np.linalg.norm(vectors, axis=1), 1, atol=1e-4)
    assert encoder.model.device.type == "cpu"
    source = tmp_path / "corpus.jsonl"
    source.write_text(
        "".join(json.dumps({"_id": str(i), "text": text}) + "\n" for i, text in enumerate(texts)),
        encoding="utf-8",
    )
    directory = tmp_path / "real-index"
    manifest = build_index(source, directory, "unix", encoder, expected_count=5)
    assert manifest["truncated_documents"] == 1
    retriever = FaissDenseRetriever(directory, encoder)
    before = encoder.encode_calls
    ranking = retriever.search(Query("unix:query", "unix", texts[0]), k=3)
    assert encoder.encode_calls == before + 1
    assert ranking.hits[0].doc_id == "unix:0"
    assert ranking.hits[0].score == pytest.approx(1, abs=1e-5)
