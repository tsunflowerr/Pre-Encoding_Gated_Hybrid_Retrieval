# Trạng thái triển khai phần C

C1–C5 đã hoàn tất trên dữ liệu thật. Quy tắc nguồn, split và hash đầu vào nằm ở [protocol C0](C0_PROTOCOL.md); kết quả sau freeze và kiểm tra tích hợp nằm ở [tổng kết](EXECUTION_SUMMARY.md). Các đường dẫn `results/` là artifact local bị Git bỏ qua.

| Mốc | Kết quả chính | Artifact kiểm tra |
|---|---|---|
| C1 | Chọn H*/S* bằng validation cho 10 fold/miền | `results/fusion/selection_v1.json` |
| C2 | Khóa schema 21 feature và tập general 8 feature | `results/features/schema_v1.json` |
| C3 | Tạo 5.844 train và 1.948 validation examples | `results/training/c3_manifest.json` |
| C4 | Fit 20 scaler, 50 model trên train | `results/models/c4_manifest.json` |
| C5 | Factory online qua worker B, kiểm nhánh skip/dense | `results/c5_worker_smoke_v2/` |

## C1 — Fusion và chọn H*/S*

**Trạng thái:** hoàn tất triển khai và chọn trên validation ngày 24/10/2026.  
**Protocol:** `configs/gating/protocol_v1.yaml`  
**Report đầy đủ:** `results/fusion/selection_v1.json` (artifact máy local, bị Git bỏ qua).  
**Report SHA256/object hash:** `55e056ccc17c5f816f963b37828744bb2c409376e761b156161b05b313eb739c`

### Quy tắc đã thực thi

- CC min–max từng nhánh trên các hit có mặt; nhánh rỗng đóng góp 0, nhánh có range 0 đóng góp 1 cho hit hiện diện. Endpoint alpha 0/1 giữ thứ tự ranking gốc.
- RRF cộng `1 / (60 + rank)` trên các nhánh chứa document.
- H* chọn nDCG@10 cao nhất trong 9 alpha CC và RRF. Hòa trong `1e-6` ưu tiên RRF; nếu vẫn hòa giữa CC thì alpha nhỏ hơn trước.
- S* chọn trong BM25, dense, H*; hòa theo thứ tự đăng ký trong config.
- Chọn riêng từng fold và domain, dùng validation bucket `(fold + 1) % 5`. Không chấm điểm candidate trên test bucket.

### Kết quả lựa chọn

| Domain | Fold | Validation queries | H* | nDCG@10 validation | S* |
|---|---:|---:|---|---:|---|
| programmers | 0 | 175 | CC α=0.4 | 0.340237 | H* |
| programmers | 1 | 175 | CC α=0.5 | 0.329546 | H* |
| programmers | 2 | 175 | CC α=0.5 | 0.325182 | H* |
| programmers | 3 | 175 | CC α=0.4 | 0.351063 | H* |
| programmers | 4 | 176 | CC α=0.5 | 0.305721 | H* |
| unix | 0 | 215 | CC α=0.3 | 0.307575 | H* |
| unix | 1 | 214 | CC α=0.4 | 0.323975 | H* |
| unix | 2 | 214 | CC α=0.5 | 0.283935 | H* |
| unix | 3 | 214 | CC α=0.5 | 0.309906 | H* |
| unix | 4 | 215 | CC α=0.2 | 0.305974 | H* |

Report lưu metrics của cả BM25, dense, 9 CC, RRF, H*/S*, validation query hash,
split/corpus/retriever hashes, source/config hashes và quy tắc hòa. `report_hash`
đã được tính lại độc lập và khớp.

### Cách chạy lại

```powershell
.\.venv\Scripts\python.exe scripts_c\select_fusion.py
```

Chạy lại sẽ thay thế report local sau khi xác thực toàn bộ input hash. Fixture
`tests/c/test_fusion_contract.py` đã kiểm CC/RRF, nhánh rỗng, score hòa, endpoint,
quy tắc tie selection; C1 cũng đã thực thi trên ranking thật đủ 10 fold/miền.

