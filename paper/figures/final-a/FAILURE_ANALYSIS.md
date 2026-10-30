# Frozen routing outcomes — 30 October 2026

Source: the five-fold experiment with freeze `b22092218033d7b8d50ca866c1a0af205f2ed77de74d274b2fc31bfcca42cbd0`.
The analysis checks all 1,948 decisions and 29,220 measured request rankings before
selecting cases. The matching [report manifest](report.json) lists input/output SHA-256.

| Domain | Missed benefit | Wasted dense | Useful dense | Safe skip |
|---|---:|---:|---:|---:|
| Programmers | 29 | 508 | 146 | 193 |
| Unix | 67 | 413 | 58 | 534 |
| Total | 96 | 921 | 204 | 727 |

`delta_U = U_H - U_B` uses nDCG@10 of the two actual actions. Missed benefit is skip
with delta > 0; wasted dense is dense with delta <= 0; useful dense is dense with delta > 0;
safe skip is skip with delta <= 0. Zero gain is retained and does not imply no improvement
in MRR or recall. Every query belongs to exactly one category.

Five cases are selected per domain/category (40 total):

- Missed benefit: decreasing missed gain, tie by canonical query ID.
- Wasted dense: increasing gain (largest harm first), tie by query ID. This selects by
  quality harm, not by encode cost, because main-request stage timing is disabled.
- Useful dense: four largest gains and one median-gain case when enough candidates exist.
- Safe skip: increasing SHA-256 of `[20261019, canonical query ID]`, tie by query ID.

These are explicit post-freeze descriptive choices within the plan's categories. The
fixed seed is recorded for reproducibility, not claimed to have been registered before
test. No model, feature, threshold or operating point is changed using these cases.

[gate-cases.csv](gate-cases.csv) is the compact review table.
[gate-cases.jsonl](gate-cases.jsonl) also includes all 21 named features, schema hash,
gate score/threshold/fallback, `U_B/U_H/U_S/U_PE`, top-10 IDs, all positive non-self qrels
and the five observed request times. No corpus text is reproduced. Detailed stage timing
is attached only when available from the separate Programmers fold-0 diagnostic sample;
it is explicitly labelled as a different timing run. Other stage fields are null.

The aggregate gate misses 96 beneficial queries and spends dense calls on 921 queries
without positive nDCG@10 gain; 204 queries benefit from the selected dense branch. This
documents substantial headroom but does not show that the missing gains can be predicted
from the available features. The oracle remains a diagnostic using test labels.

Rebuild from the preserved local artifacts:

```powershell
python scripts_a/finalize_report.py --output results/paper/final-a-20261030
```

The baseline-only 80-query audit in the parent folder remains a separate historical
analysis. Its lexical query classes are not causal routing-failure labels.
