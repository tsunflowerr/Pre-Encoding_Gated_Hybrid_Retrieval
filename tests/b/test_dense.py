from __future__ import annotations

import json
from dataclasses import replace

import faiss
import numpy as np
import pytest

from contracts.types import Query
from pegh.dense.artifacts import read_json
from pegh.dense.corpus import iter_corpus, load_queries
from pegh.dense.encoder import checked_vectors
from pegh.dense.index import build_index, verify_index
from pegh.dense.retriever import FaissDenseRetriever
from pegh.profiling.trace import TraceSink
from tests.b.fakes import DeterministicEncoder


def test_faiss_matches_numpy_and_self_filter(built_index):
    encoder = DeterministicEncoder()
    retriever = FaissDenseRetriever(built_index, encoder)
    vectors = retriever.index.reconstruct_n(0, retriever.index.ntotal)
    for qid, text in [("unix:q1", "another topic"), ("unix:d03", "Topic 3\nTechnical body 3.")]:
        query = Query(qid, "unix", text)
        vector = encoder.encode([text])
        scores = (vectors @ vector[0]).tolist()
        expected = sorted(
            [
                (doc_id, score)
                for doc_id, score in zip(retriever.doc_ids, scores, strict=True)
                if doc_id != qid
            ],
            key=lambda item: (-item[1], item[0]),
        )[:5]
        before = encoder.encode_calls
        result = retriever.search(query, k=5)
        assert encoder.encode_calls == before + 1
        assert [hit.doc_id for hit in result.hits] == [item[0] for item in expected]
        np.testing.assert_allclose(
            [hit.score for hit in result.hits], [e[1] for e in expected], atol=1e-6
        )


def test_exact_ties_are_deterministic_beyond_initial_k(tmp_path):
    source = tmp_path / "ties.jsonl"
    source.write_text(
        "".join(
            json.dumps({"_id": str(i), "title": "same", "text": "text"}) + "\n"
            for i in range(15, 0, -1)
        ),
        encoding="utf-8",
    )
    encoder = DeterministicEncoder()
    directory = tmp_path / "index"
    build_index(source, directory, "unix", encoder)
    retriever = FaissDenseRetriever(directory, encoder)
    result = retriever.search(Query("unix:q", "unix", "same\ntext"), k=3)
    assert [hit.doc_id for hit in result.hits] == ["unix:1", "unix:10", "unix:11"]
    assert retriever.vector_search_calls > 1


def test_search_k_larger_than_corpus_and_empty_query(built_index):
    encoder = DeterministicEncoder()
    retriever = FaissDenseRetriever(built_index, encoder)
    assert len(retriever.search(Query("unix:d00", "unix", "topic"), k=100).hits) == 12
    before = encoder.encode_calls
    assert retriever.search(Query("unix:empty", "unix", " \n ")).hits == ()
    assert encoder.encode_calls == before


def test_repeated_query_text_is_encoded_again_and_vector_reuse_is_explicit(built_index):
    encoder = DeterministicEncoder()
    retriever = FaissDenseRetriever(built_index, encoder)
    query = Query("unix:q", "unix", "same query text")
    retriever.search(query)
    retriever.search(query)
    assert encoder.encode_calls == 2
    vector = retriever.encode_query(query)
    retriever.search_vector(query, vector)
    assert encoder.encode_calls == 3


def test_resume_avoids_reencoding_completed_chunks(corpus, tmp_path):
    encoder = DeterministicEncoder()
    directory = tmp_path / "resume"
    partial = build_index(corpus, directory, "unix", encoder, max_new_chunks=1)
    assert partial["status"] == "building" and partial["ntotal"] == 4
    with pytest.raises(ValueError, match="incomplete"):
        FaissDenseRetriever(directory, encoder)
    resumed = DeterministicEncoder()
    complete = build_index(corpus, directory, "unix", resumed, resume=True, expected_count=13)
    assert complete["status"] == "complete"
    assert len(resumed.encoded_texts) == 9
    assert not any("body 0." in text for text in resumed.encoded_texts)
    other = tmp_path / "fresh"
    build_index(corpus, other, "unix", DeterministicEncoder())
    first = FaissDenseRetriever(directory, resumed)
    second = FaissDenseRetriever(other, DeterministicEncoder())
    assert first.search(Query("unix:q", "unix", "topic")) == second.search(
        Query("unix:q", "unix", "topic")
    )


def test_completed_resume_verifies_but_does_not_encode(corpus, built_index):
    encoder = DeterministicEncoder()
    build_index(corpus, built_index, "unix", encoder, resume=True, expected_count=13)
    assert encoder.encode_calls == 0


def test_resume_rejects_changed_source_and_config(corpus, tmp_path):
    output = tmp_path / "index"
    encoder = DeterministicEncoder()
    build_index(corpus, output, "unix", encoder, max_new_chunks=1)
    changed = DeterministicEncoder(replace(encoder.config, revision="different"))
    with pytest.raises(ValueError, match="resume"):
        build_index(corpus, output, "unix", changed, resume=True)
    corpus.write_text(corpus.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="resume"):
        build_index(corpus, output, "unix", encoder, resume=True)


