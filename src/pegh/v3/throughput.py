"""Closed-loop throughput: N single-thread server processes share the same pinned cores.

The latency benchmark measures one request at a time; this measures how many queries per
second a fixed CPU budget sustains when CPU time, not wall time, is the bottleneck.
"""

from __future__ import annotations

import importlib
import inspect
import multiprocessing as mp
import os
import random
import time

import psutil


def _serve(
    entry: dict, queries: list[dict], affinity: list[int], barrier, results, seed: int
) -> None:
    os.environ.update(
        {"OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1", "TOKENIZERS_PARALLELISM": "false"}
    )
    psutil.Process().cpu_affinity(affinity)
    import faiss
    import torch

    from contracts.types import Query
    from pegh.profiling.trace import NullTraceSink

    torch.set_num_threads(1)
    faiss.omp_set_num_threads(1)
    module, function = entry["factory"].rsplit(":", 1)
    factory = getattr(importlib.import_module(module), function)
    kwargs = dict(entry["kwargs"])
    parameters = inspect.signature(factory).parameters
    if "torch_threads" in parameters:
        kwargs["torch_threads"] = 1
    if "faiss_threads" in parameters:
        kwargs["faiss_threads"] = 1
    if kwargs.get("parallel_branches"):
        kwargs["parallel_branches"] = False  # one thread per server process
    method = factory(trace=NullTraceSink(), **kwargs)
    stream = [Query(**q) for q in queries]
    random.Random(seed).shuffle(stream)
    for query in stream[:20]:
        method.search(query, k=100)
    barrier.wait()
    cpu, start = time.process_time(), time.perf_counter()
    dense = 0
    for query in stream:
        dense += method.search(query, k=100).encoder_calls
    results.put(
        {
            "seconds": time.perf_counter() - start,
            "cpu": time.process_time() - cpu,
            "queries": len(stream),
            "dense": dense,
        }
    )


def measure(entry: dict, queries: list[dict], *, processes: int, affinity: list[int]) -> dict:
    context = mp.get_context("spawn")
    barrier, results = context.Barrier(processes), context.Queue()
    workers = [
        context.Process(target=_serve, args=(entry, queries, affinity, barrier, results, seed))
        for seed in range(processes)
    ]
    for worker in workers:
        worker.start()
    outputs = [results.get(timeout=3600) for _ in workers]
    for worker in workers:
        worker.join()
        if worker.exitcode:
            raise RuntimeError(f"throughput worker failed with exit code {worker.exitcode}")
    total = sum(o["queries"] for o in outputs)
    wall = max(o["seconds"] for o in outputs)
    return {
        "processes": processes,
        "affinity": affinity,
        "queries": total,
        "wall_seconds": wall,
        "qps": total / wall,
        "cpu_ms_per_query": 1000 * sum(o["cpu"] for o in outputs) / total,
        "dense_ratio": sum(o["dense"] for o in outputs) / total,
    }
