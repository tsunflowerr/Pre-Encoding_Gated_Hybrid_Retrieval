from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import psutil
import pytest

from contracts.types import Query
from pegh.dense.artifacts import read_json
from pegh.profiling.report import make_figures, summarize_run
from pegh.profiling.runner import run_benchmark
from pegh.profiling.runtime import RuntimeSettings
from pegh.profiling.trace import TraceSink


def registry(index, factory="create_fixture_dense"):
    return [
        {
            "id": "fixture_dense",
            "factory": "tests.b.fakes:" + factory,
            "kwargs": {"index_dir": str(index)},
        }
    ]


def inputs():
    return (
        [Query(f"unix:q{i}", "unix", f"query {i}") for i in range(5)],
        [Query("unix:warm", "unix", "warmup query")],
    )


def settings(**overrides):
    return replace(
        RuntimeSettings(
            warmup_queries=2, repetitions=2, enforce_memory_limit=False, detailed_stages=True
        ),
        **overrides,
    )


def test_isolated_benchmark_and_report(built_index, tmp_path):
    queries, warmup = inputs()
    output = tmp_path / "benchmark"
    manifest = run_benchmark(
        registry(built_index), queries, warmup, output, settings(), split="fixture"
    )
    assert manifest["status"] == "complete"
    receipts = [read_json(output / w["directory"] / "worker.json") for w in manifest["workers"]]
    assert len({r["runtime"]["pid"] for r in receipts}) == 2
    assert all(len(r["runtime"]["resources"]["effective_affinity"]) <= 4 for r in receipts)
    summary = summarize_run(output, bootstrap_samples=20)["summaries"][0]
    assert summary["unique_queries"] == 5 and summary["timing_samples"] == 10
    assert summary["dense_call_ratio"] == 1.0
    assert summary["stage_means"]["encode_ms"] >= 0
    assert summary["peak_rss_bytes"] > 0
    assert len(make_figures(output)) == 2


def test_gated_fixture_really_skips_encoding(built_index, tmp_path):
    queries, warmup = inputs()
    output = tmp_path / "gated-fixture"
    manifest = run_benchmark(
        registry(built_index, "create_fixture_gated"),
        queries,
        warmup,
        output,
        settings(repetitions=1),
        split="fixture",
    )
    rows = [
        json.loads(line)
        for line in (output / manifest["workers"][0]["directory"] / "requests.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    skipped = [r for r in rows if not r["use_dense"]]
    assert len(skipped) == 3
    assert all(r["encoder_calls"] == r["vector_search_calls"] == 0 for r in skipped)
    assert all(r["encode_ns"] == r["vector_ns"] == 0 for r in skipped)
    assert all(r["stage_calls"]["sparse"] == 1 for r in rows)
    summary = summarize_run(output, bootstrap_samples=10)["summaries"][0]
    assert summary["dense_call_ratio"] == 0.4


@pytest.mark.parametrize(
    "factory",
    [
        "create_wrong_counter",
        "create_fallback_method",
        "create_false_empty_fallback",
        "create_cached_query_vector",
    ],
)
def test_invalid_worker_fails_without_a_valid_summary(built_index, tmp_path, factory):
    queries, warmup = inputs()
    output = tmp_path / factory
    with pytest.raises(RuntimeError, match="failed"):
        run_benchmark(
            registry(built_index, factory),
            queries,
            warmup,
            output,
            settings(repetitions=1),
            split="fixture",
        )
    assert read_json(output / "manifest.json")["status"] == "failed"
    with pytest.raises(ValueError, match="complete"):
        summarize_run(output)


def test_warmup_overlap_is_rejected_before_run(built_index, tmp_path):
    queries, _ = inputs()
    with pytest.raises(ValueError, match="overlap"):
        run_benchmark(
            registry(built_index),
            queries,
            queries[:1],
            tmp_path / "bad",
            settings(),
            split="fixture",
        )
    assert not (tmp_path / "bad").exists()


def test_stop_prevents_workers(built_index, tmp_path):
    queries, warmup = inputs()
    stop = tmp_path / "STOP"
    stop.touch()
    result = run_benchmark(
        registry(built_index),
        queries,
        warmup,
        tmp_path / "paused",
        settings(),
        split="fixture",
        stop_file=stop,
    )
    assert result["status"] == "paused" and result["workers"] == []


def test_strict_resource_limits_are_applied_in_worker_only(built_index, tmp_path):
    queries, warmup = inputs()
    output = tmp_path / "strict-limits"
    manifest = run_benchmark(
        registry(built_index),
        queries,
        warmup,
        output,
        settings(repetitions=1, enforce_memory_limit=True),
        split="fixture",
    )
    receipt = read_json(output / manifest["workers"][0]["directory"] / "worker.json")
    resources = receipt["runtime"]["resources"]
    assert resources["memory_limit_kind"] != "observed_only"
    assert resources["memory_limit_bytes"] == 8_000_000_000
    assert len(resources["effective_affinity"]) <= 4


def test_explicit_affinity_is_applied_without_changing_parent(built_index, tmp_path):
    parent_affinity = psutil.Process().cpu_affinity()
    requested = tuple(parent_affinity[::2][:2])
    queries, warmup = inputs()
    output = tmp_path / "explicit-affinity"
    manifest = run_benchmark(
        registry(built_index),
        queries,
        warmup,
        output,
        settings(repetitions=1, affinity_cpus=requested),
        split="fixture",
    )
    receipt = read_json(output / manifest["workers"][0]["directory"] / "worker.json")
    assert receipt["runtime"]["resources"]["effective_affinity"] == list(requested)
    assert psutil.Process().cpu_affinity() == parent_affinity


def test_missing_request_cannot_be_silently_dropped(built_index, tmp_path):
    queries, warmup = inputs()
    output = tmp_path / "broken"
    manifest = run_benchmark(
        registry(built_index), queries, warmup, output, settings(repetitions=1), split="fixture"
    )
    path = output / manifest["workers"][0]["directory"] / "requests.jsonl"
    path.write_text(
        "\n".join(path.read_text(encoding="utf-8").splitlines()[1:]) + "\n", encoding="utf-8"
    )
    with pytest.raises(ValueError):
        summarize_run(output)


def test_trace_detects_nested_requests():
    trace = TraceSink()
    trace.begin_request()
    with pytest.raises(RuntimeError, match="already"):
        trace.begin_request()
    with pytest.raises(ValueError, match="unregistered"):
        with trace.stage("wrong_stage"):
            pass
    assert trace.end_request()["encoder_calls"] == 0


def test_quality_csv_is_required_for_pareto_not_invented(built_index, tmp_path):
    queries, warmup = inputs()
    output = tmp_path / "run"
    run_benchmark(
        registry(built_index), queries, warmup, output, settings(repetitions=1), split="fixture"
    )
    summarize_run(output, bootstrap_samples=10)
    quality = tmp_path / "quality.csv"
    quality.write_text(
        "method,domain,ndcg_at_10,run_id\nfixture_dense,unix,0.5,wrong-run\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="identity"):
        make_figures(output, quality)
    quality.write_text(
        "method,domain,ndcg_at_10,run_id\nfixture_dense,unix,0.5,run\n", encoding="utf-8"
    )
    figures = make_figures(output, quality)
    assert any(Path(path).name == "quality-latency-unix.png" for path in figures)
    quality.write_text(
        quality.read_text(encoding="utf-8") + "fixture_dense,unix,0.5,run\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="duplicate"):
        make_figures(output, quality)
