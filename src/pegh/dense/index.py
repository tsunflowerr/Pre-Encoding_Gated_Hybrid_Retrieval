from __future__ import annotations

import hashlib
import itertools
import json
import os
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import faiss
import numpy as np
import psutil

from pegh.dense.artifacts import (
    atomic_json,
    canonical_json,
    checked_child,
    file_hash,
    read_json,
    write_jsonl,
)
from pegh.dense.corpus import TEXT_POLICY, iter_corpus
from pegh.dense.encoder import TextEncoder, checked_vectors, implementation_fingerprint


def package_versions() -> dict[str, str]:
    result = {}
    for name in ("numpy", "faiss-cpu", "torch", "sentence-transformers", "transformers"):
        try:
            result[name] = version(name)
        except PackageNotFoundError:
            result[name] = "not-installed"
    return result


@contextmanager
def index_lock(directory: Path, *, recover_stale: bool = False) -> Iterator[None]:
    lock = directory / ".build.lock"
    if lock.exists() and recover_stale:
        owner = read_json(lock)
        if psutil.pid_exists(owner["pid"]):
            raise RuntimeError("build lock belongs to a live PID; refusing recovery")
        lock.unlink()
    try:
        with lock.open("x", encoding="utf-8") as stream:
            json.dump({"pid": os.getpid(), "created_at_unix": time.time()}, stream)
    except FileExistsError as exc:
        raise RuntimeError("index is locked; only recover a confirmed stale lock") from exc
    try:
        yield
    finally:
        lock.unlink(missing_ok=True)


def _verified_chunk(directory: Path, chunk: dict, dimension: int) -> tuple[np.ndarray, list[str]]:
    vectors_path = checked_child(directory, chunk["vectors"])
    ids_path = checked_child(directory, chunk["ids"])
    if file_hash(vectors_path) != chunk["vectors_sha256"]:
        raise ValueError("embedding checkpoint checksum mismatch")
    if file_hash(ids_path) != chunk["ids_sha256"]:
        raise ValueError("ID checkpoint checksum mismatch")
    vectors = checked_vectors(np.load(vectors_path, allow_pickle=False), chunk["count"], dimension)
    with ids_path.open(encoding="utf-8") as stream:
        ids = [json.loads(line)["doc_id"] for line in stream]
    if len(ids) != chunk["count"]:
        raise ValueError("checkpoint ID count mismatch")
    return vectors, ids


