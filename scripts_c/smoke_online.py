"""Check C5 empty, sparse skip, and OOV dense paths with real local artifacts."""

from __future__ import annotations

import argparse
import json

from contracts.io import load_queries
from contracts.types import Query
from pegh.app.factories import create_gated_method
from pegh.profiling.trace import TraceSink


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", required=True)
    parser.add_argument("--queries", required=True)
    args = parser.parse_args()
    entry = json.loads(open(args.registry, encoding="utf-8").read())["methods"][0]
    trace = TraceSink(detailed=False)
    method = create_gated_method(trace=trace, **entry["kwargs"])
    try:
        kwargs = entry["kwargs"]
        query = load_queries(args.queries, kwargs["domain"])[0]
        trace.begin_request()
        empty = method.search(Query(query.query_id, query.domain, "  "))
        empty_trace = trace.end_request()
        assert not empty.ranking.hits and empty.fallback_reason == "empty_query"
        assert empty.encoder_calls == 0 and not empty_trace["stage_calls"]

        trace.begin_request()
        skip = method.search(query)
        skip_trace = trace.end_request()
        assert not skip.use_dense and skip.encoder_calls == 0
        assert skip_trace["stage_calls"] == {"sparse": 1, "stats": 1, "features": 1, "gate": 1}
        original = method.sparse.search(query)
        assert skip.ranking == original

        oov = Query(query.query_id, query.domain, "zzzz_c5_oov_8172635409")
        trace.begin_request()
        dense = method.search(oov)
        dense_trace = trace.end_request()
        assert dense.use_dense and dense.encoder_calls == dense_trace["encoder_calls"] == 1
        assert dense_trace["stage_calls"] == {
            "sparse": 1,
            "stats": 1,
            "features": 1,
            "gate": 1,
            "encode": 1,
            "vector": 1,
            "fusion": 1,
        }
        dense.ranking.validate()
        print("C5 smoke passed: empty=0, skip=0, OOV dense=1 encoder call")
    finally:
        method.close()


if __name__ == "__main__":
    main()
