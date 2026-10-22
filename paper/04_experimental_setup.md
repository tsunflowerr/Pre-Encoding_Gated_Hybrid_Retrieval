# Experimental setup

## Data and splits

We use the `programmers` and `unix` domains of CQADupStack. Corpus and query data are
pinned to `BeIR/cqadupstack` revision
`e84b7220ce5a4e6c49aeb568983b0ec5a7584c2c`; qrels are pinned to
`BeIR/cqadupstack-qrels` revision
`13595a9f221256a9a21e91c8b0fed3563382b6a7`. The canonical inputs contain 32,176
documents, 876 queries and 1,675 qrel pairs for Programmers, and 47,382 documents,
1,072 queries and 1,693 qrel pairs for Unix. Source and canonical SHA-256 checksums are
recorded in the generated manifests. The registered dataset license is CC BY-SA 4.0.

Queries are grouped by normalized text and shared positive qrels before deterministic
five-fold allocation with seed 42. The Programmers test buckets contain
176/175/175/175/175 queries and the Unix buckets contain 215/215/214/214/214 queries.
For fold `f`, bucket `f` is test, bucket `(f+1) mod 5` is validation, and the remaining
three buckets are training data. Every query contributes exactly one out-of-fold test
prediction.

## Sparse retrieval

The sparse baseline uses a frozen technical tokenizer and BM25 with `k1=1.2`, `b=0.75`,
and IDF `log(1 + (N-df+0.5)/(df+0.5))`. Exact self-hits are removed; ties are ordered by
ascending canonical document ID. The reference SQLite implementation was checked against
BM25S 0.3.14 configured with ATIRE term-frequency saturation and Lucene IDF while sharing
the exact token lists.

Across all 1,948 real queries the two implementations produced identical top-100 sets.
They produced identical order for 876/876 Programmers queries and 1,068/1,072 Unix
queries; the four Unix order differences were float32 ties. Maximum absolute score error
was below `7.8e-6`.

## Evaluation

The primary metric is nDCG@10; secondary metrics are MRR@10, Recall@10 and Recall@100.
IDCG uses all positive qrels for a query. Missing rankings remain in the denominator with
score zero. We report each domain, equal-weight macro across the two domains, pooled micro,
and fold-level results. The local evaluator matched `ir-measures` 0.4.3 on every aggregate
metric, with maximum absolute difference `2.3e-16`.

The final comparison uses paired query differences and group-aware bootstrap resampling
with seed 20261019. Groups are sampled within each domain before equal-weight macro
aggregation. These confidence intervals describe fixed out-of-fold predictions and do not
include uncertainty from retraining or model selection.
