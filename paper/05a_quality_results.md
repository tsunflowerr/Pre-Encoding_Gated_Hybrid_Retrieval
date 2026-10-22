# Quality results

## Audited baselines available on 22 October 2026

The table is generated from pinned real data and the exact five-fold OOF test-query
partition. Both frozen retrievers are unsupervised; slicing their complete caches by test
fold changes no score, but enforces the accounting contract required of learned systems.

| Method | Programmers nDCG@10 | Unix nDCG@10 | Macro nDCG@10 | Macro MRR@10 | Macro R@100 |
|---|---:|---:|---:|---:|---:|
| BM25 | 0.292620 | 0.287191 | 0.289906 | 0.292611 | 0.547713 |
| Dense MiniLM | 0.248497 | 0.222105 | 0.235301 | 0.229980 | 0.517783 |

Pooled micro nDCG@10 is 0.289633 for BM25 and 0.233973 for dense. No ranking is missing
or empty among the 1,948 queries. Dense minus BM25 macro nDCG@10 is -0.054605. Dense helps
166 of 876 Programmers queries and 131 of 1,072 Unix queries, which leaves useful
query-dependent complementarity despite the lower standalone mean. These counts are
descriptive and must not be used to choose a test-time gate.

The dense indexes were rebuilt locally from the pinned model revision and canonical corpus.
Verifier checks passed for every vector, with dimension 384 and L2 norms within
`[0.99999988, 1.00000012]`. Model/config/corpus/ID-order hashes match B's registered
manifests. FAISS index bytes and ranking hashes differ from B's earlier machine-specific
artifacts, so these are explicitly labeled rebuilt runs rather than byte-identical copies.

The generated `quality-ndcg10.png` and `fold-stability.png` figures compare both baselines.
The deterministic failure audit contains the bottom 20 queries per method and domain (80
rows): 23 code/CLI, 53 natural-language, and 4 short queries under lexical heuristic labels.
These labels are descriptive, not causal diagnoses.

## Results not yet claimable

H*, S*, and PE-GH rows remain absent until their ranking-v1 artifacts and sidecars exist for
both domains and all five folds. No C run is present in the repository as of the audit date.
Therefore H* utility, the S*→PE-GH comparison, its paired confidence interval, and the
paper's primary effectiveness claim cannot be produced without inventing data. The final
strict OOF runner rejects missing metadata, forged provenance, wrong fold membership,
missing sidecars, mixed retrievers, and rankings longer than top-100.
