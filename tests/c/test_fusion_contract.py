"""Small independent fixtures for registered C1 fusion and selection rules."""

import pytest

from contracts.types import Ranking, SearchHit
from pegh.fusion.engines import fuse_cc, fuse_rrf
from scripts_c.select_fusion import _choose


def _ranking(scores: list[tuple[str, float]], retriever: str) -> Ranking:
    return Ranking(
        "programmers:q",
        "programmers",
        tuple(
            SearchHit(f"programmers:{doc}", score, rank)
            for rank, (doc, score) in enumerate(scores, 1)
        ),
        "corpus-fixture",
        retriever,
    )


def test_cc_and_rrf_handle_missing_hits_and_deterministic_ties() -> None:
    sparse = _ranking([("a", 10.0), ("b", 5.0)], "sparse-fixture")
    dense = _ranking([("b", 2.0), ("c", 1.0)], "dense-fixture")

    cc = fuse_cc(sparse, dense, alpha_dense=0.5)
    assert [(hit.doc_id, hit.score) for hit in cc.hits] == [
        ("programmers:a", 0.5),
        ("programmers:b", 0.5),
        ("programmers:c", 0.0),
    ]
    assert [hit.doc_id for hit in fuse_cc(sparse, dense, alpha_dense=0).hits] == [
        "programmers:a",
        "programmers:b",
    ]
    assert [hit.doc_id for hit in fuse_cc(sparse, dense, alpha_dense=1).hits] == [
        "programmers:b",
        "programmers:c",
    ]

    rrf = fuse_rrf(sparse, dense)
    assert [hit.doc_id for hit in rrf.hits] == ["programmers:b", "programmers:a", "programmers:c"]
    assert rrf.hits[0].score == pytest.approx(1 / 62 + 1 / 61)
    assert rrf.hits[1].score == pytest.approx(1 / 61)
    assert rrf.hits[2].score == pytest.approx(1 / 62)


def test_cc_empty_and_flat_branch_and_registered_selection_ties() -> None:
    empty = _ranking([], "sparse-fixture")
    flat = _ranking([("a", 3.0), ("b", 3.0)], "dense-fixture")
    cc = fuse_cc(empty, flat, alpha_dense=0.4)
    assert [(hit.doc_id, hit.score) for hit in cc.hits] == [
        ("programmers:a", 0.4),
        ("programmers:b", 0.4),
    ]

    scores = {
        "cc_0.2": {"ndcg_at_10": 0.5},
        "cc_0.3": {"ndcg_at_10": 0.5000004},
        "rrf": {"ndcg_at_10": 0.4999998},
    }
    names = ["cc_0.2", "cc_0.3", "rrf"]
    assert _choose(scores, names, 1e-6, preferred=["rrf"])[0] == "rrf"
    assert _choose(scores, names, 1e-6)[0] == "cc_0.2"
    assert _choose(scores, names, 0)[0] == "cc_0.3"
