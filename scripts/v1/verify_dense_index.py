"""Check a saved FAISS artifact in a fresh process, without loading a model."""

from __future__ import annotations

import argparse
from pathlib import Path

import faiss
import numpy as np

from pegh.dense.artifacts import atomic_json, checked_child, file_hash
from pegh.dense.index import verify_index


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", required=True)
    parser.add_argument("--expected-count", required=True, type=int)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    directory = Path(args.index)
    output = Path(args.output)
    if output.exists():
        raise FileExistsError("choose a new verification receipt path")
    manifest, ids = verify_index(directory)
    index = faiss.read_index(str(checked_child(directory, manifest["index_file"])))
    if (
        not isinstance(index, faiss.IndexFlatIP)
        or index.d != manifest["config"]["dimension"]
        or index.ntotal != len(ids)
        or index.ntotal != args.expected_count
    ):
        raise ValueError("index type/dimension/count mismatch")
    minimum, maximum = float("inf"), float("-inf")
    for start in range(0, index.ntotal, 512):
        vectors = index.reconstruct_n(start, min(512, index.ntotal - start))
        norms = np.linalg.norm(vectors, axis=1)
        if not np.isfinite(vectors).all() or not np.allclose(norms, 1.0, atol=1e-4):
            raise ValueError("nonfinite or unnormalized saved vectors")
        minimum, maximum = min(minimum, float(norms.min())), max(maximum, float(norms.max()))
    receipt = {
        "status": "passed",
        "index": str(directory.resolve()),
        "index_sha256": manifest["index_sha256"],
        "manifest_sha256": file_hash(directory / "manifest.json"),
        "domain": manifest["domain"],
        "document_count": index.ntotal,
        "dimension": index.d,
        "index_type": type(index).__name__,
        "every_vector_checked": True,
        "norm_min": minimum,
        "norm_max": maximum,
        "raw_vector_bytes": manifest["vector_raw_bytes"],
        "index_file_bytes": (directory / manifest["index_file"]).stat().st_size,
        "quality_evaluated": False,
    }
    atomic_json(output, receipt)
    print(receipt)


if __name__ == "__main__":
    main()
