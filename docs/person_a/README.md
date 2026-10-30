# Phần A: dữ liệu, BM25 và đánh giá

Implementation nằm trong `src/pegh/data`, `src/pegh/sparse` và `src/pegh/evaluation`;
CLI nằm trong `scripts_a`; correctness tests ở `tests/a`.

Trạng thái ngày 30/10/2026: A đã nhận đủ run C, sinh OOF chính và 14 đối chứng,
utility H*/S*, CI và bảng/hình/failure analysis cuối. Xem [biên bản đóng A](EXECUTION_SUMMARY.md),
[paper chất lượng](../../paper/05a_quality_results.md) và [bằng chứng](validation/2026-10-30/).

## Tái tạo baseline thật

```powershell
uv sync --locked --extra dev
uv run --no-sync python scripts_a/fetch_inputs.py
uv run --no-sync python scripts_a/prepare_data.py
uv run --no-sync python scripts_a/build_sparse.py --corpus data/raw/programmers/corpus.jsonl --domain programmers --output artifacts/sparse/programmers
uv run --no-sync python scripts_a/build_sparse.py --corpus data/raw/unix/corpus.jsonl --domain unix --output artifacts/sparse/unix
```

Sau khi xuất full top-100, dùng `materialize_fold_runs.py` để tạo đúng năm test run, rồi
chạy `run_final_oof.py` với registry. `oof_final.example.json` là contract nhận H*/S*/PE-GH
từ C; runner từ chối run thiếu query, thừa query, sai fold hoặc lẫn provenance.

## Kiểm tra

```powershell
uv lock --check
uv run --no-sync ruff check src contracts scripts_a tests/a
uv run --no-sync ruff format --check src contracts scripts_a tests/a
uv run --no-sync pytest tests/shared tests/a -q
```

Dữ liệu raw, index và run lớn bị loại khỏi Git. Manifests, split, figure, failure audit và
paper text được giữ lại. Xem [trạng thái triển khai](IMPLEMENTATION_STATUS.md) để biết phần
nào đã đo thật và các giới hạn của kết quả.

## Dựng báo cáo cuối từ artifact đã đo

```powershell
uv run --no-sync python scripts_a/finalize_report.py --output results/paper/final-a-20261030
```

Lệnh kiểm checksum freeze/report, raw receipts, ranking online/OOF và quyết định gate,
rồi sinh bảng 14 method, ba hình và 40 case. Không cần encode hoặc train lại.
`gate-cases.jsonl` chứa feature, score/threshold, utility, top document IDs, qrels và timing.
Stages không instrument được ghi `null`, không ước lượng bằng tỷ lệ dense.

## Chạy lại materialization an toàn

`materialize_fold_runs.py --reuse-identical` chỉ tái sử dụng run và sidecar khớp chính xác
nguồn, split, query, retriever và run ID yêu cầu. Mặc định vẫn từ chối output tồn tại.
CLI kiểm cả năm fold trước khi ghi; file khác/thiếu sidecar phải dùng output directory mới.
Driver tích hợp dùng `results/oof_runs/release_bm25/` riêng, tránh đụng các run A cũ trong
`results/oof_runs/bm25/`. Registry vẫn dùng method `bm25`.

Một freeze cũ ràng buộc toàn bộ source. Sau thay đổi code, dùng checkout/results mới để
chạy lại end-to-end; không sửa hash freeze để resume. Báo cáo phân tích trên artifact cũ
vẫn hợp lệ khi các checksum của lượt cũ còn nguyên. Chi tiết [clean rerun](validation/CLEAN_RERUN.md).
