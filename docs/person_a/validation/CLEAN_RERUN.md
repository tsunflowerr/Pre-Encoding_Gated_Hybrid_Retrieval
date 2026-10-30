# Part A handoff verification — 30 October 2026

The 22 October independent audit is preserved in
[the historical snapshot](2026-10-22/CLEAN_RERUN.md). This report records the current
handoff verification by the primary agent; no new independent human audit is claimed.

## Isolated checkout

A local clone with independent Git objects was created, detached at
`c3b4b9cf3817445db5bd8afd47659297f4b9d96c`. The exact current A source/test changes
were copied into that checkout. It shares the existing pinned Python environment and
model cache, but imports were explicitly checked to resolve to the isolated checkout.
No commit, branch update or push was made.

The source snapshots of the handoff tree and isolated clone match:
`e13b0d2af231536cacd36671120d42ba38efbe2746d21165dbd6e2d20981b795`.
The full checkout path, XML digest and scope are in [HANDOFF_AUDIT.json](2026-10-30/HANDOFF_AUDIT.json).
An initial Git-archive export lacked `.git` and failed one Git-metadata test after 130
passes. That setup was replaced by a real local clone, and the complete suite passed.

| Check | Result |
|---|---|
| `uv lock --check` | Passed, 64 packages |
| `uv pip check` | Passed, 58 installed packages compatible |
| CI-scope Ruff lint and format | Passed, 112 Python files formatted |
| Shared + A + B + C, including pinned real CPU model | **131 passed**, no skip/failure |
| Compileall and `git diff --check` | Passed |
| Six new materialization/failure-selection regression tests | Passed |
| Real materialization, two domains, two invocations | 10 folds written, then 10 reused; original run/sidecar bytes identical |
| Strict 14-method OOF from isolated source | 1,948 queries/method, 10,000 bootstrap samples; all saved statistics identical |
| OOF per-query, utility, comparison and quality CSV/JSON | Byte-identical to saved results |
| Final analysis on preserved online artifacts | All 29,220 rankings verified; 40 cases, 3 plots, 14-method table |
| Final report rebuilt from isolated source | Tables, cases, three PNGs and analysis manifest byte-identical |
| Historical baseline reporting CLI after refactor | Passed, 80 baseline failure cases retained |
| Provider parity | BM25S/ir-measures passed on both complete domains |

The clean full-suite [JUnit XML](2026-10-30/full-tests.xml) and
[OOF recheck summary](2026-10-30/quality-recheck.json) are tracked. The original 30 October
experiment source remains `bec368c6…fa13`; analysis/materialization changes create a new
source identity and do not rewrite the old freeze or timing receipts.

## Remaining release scope

This is a local clone plus an uncommitted patch, not hosted CI of a new committed revision.
Dependencies were checked from the existing locked installation; they were not installed
again into a fresh environment. The real model test used the pinned local cache offline.
The full online benchmark was completed before these reporting/materialization edits;
its timing results are preserved and were not benchmarked again after the edits.

No C-input blocker remains for A. A new end-to-end experiment after source changes must
use a fresh results directory/checkout and create a new freeze. Existing raw artifacts
can still be evaluated and reported after their original identity/checksums are verified.
