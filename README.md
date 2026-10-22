# PE-GH

Reproducible implementation for a three-person pre-encoding gated hybrid retrieval study.

- [Kế hoạch nhóm](PE_GH_KE_HOACH_HOAN_CHINH_3_NGUOI_V2.md)
- [Phần A: dữ liệu, BM25 và đánh giá](docs/person_a/README.md)
- [Trạng thái phần A](docs/person_a/IMPLEMENTATION_STATUS.md)
- [Phần B: dense encoder, FAISS và profiling](docs/person_b/README.md)
- [Handoff B cho A/C](docs/person_b/HANDOFF_A_C.md)
- [Shared contracts](docs/SHARED_BASE.md)
- [Experimental setup](paper/04_experimental_setup.md)
- [Quality results](paper/05a_quality_results.md)
- [Efficiency results](paper/05b_efficiency_results.md)

Phần A và B dùng chung canonical IDs, text policy, ranking-v1 schema và lockfile. Part A
owns pinned data, leakage-safe splits, exact BM25, provider validation, OOF aggregation,
utilities and quality reporting. Part B owns dense/FAISS and online profiling. Part C must
provide fold-specific H*, S* and PE-GH ranking-v1 runs before the final effectiveness claim
can be computed.
