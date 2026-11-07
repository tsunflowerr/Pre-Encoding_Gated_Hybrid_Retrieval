from __future__ import annotations

import math
import re
from collections import Counter

from contracts.types import FeatureVector, LexicalStats, Query, Ranking
from pegh.data.artifacts import object_hash
from pegh.sparse.tokenizer import TechnicalTokenizer

FEATURE_NAMES = (
    "log_char_count",
    "log_token_count",
    "token_unique_ratio",
    "token_entropy",
    "digit_char_ratio",
    "code_punct_char_ratio",
    "has_error_identifier",
    "has_path_or_flag",
    "identifier_token_ratio",
    "idf_min",
    "idf_mean",
    "idf_std",
    "oov_ratio",
    "hit_count_ratio",
    "bm25_top1",
    "bm25_gap12",
    "bm25_rel_gap12",
    "bm25_rel_gap15",
    "bm25_top10_mean",
    "bm25_top10_std",
    "bm25_flat_indicator",
)

_FORMULAS = (
    "ln(1 + Unicode code-point count of raw query text)",
    "ln(1 + token count from the case-folded A sparse tokenizer)",
    "unique case-folded sparse tokens / token count; 0 if empty",
    "Shannon entropy in nats over case-folded sparse-token frequencies; 0 if empty",
    "Unicode digit characters / max(raw query code-point count, 1)",
    "characters in the configured punctuation set / max(raw query code-point count, 1)",
    "1 if configured error-identifier regex matches raw query text, else 0",
    "1 if configured path-or-flag regex matches raw query text, else 0",
    "raw-case sparse tokens matching the configured identifier regex / token count; 0 if empty",
    "minimum in-vocabulary token IDF from SQLiteBM25.query_stats; 0 if absent",
    "mean in-vocabulary token IDF from SQLiteBM25.query_stats; 0 if absent",
    "population standard deviation of in-vocabulary token IDF from query_stats",
    "OOV sparse-token ratio from SQLiteBM25.query_stats",
    "min(sparse hit count, 100) / 100",
    "first sparse hit score; 0 if empty",
    "s1 - s2; missing s1/s2 scores are 0",
    "(s1 - s2) / (abs(s1) + 1e-8)",
    "(s1 - s5) / (abs(s1) + 1e-8); missing scores are 0",
    "mean scores among existing first 10 sparse hits; 0 if empty",
    "population standard deviation among existing first 10 sparse hit scores; 0 for <=1 hit",
    "1 if at least one of the first 10 hits exists and score range <= configured epsilon",
)


