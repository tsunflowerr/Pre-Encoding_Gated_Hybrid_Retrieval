# Method: pre-encoding gated hybrid retrieval

## Retrieval branches

For query `q`, the sparse backend returns the top-100 BM25 ranking `B(q)` and lexical statistics. If the gate selects the dense branch, a pinned MiniLM query encoder runs once, FAISS returns dense top-100 `D(q)`, and the selected fusion engine constructs `H_f(q) = F_f(B(q), D(q))`. Both branches use the same canonical corpus and document IDs; self-hits are removed and score ties break by document ID. BM25's ranking is reused in fusion, so each request performs at most one sparse search.

The fusion candidates are min–max score combination (CC) for dense weights 0.1–0.9 and RRF with `k=60`. CC normalizes each nonempty branch within its ranking and gives an absent document zero contribution from that branch. On each fold/domain, validation nDCG@10 chooses H* with the registered tie rule. S* is separately selected from BM25, dense-only, and H*. In the present artifacts every H* is CC with dense weight 0.2–0.5, and every S* is H*; these are frozen per fold/domain before test.

## Pre-dense features and learning target

The gate uses 21 deterministic features calculated from the query text, the BM25 tokenizer/IDF statistics, and the initial BM25 ranking. They include length and token-distribution measures, technical punctuation and identifier indicators, in-vocabulary IDF and OOV ratio, hit count, top BM25 score, score gaps, and top-10 score dispersion. The eight-feature general subset supports a smaller-model ablation. All feature positions, formulas, tokenizer hash, and schema hashes are pinned in the [protocol](../configs/gating/protocol_v1.yaml) and materialized [feature manifest](../results/features/schema_v1.json). No feature reads the dense ranking or an encoded query.

For a labeled training query `i`, let `U_B(i)` and `U_H(i)` be BM25 and H* nDCG@10. The primary target is `delta_U(i) = U_H(i) - U_B(i)`. A StandardScaler is fitted on that fold/domain's training rows only; Ridge with `alpha=1` predicts the gain for a new query. We also fit logistic gain, logistic sparse-success, LinearSVC, and an eight-feature Ridge variant under the same split. Each model artifact carries a feature-schema hash, training-ID hash, reference H* selection hash, package versions, and scaler/model checksums. The loader rejects mismatched artifacts or non-finite scores.

## Operating point and request policy

For fold `f`, we pool its two **validation** domains to turn the preregistered desired dense budgets `0, 0.1, ..., 1` into numeric score thresholds. The online decision is strictly `predicted_gain(q) > threshold_f`; score ties skip dense. A nonempty sparse OOV query is forced to dense, including in the measured dense-call ratio. The chosen point minimizes actual validation dense-call ratio subject to at most 0.005 macro nDCG@10 loss and at most 0.01 loss in either domain relative to S*. If no gated point meets both conditions, the protocol uses always-H* and records that fallback rather than calling it a successful gate. In the current experiment the primary Ridge gate has a feasible point in every fold.

```text
nonempty q → BM25 top-100 + lexical stats → 21 features → Ridge score
                                                  ├─ score ≤ threshold → B(q)
                                                  └─ score > threshold → encode once → D(q) → H*(q)
                         full sparse OOV ────────────────────────────────┘
```

Empty or whitespace-only queries return an empty ranking without backend calls. Other model, index, or dense errors fail the benchmark request; they cannot be counted as a valid sparse skip. The production SearchMethod reports `use_dense`, the finite gate score, actual encoder-call count, and a JSON-serializable provenance record. The worker compares those declarations with `TraceSink` counters and records sparse, stats, features, gate, encode, vector, and fusion stages. Model and index loading occur before the timed `search` call.

## Leakage control and analysis contract

Five group-aware folds are fixed before model fitting. For test fold `f`, validation is bucket `(f+1) mod 5` and training is the other three buckets. Fusion selection, feature recipe, scaler, model, and threshold are fixed before opening test qrels. The [C6 freeze manifest](../results/frozen/c6_manifest.json) binds source/config hashes and every primary model, index, and threshold. Offline ranking export reads checksum-verified sparse/dense caches to avoid re-encoding test queries for quality scoring; it does not enter online timing. The final evaluator verifies exactly one test ranking per query, sidecars, corpus/retriever identities, and fold membership. Random 30-seed and oracle exact-budget comparisons are explicitly post-freeze **batch diagnostics**, not online routing policies.

The primary quality test is paired S* versus PE-GH on fixed OOF predictions, with domain-equal macro aggregation and a one-sided group-bootstrap lower bound against margin −0.01. Runtime is evaluated separately with fresh query encoding and isolated workers. The method does not infer latency savings from an offline dense-call ratio.
