from __future__ import annotations

import json
import shutil
from dataclasses import asdict, replace
from pathlib import Path

import numpy as np
import pytest
import yaml

from pegh.dense.index import build_index
from pegh.sparse.config import BM25Config
from pegh.sparse.fast import FORMAT, compile_index
from pegh.sparse.index import build_index as build_sparse
from pegh.v3 import build as v3
from pegh.v3.cache import load_npz_cache, npz_inputs, npz_ready, seal_npz
from pegh.v3.workspace import Workspace as V3Workspace
from pegh.v4 import build as v4
from pegh.v4.workspace import Workspace
from tests.b.fakes import DeterministicEncoder


@pytest.fixture(params=[3, 4])
def workspace(tmp_path, request):
    fixture = Path("tests/fixtures/shared/unix")
    if request.param == 3:
        ws = V3Workspace.create(tmp_path / "v3", tmp_path / "dev", tmp_path / "dense")
        module = v3
    else:
        ws = Workspace.create(
            tmp_path / "v4", tmp_path / "v3", tmp_path / "dev", tmp_path / "dense"
        )
        module = v4
    ws = replace(ws, repo=tmp_path / "repo")
    raw = ws.raw("unix")
    raw.mkdir(parents=True)
    for name in ("corpus.jsonl", "queries.jsonl"):
        shutil.copy2(fixture / name, raw / name)
    dense = ws.repo / "configs/dense/primary.yaml"
    sparse = ws.repo / "configs/sparse/bm25.yaml"
    dense.parent.mkdir(parents=True)
    sparse.parent.mkdir(parents=True)
    dense.write_text(yaml.safe_dump({"dense": asdict(DeterministicEncoder().config)}))
    sparse.write_text(yaml.safe_dump({"sparse": asdict(BM25Config())}))
    build_sparse(raw / "corpus.jsonl", ws.sparse("unix"), "unix", BM25Config())
    compile_index(ws.sparse("unix"), ws.sparse("unix") / FORMAT)
    build_index(raw / "corpus.jsonl", ws.dense("minilm", "unix"), "unix", DeterministicEncoder())
    return ws, module


def test_completed_dense_is_verified_without_loading_model(workspace, monkeypatch):
    ws, module = workspace

    def unexpected(*args, **kwargs):
        pytest.fail("verified dense resume should not load the neural encoder")

    monkeypatch.setattr(module, "_encoder" if module is v3 else "encoder", unexpected)
    assert module.build_dense(ws, "minilm", "unix", 1) == ws.dense("minilm", "unix")


@pytest.mark.parametrize("change", ["index", "corpus", "model"])
def test_dense_resume_rejects_changed_inputs(workspace, change):
    ws, module = workspace
    if change == "index":
        path = ws.dense("minilm", "unix") / "index.faiss"
        path.write_bytes(path.read_bytes() + b"corrupt")
    elif change == "corpus":
        path = ws.raw("unix") / "corpus.jsonl"
        path.write_text(path.read_text() + "\n")
    else:
        path = ws.repo / "configs/dense/primary.yaml"
        payload = yaml.safe_load(path.read_text())
        payload["dense"]["revision"] = "fixture-v2"
        path.write_text(yaml.safe_dump(payload))
    with pytest.raises(ValueError):
        module.build_dense(ws, "minilm", "unix", 1)


@pytest.mark.parametrize("change", ["ranking", "query", "corpus", "sidecar"])
def test_quality_resume_rejects_corruption_and_stale_inputs(workspace, change):
    ws, module = workspace
    output = module.quality_cache(ws, "bm25", "unix")
    assert module.quality_cache(ws, "bm25", "unix") == output
    if change == "ranking":
        output.write_text("not a ranking\n")
    elif change in ("query", "corpus"):
        path = ws.raw("unix") / ("queries.jsonl" if change == "query" else "corpus.jsonl")
        payload = [json.loads(line) for line in path.read_text().splitlines()]
        payload[0]["text"] = "changed input text"
        path.write_text("\n".join(json.dumps(row) for row in payload) + "\n")
    else:
        output.with_suffix(".jsonl.meta.json").unlink()
    with pytest.raises(ValueError):
        module.quality_cache(ws, "bm25", "unix")


