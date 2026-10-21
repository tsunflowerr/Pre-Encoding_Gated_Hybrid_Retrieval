# Base dùng chung cho A, B, C

Nhánh `main` chứa base chung và phần B đã hoàn thành. A và C nên tạo nhánh làm
việc từ base này để cùng dùng một bộ contracts, fixture và lockfile. Không tạo
`Document`, `Query`, `Hit` hoặc loader riêng trong module của từng người.

## 1. Public API

```python
from contracts import Document, Query, SearchHit, Ranking
from contracts.ids import canonical_id
from contracts.io import iter_corpus, iter_queries, load_queries
from contracts.model import get_primary_model
from contracts.ranking import ranking_from_record, ranking_to_record, dumps_ranking
from contracts.text import build_document_text
```

Contracts chỉ dùng Python standard library; import không load Torch/FAISS/model.
Các protocol `SparseBackend`, `DenseBackend`, `FusionEngine`, `FeatureExtractor`,
`Gate`, `SearchMethod` và `SearchResponse` ở `contracts.types` đã có để A/C nối vào B.

| Kiểu | Fields | Quy tắc |
|---|---|---|
| `Document` | `doc_id, domain, title, body` | Immutable; `text` là property dựng theo policy chung |
| `Query` | `query_id, domain, text` | Immutable; giữ nguyên text, cho phép empty query để adapter xử lý |
| `SearchHit` | `doc_id, score, rank` | ID canonical, score hữu hạn, rank nguyên từ 1 |
| `Ranking` | `query_id, domain, hits, corpus_hash, retriever_hash` | `hits` là tuple SearchHit; gọi `validate()` ở boundary |

`Hit is SearchHit`: tên `Hit` cũ của B là alias chính xác, không có hai class khác
nhau. Score từ NumPy/engine phải chuyển sang Python `float` trước tạo SearchHit.
Ranking cho phép score âm, không yêu cầu score BM25 và dense có cùng thang đo.

## 2. ID chuẩn

`domain:source_id`, ví dụ `unix:001` và `programmers:001` là hai document khác nhau.
Domain dùng chữ thường `[a-z][a-z0-9_-]*`; source ID bắt đầu bằng chữ/số và chỉ
chứa ASCII chữ/số, `_`, `-`, `.`. ID trong DTO/ranking luôn có namespace.

```python
assert canonical_id("001", "unix") == "unix:001"
assert canonical_id("unix:001", "unix") == "unix:001"
```

Không cast integer, strip, lowercase, thêm namespace lần hai, hoặc dùng FAISS row
number thay source ID. ID integer, ID khác domain, khoảng trắng hoặc dấu `:` thêm
sẽ bị từ chối. Qrels của A phải áp dụng cùng hàm cho query ID và document ID.
Nếu query ID trùng document ID thì backend bỏ chính self-hit đó trước trả ranking.

## 3. Text policy chung

Policy: `join_nonempty_title_text_newline_v1`.

```python
text = "\n".join(part for part in (title, body) if part)
```

Không thêm newline khi một phần là chuỗi rỗng; không strip phần không rỗng,
lowercase, sửa Unicode, bỏ code/HTML hoặc thay khoảng trắng. Ví dụ title `"T"`,
body `"\n  x = 1\n"` cho `"T\n\n  x = 1\n"`. Không tự ghép title hai lần.
Document có cả title/body rỗng hoặc chỉ whitespace bị từ chối. `None` không được
coi là chuỗi rỗng. Query.text giữ đúng nội dung file; empty query được test riêng
và không gọi dense encoder theo adapter B.

BM25 tokenizer có thể chuẩn hóa token trong bước riêng của A, nhưng không sửa
`Document.text` hoặc ghi corpus khác cho mỗi method.

## 4. Corpus iterator và file boundary

```python
documents = iter_corpus("tests/fixtures/shared/unix/corpus.jsonl", "unix")
for document in documents:
    sparse_index.add(document.doc_id, document.text)  # API add là ví dụ adapter A

queries = load_queries("tests/fixtures/shared/unix/queries.jsonl", "unix")
```

Iterator giữ thứ tự dòng, đọc từng record, không nạp toàn corpus text vào RAM;
chỉ giữ tập IDs để phát hiện trùng. Hai ID raw/canonical trỏ cùng document cũng
bị coi là trùng. `iter_queries` là bản streaming; `load_queries` trả list tiện dùng.
Domain luôn truyền tường minh, record có domain khác sẽ lỗi.

File corpus chuẩn BEIR-compatible:

```json
{"_id":"001","title":"A title","text":"The body, not the joined retrieval text"}
```

Ở **corpus JSONL**, `text` nghĩa là body nguồn. Sau load, `Document.body` chứa phần
này và `Document.text` là title+body đã dựng. Loader cũng nhận `doc_id` thay `_id`,
`body` thay `text`; nếu cùng xuất hiện thì các aliases phải thống nhất. Không
ghi joined text vào `text` rồi vẫn giữ title. Query JSONL dùng `_id`/`query_id`
và `text`, không ghép title.

Giữ nguyên canonical JSONL bytes và ordering khi chia sẻ với B. `corpus_hash` ở
ranking B là SHA256 của **đúng bytes file**, không phải hash danh sách đã parse.
Cùng document count hoặc text chưa đảm bảo cùng file hash. A có thể nhận trực tiếp
JSONL/manifest đã có trong `C:/Users/quang/.cache/pegh/data`; nếu đổi bytes/order,
B cần artifact mới. Không thay field hash để vượt compatibility check.

