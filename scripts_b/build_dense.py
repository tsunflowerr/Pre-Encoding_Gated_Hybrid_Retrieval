"""Build/resume a dense index. All large artifacts stay outside Git."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from pegh.dense.artifacts import atomic_json
from pegh.dense.config import DenseConfig
from pegh.dense.encoder import CPUEncoder
from pegh.dense.index import build_index
from pegh.profiling.provenance import source_snapshot
from pegh.profiling.runtime import RuntimeSettings, configure_resources, runtime_manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="configs/dense/primary.yaml")
    parser.add_argument("--corpus", required=True)
    parser.add_argument("--domain", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--expected-count", type=int)
    parser.add_argument("--cache-folder")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--recover-stale-lock", action="store_true")
    parser.add_argument("--stop-file")
    parser.add_argument("--max-new-chunks", type=int)
    parser.add_argument("--runtime", default="configs/runtime/cpu4.yaml")
    args = parser.parse_args()
    settings = RuntimeSettings.from_yaml(args.runtime)
    resources = configure_resources(settings)
    runtime = runtime_manifest(settings, resources)
    started = time.perf_counter()
    encoder = CPUEncoder(DenseConfig.from_yaml(args.config), cache_folder=args.cache_folder)
    model_load_seconds = time.perf_counter() - started
    manifest = build_index(
        args.corpus,
        args.output,
        args.domain,
        encoder,
        expected_count=args.expected_count,
        resume=args.resume,
        recover_stale_lock=args.recover_stale_lock,
        stop_file=args.stop_file,
        max_new_chunks=args.max_new_chunks,
        progress=lambda row: print(json.dumps(row), flush=True),
    )
    print(json.dumps({"status": manifest["status"], "documents": manifest["ntotal"]}))
    atomic_json(
        Path(args.output) / "build_profile.json",
        {
            "runtime": runtime,
            "source_snapshot": source_snapshot(),
            "latest_model_load_seconds": model_load_seconds,
            "all_indexing_sessions": manifest["sessions"],
            "document_count": manifest["ntotal"],
            "status": manifest["status"],
            "time_scope_note": "session indexing time excludes model load; token audit included",
        },
    )
    return 0 if manifest["status"] == "complete" else 75


if __name__ == "__main__":
    raise SystemExit(main())
