from __future__ import annotations

import os
import random
import subprocess
import sys
import time
from dataclasses import asdict
from pathlib import Path

from contracts.types import Query
from pegh.dense.artifacts import atomic_json, file_hash, object_hash, read_json
from pegh.profiling.provenance import source_snapshot
from pegh.profiling.runtime import RuntimeSettings


def run_benchmark(
    registry: list[dict],
    queries: list[Query],
    warmup_queries: list[Query],
    output: str | Path,
    settings: RuntimeSettings,
    *,
    split: str,
    fold: int | None = None,
    k: int = 100,
    stop_file: str | Path | None = None,
) -> dict:
    """Launch isolated workers; change method order per repeat, preserve query order."""
    if not registry or not queries or k < 1:
        raise ValueError("methods, queries and positive k are required")
    if len({m["id"] for m in registry}) != len(registry):
        raise ValueError("method IDs must be unique")
    if any(not m["id"].replace("_", "").replace("-", "").isalnum() for m in registry):
        raise ValueError("method IDs must be safe filename components")
    if len({q.query_id for q in queries}) != len(queries):
        raise ValueError("measured query IDs must be unique")
    domains = {q.domain for q in queries}
    if len(domains) != 1 or any(q.domain not in domains for q in warmup_queries):
        raise ValueError("run one domain at a time, with warmup queries from that same domain")
    if {q.query_id for q in queries} & {q.query_id for q in warmup_queries}:
        raise ValueError("warmup queries overlap measured queries")
    if settings.warmup_queries and not warmup_queries:
        raise ValueError("warmup inputs required")
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    manifest = {
        "schema_version": "1.0",
        "status": "running",
        "run_id": output.name,
        "registry": registry,
        "registry_hash": object_hash(registry),
        "query_ids_hash": object_hash([q.query_id for q in queries]),
        "query_id_set_hash": object_hash(sorted(q.query_id for q in queries)),
        "queries_hash": object_hash([asdict(q) for q in queries]),
        "warmup_hash": object_hash([asdict(q) for q in warmup_queries]),
        "query_count": len(queries),
        "domain": queries[0].domain,
        "settings": asdict(settings),
        "split": split,
        "fold": fold,
        "k": k,
        "workers": [],
        "quality_cache_used": False,
        "source_snapshot": source_snapshot(),
        "started_at_unix": time.time(),
    }
    manifest_path = output / "manifest.json"
    atomic_json(manifest_path, manifest)
    env = dict(os.environ)
    env.update(
        {
            "OMP_NUM_THREADS": str(settings.logical_cpus),
            "MKL_NUM_THREADS": str(settings.logical_cpus),
            "OPENBLAS_NUM_THREADS": "1",
            "TOKENIZERS_PARALLELISM": "false",
            "HF_HUB_DISABLE_XET": "1",
        }
    )
    try:
        for repetition in range(settings.repetitions):
            methods = list(registry)
            random.Random(settings.seed + 10000 + repetition).shuffle(methods)
            for method in methods:
                if stop_file is not None and Path(stop_file).exists():
                    manifest["status"] = "paused"
                    atomic_json(manifest_path, manifest)
                    return manifest
                name = f"{repetition:02d}-{method['id']}"
                payload = {
                    "method": method,
                    "queries": [asdict(q) for q in queries],
                    "warmup_queries": [asdict(q) for q in warmup_queries],
                    "settings": asdict(settings),
                    "output": str(output / name),
                    "repetition": repetition,
                    "run_id": output.name,
                    "split": split,
                    "fold": fold,
                    "k": k,
                    "stop_file": str(stop_file) if stop_file is not None else None,
                    "expected_source_hash": manifest["source_snapshot"]["combined_sha256"],
                }
                request_path = output / f"{name}.input.json"
                atomic_json(request_path, payload)
                with (output / f"{name}.log").open("w", encoding="utf-8") as log:
                    completed = subprocess.run(
                        [sys.executable, "-m", "pegh.profiling.worker", str(request_path)],
                        env=env,
                        stdout=log,
                        stderr=subprocess.STDOUT,
                        check=False,
                        timeout=settings.worker_timeout_seconds,
                    )
                worker_path = output / name / "worker.json"
                if not worker_path.exists():
                    raise RuntimeError(f"worker {name} produced no receipt; inspect its log")
                receipt = read_json(worker_path)
                manifest["workers"].append(
                    {
                        "directory": name,
                        "method": method["id"],
                        "repetition": repetition,
                        "status": receipt["status"],
                        "returncode": completed.returncode,
                        "receipt_sha256": file_hash(worker_path),
                    }
                )
                atomic_json(manifest_path, manifest)
                if completed.returncode == 75 and receipt["status"] == "paused":
                    manifest["status"] = "paused"
                    atomic_json(manifest_path, manifest)
                    return manifest
                if completed.returncode or receipt["status"] != "complete":
                    raise RuntimeError(f"worker {name} failed; inspect {worker_path}")
        manifest["status"] = "complete"
    except Exception as exc:
        manifest["status"] = "failed"
        manifest["error"] = str(exc)
        raise
    finally:
        manifest["ended_at_unix"] = time.time()
        atomic_json(manifest_path, manifest)
    return manifest
