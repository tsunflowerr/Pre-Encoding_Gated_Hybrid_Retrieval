from __future__ import annotations

import json

import pytest

from pegh.dense.index import build_index
from tests.b.fakes import DeterministicEncoder


@pytest.fixture
def corpus(tmp_path):
    path = tmp_path / "corpus.jsonl"
    rows = [
        {"_id": f"d{i:02d}", "title": f"Topic {i}", "text": f"Technical body {i}."}
        for i in range(13)
    ]
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    return path


@pytest.fixture
def built_index(tmp_path, corpus):
    encoder = DeterministicEncoder()
    directory = tmp_path / "index"
    build_index(corpus, directory, "unix", encoder, expected_count=13)
    return directory
