"""Audit the two public BEIR query sets; this does not benchmark retrieval.

Uses Python's standard library. Pinned qrels are downloaded from Hugging Face.
Query text comes from the dataset-viewer rows API; the API view is not asserted
to be a cryptographically pinned decode of the Parquet files. Saved JSONL hashes
allow comparison with the snapshot recorded in source_audit.json.

Usage: python research_evidence/audit_queries.py --output research_evidence/latest
"""
from __future__ import annotations

import argparse
import collections
import concurrent.futures
import csv
import hashlib
import io
import json
import pathlib
import re
import urllib.parse
import urllib.request

DATASET_REVISION = "e84b7220ce5a4e6c49aeb568983b0ec5a7584c2c"
QRELS_REVISION = "13595a9f221256a9a21e91c8b0fed3563382b6a7"
EXPECTED = {"programmers": 876, "unix": 1072}
STRICT = (
    r"0x[0-9a-fA-F]+|\b[A-Za-z_$][\w.$]*(?:Exception|Error)\b|"
    r"\bHTTP\s+[45]\d{2}\b|"
    r"\b(?:EACCES|ENOENT|ECONNREFUSED|ETIMEDOUT|ERESOLVE|EADDRINUSE|ENOSPC|EPIPE)\b"
)
BROAD = r"\b(error|failed|failure|denied|cannot|unable|not found)\b"


def fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "PE-GH-query-audit/2.0"})
    with urllib.request.urlopen(request, timeout=45) as response:
        return response.read()


def get_page(task: tuple[str, int]) -> tuple[str, list[dict]]:
    domain, offset = task
    params = urllib.parse.urlencode({
        "dataset": "BeIR/cqadupstack", "config": domain,
        "split": "queries", "offset": offset, "length": 100,
    })
    payload = json.loads(fetch("https://datasets-server.huggingface.co/rows?" + params))
    return domain, [item["row"] for item in payload["rows"]]


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=pathlib.Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    target = args.output / "query_audit.json"
    if target.exists():
        raise SystemExit("Output already has query_audit.json; choose a new directory.")

    rows: dict[str, list[dict]] = collections.defaultdict(list)
    tasks = [(d, start) for d, n in EXPECTED.items() for start in range(0, n, 100)]
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        for domain, page in pool.map(get_page, tasks):
            rows[domain].extend(page)

    audit = {
        "kind": "query_and_qrels_audit_not_retrieval_benchmark",
        "dataset_revision_recorded": DATASET_REVISION,
        "qrels_revision_pinned": QRELS_REVISION,
        "query_transport": "HF dataset-viewer rows API, current view",
        "strict_regex_case_sensitive": STRICT,
        "broad_regex_case_insensitive": BROAD,
        "domains": {},
    }
    for domain, expected in EXPECTED.items():
        records = rows[domain]
        if len(records) != expected or len({r["_id"] for r in records}) != expected:
            raise ValueError(f"Unexpected query count/duplicate IDs in {domain}")
        query_bytes = "".join(
            json.dumps(r, ensure_ascii=False) + "\n" for r in records
        ).encode("utf-8")
        (args.output / f"{domain}-queries.jsonl").write_bytes(query_bytes)
        qrels_url = (
            "https://huggingface.co/datasets/BeIR/cqadupstack-qrels/resolve/"
            + QRELS_REVISION + "/" + domain + "/test.tsv"
        )
        qrels_bytes = fetch(qrels_url)
        (args.output / f"{domain}-qrels.tsv").write_bytes(qrels_bytes)
        qrels = list(csv.DictReader(io.StringIO(qrels_bytes.decode("utf-8")), delimiter="\t"))
        texts = [r["text"] for r in records]
        matches = [r for r in records if re.search(STRICT, r["text"])]
        audit["domains"][domain] = {
            "queries": len(records),
            "qrels_rows": len(qrels),
            "positive_qrels": sum(float(r["score"]) > 0 for r in qrels),
            "qrel_query_ids": len({r["query-id"] for r in qrels}),
            "qrel_unique_doc_ids": len({r["corpus-id"] for r in qrels}),
            "mean_query_chars": sum(map(len, texts)) / len(texts),
            "max_query_chars": max(map(len, texts)),
            "multiline_queries": sum("\n" in text for text in texts),
            "all_query_titles_empty": all(not r["title"] for r in records),
            "strict_identifier_regex_matches": len(matches),
            "broad_error_word_matches": sum(bool(re.search(BROAD, t, re.I)) for t in texts),
            "strict_examples": matches,
            "queries_jsonl_sha256": sha256(query_bytes),
            "qrels_tsv_sha256": sha256(qrels_bytes),
        }
    target.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(audit, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
