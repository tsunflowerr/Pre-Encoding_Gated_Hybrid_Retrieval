# Gate analysis and C-side results

All quality numbers in this section come from the strict five-fold OOF evaluator, with one test prediction for each of 1,948 queries across Programmers and Unix. The primary frozen comparison is S* versus PE-GH; H* and S* happen to coincide in every fold/domain. The tracked [C7 facts](../docs/person_c/validation/C7_FACTS.json) record method scores, input hashes, freeze identity, and figure hashes; full raw receipts remain under the ignored `results/` directory. Timing evidence is reported separately below.

## Quality at the selected operating points

| Method | Macro nDCG@10 | Dense-call ratio on test |
|---|---:|---:|
| BM25 | 0.28991 | 0.000 |
| Dense only | 0.23530 | 1.000 |
| CC, dense weight 0.5 | 0.31426 | 1.000 |
| RRF, (k=60) | 0.29481 | 1.000 |
| H* / S* | 0.31463 | 1.000 |
| **PE-GH: Ridge gain, 21 features** | **0.31216** | **0.578** |
| Logistic gain, 21 features | 0.31342 | 0.629 |
| Logistic sparse-success, 21 features | 0.31209 | 0.619 |
| LinearSVC gain, eight features | 0.31049 | 0.555 |
| Ridge gain, eight features | 0.31131 | 0.620 |
| BM25 margin rule | 0.31299 | 0.698 |
| Identifier + margin | 0.31463 | 1.000 |
| Query-ID random gate, seed 0 | 0.30956 | 0.729 |

The identifier rule has no feasible gated validation point in any fold. Its recorded policy is **always H***, which explains its 1.000 dense ratio and H* quality; it is not evidence of successful routing. The learned comparators form a quality–compute trade-off: Logistic gain is slightly higher quality than PE-GH while using more dense calls, whereas the eight-feature LinearSVC uses fewer dense calls at lower quality. Dense-call ratio is an observed count, not a latency estimate. All control thresholds were chosen on validation before test.

![Quality versus dense-call ratio](figures/c7_quality_compute.png)

## Primary comparison and fold behavior

PE-GH makes 1,125 dense calls on 1,948 queries (57.75%). Its macro nDCG@10 is 0.31216 versus 0.31463 for S*, a paired mean difference of −0.00246. The preregistered one-sided 95% group-bootstrap lower bound is −0.00601, above the noninferiority margin of −0.01. Domain-level differences are −0.00043 on Programmers and −0.00450 on Unix; their lower bounds are −0.00550 and −0.00960, respectively. This supports the registered quality noninferiority statement for the fixed OOF predictions. The bootstrap does not include retraining or operating-point selection uncertainty.

Five validation-selected PE-GH budget points target 0.7, 0.5, 0.5, 0.8, and 0.3 dense ratio by fold. Test ratios vary by domain: the Unix fold-4 gate calls dense for only 16/214 queries, while Programmers fold 3 calls it for 161/175. The shared numeric threshold is applied to separately trained domain models; differing score scales may contribute to these route-rate gaps, but that cause is an inference rather than a measured finding. The corresponding quality outcomes are not uniformly favorable. Programmers fold 0 loses about 0.010 nDCG@10 relative to S*; Unix fold 4 loses about 0.0147. Programmers fold 4 gains about 0.0166. We retain all fold outcomes in the macro comparison and do not retune any threshold on test.

![Validation budget curves](figures/c7_validation_thresholds.png)

![Test quality and dense-call ratio by fold](figures/c7_fold_analysis.png)

## Post-freeze diagnostics

At the exact PE-GH dense count in each fold/domain, 30 query-ID hash random seeds have mean macro nDCG@10 of 0.30569. PE-GH reaches 0.31216; the batch oracle that picks the largest observed H*–BM25 gains reaches 0.33673. The oracle reads test utility and is an upper-bound diagnostic, not a deployable gate. The random experiment uses all registered seeds and reports their distribution; no seed is selected from test outcomes. The gap to the oracle shows remaining routing headroom within this fixed fusion system, without implying that the observed gap can be learned from the current features.

![Random and oracle exact-budget diagnostics](figures/c7_random_oracle.png)

## Online execution and limits

The full B-worker benchmark covers all 1,948 test queries across ten fold/domain runs, five repetitions each, for H*, S*, and PE-GH: 29,220 measured requests. All 29,220 online ranking-ID sequences match the corresponding frozen OOF ranking, and encoder-call totals match the frozen sidecars for every fold. The worker performs real retrieval and query encoding; its `quality_cache_used` receipt is false. The [C7 facts](../docs/person_c/validation/C7_FACTS.json) contain the verified per-fold summaries and pooled values. Means and p95 below pool request timings within each domain; repeats are correlated observations of the same queries. Peak RSS is the largest worker peak across the relevant folds and includes loading and warmup.

| Domain | Method | Dense % | Mean ms | p95 ms | CPU mean ms | Peak RSS MiB |
|---|---|---:|---:|---:|---:|---:|
| Programmers | S* | 100.0 | 691.9 | 1442.2 | 1121.5 | 521.5 |
| Programmers | PE-GH | 74.7 | 737.9 | 1465.5 | 996.9 | 520.1 |
| Unix | S* | 100.0 | 648.8 | 1224.6 | 1185.7 | 549.5 |
| Unix | PE-GH | 43.9 | 606.0 | 1183.9 | 841.8 | 546.8 |
| Both domains | S* | 100.0 | 668.2 | 1317.7 | 1156.8 | 549.5 |
| Both domains | PE-GH | 57.8 | 665.3 | 1302.8 | 911.5 | 546.8 |

PE-GH is slower than S* on Programmers by 46.0 ms in the pooled mean and 23.3 ms at p95, while it is faster on Unix by 42.9 ms and 40.8 ms, respectively. Across both domains its mean is only 2.9 ms lower and p95 14.9 ms lower. Programmers fold 0 and fold 2 in particular show higher PE-GH mean latency than S*. The sparse stage dominates wall time and differs between methods despite using the same sparse backend: pooled sparse means on Programmers are 715.3 ms for PE-GH and 666.0 ms for S*. This indicates run-to-run conditions materially affect the end-to-end comparison; the pooled difference is too small and uneven to claim a reliable general latency speedup. CPU usage and dense calls fall substantially, but those savings should be reported separately from wall latency.

H* and S* have identical ranked results here, yet H* pooled mean is 717.1 ms versus 668.2 ms for S*, another sign of timing variability. A previous one-fold, one-repeat integration sample remains a distinct check and is not included in this five-repeat table. The study uses two technical-question domains, one pinned dense model, and one local i3 CPU; broader hardware or workload claims need new measurements. [Experimental setup](04_experimental_setup.md) records split and metric semantics; [C6–C8 execution summary](../docs/person_c/EXECUTION_SUMMARY.md) lists exact commands and artifacts.
