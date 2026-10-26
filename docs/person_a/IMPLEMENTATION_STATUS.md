# Trạng thái triển khai phần A

## Cập nhật tích hợp 26/10/2026

Các lỗi kiểm chứng phát hiện trong [review A](../person_b/REVIEW_A_2026-10-25.md) đã được sửa: canonical query coverage, split/group integrity, sidecar/retriever identity, utility split/fold, provider score parity và SQLite manifest integrity. Backend NumPy mới khớp SQLite đến từng score trên 1.948 query. Đã có đủ run C và OOF chính/14 đối chứng trong lượt end-to-end mới; xem [báo cáo tích hợp](../integration/2026-10-26/README.md) và [cách tái lập](../INTEGRATION_V2.md).

Phần dưới là bản ghi ngày 22/10, bao gồm các phụ thuộc và khẳng định kiểm tra tại thời điểm đó; không dùng mục “Phụ thuộc chưa có” làm trạng thái hiện tại.

Ngày kiểm tra: 22/10/2026.

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
- Sinh bảng BM25/Dense thật, hai figure và failure audit 80 query.
- `uv lock`, dependency check, ruff, format, compileall và full non-network CI đều pass.
- Thành viên độc lập clean-rerun và mutation-audit; các provenance attack đều bị từ chối.

## Kết quả baseline thật

| Method | Miền | nDCG@10 | MRR@10 | Recall@10 | Recall@100 |
|---|---|---:|---:|---:|---:|
| BM25 | programmers | 0.292620 | 0.294810 | 0.367661 | 0.565966 |
| BM25 | unix | 0.287191 | 0.290412 | 0.345109 | 0.529459 |
| BM25 | macro-2 | 0.289906 | 0.292611 | 0.356385 | 0.547713 |
| Dense | programmers | 0.248497 | 0.245899 | 0.333510 | 0.555559 |
| Dense | unix | 0.222105 | 0.214061 | 0.287706 | 0.480007 |
| Dense | macro-2 | 0.235301 | 0.229980 | 0.310608 | 0.517783 |

Dense được ghi rõ là rebuilt artifact: config/model/corpus/ID order khớp manifest B và
verifier pass, nhưng byte hash FAISS/run không trùng artifact B cũ.

## Phụ thuộc chưa có

- Repository không có ranking-v1 của C cho H*, S* hoặc PE-GH.
- Chưa thể sinh utility H*/S*, bảng final PE-GH hoặc CI claim chính một cách trung thực.
  `configs/evaluation/oof_final.example.json` xác định 30 run và 30 sidecar cần nhận
  (3 method × 2 miền × 5 fold).
- Clean-rerun hiện là independent rerun của working tree, chưa phải fresh clone từ commit vì
  thay đổi A chưa được chủ repository commit.

Không được đổi số fixture, số latency hoặc placeholder thành kết quả chất lượng cuối.
