# Biên bản thực hiện 8 đầu việc

Ngày chốt: 30/10/2026. **Phần A hoàn thành.** Bản ghi 22/10 được giữ ở
[snapshot lịch sử](validation/2026-10-22/EXECUTION_SUMMARY.md).

| # | Đầu việc | Trạng thái | Bằng chứng chính |
|---:|---|---|---|
| 1 | Tải và khóa revision dữ liệu/qrels thật | Hoàn thành | `configs/data/cqadupstack.yaml`, source manifests, SHA-256 audit |
| 2 | Sinh manifests và năm split thật | Hoàn thành | `data/manifests`, `data/splits`, split hash `c6230440...3446` |
| 3 | Build BM25 hai miền, xuất top-100 | Hoàn thành | 79.558 docs, 1.948 query, hai full runs và 10 OOF runs |
| 4 | Đối chiếu BM25S/evaluator chuẩn | Hoàn thành | BM25S top-100 set trùng 100%; ir-measures sai số tối đa `2.3e-16` |
| 5 | Final OOF, macro aggregation, CI | Hoàn thành | Strict registry, domain/macro/micro, multi-utility, grouped bootstrap 10k |
| 6 | Nhận run B/C, utility H*/S*, bảng | Hoàn thành | Đủ 30 C runs + 30 sidecars, 14-method OOF, 3.896 utility rows |
| 7 | Figure, failure analysis, paper | Hoàn thành phạm vi A | Bảng 14 methods, 3 hình cuối, 40 routing cases, paper 05a cập nhật |
| 8 | uv/ruff/toàn CI/clean rerun | Hoàn thành kiểm tra local | Xem receipt/test và phạm vi checkout trong CLEAN_RERUN.md |

## Kết quả baseline

| Method | Programmers nDCG@10 | Unix nDCG@10 | Macro nDCG@10 | Macro MRR@10 | Macro R@100 |
|---|---:|---:|---:|---:|---:|
| BM25 | 0.292620 | 0.287191 | 0.289906 | 0.292611 | 0.547713 |
| Dense rebuilt | 0.248497 | 0.222105 | 0.235301 | 0.229980 | 0.517783 |
| H*/S* | 0.327311 | 0.301939 | 0.314625 | 0.315820 | 0.589594 |
| PE-GH | 0.326882 | 0.297444 | 0.312163 | 0.315880 | 0.576145 |

Dense giúp 297/1.948 query theo nDCG@10 dù mean thấp hơn BM25. Đây là phân tích
complementarity để C sử dụng trên train/validation, không phải kết quả PE-GH.

## Kết quả chốt và bàn giao

PE-GH gọi dense 1.125/1.948 query, tỷ lệ 57,75%. Chênh macro so S* `-0.002462`,
cận dưới một phía 95% `-0.006009 > -0.01`; cả hai domain đạt biên, Unix sát biên.
Timing lượt 30/10 trên Ryzen 7 8745H giảm mean gộp 33,80% so H*, CI [32,01%; 35,65%].
Programmers riêng giảm 19,73%, p95 hơi xấu hơn; không gộp số với i3/i7 của lượt cũ.

[Failure analysis](../../paper/figures/final-a/FAILURE_ANALYSIS.md) kiểm 1.948 quyết định:
96 missed benefit, 921 wasted dense, 204 useful dense, 727 safe skip. Đã xuất 40 case
có quy tắc, giữ zero-gain trong wasted/safe đúng định nghĩa.

`scripts_a/finalize_report.py` kiểm lại toàn bộ 29.220 online ranking và checksum,
rồi dựng bảng/hình/case. [Manifest phân tích](../../paper/figures/final-a/report.json)
khóa input/output và mã phân tích; [evidence 30/10](validation/2026-10-30/) giữ freeze,
release, bảng quality, utility và CI. Các artifact B/C gốc vẫn giữ nguyên.

Không còn đầu việc A bị chặn bởi C. Nghiệm thu rộng hơn của dự án vẫn cần các timing
baseline/operating point còn thiếu của B/C và ghép toàn bộ paper. Thay đổi A chưa commit;
không tự commit hoặc đẩy nhánh khi chưa được yêu cầu.