## 5. Schema ranking v1

Schema: [ranking-v1.schema.json](../contracts/schemas/ranking-v1.schema.json).
`schema_version="1.0"`; required: `query_id,domain,hits,corpus_hash,retriever_hash`.
Metadata tùy chọn: `method,split,run_id,fold`. Không chấp nhận fields lạ. Fold là
null hoặc số nguyên không âm; method/split/run_id nếu có phải là chuỗi không rỗng.

```python
ranking = Ranking(
    query_id="unix:q01",
    domain="unix",
    hits=(SearchHit("unix:001", 0.9, 1), SearchHit("unix:002", 0.4, 2)),
    corpus_hash="fixture-corpus",       # production dùng hash canonical corpus
    retriever_hash="fixture-retriever", # production dùng fingerprint retriever
)
record = ranking_to_record(ranking, method="bm25", split="fixture")
assert ranking_from_record(record) == ranking
line = dumps_ranking(ranking, method="bm25", split="fixture")
```

`Ranking.validate()` và codec kiểm unique doc IDs, rank liên tiếp từ 1, cùng miền,
không self-hit, score hữu hạn; thứ tự score giảm dần, hòa score thì doc_id tăng dần
theo Python string order. Empty ranking hợp lệ. Giữ score chính xác, không round
trước sort/serialize. JSON Schema kiểm cấu trúc; các ràng buộc giữa fields/thứ tự/
self-hit cần validator Python, không chỉ dùng JSON Schema rồi bỏ semantic checks.

Không cần cast schema thành dict thủ công theo từng method. Format vẫn đọc được
quality outputs v1 của B; validation mới thực thi chặt các quy tắc đã thống nhất.
`Hit` alias không thay wire fields hoặc thứ tự/ID của artifact cũ. Hai CLI B cho
quality export/online benchmark dùng query loader chung; exporter gọi chính codec
này để các kết quả mới không hình thành một schema riêng.

## 6. Fixture chung

[`tests/fixtures/shared`](../tests/fixtures/shared/manifest.json): **20 documents**,
10 programmers +10 unix, **6 queries**, có query ID trùng một document để kiểm
self-filter. Có trường hợp title/body rỗng riêng lẻ, code, Unicode, leading-zero
ID và whitespace cần bảo toàn. Manifest ghi counts và SHA256 từng file.

Fixture được tự viết cho integration/correctness, không phải benchmark hoặc
relevance labels; không dùng score minh họa làm ground truth nghiên cứu. A có thể
dựng toy BM25 trên 10 docs/domain; C nối sparse/dense qua cùng contracts và fixture
trước train gate. Dataset thật, qrels và split vẫn do A quản lý.

## 7. Model chính và revision

Nguồn chung: [`contracts/resources/primary_model.json`](../contracts/resources/primary_model.json).
Đọc bằng `get_primary_model()`; không copy model ID/revision vào code A/C.

| Field | Giá trị |
|---|---|
| model_id | sentence-transformers/msmarco-MiniLM-L6-cos-v5 |
| revision | 14ca9be4bbcf1402eac0f43a2e2ccb6e0f994ba3 |
| dimension | 384 |
| max_length | 256 |
| device/dtype | cpu / float32 |
| normalize | true |

```python
from dataclasses import asdict
from pegh.dense.config import DenseConfig

dense_config = DenseConfig(**asdict(get_primary_model()))
```

DenseConfig/default YAML và B corpus parser thuộc snapshot đã khóa vào fingerprint
các index v1. B giữ nguyên bốn file encoder/config/corpus/index; parser nội bộ B
không phải API để A/C mở rộng. `scripts_shared/check_base.py` và CI kiểm defaults/
YAML khớp registry, và iterator chung trả cùng `(doc_id,text)` với B v1. Đây là
compatibility boundary có kiểm tra; không sửa fingerprint hoặc rebuild toàn bộ
index chỉ để đổi vị trí code. Nếu đổi text/model semantics, phải version/config và
rebuild artifact thay vì cập nhật snapshot âm thầm.

## 8. Chạy kiểm tra và hợp nhất

Từ repository root, cài theo `uv.lock`:

```powershell
uv sync --locked --extra dev
uv run --no-sync python scripts_shared/check_base.py
uv run --no-sync pytest tests/shared tests/b -m 'not model' -q
# Có pinned model trong cache hoặc có mạng:
uv run --no-sync pytest tests/b/test_model.py -m model -q
```

Kiểm cùng parser B trên corpus thật:

```powershell
uv run --no-sync python scripts_shared/check_base.py --corpus <corpus.jsonl> --domain unix
```

A và C tạo branch từ cùng commit của `main`; A/C sửa module của mình
và thêm tests riêng, cùng import contracts. Khi cần thêm field/model/config thì
review contract chung trước; không tự đổi ranking envelope, text hoặc ID policy.
B quản lý dependency/lockfile chung, A quản lý canonical data/qrels/split; C quản
lý factory/gate/fusion. CI chạy shared+B tests ở cả hai cấu hình OS đã khai báo.

Kết quả đã chạy và giới hạn kiểm chứng nằm trong
[SHARED_BASE_VALIDATION.md](SHARED_BASE_VALIDATION.md).