class QueryFeatureExtractor:
    """Deterministic pre-dense features bound to A's sparse tokenizer and stats."""

    def __init__(self, config: dict, tokenizer: TechnicalTokenizer) -> None:
        if config.get("full_schema") != "full_v1_21":
            raise ValueError("unsupported full feature schema")
        if (
            config.get("unicode_character_count") != "code_points"
            or config.get("token_entropy_log_base") != "e"
            or config.get("identifier_token_source") != "sparse_pattern_preserving_raw_case"
        ):
            raise ValueError("unsupported feature recipe")
        if config.get("tokenizer_hash") != tokenizer.fingerprint:
            raise ValueError("feature schema and sparse tokenizer hashes differ")
        indices = config.get("general_indices_one_based")
        if not isinstance(indices, list) or len(indices) != 8 or len(set(indices)) != 8:
            raise ValueError("general feature indices must contain eight unique entries")
        if any(type(index) is not int or not 1 <= index <= len(FEATURE_NAMES) for index in indices):
            raise ValueError("general feature index is outside the full schema")
        self.tokenizer = tokenizer
        self.indices = tuple(indices)
        self.punctuation = frozenset(config["code_punctuation"])
        self.error_pattern = re.compile(config["error_identifier_pattern"])
        self.path_pattern = re.compile(config["path_or_flag_pattern"])
        self.identifier_pattern = re.compile(config["identifier_token_pattern"])
        self.flat_epsilon = float(config["flat_range_epsilon"])
        if not math.isfinite(self.flat_epsilon) or self.flat_epsilon < 0:
            raise ValueError("flat_range_epsilon must be finite and nonnegative")

        self.schema = {
            "schema_version": config["full_schema"],
            "feature_names": list(FEATURE_NAMES),
            "formulas": list(_FORMULAS),
            "tokenizer_hash": tokenizer.fingerprint,
            "unicode_character_count": config["unicode_character_count"],
            "token_entropy_log_base": config["token_entropy_log_base"],
            "identifier_token_source": config["identifier_token_source"],
            "flat_range_epsilon": self.flat_epsilon,
            "code_punctuation": config["code_punctuation"],
            "error_identifier_pattern": config["error_identifier_pattern"],
            "path_or_flag_pattern": config["path_or_flag_pattern"],
            "identifier_token_pattern": config["identifier_token_pattern"],
        }
        self.schema_hash = object_hash(self.schema)
        self.general_schema = {
            "schema_version": "general_v1_8",
            "parent_schema_hash": self.schema_hash,
            "indices_one_based": list(self.indices),
            "feature_names": [FEATURE_NAMES[index - 1] for index in self.indices],
        }
        self.general_schema_hash = object_hash(self.general_schema)
        expected = config.get("schema_hashes", {})
        for key, actual in (("full", self.schema_hash), ("general", self.general_schema_hash)):
            pinned = expected.get(key)
            if pinned not in (None, "pending", actual):
                raise ValueError(f"pinned {key} feature schema hash differs")

    def schema_manifest(self) -> dict:
        return {
            "full": {**self.schema, "schema_hash": self.schema_hash},
            "general": {**self.general_schema, "schema_hash": self.general_schema_hash},
        }

    def transform(self, query: Query, sparse: Ranking, stats: LexicalStats) -> FeatureVector:
        sparse.validate()
        if (query.query_id, query.domain) != (sparse.query_id, sparse.domain):
            raise ValueError("query and sparse ranking identity differs")
        if stats.tokenizer_hash != self.tokenizer.fingerprint:
            raise ValueError("query stats use a different sparse tokenizer")
        tokens = self.tokenizer.tokenize(query.text)
        if len(tokens) != stats.token_count:
            raise ValueError("query stats token count differs from the configured tokenizer")
        if not all(
            math.isfinite(value)
            for value in (stats.idf_min, stats.idf_mean, stats.idf_std, stats.oov_ratio)
        ):
            raise ValueError("query stats contain a non-finite feature")

        token_count = len(tokens)
        counts = Counter(tokens)
        entropy = (
            -sum((count / token_count) * math.log(count / token_count) for count in counts.values())
            if token_count
            else 0.0
        )
        raw_tokens = self.tokenizer.pattern.findall(query.text)
        raw_length = len(query.text)
        hits = sparse.hits
        top10_scores = [hit.score for hit in hits[:10]]
        top10_mean = sum(top10_scores) / len(top10_scores) if top10_scores else 0.0
        s1 = hits[0].score if len(hits) > 0 else 0.0
        s2 = hits[1].score if len(hits) > 1 else 0.0
        s5 = hits[4].score if len(hits) > 4 else 0.0
        denominator = abs(s1) + 1e-8
        values = (
            math.log1p(raw_length),
            math.log1p(token_count),
            len(counts) / token_count if token_count else 0.0,
            entropy,
            sum(character.isdigit() for character in query.text) / max(raw_length, 1),
            sum(character in self.punctuation for character in query.text) / max(raw_length, 1),
            float(bool(self.error_pattern.search(query.text))),
            float(bool(self.path_pattern.search(query.text))),
            sum(bool(self.identifier_pattern.search(token)) for token in raw_tokens)
            / len(raw_tokens)
            if raw_tokens
            else 0.0,
            stats.idf_min,
            stats.idf_mean,
            stats.idf_std,
            stats.oov_ratio,
            min(len(hits), 100) / 100,
            s1,
            s1 - s2,
            (s1 - s2) / denominator,
            (s1 - s5) / denominator,
            top10_mean,
            math.sqrt(sum((score - top10_mean) ** 2 for score in top10_scores) / len(top10_scores))
            if top10_scores
            else 0.0,
            float(
                bool(top10_scores) and max(top10_scores) - min(top10_scores) <= self.flat_epsilon
            ),
        )
        if len(values) != len(FEATURE_NAMES) or not all(math.isfinite(value) for value in values):
            raise ValueError("feature transform produced an invalid vector")
        return FeatureVector(tuple(float(value) for value in values), self.schema_hash)

    def transform_general(
        self, query: Query, sparse: Ranking, stats: LexicalStats
    ) -> FeatureVector:
        full = self.transform(query, sparse, stats)
        return FeatureVector(
            tuple(full.values[index - 1] for index in self.indices), self.general_schema_hash
        )
