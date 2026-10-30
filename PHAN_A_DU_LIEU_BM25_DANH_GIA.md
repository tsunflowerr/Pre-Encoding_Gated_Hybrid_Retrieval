# Phần A — Dữ liệu, BM25 và đánh giá

Tài liệu này chuyển gói A trong kế hoạch nhóm thành một backlog triển khai có thứ
tự, đầu ra và điều kiện nghiệm thu cụ thể. Phần A dùng contracts chung hiện có và
không định nghĩa lại `Document`, `Query`, `Ranking` hoặc chính sách ID/text.

> **Nghiệm thu A ngày 30/10/2026:** đã hoàn thành dữ liệu/BM25/provider parity,
> nhận đủ run C, strict OOF 14 phương pháp, utility H*/S*, CI, ba hình cuối và 40 routing
> cases. PE-GH macro nDCG@10 0,312163, S* 0,314625; cận dưới một phía 95%
> -0,006009 > -0,01. Rerun trong clone local cộng patch A đạt 131 test gồm model thật.
> Xem [biên bản đóng A](docs/person_a/EXECUTION_SUMMARY.md) và
> [paper chất lượng](paper/05a_quality_results.md).

## 1. Mục tiêu và ranh giới

A sở hữu ba lớp nền tảng:

1. dữ liệu/qrels/split có provenance và không leakage;
2. sparse retrieval và lexical statistics dùng cùng tokenizer/corpus;
3. quality evaluation, utility và paired uncertainty cho mọi method.

A không sở hữu dense/FAISS/profiling của B, cũng không chọn feature/gate/fusion của
C. A nhận ranking v1 từ B/C và chấm qua cùng evaluator.

## 2. Backlog 80 giờ

| ID | Giờ | Việc | Đầu ra | Trạng thái code |
|---|---:|---|---|---|
| A0 | 6 | Review contracts, ID, text, fixture và protocol | shared contract được tái sử dụng | Hoàn thành |
| A1 | 8 | Audit nguồn, qrels và coverage | dataset manifest/checksum | Hoàn thành dữ liệu thật |
| A2 | 14 | Loader qrels, validation, grouping và five-fold split | `fold_0..4.json`, split manifest | Hoàn thành dữ liệu thật |
| A3 | 10 | BM25 index/search/save-load và query stats | SQLite index, top-100 ranking v1 | Hoàn thành dữ liệu thật |
| A4 | 12 | nDCG/MRR/Recall, utility, aggregation và bootstrap | per-query/summary/CI | Hoàn thành OOF cuối |
| A5 | 10 | CLI build/run/evaluate/utility | scripts tái lập | Hoàn thành và kiểm rerun |
| A6 | 8 | Đối chiếu provider chuẩn và failure/coverage audit | validation report | Hoàn thành BM25 thật |
| A7 | 8 | Bảng/hình chất lượng, paper và clean rerun | report release | Hoàn thành final và 40 routing cases |
| A8 | 4 | Dự phòng sửa integration/data | issue log | Đã sửa rerun output cũ, có regression tests |

Trạng thái trên dựa vào artifact dữ liệu/thực nghiệm thật và receipt kiểm tra ngày
30/10. Fixture vẫn dùng để bắt lỗi hợp đồng; số nghiên cứu lấy từ OOF thật.

## 3. Thứ tự thực hiện

### Mốc A0 — khóa boundary

- Import types/loader/ranking codec từ `contracts`.
- Giữ ID `domain:source_id`, text policy và self-filter thống nhất với B.
- Ranking sparse dùng schema v1 để C fusion và A evaluator đọc trực tiếp.

### Mốc A1 — dữ liệu thật

- Chuẩn bị `corpus.jsonl`, `queries.jsonl`, `qrels.tsv` cho `programmers`, `unix`.
- Pin source revision, lưu SHA256 và row counts.
- Chạy audit: unique IDs, qrels trỏ đúng corpus/query, báo query thiếu qrels.
- Không sửa raw text hoặc thay ordering sau khi B đã build index; nếu đổi bytes phải
  báo B rebuild dense artifact.

### Mốc A2 — split

- Group query có normalized text giống nhau.
- Group query cùng relevant document; nếu relevant document cũng là query ID thì
  nối cùng component.
- Greedy-balance component vào năm bucket, seed 42.
- Fold f: test bucket f, validation bucket (f+1) mod 5, train ba bucket còn lại.
- Validation bắt buộc: disjoint trong fold và mỗi query test đúng một lần.

### Mốc A3 — sparse

