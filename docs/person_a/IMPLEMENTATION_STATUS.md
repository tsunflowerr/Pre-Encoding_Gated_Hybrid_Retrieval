# Trạng thái triển khai phần A

## Nghiệm thu cuối ngày 30/10/2026

Các lỗi kiểm chứng phát hiện trong [review A](../person_b/REVIEW_A_2026-10-25.md) đã được sửa: canonical query coverage, split/group integrity, sidecar/retriever identity, utility split/fold, provider score parity và SQLite manifest integrity. Backend NumPy mới khớp SQLite đến từng score trên 1.948 query. Đã có đủ run C và OOF chính/14 đối chứng trong lượt end-to-end mới; xem [báo cáo tích hợp](../integration/2026-10-26/README.md) và [cách tái lập](../INTEGRATION_V2.md).

**A hoàn thành triển khai, tích hợp chất lượng và báo cáo cuối.** Blocker nhận run C đã đóng.
Biên bản 22/10 được giữ ở [snapshot lịch sử](validation/2026-10-22/IMPLEMENTATION_STATUS.md).

Lượt thực nghiệm đầy đủ 30/10 có freeze `b2209221…42cbd0`, source
`bec368c6…fa13`, đủ 29.220 request online và quality khớp lượt 26/10.

## Đã hoàn thành và chạy trên dữ liệu thật

- Khóa revision corpus/query/qrels, kiểm SHA-256 và số dòng cho hai miền.
- Audit 79.558 tài liệu, 1.948 query và 3.368 cặp qrel; không có dangling ID.
- Sinh grouped five-fold split, kiểm disjoint và mỗi query test đúng một lần.
- Build hai SQLite BM25 index và xuất đủ 1.948 ranking top-100.
- Build lại hai dense MiniLM/FAISS index từ revision đã khóa, verify toàn bộ vector và xuất
  đủ 1.948 ranking top-100.
- Đối chiếu BM25S trên toàn bộ query: tập top-100 trùng 100%; sai số score tối đa `<7.8e-6`.
- Đối chiếu `ir-measures`: sai khác aggregate tối đa `2.3e-16`.
- Final OOF runner kiểm dataset/split hash, sidecar, exact query-set, metadata, corpus và
  retriever provenance; có domain/macro/micro aggregation, utility và paired group bootstrap.
- Nhận đủ H*/S*/PE-GH từ C; strict OOF chính và 14 method đều đủ 1.948 query.
- Sinh utility `U_H-U_B`, `U_PE-U_S*`, bảng final và CI 10.000 bootstrap samples.
- Ba figure cuối bao gồm BM25/Dense/H*/S*/PE-GH, ổn định theo fold và noninferiority.
- Audit toàn bộ quyết định gate, chọn 40 case theo bốn nhóm đã đăng ký. Mỗi case có
  features, score/threshold, utility, top IDs, qrels và timing thật.
- Tách output BM25 release khỏi output lịch sử; có opt-in tái sử dụng đúng byte/sidecar,
  preflight năm fold và regression tests cho file bị sửa hoặc thiếu sidecar.
- `uv lock`, dependency check, ruff, format và compileall đều pass; clone local cộng patch
  A đạt 131 test, gồm model CPU thật. [JUnit](validation/2026-10-30/full-tests.xml).
- Audit độc lập ngày 22/10 và mutation tests được giữ trong snapshot lịch sử; lượt chốt
  30/10 do agent chính chạy. Không coi đây là một người review độc lập mới.

## Kết quả baseline thật

| Method | Miền | nDCG@10 | MRR@10 | Recall@10 | Recall@100 |
|---|---|---:|---:|---:|---:|
| BM25 | programmers | 0.292620 | 0.294810 | 0.367661 | 0.565966 |
| BM25 | unix | 0.287191 | 0.290412 | 0.345109 | 0.529459 |
| BM25 | macro-2 | 0.289906 | 0.292611 | 0.356385 | 0.547713 |
| Dense | programmers | 0.248497 | 0.245899 | 0.333510 | 0.555559 |
| Dense | unix | 0.222105 | 0.214061 | 0.287706 | 0.480007 |
| Dense | macro-2 | 0.235301 | 0.229980 | 0.310608 | 0.517783 |
| H*/S* | macro-2 | 0.314625 | 0.315820 | 0.391686 | 0.589594 |
| PE-GH | macro-2 | 0.312163 | 0.315880 | 0.381008 | 0.576145 |

Dense được ghi rõ là rebuilt artifact: config/model/corpus/ID order khớp manifest B và
verifier pass, nhưng byte hash FAISS/run không trùng artifact B cũ.

## Bằng chứng và giới hạn

- [Bảng/hình/failure analysis trong paper](../../paper/05a_quality_results.md).
- [Release, freeze, utility và CI](validation/2026-10-30/).
- [Clean rerun và phạm vi kiểm chứng](validation/CLEAN_RERUN.md).
- Macro PE-GH − S* `-0.002462`, cận dưới một phía 95% `-0.006009`, đạt biên `-0.01`.
  Programmers `-0.005502`, Unix `-0.009601`; Unix sát biên.
- Dense ratio `57.75%`; 921 query gọi dense nhưng gain nDCG@10 không dương, 96 query
  bị skip dù H* có gain dương. Đây là phân tích mô tả, không đổi threshold theo test.
- Timing baseline margin/LiteGator-style và các operating point bổ sung vẫn thuộc
  nghiệm thu toàn dự án B/C. Không suy latency của các method này từ dense ratio.
- Các thay đổi bàn giao A hiện chưa commit. Kiểm tra checkout tách biệt dùng HEAD cộng
  patch hiện tại; không gọi đó là hosted CI hay tái lập độc lập bởi một người khác.
