# PE-GH

Research plan and implementation for a three-person hybrid retrieval project.

- [Kế hoạch nhóm](PE_GH_KE_HOACH_HOAN_CHINH_3_NGUOI_V2.md)
- [Phần B: dense encoder, FAISS, online profiling](docs/person_b/README.md)
- [Handoff cho A/C](docs/person_b/HANDOFF_A_C.md)
- [Trạng thái triển khai/quota](docs/person_b/IMPLEMENTATION_STATUS.md)
- [Kết quả thực chạy](paper/05b_efficiency_results.md)

Code hiện có là phần B và shared contracts tối thiểu. A phụ trách dữ liệu/BM25/
evaluator; C phụ trách fusion/gate/app. Xem hướng dẫn phần B để cài `uv.lock` và
chạy correctness tests, index build, quality export hoặc online benchmarks.