- Tokenizer kỹ thuật v1: Unicode word/identifier/flag, casefold, không sửa raw text.
- BM25 Robertson với `k1=1.2`, `b=0.75`, IDF
  `log(1 + (N-df+0.5)/(df+0.5))`.
- SQLite artifact giữ doc length, postings, df/idf và mapping ID.
- Search loại exact self-hit, sort `score desc, doc_id asc`, trả tối đa top-100.
- `query_stats` dùng đúng tokenizer/vocab/index trên.

Backend này là implementation BM25 chuẩn, dependency-free để correctness và
integration chạy ngay. Trước số cuối, A phải đối chiếu toy/full sample với provider
đã đăng ký (`ir_measures` cho metrics và BM25S/Pyserini nếu nhóm chọn), rồi ghi rõ
backend thực tế; không gọi hai backend khác nhau là cùng baseline.

### Mốc A4 — evaluator

- nDCG@10 dùng IDCG từ toàn bộ qrels, không chỉ candidate tìm thấy.
- MRR@10, Recall@10 và Recall@100 tính trên mọi expected query; missing run = 0.
- Self qrel được loại khi `remove_self=true`, khớp retrieval self-filter.
- Utility `delta = nDCG(candidate)-nDCG(bm25)` xuất theo query cho C.
- Bootstrap paired theo query group, seed 20261019; báo one-sided lower 95% và
  two-sided 95%. CI này không bao quát bất định retraining/model selection.

### Mốc A5–A7 — run và bàn giao

1. Build BM25 từng domain.
2. Xuất sparse top-100 cho toàn query, có corpus/retriever hash.
3. Nhận dense/hybrid/gate runs theo ranking v1.
4. Chỉ dùng train/validation để chọn; test được tổng hợp out-of-fold sau freeze.
5. Xuất per-query CSV, summary JSON, utility JSONL và provenance.
6. Đối chiếu evaluator trên toy cases và provider chuẩn trước khi viết claim.

## 4. Lệnh chuẩn

```powershell
python scripts_a/prepare_data.py --config configs/data/cqadupstack.yaml
python scripts_a/build_sparse.py --config configs/sparse/bm25.yaml --corpus <corpus.jsonl> --domain unix --output <index_dir>
python scripts_a/generate_sparse_runs.py --index <index_dir> --queries <queries.jsonl> --output <bm25.jsonl> --split validation
python scripts_a/evaluate_quality.py --queries <queries.jsonl> --qrels <qrels.tsv> --run <bm25.jsonl> --domain unix --output <result_dir>
python scripts_a/build_utility.py --queries <queries.jsonl> --qrels <qrels.tsv> --baseline-run <bm25.jsonl> --candidate-run <hybrid.jsonl> --domain unix --output <utility.jsonl>
python -m pytest tests/shared tests/a -q
```

## 5. Definition of done

- Dataset manifest có checksums/counts/coverage và không có dangling qrels.
- Năm fold disjoint; mỗi query test đúng một lần; group không bị tách.
- BM25 save/load giữ nguyên ranking, tokenizer hash và corpus hash.
- Empty/OOV query có hành vi định trước; self-hit không xuất hiện.
- Evaluator bắt case hai relevant nhưng run tìm một relevant ở rank 1: nDCG@10
  xấp xỉ 0.613147.
- Missing query được tính 0, Recall@100 đọc top-100 thật.
- Utility join từ đúng query/domain/corpus-compatible runs.
- Một người khác chạy lại từ config và tạo cùng artifacts trong sai số đã định.

## 6. Tích hợp và giới hạn bàn giao

- Dữ liệu/qrels raw và artifact lớn không commit vào Git; revision, checksum, manifests và
  split được lưu để tái tạo.
- `uv` 0.13.3, lockfile, ruff và CI đã được kiểm tra trong môi trường hiện tại.
- BM25S 0.3.14 và `ir-measures` 0.4.3 đã đối chiếu trên toàn bộ dữ liệu thật và đạt tolerance.
- Đã nhận đủ 30 C output test-fold cùng sidecar; H*/S*/PE-GH, utility và CI đã chốt.
  Contract cho lượt mới nằm tại `docs/person_a/RUNS_REQUIRED_FROM_C.md`.
- Đo thêm online các baseline margin/LiteGator-style và ghép toàn bộ paper thuộc phần
  tích hợp B/C của dự án; đây không còn là blocker đầu vào của A.
- Patch bàn giao hiện chưa commit. Clean rerun local dùng clone có `.git`, exact source
  overlay và môi trường/cache đã khóa; xem `docs/person_a/validation/CLEAN_RERUN.md`.
