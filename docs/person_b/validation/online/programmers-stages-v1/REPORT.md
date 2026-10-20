# Online profile: programmers-stages-v1

Split: `development_validation`; fold: `None`.

OS: Windows-11-10.0.26200-SP0; affinity: [0, 2, 4, 6]; memory policy: windows_job_process_commit_limit.

| Method/domain | Queries × repeats | Dense % | Mean ms | p95 ms | CPU ms | Peak RSS MiB |
|---|---:|---:|---:|---:|---:|---:|
| dense_minilm/programmers | 128 × 1 | 100.0 | 42.499 | 54.651 | 160.889 | 488.3 |

Model/index load and disk logging are outside request latency. RSS includes process setup, model/index loading and warmup.

Quality is not evaluated here. No gate improvement or non-inferiority is inferred from these timings. Repeated timings are not independent queries.

This run is development/fixture validation, not the registered final test.