def test_derived_cache_rejects_legacy_changed_schema_and_modified_arrays(tmp_path):
    path = tmp_path / "features.npz"
    inputs = {"feature_schema": ["length", "gap"], "queries_hash": "before"}
    np.savez_compressed(path, ids=np.array(["unix:q1"]), v1=np.array([[1.0, 2.0]]))
    with pytest.raises(ValueError, match="legacy"):
        npz_ready(path, inputs)
    seal_npz(path, inputs)
    assert npz_ready(path, inputs)
    with pytest.raises(ValueError, match="inputs/checksum"):
        npz_ready(path, {**inputs, "queries_hash": "after"})
    with pytest.raises(ValueError, match="inputs/checksum"):
        npz_ready(path, {**inputs, "feature_schema": ["length", "new_feature"]})
    np.savez_compressed(path, ids=np.array(["unix:q1"]), v1=np.array([[9.0, 2.0]]))
    with pytest.raises(ValueError, match="inputs/checksum"):
        npz_ready(path, inputs)


def test_dense_quality_resume_checks_model_and_prefix_without_loading_encoder(
    workspace, monkeypatch
):
    ws, module = workspace
    name = "_encoder" if module is v3 else "encoder"
    monkeypatch.setattr(module, name, lambda *args: DeterministicEncoder())
    path = module.quality_cache(ws, "minilm", "unix")

    def unexpected(*args, **kwargs):
        pytest.fail("quality resume must validate inputs without loading the encoder")

    monkeypatch.setattr(module, name, unexpected)
    assert module.quality_cache(ws, "minilm", "unix") == path
    sidecar = path.with_suffix(".jsonl.meta.json")
    original = sidecar.read_text()
    metadata = json.loads(original)
    metadata["query_prefix"] = "changed prefix"
    sidecar.write_text(json.dumps(metadata))
    with pytest.raises(ValueError, match="prefix"):
        module.quality_cache(ws, "minilm", "unix")
    sidecar.write_text(original)
    config_path = ws.repo / "configs/dense/primary.yaml"
    config = yaml.safe_load(config_path.read_text())
    config["dense"]["revision"] = "fixture-v2"
    config_path.write_text(yaml.safe_dump(config))
    with pytest.raises(ValueError, match="model/revision/config"):
        module.quality_cache(ws, "minilm", "unix")


@pytest.mark.parametrize("kind", ["features", "tiers"])
def test_derived_cache_is_bound_to_real_workspace_dependencies(workspace, kind):
    ws, module = workspace
    module.quality_cache(ws, "bm25", "unix")
    sources = [
        "configs/gating/protocol_v1.yaml",
        "scripts_shared/experiment_v3.py",
        "scripts_shared/experiment_v4.py",
    ]
    sources += [
        f"src/pegh/{p}"
        for p in (
            "v3/features.py",
            "v3/proxy.py",
            "v3/rescore.py",
            "gating/features.py",
            "fusion/engines.py",
            "evaluation/metrics.py",
        )
    ]
    for name in sources:
        target = ws.repo / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(Path(name), target)
    proxy = ws.proxy("minilm", "unix") if module is v4 else ws.root / "artifacts/proxy/minilm/unix"
    proxy.mkdir(parents=True, exist_ok=True)
    (proxy / "manifest.json").write_text("{}")
    np.save(proxy / "table.npy", np.ones((4, 8)))
    np.save(proxy / "weights.npy", np.ones(4))
    (ws.raw("unix") / "qrels.tsv").write_text("query-id\tcorpus-id\tscore\nq1\td1\t1\n")
    inputs = npz_inputs(ws, "minilm", "unix", kind)
    path = ws.root / f"{kind}.npz"
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(path, ids=np.array(["unix:q1"]), values=np.array([0.5]))
    seal_npz(path, inputs)
    assert load_npz_cache(ws, "minilm", "unix", kind, path)["values"][0] == 0.5
    if kind == "features":
        np.save(proxy / "table.npy", np.zeros((4, 8)))
    else:
        (ws.raw("unix") / "qrels.tsv").write_text("changed relevance labels")
    with pytest.raises(ValueError, match="inputs/checksum"):
        load_npz_cache(ws, "minilm", "unix", kind, path)