## C2 — Feature trước dense

**Trạng thái:** hoàn tất schema, extractor và materialization ngày 24/10/2026.  
**Extractor:** `src/pegh/gating/features.py`  
**Schema:** `results/features/schema_v1.json` (artifact local, bị Git bỏ qua).  
**Materialized vectors:** `results/features/{programmers,unix}.jsonl` và sidecar.

### Schema đã ghim

- Full schema `full_v1_21`: `2a9acfd8245c202ba000ff1a546337a1dc3695d44a05cf79ababd697e756dd81`.
- General schema `general_v1_8`: `d0ec0e92e16648dbecf698a12464c0eeb70f2017cfc263305b2262fbcfa83426`.
- Dùng sparse tokenizer fingerprint A: `dcf142354e5beb4d72720ba36b0a574d43852b83ca13dcc7c51e4b6453036f61`.
- General feature lấy đúng index 1-based `4, 10, 11, 12, 15, 16, 19, 20`.

Các công thức theo thứ tự 21 feature được ghi trong schema JSON và bảng ở
`PE_GH_KE_HOACH_HOAN_CHINH_3_NGUOI_V2.md` §11.1. Quy tắc đã khóa gồm Unicode
code points cho độ dài, entropy Shannon dùng log tự nhiên, identifier ratio đếm
token sparse trước case-fold, và flat indicator dùng range `<= 1e-8`. IDF/OOV
lấy trực tiếp từ `SQLiteBM25.query_stats()`; không có tokenizer neural.

### Kết quả materialization

| Domain | Queries | Feature rows SHA256 |
|---|---:|---|
| programmers | 876 | `55e52f1b24fdba4023f8e6efcd581bf902a76c4a401aac95f00a3ba4ff20516a` |
| unix | 1.072 | `c981ccc31e6d7cd479dadb80994aa3957ff1f67e96647d91efc7413d4a8e8343` |

Đã đối chiếu 1.948 dòng: mỗi dòng có 21 giá trị hữu hạn; 8 giá trị general
khớp đúng phép chiếu từ full schema. Query stats được lấy một lần mỗi query và
ranking BM25 tái sử dụng từ cache C0; không chạy BM25 search lại. Materializer
không đọc qrels hoặc dùng utility/label.

### Chạy lại

```powershell
.\.venv\Scripts\python.exe scripts_c\materialize_features.py
```

Artifact chứa query features cả train/validation/test vì bước này không dùng
nhãn; C3 đã phân vai query theo `fold_record` trước khi tạo train/validation
tables. Không dùng các hàng test để fit scaler hoặc model.

## C3 — Train labels và control policies

**Trạng thái:** hoàn tất ngày 24/10/2026.  
**Builder:** `scripts_c/build_training_tables.py`  
**Recipe:** `configs/gating/labels_v1.yaml`  
**Manifest:** `results/training/c3_manifest.json` (artifact local, bị Git bỏ qua).  
**Manifest hash:** `c4f9cee905d7271be3c9f30e03a753c878915255051b225b85bf35307fff6d5d`

### Nội dung đã tạo

- 20 bảng JSONL tách riêng theo fold, domain và vai trò train/validation; tổng 7.792 example (5.844 train, 1.948 validation).
- Mỗi dòng có `x_01`…`x_21`, `U_B`, `U_H`, `delta_U`, `gain_binary_label`, `sparse_success_label`, group ID và `reference_hash` của H* fold/domain.
- Có thêm điểm control `identifier_margin_score`, `bm25_margin_score` và 30 cột random score với seed cố định 0–29.
- Giữ nguyên các hàng cả BM25 và H* đều có nDCG@10 bằng 0; có 3.080 train example dạng này.

### Recipe

