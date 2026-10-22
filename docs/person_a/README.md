# Phần A: dữ liệu, BM25 và đánh giá

Implementation nằm trong `src/pegh/data`, `src/pegh/sparse` và `src/pegh/evaluation`;
CLI nằm trong `scripts_a`; correctness tests ở `tests/a`.

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
nào đã đo thật và phần nào còn chờ C.
