from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import asdict, replace
from itertools import zip_longest
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, ValidationError

from contracts import Document, Hit, Query, Ranking, SearchHit
from contracts.ids import canonical_id
from contracts.io import iter_corpus, load_queries
from contracts.model import get_primary_model
from contracts.ranking import dumps_ranking, ranking_from_record, ranking_schema, ranking_to_record
from contracts.text import build_document_text
from pegh.dense.config import DenseConfig
from pegh.dense.corpus import iter_corpus as legacy_corpus

FIXTURE = Path("tests/fixtures/shared")


def example() -> Ranking:
    return Ranking(
        "unix:q01",
        "unix",
        (SearchHit("unix:001", 0.9, 1), SearchHit("unix:002", 0.4, 2)),
        "corpus-example",
        "retriever-example",
    )


def test_same_class_alias_and_lightweight_import():
    assert Hit is SearchHit
    script = "import contracts, contracts.io, contracts.model, contracts.ranking, sys; assert 'torch' not in sys.modules and 'faiss' not in sys.modules"
    subprocess.run([sys.executable, "-c", script], check=True)


@pytest.mark.parametrize("value", ["001", "unix:001"])
def test_canonical_id_preserves_leading_zeroes(value):
    assert canonical_id(value, "unix") == "unix:001"


@pytest.mark.parametrize(
    "value", [1, None, "", " 1", "1 ", "unix:", "programmers:1", "unix:unix:1", "1\n"]
)
def test_reject_ambiguous_ids(value):
    with pytest.raises(ValueError):
        canonical_id(value, "unix")


def test_document_text_exact_and_query_empty_policy():
    document = Document("unix:1", "unix", "  Title  ", "\n\tX = 1\n")
    assert document.text == "  Title  \n\n\tX = 1\n"
    assert build_document_text("", "code\n") == "code\n"
    assert build_document_text("Title", "") == "Title"
    assert Query("unix:empty", "unix", " \n").text == " \n"
    with pytest.raises(ValueError):
        Document("unix:empty", "unix", " ", "\n")
    with pytest.raises(TypeError):
        Document("unix:1", "unix", None, "body")


def test_fixture_20_documents_six_queries_and_v1_parity():
    total_docs = total_queries = 0
    for domain in ("programmers", "unix"):
        source = FIXTURE / domain / "corpus.jsonl"
        for document, old in zip_longest(
            iter_corpus(source, domain), legacy_corpus(source, domain)
        ):
            assert isinstance(document, Document)
            assert (document.doc_id, document.text) == (old.doc_id, old.text)
            total_docs += 1
        total_queries += len(load_queries(FIXTURE / domain / "queries.jsonl", domain))
    assert (total_docs, total_queries) == (20, 6)


def test_native_body_and_beir_aliases_are_explicit(tmp_path):
    path = tmp_path / "input.jsonl"
    path.write_text(
        json.dumps({"doc_id": "unix:01", "_id": "01", "title": "T", "body": "B"}) + "\n",
        encoding="utf-8",
    )
    assert next(iter_corpus(path, "unix")).text == "T\nB"
    path.write_text(
        json.dumps({"_id": "01", "body": "B", "text": "already joined"}), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="aliases disagree"):
        list(iter_corpus(path, "unix"))


@pytest.mark.parametrize(
    "row",
    [
        {"_id": "1", "doc_id": "unix:2", "text": "body"},
        {"_id": "1", "domain": "programmers", "text": "body"},
        {"_id": 1, "text": "body"},
    ],
)
def test_corpus_rejects_conflicting_ids_domains_and_integer_ids(tmp_path, row):
    source = tmp_path / "bad.jsonl"
    source.write_text(json.dumps(row), encoding="utf-8")
    with pytest.raises(ValueError, match="bad.jsonl:1"):
        list(iter_corpus(source, "unix"))


def test_malformed_record_reports_file_and_line(tmp_path):
    source = tmp_path / "bad.jsonl"
    source.write_text('\n{"_id": "bad"\n', encoding="utf-8")
    with pytest.raises(ValueError, match="bad.jsonl:2: malformed JSON"):
        list(iter_corpus(source, "unix"))


def test_iterator_is_lazy_and_detects_duplicate_canonical_ids(tmp_path):
    source = tmp_path / "corpus.jsonl"
    source.write_text(
        '{"_id":"01","text":"first"}\n{"_id":"unix:01","text":"second"}\n', encoding="utf-8"
    )
    iterator = iter_corpus(source, "unix")
    assert next(iterator).body == "first"
    with pytest.raises(ValueError, match="duplicate"):
        next(iterator)


def test_primary_model_matches_frozen_dense_defaults_and_yaml():
    spec = get_primary_model()
    for config in (DenseConfig(), DenseConfig.from_yaml("configs/dense/primary.yaml")):
        assert {key: getattr(config, key) for key in asdict(spec)} == asdict(spec)
    assert spec.revision == "14ca9be4bbcf1402eac0f43a2e2ccb6e0f994ba3"


def test_ranking_roundtrip_and_json_schema():
    ranking = example()
    record = json.loads(dumps_ranking(ranking, method="dense", split="fixture", fold=None))
    schema = ranking_schema()
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(record)
    assert ranking_from_record(record) == ranking
    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate({**record, "unknown": 1})
    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate({**record, "query_id": "unix:q01\n"})


@pytest.mark.parametrize(
    "hits",
    [
        (SearchHit("unix:001", 0.4, 1), SearchHit("unix:002", 0.9, 2)),
        (SearchHit("unix:002", 0.9, 1), SearchHit("unix:001", 0.9, 2)),
        (SearchHit("unix:001", 0.9, 1), SearchHit("unix:001", 0.4, 2)),
        (SearchHit("unix:q01", 0.9, 1),),
        (SearchHit("programmers:1", 0.9, 1),),
        (SearchHit("unix:001", 0.9, 2),),
    ],
)
def test_ranking_semantic_invariants(hits):
    with pytest.raises(ValueError):
        ranking_to_record(replace(example(), hits=hits))


@pytest.mark.parametrize("score", [float("nan"), float("inf"), True, "0.5"])
def test_score_must_be_finite_json_number(score):
    with pytest.raises((ValueError, TypeError)):
        SearchHit("unix:1", score, 1)


def test_empty_ranking_is_valid_but_unknown_version_metadata_are_not():
    empty = replace(example(), hits=())
    assert ranking_from_record(ranking_to_record(empty)) == empty
    with pytest.raises(ValueError, match="version"):
        ranking_from_record({**ranking_to_record(empty), "schema_version": "2.0"})
    with pytest.raises(ValueError):
        ranking_to_record(empty, fold=True)