- `U_B` và `U_H` là nDCG@10 của BM25 và H* đúng fold/domain; `delta_U = U_H - U_B`.
- `gain_binary_label = 1` khi `delta_U > 0`, nếu hòa hoặc âm thì 0.
- `sparse_success_label = 0` nếu BM25 có positive non-self qrel trong top 10; nếu không thì 1.
- `identifier_margin_score = max(identifier_present, -bm25_rel_gap12)`; `identifier_present` bật nếu có error identifier, path/flag hoặc identifier token.
- `bm25_margin_score = -bm25_rel_gap12`. Hai threshold control chỉ được chọn trên validation.
- Random score dùng SHA256(seed, NUL, canonical query ID), 64 bit đầu theo big-endian và biến đổi thành `1-u`; dense khi score lớn hơn threshold. Seed không được chọn theo kết quả.

Builder chỉ chuyển qrel relevance thành số cho train và validation IDs; query test bị bỏ qua khi lọc ID, nên qrel test không tham gia label hay utility. Không có test utility table. Các sidecar xác nhận ID membership theo `fold_record`, query scope, feature/schema/input hashes và reference selection hash. Có **3.080 train rows** giữ lại khi cả hai utility bằng 0.

### Chạy lại

```powershell
.\.venv\Scripts\python.exe scripts_c\build_training_tables.py
```

Validation labels được lưu riêng để dùng cho model/threshold selection; C4 đã chỉ fit scaler và model trên bảng `train.jsonl`.

## C4 — Model và scaler theo fold/miền

**Trạng thái:** hoàn tất ngày 24/10/2026.  
**Recipe:** `configs/gating/models_v1.yaml`  
**Trainer:** `scripts_c/train_gates.py`  
**Loader:** `src/pegh/gating/models.py`  
**Manifest local:** `results/models/c4_manifest.json`  
**Manifest hash:** `09526778cc932fee080abcd4f07840c65546f0ebda7fbeb2555f981cce3cefe1`

### Model đã fit

Mỗi fold/miền có một StandardScaler cho 21 feature và một cho 8 feature general. Chỉ train rows của fold/miền đó được dùng để fit scaler và model. Có 10 fold/miền, 20 scaler, 50 model và 9.740 dự đoán validation.

| Method | Features | Target | Output score |
|---|---:|---|---|
| `ridge_gain_full` | 21 | `delta_U` | Dự đoán gain nDCG@10 |
| `logistic_gain_full` | 21 | `gain_binary_label` | Xác suất nhãn gain dương |
| `logistic_sparse_success_full` | 21 | `sparse_success_label` | Xác suất BM25 không có relevant top-10 |
| `linear_svc_gain_general` | 8 | `gain_binary_label` | Signed margin cho nhãn gain dương |
| `ridge_gain_general` | 8 | `delta_U` | Dự đoán gain nDCG@10 |

Ridge dùng `alpha=1`; Logistic dùng `C=1`, `liblinear`; LinearSVC dùng `C=1`, `dual=false`. Mỗi model lưu manifest có train IDs hash, validation IDs hash, scaler train IDs hash, feature/target/reference/split/source hashes, phiên bản sklearn/numpy/scipy và checksum của model/scaler. `selected_threshold` để `null` cho C6 chọn từ validation.

### Kiểm tra artifact

- Mỗi scaler có `n_samples_seen_` bằng đúng số train rows; mean của 20 scaler khớp mean tính trực tiếp từ train table.
- Model/scaler được nạp lại từ file sau khi kiểm checksum và package versions; dự đoán validation từ bản nạp lại lệch model trong bộ nhớ nhiều nhất `4.44e-16`.
- 50 prediction files chứa đúng validation query IDs của `fold_record`; mọi điểm hữu hạn. Không tạo test predictions hay dùng test qrels.
- `uv.lock` chỉ thêm scikit-learn làm dependency trực tiếp; `uv sync --locked --python 3.12 --extra dev` đạt.

