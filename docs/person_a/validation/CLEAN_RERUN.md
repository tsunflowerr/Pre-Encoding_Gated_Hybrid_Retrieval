# Independent clean-rerun report

Date: 22 October 2026. Executor: independent read-only audit agent; no repository files
were edited by the auditor.

## Final focused rerun

| Check | Result |
|---|---|
| `uv lock --check` | Passed, 64 packages |
| Ruff lint | Passed |
| Ruff format | Passed, 71 files |
| Shared + A + B tests excluding network model test (initial independent run) | Passed, 82 tests; 1 deselected |
| Part A tests after strictness fixes (independent focused rerun) | Passed, 15 tests |
| Compileall | Passed |
| `git diff --check` | Passed |
| Strict BM25 OOF registry | Passed, 1,948 query rows |

The independently recomputed macro results were nDCG@10 `0.2899056486375368`, MRR@10
`0.29261130830004145`, Recall@10 `0.35638490954447977`, and Recall@100
`0.5477127409095295`, exactly matching the saved result.

## Mutation audit

The auditor first demonstrated that an earlier runner revision accepted missing run metadata,
a consistent bogus corpus hash, and a forged split hash. After the fixes, the auditor
repeated those attacks in a temporary directory. All three were rejected:

- missing `method`/`split`/`fold`/`run_id`: rejected;
- noncanonical corpus hash: rejected;
- forged/stale split hash: rejected.

The final runner additionally verifies the dataset-manifest binding, run sidecar SHA and
query-set hashes, exact fold query membership, per-file retriever consistency, and top-100
limit.

After adding the two strictness regression tests, the primary agent's final complete suite
passed 84 tests with one network-model test deselected.

## Scope caveat

This is an independent rerun of the current working tree, not a fresh clone of a commit,
because Part A changes are not committed in the user-owned workspace. A literal fresh-clone
rerun remains a release step after the owner commits the work. The missing C artifacts are
an input blocker, not a test failure.
