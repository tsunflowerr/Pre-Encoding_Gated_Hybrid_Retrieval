"""Build a persistent exact BM25 index for one canonical corpus."""

from __future__ import annotations

import argparse
import json

from pegh.sparse.config import BM25Config
from pegh.sparse.index import build_index


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="configs/sparse/bm25.yaml")
    parser.add_argument("--corpus", required=True)
    parser.add_argument("--domain", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    manifest = build_index(args.corpus, args.output, args.domain, BM25Config.from_yaml(args.config))
    print(json.dumps({"documents": manifest["document_count"], "output": args.output}))


if __name__ == "__main__":
    main()