def test_checkpoint_corruption_is_detected(corpus, tmp_path):
    output = tmp_path / "index"
    build_index(corpus, output, "unix", DeterministicEncoder(), max_new_chunks=1)
    with (output / "chunks/000000.npy").open("ab") as stream:
        stream.write(b"corrupted")
    with pytest.raises(ValueError, match="checksum"):
        build_index(corpus, output, "unix", DeterministicEncoder(), resume=True)


def test_mapping_corruption_and_encoder_mismatch(built_index):
    encoder = DeterministicEncoder()
    with pytest.raises(ValueError, match="incompatible"):
        FaissDenseRetriever(
            built_index, DeterministicEncoder(replace(encoder.config, max_length=128))
        )
    with (built_index / "doc_ids.jsonl").open("a", encoding="utf-8") as stream:
        stream.write('{"doc_id":"unix:extra"}\n')
    with pytest.raises(ValueError, match="checksum"):
        verify_index(built_index)


@pytest.mark.parametrize(
    "bad",
    [
        np.array([[0.0, 0.0]], dtype=np.float32),
        np.array([[np.nan, 1.0]], dtype=np.float32),
        np.array([[1.0, 0.0]], dtype=np.float64),
    ],
)
def test_invalid_vectors_are_rejected(bad):
    with pytest.raises(ValueError):
        checked_vectors(bad, 1, 2)


def test_duplicate_documents_and_id_types(tmp_path):
    source = tmp_path / "duplicate.jsonl"
    source.write_text('{"_id":"1","text":"a"}\n{"_id":"1","text":"b"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate"):
        list(iter_corpus(source, "unix"))
    source.write_text('{"_id":1,"text":"a"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="IDs"):
        list(iter_corpus(source, "unix"))


def test_text_boundary_preserves_code_and_namespace(tmp_path):
    source = tmp_path / "corpus.jsonl"
    source.write_text(
        json.dumps({"_id": "007", "title": "C++", "text": "0x123\n/etc/hosts"}) + "\n",
        encoding="utf-8",
    )
    document = list(iter_corpus(source, "unix"))[0]
    assert document.doc_id == "unix:007"
    assert document.text == "C++\n0x123\n/etc/hosts"


def test_query_duplicate_rejected(tmp_path):
    path = tmp_path / "queries.jsonl"
    path.write_text('{"_id":"q","text":"a"}\n{"_id":"q","text":"b"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate"):
        load_queries(path, "unix")


def test_source_change_during_build_is_not_completed(corpus, tmp_path):
    def mutate(_):
        with corpus.open("a", encoding="utf-8") as stream:
            stream.write("\n")

    output = tmp_path / "index"
    with pytest.raises(ValueError, match="changed during"):
        build_index(corpus, output, "unix", DeterministicEncoder(), progress=mutate)
    assert read_json(output / "manifest.json")["status"] == "building"


def test_stop_file_preserves_checkpoint(corpus, tmp_path):
    stop = tmp_path / "STOP"
    stop.touch()
    encoder = DeterministicEncoder()
    output = tmp_path / "index"
    manifest = build_index(corpus, output, "unix", encoder, stop_file=stop)
    assert manifest["status"] == "building" and encoder.encode_calls == 0
    stop.unlink()
    assert build_index(corpus, output, "unix", encoder, resume=True)["status"] == "complete"


def test_trace_counts_real_backend_calls_and_resets(built_index):
    sink = TraceSink(detailed=False)
    retriever = FaissDenseRetriever(built_index, DeterministicEncoder(), trace=sink)
    sink.begin_request()
    retriever.search(Query("unix:q", "unix", "topic"))
    row = sink.end_request()
    assert row["encoder_calls"] == 1 and row["encode_ns"] is None
    sink.begin_request()
    retriever.search(Query("unix:q", "unix", ""))
    row = sink.end_request()
    assert row["encoder_calls"] == 0 and row["encode_ns"] == 0


def test_index_is_exact_inner_product(built_index):
    index = faiss.read_index(str(built_index / "index.faiss"))
    assert isinstance(index, faiss.IndexFlatIP)
    assert index.metric_type == faiss.METRIC_INNER_PRODUCT


def test_wrong_expected_count_does_not_complete(corpus, tmp_path):
    output = tmp_path / "index"
    with pytest.raises(ValueError, match="expected 14"):
        build_index(corpus, output, "unix", DeterministicEncoder(), expected_count=14)
    assert read_json(output / "manifest.json")["status"] == "building"


def test_existing_output_requires_explicit_resume(corpus, built_index):
    with pytest.raises(FileExistsError):
        build_index(corpus, built_index, "unix", DeterministicEncoder())


def test_foreign_output_directory_is_not_overwritten(corpus, tmp_path):
    output = tmp_path / "foreign"
    output.mkdir()
    marker = output / "important.txt"
    marker.write_text("preserve", encoding="utf-8")
    with pytest.raises(FileExistsError, match="nonempty"):
        build_index(corpus, output, "unix", DeterministicEncoder())
    assert marker.read_text(encoding="utf-8") == "preserve"
