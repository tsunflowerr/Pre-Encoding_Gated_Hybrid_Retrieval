"""Compile static BM25 postings for exact in-memory execution."""

from __future__ import annotations

import argparse
from pathlib import Path

from pegh.sparse.fast import FORMAT, compile_index


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", required=True)
    parser.add_argument("--output")
    args = parser.parse_args()
    output = Path(args.output) if args.output else Path(args.index) / FORMAT
    manifest = compile_index(args.index, output)
    print(
        f"Compiled {manifest['document_count']} documents / {manifest['posting_count']} postings: {output}"
    )


if __name__ == "__main__":
    main()
