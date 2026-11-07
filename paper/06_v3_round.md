# Second round: re-scoring tiers and a preregistered confirmation

The first round left two open questions. At matched dense budgets, the Ridge gate was not distinguishable from a BM25-margin rule or a LiteGator-style SVM, and its test split had been observed during development. The second round therefore (i) tried new pre-encoding signals, (ii) redesigned what the cheap and the expensive routes compute, and (iii) confirmed the resulting claims on four CQADupStack domains that no earlier step had touched. Full receipts: [v3 report](../docs/v3/README.md).

## Design

**Static semantic proxy.** Every WordPiece of the pinned encoder's vocabulary is encoded once, alone (`[CLS] t [SEP]`), giving a static token table (as in Model2Vec-style distillation). A query proxy is the SIF-weighted mean of its token vectors, with weights `a/(a+p(t))` estimated from the domain corpus. Computing it needs only the tokenizer and a table lookup. On fold-0 training queries its cosine with the stored document vectors of the BM25 top-100 correlates with the real dense cosine at Pearson 0.64–0.70 (no relevance labels involved).

**Two re-scoring tiers on the BM25 top-100.** P\* fuses BM25 with the proxy cosine (CC, alpha in 0.1–0.9 or plain BM25). R\* encodes the query once and fuses BM25 with the true query–document cosine of the same candidates, with no vector-index search. Both alphas are chosen on validation per fold and domain with the v1 tie rules. A cascade gate chooses P\* or R\*.

**Additional gate features.** Seven BM25 query-performance predictors (NQC, WIG, SMV, score ratios, IDF max/sum) and nine proxy features were tested as additions to the 21 v1 features.

## Development (programmers/unix; exploratory)

A reimplementation of the v1 protocol for arbitrary domain sets reproduces every published v1 number exactly (PE-GH 0.312163 macro nDCG@10 with 1,125 dense calls; all controls identical), and recomputed v1 features match the frozen ones with zero error. Selection used validation rows only. Neither QPP nor proxy features improved the gate's validation quality–budget area (0.3088 and 0.3069 versus 0.3086), so the cascade kept the v1 Ridge gate. As tiers, however, P\* raised BM25 from 0.2899 to 0.3001 and R\* reached 0.3174 versus 0.3146 for the FAISS hybrid H\*. Because this test split was observed in round one, these numbers only motivated the confirmation protocol.

## Preregistered confirmation (android, gis, mathematica, webmasters)

The protocol (hypotheses, selection rules, Holm correction) was hashed and recorded before any feature, tier or label of the new domains was computed. Over 2,894 queries and 95,693 documents:

| Hypothesis | Estimate | 95% CI | Result |
|---|---:|---|---|
| H1 R\* non-inferior to H\* (margin 0.01) | −0.0006 | [−0.0039, 0.0028] | supported |
| H2 P\* superior to BM25 | +0.0063 | [0.0029, 0.0096] | supported |
| H3 PE-GH v1 non-inferior to S\* | −0.0023 | [−0.0051, 0.0004] | supported |
| H4 v1 gate beats random at matched budget | −0.0001 | [−0.0023, 0.0021] | not supported |
| H5 cascade gate beats random at matched budget | −0.0003 | [−0.0015, 0.0010] | not supported |

The learned gates carry no measurable signal on unseen domains (v1 Ridge AUC for positive gain 0.503, Spearman 0.007). Their quality–budget curves track 30-seed random routing, and the validation-selected v1 operating point routes 81% of queries to dense instead of 57.75%. The architectural findings replicate: re-scoring BM25 candidates with the query vector matches the full FAISS hybrid, and the static proxy improves BM25 without any encoder call.

## Online efficiency (programmers/unix)

All six methods ran in the round-one harness and runtime profile (four pinned physical cores, four torch threads, 50 warm-up queries, five repetitions; 9,740 timed requests per method). All 58,440 online rankings, and every cascade routing decision, matched the offline computation.

