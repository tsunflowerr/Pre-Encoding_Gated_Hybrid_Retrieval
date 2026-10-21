# Fixture chung A/B/C

20 documents tự viết: 10 programmers và 10 unix; 6 queries, 3 mỗi domain. Đây là
fixture kiểm tính đúng/integration, không phải benchmark hoặc relevance labels.

- `DOMAIN/corpus.jsonl`: BEIR-compatible `_id,title,text`; `text` là body nguồn.
- `DOMAIN/queries.jsonl`: `_id,text`, có một query cùng ID với document để test self-filter.
- `manifest.json`: counts, text policy và SHA256 của cả bốn JSONL files.

Đọc qua `contracts.io.iter_corpus/load_queries`, không tự ghép title/text hay đổi
ID. Xem [base chung](../../../docs/SHARED_BASE.md) để biết API và model revision.

Kiểm từ repository root: `python scripts_shared/check_base.py`.
