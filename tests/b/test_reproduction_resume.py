from __future__ import annotations

from pathlib import Path

import pytest

from scripts_shared.reproduce import completed_benchmark
from tests.b.test_profiling import inputs, registry, settings


def test_reproduction_preserves_interrupted_run_before_restarting(built_index, tmp_path):
    queries, warmup = inputs()
    stop = tmp_path / "STOP"
    stop.touch()
    output = tmp_path / "results/run"
    kwargs = {"split": "fixture", "fold": 0, "stop_file": str(stop)}
    configuration = {"methods": registry(built_index)}
    with pytest.raises(SystemExit) as paused:
        completed_benchmark(
            tmp_path, configuration, queries, warmup, output, settings(repetitions=1), **kwargs
        )
    assert paused.value.code == 75
    stop.unlink()
    manifest, rows, _ = completed_benchmark(
        tmp_path,
        configuration,
        queries,
        warmup,
        output,
        settings(repetitions=1),
        restart_incomplete=True,
        **kwargs,
    )
    assert manifest["status"] == "complete"
    assert len(rows) == len(queries)
    preserved = list((tmp_path / "results").glob("run.interrupted.*"))
    assert len(preserved) == 1
    assert (Path(preserved[0]) / "manifest.json").is_file()