| Method | nDCG@10 | Encoded | Mean ms | p95 ms | CPU ms | Mean vs H\* (95% CI) |
|---|---:|---:|---:|---:|---:|---:|
| BM25 | 0.2899 | 0% | 2.41 | 4.39 | 2.4 | −90.9% |
| P\* | 0.3001 | 0% | 4.17 | 6.99 | 4.2 | −84.3% [−84.5, −84.1] |
| H\* | 0.3146 | 100% | 26.51 | 35.33 | 99.7 | — |
| PE-GH v1 | 0.3122 | 57.75% | 16.45 | 30.75 | 62.1 | −38.0% [−40.0, −36.0] |
| R\* | 0.3174 | 100% | 15.14 | 22.01 | 58.5 | −42.9% [−43.5, −42.3] |
| Cascade | 0.3113 | 59.3% | 11.78 | 20.69 | 44.6 | −55.6% [−56.7, −54.4] |

The exhaustive FAISS search accounts for about 8.5 of H\*'s 23.6 ms. Removing it gives R\*, which is both more accurate and faster than PE-GH v1 although it encodes every query; on the fresh domains PE-GH v1 encodes 81% of queries for 0.3209 while R\* reaches 0.3236. R\* is the forward-index interpolation of Leonhardt et al. (WWW 2022), a known baseline that round one omitted. In this setting it dominates the learned gate. The cascade is the fastest encoding configuration, but since its gate is not distinguishable from random routing (H5), it is best read as a budget dial between P\* and R\*.

**Throughput.** With four single-threaded server processes sharing the same four cores (folds 0–1, closed loop), H\* sustains 106 queries/s, PE-GH v1 179 (×1.69, 63.6% encoded on these folds), R\* 197 (×1.86), and the cascade 234 (×2.21, 76.7% encoded). Single-threaded serving uses far less CPU per request than one four-thread request (36 versus 100 ms for H\*), so the latency ranking carries over to load.

## A stronger encoder (programmers/unix; exploratory)

With BAAI/bge-small-en-v1.5 (pinned revision, 384-d, 13.8 ms per query versus 7.6 ms for MiniLM), dense retrieval alone beats BM25 (0.3683 versus 0.2899) and H\* reaches 0.3971. The picture changes in three ways. First, R\* falls to 0.3681, 0.029 below H\* (95% CI [−0.037, −0.021]): relevant documents outside the BM25 top-100 now matter, so forward-index re-scoring is only a substitute for FAISS when the encoder is weaker than BM25. Second, the gate carries more signal (AUC 0.588, Spearman 0.161) and beats random routing by 0.0137 at matched budget, but it is again indistinguishable from the BM25-margin rule (+0.0003, CI [−0.0031, 0.0036]), and the validation-selected threshold encodes 87% of queries. Third, the static proxy still helps BM25 (+0.011).

## Second preregistered confirmation with bge-small (android, gis, mathematica, webmasters)

Four hypotheses taken from the exploratory bge-small run were hashed and recorded before any bge-small vector, proxy, tier or ranking of the fresh domains was computed. The same folds and selection rules were used, with Holm correction over B1–B4. The relevance labels of these domains had already been scored once with MiniLM, and the protocol states this. The test therefore confirms configurations chosen without these domains; it is not a test on labels nobody has seen.

| Hypothesis | Estimate | 95% CI | Result |
|---|---:|---|---|
| B1 H\* superior to R\* | +0.0158 | [0.0099, 0.0219] | supported |
| B2 P\* superior to BM25 | +0.0146 | [0.0106, 0.0187] | supported |
| B3 PE-GH v1 non-inferior to S\* (margin 0.01) | −0.0009 | [−0.0029, 0.0010] | supported |
| B4 v1 gate beats random at matched budget | +0.0028 | [0.0009, 0.0047] | supported (p = 0.002) |

