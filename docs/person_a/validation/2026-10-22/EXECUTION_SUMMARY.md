# Biên bản thực hiện 8 đầu việc

Ngày chốt: 22/10/2026.

| # | Đầu việc | Trạng thái | Bằng chứng chính |
|---:|---|---|---|
| 1 | Tải và khóa revision dữ liệu/qrels thật | Hoàn thành | `configs/data/cqadupstack.yaml`, source manifests, SHA-256 audit |
| 2 | Sinh manifests và năm split thật | Hoàn thành | `data/manifests`, `data/splits`, split hash `c6230440...3446` |
| 3 | Build BM25 hai miền, xuất top-100 | Hoàn thành | 79.558 docs, 1.948 query, hai full runs và 10 OOF runs |
| 4 | Đối chiếu BM25S/evaluator chuẩn | Hoàn thành | BM25S top-100 set trùng 100%; ir-measures sai số tối đa `2.3e-16` |
| 5 | Final OOF, macro aggregation, CI | Hoàn thành code và baseline runs | Strict registry, domain/macro/micro, multi-utility, grouped bootstrap 10k |
| 6 | Nhận run B/C, utility H*/S*, bảng | B hoàn thành; C bị chặn | B rebuilt/verified; thiếu 30 run + 30 sidecar C nên chưa có H*/S*/PE-GH |
| 7 | Figure, failure analysis, paper | Baseline hoàn thành; claim cuối bị chặn | BM25/Dense figures, 80 failure rows, setup/results updated |
| 8 | uv/ruff/toàn CI/clean rerun | Hoàn thành trong working tree | 84 passed, 1 model-network deselected; independent mutation audit passed |

## Kết quả baseline

| Method | Programmers nDCG@10 | Unix nDCG@10 | Macro nDCG@10 | Macro MRR@10 | Macro R@100 |
|---|---:|---:|---:|---:|---:|
| BM25 | 0.292620 | 0.287191 | 0.289906 | 0.292611 | 0.547713 |
| Dense rebuilt | 0.248497 | 0.222105 | 0.235301 | 0.229980 | 0.517783 |

Dense giúp 297/1.948 query theo nDCG@10 dù mean thấp hơn BM25. Đây là phân tích
complementarity để C sử dụng trên train/validation, không phải kết quả PE-GH.

## Chốt blocker

Không có implementation hoặc ranking artifact C trong repository. Final runner yêu cầu ba
method `h_star`, `s_star`, `pe_gh` × hai miền × năm fold, cùng 30 sidecar. Cho tới khi nhận
đủ, không thể trung thực sinh `U_H-U_B`, `U_PE-U_S*`, CI non-inferiority hay hàng PE-GH
trong bảng paper. Contract bàn giao nằm ở `RUNS_REQUIRED_FROM_C.md` và registry template ở
`configs/evaluation/oof_final.example.json`.

Clean-rerun đã do thành viên độc lập thực hiện trên working tree. Fresh-clone rerun chỉ có
thể thực hiện sau khi chủ repository commit các thay đổi; agent không tự commit vì người
dùng chưa yêu cầu.
