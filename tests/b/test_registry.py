from __future__ import annotations

import runpy
import sys

import pytest

from pegh.dense.artifacts import file_hash, read_json
from pegh.dense.factory import create_dense_method
from pegh.profiling.trace import TraceSink


def test_registry_binds_complete_index_and_rejects_drift(built_index, tmp_path, monkeypatch):
    output = tmp_path / "registry.json"
    monkeypatch.setattr(
        sys,
        "argv",
        ["make_dense_registry.py", "--index", str(built_index), "--output", str(output)],
    )
    runpy.run_path("scripts_b/make_dense_registry.py", run_name="__main__")
    method = read_json(output)["methods"][0]
    assert method["require_dense_warmup"] is True
    assert method["kwargs"]["expected_index_sha256"] == file_hash(built_index / "index.faiss")
    with pytest.raises(ValueError, match="checksum"):
        create_dense_method(
            trace=TraceSink(), index_dir=str(built_index), expected_index_sha256="0" * 64
        )