def build_index(
    corpus_path: str | Path,
    output: str | Path,
    domain: str,
    encoder: TextEncoder,
    *,
    expected_count: int | None = None,
    resume: bool = False,
    recover_stale_lock: bool = False,
    stop_file: str | Path | None = None,
    max_new_chunks: int | None = None,
    progress: Callable[[dict], None] | None = None,
) -> dict:
    """Stream corpus chunks, checkpoint atomically and reconstruct on resume.

    Complete chunks are never encoded again. Partial/failed chunks are not included
    in the manifest. No deletion or overwrite of an incompatible artifact is allowed.
    """
    source, directory = Path(corpus_path), Path(output)
    directory.mkdir(parents=True, exist_ok=True)
    manifest_path = directory / "manifest.json"
    config = encoder.config
    implementation_hash = implementation_fingerprint(encoder)
    source_hash = file_hash(source)
    with index_lock(directory, recover_stale=recover_stale_lock):
        if manifest_path.exists():
            if not resume:
                raise FileExistsError("index exists; use --resume or a new output directory")
            manifest = read_json(manifest_path)
            if (
                manifest["corpus_sha256"] != source_hash
                or manifest["build_config_hash"] != config.fingerprint
                or manifest["domain"] != domain
                or manifest["text_policy"] != TEXT_POLICY
            ):
                raise ValueError("resume source/config/domain/text-policy mismatch")
            if manifest["package_versions"] != package_versions():
                raise ValueError("resume package versions differ from the original build")
            if manifest["encoder_implementation_hash"] != implementation_hash:
                raise ValueError("resume encoder/preprocessing implementation mismatch")
            if manifest["status"] == "complete":
                verify_index(directory)
                if expected_count is not None and manifest["ntotal"] != expected_count:
                    raise ValueError("expected corpus count mismatch")
                return manifest
        else:
            manifest = {
                "schema_version": "1.0",
                "status": "building",
                "domain": domain,
                "corpus_sha256": source_hash,
                "text_policy": TEXT_POLICY,
                "config": asdict(config),
                "build_config_hash": config.fingerprint,
                "embedding_fingerprint": config.embedding_fingerprint,
                "encoder_implementation_hash": implementation_hash,
                "index_type": "IndexFlatIP",
                "chunks": [],
                "ntotal": 0,
                "truncated_documents": 0,
                "total_untruncated_tokens": 0,
                "package_versions": package_versions(),
                "sessions": [],
            }
            atomic_json(manifest_path, manifest)
        faiss.omp_set_num_threads(config.faiss_threads)
        index = faiss.IndexFlatIP(config.dimension)
        iterator = iter_corpus(source, domain)
        ordering = hashlib.sha256()
        started = time.perf_counter()
        cpu_started = time.process_time()
        new_chunks = 0
        process = psutil.Process()
        sampled_peak = process.memory_info().rss
        chunk_number = 0
        complete_input = False
        try:
            while True:
                records = list(itertools.islice(iterator, config.checkpoint_documents))
                if not records:
                    complete_input = True
                    break
                ids = [record.doc_id for record in records]
                for doc_id in ids:
                    ordering.update((canonical_json({"doc_id": doc_id}) + "\n").encode())
                if chunk_number < len(manifest["chunks"]):
                    previous = manifest["chunks"][chunk_number]
                    if previous["start_row"] != index.ntotal:
                        raise ValueError("checkpoint row offset mismatch")
                    vectors, saved_ids = _verified_chunk(directory, previous, config.dimension)
                    if ids != saved_ids:
                        raise ValueError("resume document ordering mismatch")
                    index.add(vectors)
                    chunk_number += 1
                    continue
                if (stop_file is not None and Path(stop_file).exists()) or (
                    max_new_chunks is not None and new_chunks >= max_new_chunks
                ):
                    break
                blocks = []
                lengths: list[int] = []
                for start in range(0, len(records), config.batch_size):
                    texts = [record.text for record in records[start : start + config.batch_size]]
                    lengths.extend(encoder.token_lengths(texts))
                    blocks.append(
                        checked_vectors(encoder.encode(texts), len(texts), config.dimension)
                    )
                    sampled_peak = max(sampled_peak, process.memory_info().rss)
                vectors = np.concatenate(blocks, axis=0)
                chunk_directory = directory / "chunks"
                chunk_directory.mkdir(exist_ok=True)
                vector_name = f"chunks/{chunk_number:06d}.npy"
                ids_name = f"chunks/{chunk_number:06d}.jsonl"
                vector_path = directory / vector_name
                temporary = vector_path.with_suffix(".npy.tmp")
                with temporary.open("wb") as stream:
                    np.save(stream, vectors, allow_pickle=False)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, vector_path)
                write_jsonl(directory / ids_name, ({"doc_id": doc_id} for doc_id in ids))
                chunk = {
                    "start_row": int(index.ntotal),
                    "count": len(ids),
                    "vectors": vector_name,
                    "ids": ids_name,
                    "vectors_sha256": file_hash(vector_path),
                    "ids_sha256": file_hash(directory / ids_name),
                }
                index.add(vectors)
                manifest["chunks"].append(chunk)
                manifest["ntotal"] = int(index.ntotal)
                manifest["truncated_documents"] += sum(n > config.max_length for n in lengths)
                manifest["total_untruncated_tokens"] += sum(lengths)
                atomic_json(manifest_path, manifest)
                new_chunks += 1
                chunk_number += 1
                if progress is not None:
                    progress(
                        {
                            "domain": domain,
                            "documents": index.ntotal,
                            "new_chunks": new_chunks,
                            "elapsed_seconds": time.perf_counter() - started,
                        }
                    )
            if complete_input and chunk_number != len(manifest["chunks"]):
                raise ValueError("checkpoint includes documents beyond the current source")
            if complete_input and expected_count is not None and index.ntotal != expected_count:
                raise ValueError(f"expected {expected_count} documents, found {index.ntotal}")
            if file_hash(source) != source_hash:
                raise ValueError("corpus changed during indexing")
            if implementation_fingerprint(encoder) != implementation_hash:
                raise ValueError("encoder/preprocessing source changed during indexing")
            if complete_input:
                if index.ntotal == 0:
                    raise ValueError("cannot complete an empty index")
                temporary_index = directory / "index.faiss.tmp"
                faiss.write_index(index, str(temporary_index))
                os.replace(temporary_index, directory / "index.faiss")

                def all_ids() -> Iterator[dict]:
                    for chunk in manifest["chunks"]:
                        with (directory / chunk["ids"]).open(encoding="utf-8") as stream:
                            for line in stream:
                                yield json.loads(line)

                write_jsonl(directory / "doc_ids.jsonl", all_ids())
                manifest.update(
                    {
                        "status": "complete",
                        "index_file": "index.faiss",
                        "ids_file": "doc_ids.jsonl",
                        "index_sha256": file_hash(directory / "index.faiss"),
                        "ids_sha256": file_hash(directory / "doc_ids.jsonl"),
                        "doc_ordering_sha256": ordering.hexdigest(),
                        "vector_raw_bytes": int(index.ntotal) * config.dimension * 4,
                    }
                )
        finally:
            manifest["sessions"].append(
                {
                    "wall_seconds": time.perf_counter() - started,
                    "process_cpu_seconds": time.process_time() - cpu_started,
                    "new_chunks": new_chunks,
                    "sampled_peak_rss_bytes": sampled_peak,
                    "os_peak_rss_bytes": getattr(process.memory_info(), "peak_wset", None),
                }
            )
            atomic_json(manifest_path, manifest)
        return manifest


def verify_index(directory: str | Path) -> tuple[dict, list[str]]:
    directory = Path(directory)
    manifest = read_json(directory / "manifest.json")
    if manifest["status"] != "complete":
        raise ValueError("index is incomplete; resume the build before search")
    index_path = checked_child(directory, manifest["index_file"])
    ids_path = checked_child(directory, manifest["ids_file"])
    if (
        file_hash(index_path) != manifest["index_sha256"]
        or file_hash(ids_path) != manifest["ids_sha256"]
    ):
        raise ValueError("index or mapping checksum mismatch")
    with ids_path.open(encoding="utf-8") as stream:
        ids = [json.loads(line)["doc_id"] for line in stream]
    if len(ids) != manifest["ntotal"] or len(ids) != len(set(ids)):
        raise ValueError("invalid index/mapping counts or duplicate IDs")
    if any(not doc_id.startswith(manifest["domain"] + ":") for doc_id in ids):
        raise ValueError("mapping document domain mismatch")
    return manifest, ids