LinearSVC general có margin âm trên toàn bộ validation (`-1.99` đến `-0.168`). Điều này phản ánh độ lệch lớp trong dữ liệu và score vẫn dùng được để xếp thứ tự; C6 đã học threshold trong đơn vị margin, không lấy mốc 0 mặc định làm điểm vận hành.

### Chạy lại

```powershell
.\.venv\Scripts\python.exe scripts_c\train_gates.py
```

Model được serialize bằng pickle trong thư mục kết quả local. Loader chỉ nhận file có checksum và đúng phiên bản thư viện đã ghi. Các artifact này dành cho checkout/môi trường tin cậy của nhóm.

## C5 — Điều phối online và registry

`src/pegh/app/methods.py` thực hiện một request: query rỗng trả ranking rỗng; query khác rỗng gọi BM25 một lần, lấy stats, tạo feature, chấm gate. Nếu `score > threshold` hoặc toàn bộ token OOV thì gọi dense đúng một lần và fusion bằng H* đã chọn ở C1. Nhánh skip trả nguyên ranking BM25. Lỗi model/schema/index/dense được phát ra thành lỗi run; không biến thành kết quả skip.

`src/pegh/app/factories.py:create_gated_method` nạp model, scaler, encoder, index trước `search`. Factory đối chiếu checksum sparse/dense/protocol/selection/model, corpus, retriever, fold/miền, H* và schema. `.provenance` ghi các hash, fusion, model, threshold, chính sách OOV và việc không dùng cache query embedding hay quality. C dùng `TraceSink` của B: A đo `sparse`,`stats`; B đo `encode`,`vector`; C đo `features`,`gate`,`fusion`.

### Tạo registry cho B

Registry cần threshold **số hữu hạn do người chạy cung cấp**. Ở mốc C5 chưa chọn threshold tối ưu; C6 sau đó đã chọn bằng validation rồi freeze registry chính thức. Ví dụ kiểm tra nhánh skip (ngưỡng thử nghiệm rất cao):

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts_c\make_online_registry.py --domain programmers --fold 0 --method ridge_gain_full --threshold 1000000 --output results\c5_registry_smoke.json
.\.venv\Scripts\python.exe -X utf8 scripts_c\smoke_online.py --registry results\c5_registry_smoke.json --queries data\raw\programmers\queries.jsonl
```

Script registry nhận `--dense-dir` để chỉ index FAISS ở vị trí khác; mặc định dùng `%USERPROFILE%\.cache\pegh\artifacts\c0-v1\<domain>`, là đường dẫn ASCII đã dùng ở C0. Có thể chọn một trong năm method C4 qua `--method`. Registry đầu ra có `factory` và `kwargs` đúng giao diện benchmark worker của B. Nó nằm dưới `results/` và là artifact local, không phải registry C6 cuối cùng.

### Điều kiện bàn giao C6

- Chọn threshold từ validation theo protocol, ghi rõ lựa chọn, tie policy và điểm khả thi.
- Tạo registry cố định cho mỗi fold/miền/method; không dùng ngưỡng thử nghiệm C5 để chấm test.
- Chạy benchmark B với registry đã freeze, query warmup tách khỏi query đo. Worker B kiểm tra `encoder_calls` và các stage cho từng request.

### Kiểm tra C5 đã chạy

- Smoke artifact thật: `empty=0`, `skip=0`, `OOV dense=1 encoder call`; nhánh skip khớp nguyên `Ranking` của `SQLiteBM25`.
- Worker biệt lập của B: một request trên `programmers`, fold 0, chạy thành công với `TraceSink` chi tiết trong `results/c5_worker_smoke_v2/`.
- `ruff check` và `ruff format --check` đạt. Registry C5 hiện tại dùng threshold thử nghiệm để kiểm tra đường chạy, không dùng cho test cuối.

Lệnh kiểm tra worker một request:

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts_c\smoke_worker.py --registry results\c5_registry_smoke.json --queries data\raw\programmers\queries.jsonl --output results\c5_worker_smoke_moi
```
