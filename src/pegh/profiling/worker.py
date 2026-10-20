"""Private one-method/one-repetition worker, always launched in a new process."""

from __future__ import annotations

import importlib
import random
import sys
import time
import traceback
from pathlib import Path

from contracts.types import Query
from pegh.dense.artifacts import atomic_json, file_hash, object_hash, read_json, write_jsonl
from pegh.profiling.provenance import source_snapshot
from pegh.profiling.runtime import (
    MemorySampler,
    RuntimeSettings,
    configure_resources,
    runtime_manifest,
)
from pegh.profiling.trace import TraceSink


def execute(config_path: str | Path) -> int:
    payload = read_json(config_path)
    settings = RuntimeSettings(**payload["settings"])
    output = Path(payload["output"])
    output.mkdir(parents=True, exist_ok=False)
    rows: list[dict] = []
    result: dict = {
        "status": "failed",
        "method": payload["method"]["id"],
        "repetition": payload["repetition"],
    }
    sampler = MemorySampler(settings.memory_sample_seconds)
    sampler.start()
    code = 1
    try:
        current_source = source_snapshot()
        if current_source["combined_sha256"] != payload["expected_source_hash"]:
            raise ValueError("executable source/config drift before benchmark worker")
        result["source_hash"] = current_source["combined_sha256"]
        resources = configure_resources(settings)
        result["runtime"] = runtime_manifest(settings, resources)
        queries = [Query(**record) for record in payload["queries"]]
        warmup = [Query(**record) for record in payload["warmup_queries"]]
        if settings.warmup_queries and not warmup:
            raise ValueError("warmup query inputs are required")
        if {q.query_id for q in queries} & {q.query_id for q in warmup}:
            raise ValueError("warmup and measured query IDs must be disjoint")
        trace = TraceSink(detailed=settings.detailed_stages)
        module, function = payload["method"]["factory"].rsplit(":", 1)
        factory = getattr(importlib.import_module(module), function)
        method = factory(trace=trace, **payload["method"].get("kwargs", {}))
        result["method_provenance"] = getattr(method, "provenance", None)
        result["runtime"]["backend_threads_after_factory"] = {
            "torch": sys.modules["torch"].get_num_threads() if "torch" in sys.modules else None,
            "faiss": sys.modules["faiss"].omp_get_max_threads() if "faiss" in sys.modules else None,
        }
        warmup_calls = 0
        for i in range(settings.warmup_queries):
            trace.begin_request()
            try:
                warm_response = method.search(warmup[i % len(warmup)], k=payload["k"])
            finally:
                warm_trace = trace.end_request()
            if warm_response.encoder_calls != warm_trace["encoder_calls"]:
                raise ValueError("encoder call mismatch during warmup")
            warmup_calls += warm_trace["encoder_calls"]
        result["warmup_encoder_calls"] = warmup_calls
        if payload["method"].get("require_dense_warmup", False) and not warmup_calls:
            raise ValueError("registered dense branch was not exercised during warmup")
        order = list(queries)
        random.Random(settings.seed + payload["repetition"]).shuffle(order)
        for query in order:
            if payload.get("stop_file") and Path(payload["stop_file"]).exists():
                result["status"] = "paused"
                code = 75
                break
            trace.begin_request()
            cpu_start = time.process_time_ns()
            wall_start = time.perf_counter_ns()
            try:
                response = method.search(query, k=payload["k"])
            finally:
                total_ns = time.perf_counter_ns() - wall_start
                cpu_ns = time.process_time_ns() - cpu_start
                measurement = trace.end_request()
            response.ranking.validate()
            hits = response.ranking.hits
            if list(hits) != sorted(hits, key=lambda hit: (-hit.score, hit.doc_id)):
                raise ValueError("ranking violates descending-score/doc-ID tie order")
            if (
                response.ranking.query_id != query.query_id
                or response.ranking.domain != query.domain
                or len(response.ranking.hits) > payload["k"]
                or any(hit.doc_id == query.query_id for hit in response.ranking.hits)
            ):
                raise ValueError("search response violates query/top-k/self-filter contract")
            calls = measurement["encoder_calls"]
            if calls != response.encoder_calls or calls not in (0, 1):
                raise ValueError("declared/observed encoder calls mismatch or repeated encoding")
            if response.use_dense != (calls == 1):
                raise ValueError("dense decision disagrees with actual encoder calls")
            if response.fallback_reason not in (None, "empty_query"):
                raise ValueError("fallback is not permitted in a valid benchmark run")
            rows.append(
                {
                    "schema_version": "1.0",
                    "run_id": payload["run_id"],
                    "method": payload["method"]["id"],
                    "domain": query.domain,
                    "fold": payload.get("fold"),
                    "split": payload["split"],
                    "query_id": query.query_id,
                    "repetition": payload["repetition"],
                    "use_dense": response.use_dense,
                    "gate_score": response.gate_score,
                    "fallback_reason": response.fallback_reason,
                    "total_ns": total_ns,
                    "process_cpu_ns": cpu_ns,
                    "hits_returned": len(response.ranking.hits),
                    "ranking_hash": object_hash([hit.doc_id for hit in response.ranking.hits]),
                    **measurement,
                }
            )
        else:
            if source_snapshot()["combined_sha256"] != payload["expected_source_hash"]:
                raise ValueError("executable source/config drift during benchmark worker")
            result["status"] = "complete"
            code = 0
    except Exception:
        result["error"] = traceback.format_exc()
    finally:
        result["memory"] = sampler.stop()
        result["completed_requests"] = len(rows)
        result["expected_requests"] = len(payload["queries"])
        result["quality_cache_used"] = False
        write_jsonl(output / "requests.jsonl", rows)
        write_jsonl(output / "memory_samples.jsonl", sampler.samples)
        result["requests_sha256"] = file_hash(output / "requests.jsonl")
        result["memory_samples_sha256"] = file_hash(output / "memory_samples.jsonl")
        atomic_json(output / "worker.json", result)
    return code


if __name__ == "__main__":
    raise SystemExit(execute(sys.argv[1]))
