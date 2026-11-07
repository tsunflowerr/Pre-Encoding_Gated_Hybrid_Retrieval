from __future__ import annotations

import json
import subprocess

import pytest

import pegh.dense.retriever as retriever_module
from contracts.types import Query
from pegh.dense.artifacts import atomic_json, file_hash, read_json
from pegh.dense.index import package_versions
from pegh.dense.retriever import FaissDenseRetriever
from pegh.profiling.provenance import source_snapshot
from pegh.profiling.report import make_figures, summarize_run
from pegh.profiling.runner import run_benchmark
from pegh.profiling.runtime import RuntimeSettings, runtime_manifest
from tests.b.fakes import DeterministicEncoder
from tests.b.test_profiling import inputs, registry, settings


def test_retriever_rejects_encoder_dependency_drift(built_index, monkeypatch):
    versions = {**package_versions(), "sentence-transformers": "different-version"}
    monkeypatch.setattr(retriever_module, "package_versions", lambda: versions, raising=False)
    with pytest.raises(ValueError, match="package versions"):
        FaissDenseRetriever(built_index, DeterministicEncoder())


def test_source_snapshot_does_not_depend_on_invocation_directory(tmp_path, monkeypatch):
    expected = source_snapshot()
    monkeypatch.chdir(tmp_path)
    assert source_snapshot() == expected


def test_empty_source_root_is_not_a_valid_snapshot(tmp_path):
    with pytest.raises(ValueError, match="checkout"):
        source_snapshot(tmp_path)


def test_runtime_git_metadata_uses_checkout_not_invocation_directory(tmp_path, monkeypatch):
    expected = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()
    monkeypatch.chdir(tmp_path)
    info = runtime_manifest(RuntimeSettings(enforce_memory_limit=False), {})
    assert info["git_commit"] == expected
    assert info["cwd"] != info["source_root"]


@pytest.mark.parametrize("wrong_set", ["measured", "warmup"])
def test_benchmark_rejects_mixed_domains(built_index, tmp_path, wrong_set):
    queries, warmup = inputs()
    if wrong_set == "measured":
        queries.append(Query("programmers:q1", "programmers", "foreign domain"))
    else:
        warmup = [Query("programmers:warm", "programmers", "foreign warmup")]
    with pytest.raises(ValueError, match="domain"):
        run_benchmark(
            registry(built_index), queries, warmup, tmp_path / "bad", settings(), split="fixture"
        )
    assert not (tmp_path / "bad").exists()


def _run(built_index, tmp_path, *, repetitions=1):
    queries, warmup = inputs()
    output = tmp_path / "run"
    manifest = run_benchmark(
        registry(built_index),
        queries,
        warmup,
        output,
        settings(repetitions=repetitions),
        split="fixture",
    )
    return output, manifest


def _replace_receipt(output, manifest, receipt):
    path = output / manifest["workers"][0]["directory"] / "worker.json"
    atomic_json(path, receipt)
    manifest["workers"][0]["receipt_sha256"] = file_hash(path)
    atomic_json(output / "manifest.json", manifest)


def test_report_rejects_worker_from_a_different_source_snapshot(built_index, tmp_path):
    output, manifest = _run(built_index, tmp_path)
    receipt = read_json(output / manifest["workers"][0]["directory"] / "worker.json")
    receipt["source_hash"] = "0" * 64
    _replace_receipt(output, manifest, receipt)
    with pytest.raises(ValueError, match="source"):
        summarize_run(output)


def test_report_rejects_model_provenance_drift_between_repeats(built_index, tmp_path):
    output, manifest = _run(built_index, tmp_path, repetitions=2)
    receipt = read_json(output / manifest["workers"][0]["directory"] / "worker.json")
    receipt["method_provenance"]["index_sha256"] = "0" * 64
    _replace_receipt(output, manifest, receipt)
    with pytest.raises(ValueError, match="provenance"):
        summarize_run(output)


def test_report_rejects_resource_drift_between_repeats(built_index, tmp_path):
    output, manifest = _run(built_index, tmp_path, repetitions=2)
    receipt = read_json(output / manifest["workers"][0]["directory"] / "worker.json")
    receipt["runtime"]["resources"]["effective_affinity"] = []
    _replace_receipt(output, manifest, receipt)
    with pytest.raises(ValueError, match="runtime resources"):
        summarize_run(output)


def test_final_test_requires_method_provenance(built_index, tmp_path):
    queries, warmup = inputs()
    with pytest.raises(RuntimeError, match="failed"):
        run_benchmark(
            registry(built_index, "create_fixture_gated"),
            queries,
            warmup,
            tmp_path / "missing-provenance",
            settings(repetitions=1),
            split="test",
        )
    receipt = read_json(tmp_path / "missing-provenance/00-fixture_dense/worker.json")
    assert "method provenance" in receipt["error"]


def test_report_rejects_request_from_a_different_run(built_index, tmp_path):
    output, manifest = _run(built_index, tmp_path)
    worker = output / manifest["workers"][0]["directory"]
    rows = [
        json.loads(line)
        for line in (worker / "requests.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    rows[0]["run_id"] = "another-run"
    (worker / "requests.jsonl").write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8"
    )
    receipt = read_json(worker / "worker.json")
    receipt["requests_sha256"] = file_hash(worker / "requests.jsonl")
    _replace_receipt(output, manifest, receipt)
    with pytest.raises(ValueError, match="metadata"):
        summarize_run(output)


def test_quality_rejects_same_run_id_with_wrong_query_and_method_hashes(built_index, tmp_path):
    output, _ = _run(built_index, tmp_path)
    summarize_run(output, bootstrap_samples=10)
    quality = tmp_path / "quality.csv"
    quality.write_text(
        "method,domain,ndcg_at_10,run_id,queries_hash,method_provenance_hash\nfixture_dense,unix,0.5,run,wrong-query-set,wrong-model\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="binding"):
        make_figures(output, quality)


def test_quality_requires_hash_bindings_not_only_run_id(built_index, tmp_path):
    output, _ = _run(built_index, tmp_path)
    summarize_run(output, bootstrap_samples=10)
    quality = tmp_path / "quality.csv"
    quality.write_text(
        "method,domain,ndcg_at_10,run_id\nfixture_dense,unix,0.5,run\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="binding"):
        make_figures(output, quality)
