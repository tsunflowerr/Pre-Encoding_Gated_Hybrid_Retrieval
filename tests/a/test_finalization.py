from __future__ import annotations

import json
from pathlib import Path

import pytest

from contracts import Ranking, SearchHit
from contracts.ranking import ranking_to_record
from pegh.data.artifacts import file_hash, write_jsonl
from pegh.evaluation.failures import outcome, select_cases
from scripts_a.materialize_fold_runs import materialize_fold_runs
from tests.a.test_oof import _fixture


def _full_cache(tmp_path):
    _, registry, split, _ = _fixture(tmp_path, query_count=10)
    domain = "programmers"
    ids = [q for bucket in split["domains"][domain]["buckets"] for q in bucket]
    source = tmp_path / "full.jsonl"
    write_jsonl(
        source,
        [
            ranking_to_record(
                Ranking(
                    q, domain, (SearchHit(q.replace(":q", ":d"), 1.0, 1),), "corpus", "retriever"
                ),
                method="bm25",
                split="development_validation",
                run_id="full",
            )
            for q in ids
        ],
    )
    return (source, Path(registry["split_manifest"]), domain, "bm25", tmp_path / "out", "release")


def test_materializer_reuses_only_exact_files_without_rewriting(tmp_path):
    args = _full_cache(tmp_path)
    assert materialize_fold_runs(*args) == {"written": 5, "reused": 0}
    before = {p.name: (file_hash(p), p.stat().st_mtime_ns) for p in args[4].iterdir()}
    assert materialize_fold_runs(*args, reuse_identical=True) == {"written": 0, "reused": 5}
    assert before == {p.name: (file_hash(p), p.stat().st_mtime_ns) for p in args[4].iterdir()}
    with pytest.raises(FileExistsError):
        materialize_fold_runs(*args)


@pytest.mark.parametrize("corruption", ["ranking", "sidecar", "missing_sidecar"])
def test_materializer_refuses_corruption_before_writing_missing_folds(tmp_path, corruption):
    args = _full_cache(tmp_path)
    materialize_fold_runs(*args)
    # A late conflict must be found before regenerating an earlier missing fold.
    first = args[4] / "fold_0.jsonl"
    first.unlink()
    first.with_suffix(".jsonl.meta.json").unlink()
    last = args[4] / "fold_4.jsonl"
    sidecar = last.with_suffix(".jsonl.meta.json")
    if corruption == "ranking":
        last.write_text(last.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    elif corruption == "sidecar":
        value = json.loads(sidecar.read_text(encoding="utf-8"))
        value["split_hash"] = "forged"
        sidecar.write_text(json.dumps(value), encoding="utf-8")
    else:
        sidecar.unlink()
    with pytest.raises(FileExistsError):
        materialize_fold_runs(*args, reuse_identical=True)
    assert not first.exists()


def test_materializer_resumes_missing_complete_pairs(tmp_path):
    args = _full_cache(tmp_path)
    materialize_fold_runs(*args)
    for path in (args[4] / "fold_2.jsonl", args[4] / "fold_2.jsonl.meta.json"):
        path.unlink()
    assert materialize_fold_runs(*args, reuse_identical=True) == {"written": 1, "reused": 4}


def test_failure_selection_ties_zero_gain_median_and_fixed_seed():
    rows = []
    for i in range(20):
        rows.append(
            {"domain": "unix", "query_id": f"unix:{i:02}", "use_dense": True, "delta_u": i / 20}
        )
    for i in range(20, 40):
        rows.append(
            {
                "domain": "unix",
                "query_id": f"unix:{i:02}",
                "use_dense": False,
                "delta_u": -0.1 if i % 2 else 0.2,
            }
        )
    selected = select_cases(rows)
    assert selected == select_cases(list(reversed(rows)))
    assert outcome(True, 0) == "wasted_dense"
    assert outcome(False, 0) == "safe_skip"
    useful = [r for r in selected if r["category"] == "useful_dense"]
    assert len(useful) == 5
    assert sum(r["selection_reason"] == "median_gain" for r in useful) == 1
    missed = [r for r in selected if r["category"] == "missed_benefit"]
    assert [r["query_id"] for r in missed] == [
        "unix:20",
        "unix:22",
        "unix:24",
        "unix:26",
        "unix:28",
    ]
    with pytest.raises(ValueError, match="duplicate"):
        select_cases([rows[0], rows[0]])
