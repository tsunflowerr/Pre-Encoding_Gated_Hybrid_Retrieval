# Phần C: fusion, gate và báo cáo

Implementation nằm trong `src/pegh/fusion`, `src/pegh/gating` và `src/pegh/app`; các lệnh nằm trong `scripts_c`, fixture ở `tests/c`. C0–C8 đã hoàn tất trong workspace này. PE-GH đạt tiêu chí chất lượng không thua kém S* theo phép kiểm đã đăng ký, giảm dense calls còn 57,75%; latency online khác nhau giữa Programmers và Unix nên không kết luận speedup ổn định.

## Tài liệu cần đọc

| Tài liệu | Nội dung |
|---|---|
| [C0 protocol](C0_PROTOCOL.md) | Nguồn dữ liệu, contract A/B, quy tắc đã khóa, hash và lệnh tái tạo C0 |
| [Trạng thái triển khai](IMPLEMENTATION_STATUS.md) | C1–C5: fusion, feature, nhãn, model và factory online |
| [Tổng kết thực hiện](EXECUTION_SUMMARY.md) | C6–C8: freeze, chất lượng OOF, benchmark, review và audit tích hợp |
| [C7 facts](validation/C7_FACTS.json) | Snapshot nhỏ có hash, 14 method, 10 online run và số liệu pooled |

Bản thảo C ở [Introduction](../../paper/01_introduction.md), [Related work](../../paper/02a_routing_related_work.md), [Method](../../paper/03_method.md) và [Gate analysis](../../paper/05c_gate_analysis.md). Kế hoạch và checklist ở [`PHAN_C_FUSION_GATE_DIEU_PHOI.md`](../../PHAN_C_FUSION_GATE_DIEU_PHOI.md).

## Tái tạo báo cáo và kiểm tra

Các lệnh dưới đây dùng dữ liệu/index/model/run local đã có và được Git bỏ qua:

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts_c\report_gating.py
.\scripts_c\release_c7.ps1
```

Lệnh đầu xác minh freeze, 10 online run, 29.220 thứ tự ranking và số encoder call trước khi dựng lại JSON/hình. Lệnh sau đồng bộ môi trường khóa, chạy test và Ruff, rồi kiểm tra báo cáo đầy đủ. Benchmark gốc 10 fold × 5 repeats nằm ở `results/benchmark/c6_full/`; cách chạy lại và biên nhận nằm trong [tổng kết](EXECUTION_SUMMARY.md). Raw artifact lớn không được commit, nên checkout mới phải tái tạo chúng trước khi chạy báo cáo.