Dense retrieval alone beats BM25 on every fresh domain (0.3638 versus 0.3048 macro). R\* falls below H\* on all four domains, and the static proxy again improves BM25 on all four. With this encoder the gate's routing signal does generalize: it beats random routing at every budget, by up to 0.017 at 40% of queries encoded. The non-learned BM25-margin rule, however, does at least as well at the gate's own per-fold dense counts (gate minus margin −0.0014, CI [−0.0034, 0.0004]; areas under the quality–budget curve 0.3572 versus 0.3569; AUC 0.561 versus 0.590). B3 holds only because the validation-selected threshold encodes 95.4% of queries, which saves 4.6% of encoder calls. The oracle peaks after encoding roughly a third of queries and stays 0.033 above the gate, so better routing is possible, but none of the v1 or v3 features reaches it.

## Approximate search (HNSW)

Any saving from skipping the encoder or the exhaustive search should be compared with an H\* that uses an approximate index. We built `IndexHNSWFlat` (M = 32, efConstruction = 200, fixed in advance, built single-threaded for determinism) over the frozen document vectors. Searches used the online CPU profile (four pinned cores, four FAISS threads) and the dense retriever's self-hit rule. A rebuilt flat index reproduced the cached H\* rankings exactly.

| Encoder | Search | Search ms | Overlap@10 | H\* nDCG@10 |
|---|---|---:|---:|---:|
| MiniLM | flat (exact) | 8.51 | 1 | 0.3146 |
| MiniLM | HNSW ef 128 / 256 / 512 | 1.10 / 1.74 / 3.07 | 0.991 / 0.998 / 0.9995 | 0.3144 / 0.3139 / 0.3144 |
| bge-small | flat (exact) | 12.18 | 1 | 0.3971 |
| bge-small | HNSW ef 128 / 256 / 512 | 1.21 / 1.92 / 3.31 | 0.997 / 0.999 / 0.9998 | 0.3965 / 0.3970 / 0.3971 |

Times are request-weighted means over programmers/unix. Both encoders have the same dimension and corpus, so the two flat times differ only by measurement noise on a single host. HNSW changes H\* by at most 0.0008, and with bge-small at ef 512 not at all.

Substituting HNSW for the measured FAISS stage gives an estimated 19–21 ms for MiniLM H\*. This figure is assembled from separate measurements, not measured end to end. It is still slower and less accurate than R\*, so the MiniLM conclusion stands. With bge-small, where R\* is not an option, HNSW is the right lever: it removes 5–9 ms from every query at no measurable quality cost. The gate, in contrast, skips the 13.8 ms encoder call for only 4.6–13% of queries.

## What the round supports

Three findings hold on unseen domains under preregistered tests.

1. **Static proxy (P\*).** Re-ranking BM25 with a static token-embedding proxy improves BM25 without any encoder call, with both encoders (+0.0063 and +0.0146).
2. **Re-scoring versus full search depends on encoder strength.** Whether forward-index re-scoring can replace the full dense search depends on whether the encoder is stronger than BM25. This can be checked on validation data before deployment.
3. **PE-GH v1 non-inferiority.** PE-GH v1 remains non-inferior to the best static configuration, but its validation-selected thresholds encode most queries.

The learned gate itself is not supported as a contribution. Across six domains and two encoders, it never beat the BM25-margin rule at matched budget, and with MiniLM on unseen domains it did not beat random routing. The defensible contribution is therefore an empirical one:

- a reproducible, preregistered evaluation of selective dense retrieval with matched-budget and online parity controls;
- the finding that architectural choices (forward-index re-scoring, approximate search, static proxies), chosen by relative encoder strength, determine the quality–cost trade-off more than query-level gating does.

All timings come from one Windows host with two small 384-d encoders on CQADupStack. A Linux replication of the online benchmark, a P\* → H\*+HNSW cascade measured online with bge-small, and other BEIR collections are left for future work.
