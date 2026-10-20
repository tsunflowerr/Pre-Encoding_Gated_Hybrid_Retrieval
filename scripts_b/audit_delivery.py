"""Audit and collect small artifacts from the registered standalone B validation."""

from __future__ import annotations

import argparse
import json
import shutil
from collections import Counter
from pathlib import Path

from contracts.types import Hit, Ranking
from pegh.dense.artifacts import atomic_json, file_hash, object_hash, read_json
from pegh.dense.corpus import load_queries
from pegh.dense.index import verify_index
from pegh.profiling.report import load_complete_run


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    copies: list[dict] = []
    raw: list[dict] = []
    audits: list[dict] = []
    source_hashes: set[str] = set()

    def catalog(path: Path, *, copied_to: Path | None = None) -> dict:
        result = {
            "original": str(path.resolve()),
            "sha256": file_hash(path),
            "bytes": path.stat().st_size,
        }
        if copied_to is not None:
            result["copy"] = str(copied_to.relative_to(args.output))
        return result

    def collect(source: Path, target: Path) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and file_hash(target) != file_hash(source):
            raise FileExistsError(f"refusing to replace a different delivery artifact: {target}")
        shutil.copyfile(source, target)
        copies.append(catalog(source, copied_to=target))

    for domain, expected_count in (("programmers", 32176), ("unix", 47382)):
        index_dir = args.cache_root / "artifacts/final-v1" / domain
        index_manifest, _ = verify_index(index_dir)
        if index_manifest["ntotal"] != expected_count:
            raise ValueError("unexpected corpus count")
        verification = args.cache_root / "artifacts" / f"verify-{domain}-v1.json"
        checked = read_json(verification)
        if (
            checked["status"] != "passed"
            or not checked["every_vector_checked"]
            or checked["index_sha256"] != index_manifest["index_sha256"]
            or checked["manifest_sha256"] != file_hash(index_dir / "manifest.json")
        ):
            raise ValueError("saved-vector verification receipt is stale or invalid")
        corpus = args.cache_root / "data" / domain / "corpus.jsonl"
        query_path = args.cache_root / "data" / domain / "queries.jsonl"
        if file_hash(corpus) != index_manifest["corpus_sha256"]:
            raise ValueError("canonical corpus no longer matches the index")
        queries = load_queries(query_path, domain)
        quality_path = args.cache_root / "results/quality" / f"{domain}-top100.jsonl"
        meta_path = quality_path.with_suffix(".jsonl.meta.json")
        meta = read_json(meta_path)
        if meta["ranking_sha256"] != file_hash(quality_path) or meta["queries_sha256"] != file_hash(
            query_path
        ):
            raise ValueError("quality output/input checksum mismatch")
        rankings: dict[str, str] = {}
        with quality_path.open(encoding="utf-8") as stream:
            for line in stream:
                record = json.loads(line)
                hits = tuple(Hit(**hit) for hit in record["hits"])
                ranking = Ranking(
                    record["query_id"],
                    domain,
                    hits,
                    record["corpus_hash"],
                    record["retriever_hash"],
                )
                ranking.validate()
                if (
                    ranking.query_id in rankings
                    or len(hits) != 100
                    or any(hit.doc_id == ranking.query_id for hit in hits)
                    or list(hits) != sorted(hits, key=lambda hit: (-hit.score, hit.doc_id))
                    or ranking.corpus_hash != index_manifest["corpus_sha256"]
                    or ranking.retriever_hash != meta["retriever_hash"]
                ):
                    raise ValueError("invalid or incompatible offline ranking")
                rankings[ranking.query_id] = object_hash([hit.doc_id for hit in hits])
        if set(rankings) != {q.query_id for q in queries} or len(rankings) != meta["query_count"]:
            raise ValueError("quality query coverage mismatch")
        collect(meta_path, args.output / "quality" / meta_path.name)
        raw.extend(
            catalog(p) for p in (corpus, query_path, quality_path, index_dir / "index.faiss")
        )
        for kind, count, repeats in (("main", len(queries), 5), ("stages", 128, 1)):
            run = args.cache_root / "results/online" / f"{domain}-{kind}-v1"
            manifest, rows, receipts = load_complete_run(run)
            if manifest["query_count"] != count or manifest["settings"]["repetitions"] != repeats:
                raise ValueError("protocol query/repetition count mismatch")
            expected_ids = {q.query_id for q in (queries if kind == "main" else queries[:128])}
            if {r["query_id"] for r in rows} != expected_ids:
                raise ValueError("measured IDs differ from the registered input set")
            for row in rows:
                if (
                    row["encoder_calls"] != 1
                    or row["vector_search_calls"] < 1
                    or row["hits_returned"] != 100
                    or not row["use_dense"]
                    or row["fallback_reason"] is not None
                    or row["ranking_hash"] != rankings[row["query_id"]]
                ):
                    raise ValueError("online counters/ranking differ from the offline backend")
            for receipt in receipts:
                runtime = receipt["runtime"]
                if (
                    receipt["quality_cache_used"]
                    or receipt["warmup_encoder_calls"] != 50
                    or runtime["resources"]["effective_affinity"] != [0, 2, 4, 6]
                    or runtime["resources"]["memory_limit_kind"]
                    != "windows_job_process_commit_limit"
                    or runtime["resources"]["memory_limit_bytes"] != 8_000_000_000
                    or runtime["backend_threads_after_factory"] != {"torch": 4, "faiss": 4}
                    or receipt["method_provenance"]["retriever_hash"] != meta["retriever_hash"]
                ):
                    raise ValueError(
                        "runtime/caching/model provenance differs from the local protocol"
                    )
                source_hashes.add(receipt["source_hash"])
            for name in ("manifest.json", "summary.json", "summary.csv", "REPORT.md"):
                collect(run / name, args.output / "online" / run.name / name)
            for figure in sorted(run.glob("*.png")):
                collect(figure, args.output / "online" / run.name / figure.name)
            for worker in manifest["workers"]:
                source = run / worker["directory"]
                collect(
                    source / "worker.json",
                    args.output / "online" / run.name / f"{worker['directory']}.worker.json",
                )
                raw.extend(
                    catalog(source / name) for name in ("requests.jsonl", "memory_samples.jsonl")
                )
            audits.append(
                {
                    "run_id": run.name,
                    "status": "passed",
                    "unique_queries": count,
                    "requests": len(rows),
                    "encoder_calls": sum(r["encoder_calls"] for r in rows),
                    "vector_search_call_counts": dict(
                        Counter(r["vector_search_calls"] for r in rows)
                    ),
                    "every_ranking_matches_offline": True,
                }
            )
    if len(source_hashes) != 1:
        raise ValueError("executable source differs between registered validation runs")
    atomic_json(
        args.output / "FINAL_AUDIT.json",
        {
            "status": "passed",
            "protocol": "standalone B local Windows physical4 development validation v1",
            "runs": audits,
            "measured_requests": sum(r["requests"] for r in audits),
            "shared_executable_source_hash": next(iter(source_hashes)),
            "quality_scores_evaluated": False,
            "copies": copies,
            "large_artifacts_kept_outside_git": raw,
        },
    )
    print(
        f"Passed full audit of {sum(r['requests'] for r in audits)} requests and 1948 offline rankings"
    )


if __name__ == "__main__":
    main()
