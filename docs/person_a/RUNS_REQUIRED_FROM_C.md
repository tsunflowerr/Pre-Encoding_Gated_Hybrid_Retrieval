# Run cần nhận từ C để chốt bảng cuối

**Trạng thái 30/10/2026: đã nhận và nghiệm thu đủ.** Ba method × hai miền × năm fold đã
qua strict OOF; PE-GH nDCG@10 macro `0.312163`, S* `0.314625`, cận dưới một phía
`-0.006009 > -0.01`. Hợp đồng bên dưới tiếp tục áp dụng cho các lượt mới.

Registry thực của lượt 30/10 là `results/frozen/oof_4_methods.json` và
`results/frozen/oof_14_methods.json`; bản mẫu không phải artifact cuối.

Phần A cần đúng 30 file ranking-v1 và 30 sidecar `.meta.json`: ba method `h_star`,
`s_star`, `pe_gh`, hai miền `programmers`/`unix`, năm test fold 0–4. Mỗi file phải chứa đúng và đủ query trong
`data/splits/fold_<n>.json` tại `domains.<domain>.test`.

Mỗi record cần:

- `schema_version: "1.0"`, canonical `query_id`/`domain` và tối đa 100 hit;
- `method`, `split: "test"`, `fold`, và `run_id` nhất quán trong file;
- `corpus_hash` khớp canonical corpus của miền;
- một `retriever_hash` trong mỗi file. Hash được phép khác giữa các fold vì gate/fusion có
  thể được fit riêng trên train/validation của fold đó;
- self-hit đã loại, rank liên tiếp, score hữu hạn, thứ tự `score desc, doc_id asc`.

Sidecar phải bind `ranking_sha256`, `query_ids_hash`, `query_count`, `split_hash`,
`domain`, `method`, `fold`, `split`, `run_id`, `corpus_hash` và `retriever_hash`.
Khi registry khai báo freeze, sidecar C phải có `freeze_hash` khớp. Registry phải trỏ tới
dataset manifest; runner tự recompute split/dataset-manifest hash và không chấp nhận chỉ
đổi mọi file sang cùng một hash giả.

Điền đường dẫn vào `configs/evaluation/oof_final.example.json`, lưu thành registry mới và
chạy:

```powershell
uv run --no-sync python scripts_a/run_final_oof.py `
  --registry <final-registry.json> `
  --output results/oof/final `
  --bootstrap-samples 10000
```

Đầu ra gồm `per_query.csv`, `quality_table.csv`, `utility.csv`, `summary.json` và
`comparison.json`. `utility.csv` là utility query-level của cặp baseline/candidate khai báo
trong registry; cấu hình chuẩn so sánh `s_star` với `pe_gh` theo nDCG@10. Runner dừng ngay
nếu file thiếu/thừa query, sai fold/method/split, trộn corpus hoặc trộn retriever trong
cùng file.
