# Evidence for closing Part A — 30 October 2026

Part A has received the C runs, evaluated all 14 methods and completed its tables,
utility, confidence intervals, figures and routing case audit. The
[execution summary](../../EXECUTION_SUMMARY.md) is the handoff status.

| Artifact | Meaning |
|---|---|
| [freeze.json](freeze.json) | Original 30 October experiment freeze `b2209221…42cbd0` |
| [release.json](release.json) | Four registered targets pass; 29,220 measured requests |
| [gate-facts.json](gate-facts.json) | Frozen decisions, counts, methods and original figure receipts |
| [quality-primary.json](quality-primary.json) | BM25/H*/S*/PE-GH domain/macro/micro metrics |
| [quality-controls.json](quality-controls.json), [CSV](quality-controls.csv) | Fourteen-method strict OOF |
| [comparison.json](comparison.json) | Paired S* versus PE-GH bootstrap |
| [utility.csv](utility.csv) | 1,948 H*−BM25 and 1,948 PE-GH−S* utility rows |
| [random30-oracle.json](random30-oracle.json) | Post-freeze exact-budget diagnostics |
| [HANDOFF_AUDIT.json](HANDOFF_AUDIT.json) | Local clone/source parity, checks and original-vs-rerun identity |
| [full-tests.xml](full-tests.xml) | 131 tests passed, including the pinned CPU model |
| [quality-recheck.json](quality-recheck.json) | Strict 14-method re-evaluation with 10,000 bootstrap samples |
| [provider-programmers.json](provider-programmers.json), [provider-unix.json](provider-unix.json) | Full-query BM25S/ir-measures parity |

The experiment used the original source snapshot `bec368c6…fa13` from commit
`c3b4b9c`. The later A handoff source is `e13b0d2a…81b795`; it adds reporting and safe
materialization without changing encoder, fusion, features, model weights or thresholds.
Raw model/index/request data stay in the ignored local artifacts/results directories.
The [final analysis manifest](../../../../paper/figures/final-a/report.json) records
their checksums and checks 29,220 online ranking sequences against the frozen runs.

Main quality: PE-GH macro nDCG@10 `0.31216300915894646`; S* `0.3146252335653041`.
Paired difference `-0.0024622244063576483`, one-sided 95% lower bound
`-0.006009141863135304 > -0.01`. Dense calls `1125/1948 = 57.75%`.
Observed mean speedup versus H* on Ryzen 7 8745H is 33.80%, CI [32.01%, 35.65%].
Programmers alone is below 20% mean reduction and has slightly worse p95. Unix quality
is close to the noninferiority margin. These limits remain in the paper.

The local clone verification uses the existing pinned environment/model cache and the
current uncommitted A patch. It is not an additional independent human audit or a hosted
CI run. Details and rerun commands are in [CLEAN_RERUN.md](../CLEAN_RERUN.md).
