# Phần C — Fusion, gate và điều phối PE-GH

**Trạng thái tài liệu:** kế hoạch triển khai, chưa phải báo cáo kết quả phần C.  
**Nguồn quy tắc:** `PE_GH_KE_HOACH_HOAN_CHINH_3_NGUOI_V2.md`, nhất là mục 8–12, 18–20 và 23.  
**Ngân sách trong kế hoạch nhóm:** 80 giờ.

Tài liệu này dùng các contracts và implementation đang có trên nhánh `quang` sau khi
nhận phần A từ `bao` (24/10/2026). Phần B đã có trong base; commit sửa/review B
`dc93e33` từ `origin/thanh` đã được đối chiếu và gộp vào `quang` tại `a73bea7`.

## 1. Mục tiêu, phạm vi và trạng thái đầu vào

C xây fusion, feature extractor, gate, chính sách chọn method và `SearchMethod`
online. Gate quyết định **sau BM25 và trước dense encoding**: query được skip phải
trả ranking BM25 đã có; query được chọn chạy dense mới encode, tìm FAISS và fusion.

| Đầu vào đã có | Nơi dùng | Điều kiện trước khi chạy dữ liệu thật |
|---|---|---|
| `contracts.types`, `contracts.ranking`, `contracts.io` | DTO, protocol, codec ranking-v1 | Không tạo types/loader riêng. |
| `data/splits/manifest.json`, `fold_0..4.json` | Train/validation/test theo group | Kiểm `split_hash`; mỗi query là test đúng một fold. |
| `pegh.sparse.SQLiteBM25` | `search`, `query_stats`, tokenizer và manifest | Index sparse phải cùng corpus hash với dense. |
| `pegh.evaluation.metrics` và `pegh.evaluation.oof` | Utility offline và đánh giá cuối | Qrels chỉ được mở trong job offline. |
| `pegh.dense.FaissDenseRetriever` | Nhánh dense, một encode/request | Index/model/config/version phải qua verifier của B. |
| `pegh.profiling.TraceSink` và benchmark CLI của B | Đếm calls và đo online | Factory nhận `trace`; load model/index ngoài `search`. |

Raw `data/raw/`, sparse/dense indices và full ranking runs bị loại khỏi Git. C0
đã hoàn tất ngày 24/10/2026: raw inputs, split, hai sparse index, hai dense
index và đủ 3.896 query-ranking đã được xác minh. Biên nhận
`results/c0_audit/receipt.json` có `status: passed`; metrics khớp baseline A.
Dense artifacts nằm trong `C:/Users/quang/.cache/pegh/artifacts/c0-v1/` vì
verifier FAISS trên Windows cần đường dẫn ASCII ở máy này. Hash đầy đủ ở
`docs/person_c/C0_PROTOCOL.md`.

### C sở hữu

```text
src/pegh/fusion/
src/pegh/gating/
src/pegh/app/               # orchestrator và factory cho benchmark
configs/fusion/
configs/gating/
scripts_c/
tests/c/
tests/integration/
docs/person_c/
paper/01_introduction.md
paper/02a_routing_related_work.md
paper/03_method.md
paper/05c_gate_analysis.md
```

A giữ `contracts/`, dữ liệu, BM25 và evaluator. B giữ `dense/`, `profiling/`,
`pyproject.toml`, `uv.lock` và CI. C gửi thay đổi contract/dependency cho chủ file
review; không đổi schema hay backend của họ để vừa với một adapter C. `scikit-learn`
cần được khai báo là dependency trực tiếp khi thêm Ridge/Logistic/SVM (hiện có trong
lockfile như dependency gián tiếp).

## 2. Hợp đồng chung C phải giữ

- Import `Query`, `Ranking`, `SearchHit`, `FeatureVector`, `GateDecision`,
  `SearchResponse` và các protocol từ `contracts.types`. `Ranking.validate()` và
  codec `ranking_to_record`/`ranking_from_record` là boundary của output.
- ID là chuỗi `domain:source_id`; không đổi text/ID, không dùng row FAISS làm ID.
  Mỗi ranking có score hữu hạn, ID duy nhất, rank liên tiếp, sắp theo score giảm
  rồi doc ID tăng; không có self-hit. `k=100` là số hit **sau** self-filter.
- Hai ranking đầu vào fusion phải cùng query ID, domain và `corpus_hash`. Hash
  corpus là SHA256 của đúng bytes canonical JSONL, không phải hash text sau parse.
  Output của mỗi **method đã đóng băng** có một `retriever_hash` phản ánh
  sparse/dense hashes, công thức, alpha/RRF config, gate/threshold nếu có và
  phiên bản code. Với PE-GH, cả nhánh skip lẫn nhánh fusion dùng cùng hash ở mức
  method cho fold/miền; nhánh skip giữ nguyên hits, scores và thứ tự BM25.
- `FeatureVector` full v1 có đúng 21 giá trị theo thứ tự ở mốc C2, cùng
  `schema_hash`; tập 8 feature đối chứng có hash riêng. Schema/model/scaler lệch
  phải lỗi trước search.
- `GateDecision.use_dense=True` nghĩa là **chạy dense**. `SearchResponse.use_dense`
  và `encoder_calls` phải khớp trace quan sát thực tế: skip = 0, dense = 1.
  `gate_score` giữ đơn vị của model (Ridge là dự đoán gain, Logistic là xác suất),
  không clip tùy tiện; `fallback_reason` phân biệt empty query và lỗi thật.
- Factory nhận keyword `trace`, trả object có `search(Query, k=100) -> SearchResponse`
  và `.provenance` là dict JSON serializable. Chỉ factory biết đường dẫn artifact;
  không hardcode cache của một người trong backend.
- Inference không mở qrels, utility table, offline ranking cache hoặc vector query
  đã lưu. Loader/model/index được tạo ngoài timer; không ghi disk trong `search`.

## 3. Thứ tự thực hiện và sản phẩm từng mốc

| Mốc | Giờ | Việc cần làm | Sản phẩm kiểm được |
|---|---:|---|---|
| C0 | 8 | Hoàn tất: protocol, rà B, khôi phục và xác minh dữ liệu/index/rankings | `docs/person_c/C0_PROTOCOL.md`, receipt `results/c0_audit/receipt.json` |
| C1 | 10 | Hoàn tất: implement CC/RRF; chọn H*/S* theo fold/miền trên validation | `src/pegh/fusion/`, `scripts_c/select_fusion.py`, `docs/person_c/IMPLEMENTATION_STATUS.md` |
| C2 | 8 | Hoàn tất: implement 21 feature và tập 8 feature chung | `src/pegh/gating/features.py`, `scripts_c/materialize_features.py`, `docs/person_c/IMPLEMENTATION_STATUS.md` |
| C3 | 10 | Hoàn tất: tạo train/validation labels và controls offline | `scripts_c/build_training_tables.py`, `configs/gating/labels_v1.yaml`, `docs/person_c/IMPLEMENTATION_STATUS.md` |
| C4 | 8 | Hoàn tất: fit scaler + Ridge/Logistic/LinearSVC trên train từng fold/miền | `scripts_c/train_gates.py`, `src/pegh/gating/models.py`, `docs/person_c/IMPLEMENTATION_STATUS.md` |
| C5 | 12 | Hoàn tất orchestrator, factory, registry và trace | `SearchMethod` chạy end-to-end với A/B, nhánh skip/dense đúng counters |
| C6 | 10 | Hoàn tất threshold validation, freeze, test runs, ablation/oracle và full online B | Frozen methods, 140 run + 140 sidecar, quality OOF A, 10 online run × 5 repeats |
| C7 | 8 | Hoàn tất báo cáo method/gate, review chéo và rerun local | Bốn paper sections, bốn figures, C7 facts và release script |
| C8 | 6 | Audit tích hợp online/offline, sửa số liệu paper sau full run | `docs/person_c/EXECUTION_SUMMARY.md`, 29.220 ranking parity, pooled latency có provenance |
| **Tổng** | **80** | | |

### C0 — Khóa giao nhận và dựng đầu vào

1. Dùng bản đã gộp commit `dc93e33` của B cho final profiling; giữ kiểm tra
   dependency/provenance/counters mới. Không sửa evidence v1 để giả như được đo
   bằng source mới.
2. Dùng `configs/data/cqadupstack.yaml`, `data/manifests/` và
   `data/splits/manifest.json` của A. Khôi phục raw corpus/queries/qrels, sparse
   index, dense index và top-100 runs; xác nhận domain/count/hash/method/query set.
3. Với mỗi fold `f`, dùng `fold_record(manifest, f)`: test bucket `f`, validation
   bucket `(f+1) % 5`, train ba bucket còn lại. Không mở qrels test trong C1–C5.
4. Chốt tên method, seed, fusion grid, feature recipe, label recipe, threshold
   rule và vị trí artifact trong config/manifest trước khi đánh giá test.

### C1 — Fusion và chọn reference

CC dùng `alpha_dense` với score min–max trên **các hit có mặt** trong từng ranking.
Document vắng một nhánh nhận contribution 0; nhánh rỗng cho 0; score range bằng
0 cho mọi hit hiện diện contribution 1. `alpha_dense=0/1` trả trực tiếp sparse/
dense ranking để tránh tie do normalization. Grid H* là alpha `{0.1, 0.2, ...,
0.9}` cộng RRF `k=60`; RRF dùng rank từ 1 và không đóng góp khi document vắng.

Trên validation từng fold/miền, H* là hybrid có nDCG@10 cao nhất; hòa trong
`1e-6` ưu tiên RRF. S* là lựa chọn static tốt nhất trong BM25, dense, H* trên
cùng validation. Lưu cả score các ứng viên, rule hòa, query IDs hash, corpus/
retriever hashes và lựa chọn đã chốt. Không nhìn test để đổi H* hoặc S*.

Nếu không có RRF trong nhóm hòa của H*, chọn CC có alpha nhỏ nhất; S* hòa theo
thứ tự ứng viên đã đăng ký (`bm25`, `dense`, `h_star`). Hai quy tắc này hoàn
thiện phân xử xác định trước khi chạy selector; không thay đổi metric/grid.

### C2 — Feature trước dense

Giữ đúng thứ tự full feature v1 của kế hoạch nhóm:

| # | Feature | Quy tắc chính |
|---:|---|---|
| 1–4 | `log_char_count`, `log_token_count`, `token_unique_ratio`, `token_entropy` | Raw chars và tokenizer sparse của A; mẫu rỗng trả 0. |
| 5–9 | `digit_char_ratio`, `code_punct_char_ratio`, `has_error_identifier`, `has_path_or_flag`, `identifier_token_ratio` | Regex/tập dấu/denominator được khóa và lưu schema. |
| 10–13 | `idf_min`, `idf_mean`, `idf_std`, `oov_ratio` | Lấy từ `SQLiteBM25.query_stats()` trên cùng index/tokenizer; không dựng IDF khác. |
| 14 | `hit_count_ratio` | `min(len(sparse.hits), 100) / 100`. |
| 15–18 | `bm25_top1`, `bm25_gap12`, `bm25_rel_gap12`, `bm25_rel_gap15` | Thiếu hit thì dùng quy tắc 0/s2=0 trong kế hoạch; mẫu số relative là `abs(s1)+1e-8`. |
| 19–21 | `bm25_top10_mean`, `bm25_top10_std`, `bm25_flat_indicator` | Chỉ các hit thực có; std quần thể; rỗng/thiếu hit có giá trị cố định. |

Tập 8 feature LiteGator-style dùng chỉ số `4, 10, 11, 12, 15, 16, 19, 20`.
Không gọi neural tokenizer/encoder để tính feature. Query text và sparse ranking
được dùng lại; BM25 không search lần thứ hai.

### C3–C4 — Nhãn, model và provenance

Sau khi H* của fold/miền đã chốt, tính trên **train**:

```text
U_B(q) = nDCG@10(BM25(q))
U_H(q) = nDCG@10(H*(q))
delta_U(q) = U_H(q) - U_B(q)
```

Dùng evaluator `pegh.evaluation.metrics` của A; giữ cả query có hai utility bằng
0. Ridge `alpha=1` học `delta_U`. Logistic `C=1` so nhãn `delta_U>0` với nhãn
`sparse-success` (BM25 có relevant top-10 hay không) trên cùng full features.
LinearSVC `C=1` dùng 8 general features và nhãn gain-binary; Ridge-general là
ablation feature. Scaler chỉ fit trên train; nếu gộp hai miền, cân trọng số để
mỗi miền đóng góp bằng nhau và không thêm domain ID mặc định.

Train table tối thiểu: `fold,domain,query_id,group_id,feature_schema_hash,
x_01..x_21,U_B,U_H,delta_U,sparse_success_label,reference_hash`. Model manifest
ghi family/hyperparameters, train IDs hash, scaler train IDs hash, target recipe,
feature hash, H* hash, split hash, validation IDs hash, dependency/source version.
Validation table lưu riêng; test utility chỉ sinh **sau freeze**.

### C5 — Orchestrator và online policy

Đường nonempty query:

```text
sparse.search(query, 100) + sparse.query_stats(query)
  -> feature_extractor.transform(query, sparse_ranking, stats)
  -> gate.decide(features)
  -> skip: SearchResponse(sparse_ranking, use_dense=False, encoder_calls=0)
  -> dense: dense.search(query, 100) -> fusion.fuse(sparse, dense, 100)
            -> SearchResponse(fused, use_dense=True, encoder_calls=1)
```

Trace stage hợp lệ là `sparse`, `stats`, `features`, `gate`, `encode`, `vector`,
`fusion`. A đã wrap sparse/stats; B đã wrap encode/vector; C chỉ wrap phần
features/gate/fusion của mình, tránh tính stage hai lần. `SearchResponse.encoder_calls`
là chênh lệch counter thật trong request, đối chiếu với trace của B. Nếu dùng
query vector cho method bổ sung, gọi `encode_query` một lần rồi
`search_vector` với **cùng vector trong request đó**.

Query rỗng trả empty ranking, zero calls và `fallback_reason="empty_query"`.
Nonempty OOV của sparse theo policy đã chốt phải route dense và tính vào tỷ lệ
dense thực. Gate score NaN, mismatch model/schema hoặc lỗi dense phải được ghi
rõ; benchmark chính không trộn request fallback lỗi với run thành công. Không
biến dense failure thành một skip hợp lệ. Output luôn qua `Ranking.validate()`.

### C6 — Threshold, freeze và test

Đăng ký trước 11 ngân sách mong muốn `0, 0.1, ..., 1`; chuyển phân vị score
**validation** thành các threshold số thực, có tie policy cố định. Không dùng
phân vị/top-m của test để quyết định online. Trong các điểm validation thỏa mất
macro nDCG so S* tối đa `0.005` và từng miền tối đa `0.01`, chọn tỷ lệ dense
thấp nhất; tie ưu tiên quality. Nếu không có, ghi `no_feasible_gated_point` và
dùng always-H* theo protocol, không gọi đó là gate thành công. Tỷ lệ dense test
bao gồm OOV/fallback thật.

Freeze H*/S*, scaler/model, feature schema, threshold, factories, source/config
hashes **trước** khi chấm test. Sau đó chạy đúng test bucket của mỗi fold/miền.
Random gate online dùng hash(query ID, seed) và tỷ lệ đã chọn; exact-budget random
30 seed trên test chỉ là phân tích batch sau freeze, không mô tả là router online
và không chọn seed tốt nhất.

Danh sách method của nghiên cứu, ngoài ba method A yêu cầu để chốt bảng chính:

| Nhóm | Method cần có | Vai trò |
|---|---|---|
| Static | BM25, dense, CC `alpha_dense=0.5`, RRF `k=60`, H*, S* | Mốc so chất lượng và chi phí; endpoint không chạy nhánh thừa. |
| Router đơn giản | Identifier + margin, BM25-margin, random cùng ngân sách | Kiểm tra gate có phân bổ compute tốt hơn quy tắc rẻ. |
| Router học | LiteGator-style LinearSVC, Logistic sparse-success, Logistic gain-binary | Đối chứng prior/target trên cùng dữ liệu và hạ tầng. |
| Phương pháp chính | Ridge gain full 21 feature (PE-GH) | Đo chất lượng và dense-call ratio ở operating point đã chọn. |
| Ablation/diagnostic | Ridge gain 8 feature, oracle gain/budget, random 30 seed | Phân tích nguồn lợi ích; oracle không phải method online. |

Các method ngoài `h_star`, `s_star`, `pe_gh` vẫn cần runs/metadata tương ứng để
trình bày đầy đủ các đối chứng trong paper; bộ 30 run là **hợp đồng tối thiểu**
để unblock final OOF registry hiện tại của A.

## 4. Hợp đồng artifact bàn giao

### Cho A: chất lượng cuối

`docs/person_a/RUNS_REQUIRED_FROM_C.md` và
`configs/evaluation/oof_final.example.json` là contract nhận hiện hành. C phải
cung cấp **30 file JSONL ranking-v1 và 30 sidecar `.meta.json`**: `h_star`,
`s_star`, `pe_gh` × `programmers`, `unix` × fold `0..4`.

- Mỗi file có đúng query IDs ở `data/splits/fold_<f>.json`, `domains.<domain>.test`,
  đúng thứ tự đã đăng ký; mỗi record có `schema_version="1.0"`, `method`,
  `split="test"`, `fold`, `run_id`, `corpus_hash`, `retriever_hash`, tối đa 100 hits.
- Mỗi file dùng một `retriever_hash`; khác fold được phép khác hash. Không sửa
  `corpus_hash` của dense/BM25 để vượt check.
- Sidecar có ít nhất `ranking_sha256`, `query_ids_hash`, `query_count`,
  `split_hash`, `domain`, `method`, `fold`, `split`, `run_id`, `corpus_hash`;
  thêm model/feature/reference/selection hashes để audit C. Không overwrite run
  hoàn thành; run mới dùng ID mới và ghi quan hệ supersedes nếu cần.
- Điền đường dẫn thực vào bản sao registry mẫu rồi dùng
  `scripts_a/run_final_oof.py` để sinh per-query, quality table, utility,
  comparison và paired CI. A sở hữu kết luận chất lượng và report quality.

### Cho B: đo online thật

Registry của B trỏ tới factory C theo dạng
`"factory":"pegh.app.factories:<name>"`; `kwargs` trỏ frozen config/index/model,
factory nhận `trace`. `.provenance` cần chứa sparse/dense corpus/index/retriever
hashes, feature/gate/fusion/threshold/split/config hashes, không chứa secret.
B tạo query files và warmup train/validation tách test; mọi method được chạy
cùng runtime profile, một process/method/repetition, năm repeats. Timer ôm trọn
`SearchMethod.search`; không dùng offline ranking/embedding cache trong online
factory. Report phải tách mean/p95, CPU/RSS, dense-call ratio và stage costs.

## 5. Kiểm tra và điều kiện nghiệm thu

Các kiểm tra dưới đây là việc **phải thực hiện khi triển khai**, không phải lời
khẳng định test C hiện đã tồn tại:

- Fusion: rankings rời nhau, score flat/negative, nhánh rỗng, alpha endpoints,
  RRF rank từ 1, tie ở cutoff, corpus/query/domain mismatch và top-100.
- Feature: 21 chiều đúng thứ tự, 8 chiều đúng subset, missing hits/OOV/empty
  query, tokenizer/IDF khớp A, schema hash thay khi recipe thay.
- Training: train-only scaler, nhãn gain theo đúng H* của fold/miền, trường hợp
  BM25 và hybrid cùng fail, không mở qrels test trước freeze.
- Integration: spy dense ném lỗi nếu nhánh skip chạm dense; nhánh dense gọi
  encoder đúng một lần; BM25 không search lặp; trace và response counters khớp.
- Artifact: save/load model/factory giữ ranking; thay config/index/schema/hash
  phải fail fast; A OOF runner nhận đủ 30 file/sidecar và từ chối thiếu/thừa query.
- Release: baseline và gate dùng cùng corpus/model/resource profile; final test
  báo cả kết quả âm. Không suy speedup từ số dense calls hoặc dùng CI latency để
  kết luận non-inferiority quality.

## 6. Thứ tự CLI dự kiến và điểm chặn

Các CLI `scripts_c/*` dưới đây là **đầu ra cần triển khai**, chưa tồn tại. CLI A/B
đã có nhưng cần đúng raw artifacts tại máy chạy:

```text
1. A: fetch/prepare data; build sparse; tạo full BM25 run.
2. B: verify/build dense; tạo full dense run trên cùng canonical corpus.
3. C: select_fusion -> H*/S* manifests cho 5 fold × 2 miền.
4. C: build_train_table -> train_gates -> select_thresholds -> freeze_methods.
5. C: export test ranking-v1 + sidecar cho h_star/s_star/pe_gh.
6. A: run_final_oof.py với registry không còn REPLACE.
7. B: benchmark_online.py với frozen SearchMethod registry và test query files.
8. C: report_gating từ raw quality/latency/provenance; viết paper sections.
```

Mốc 1–2 là điều kiện để học từ dữ liệu thật. C1, C2 và nhánh skip của C5 có thể
phát triển ngay bằng fixture chung và spy backend. Không lấy fixture để chọn
alpha/model/threshold hoặc điền số vào paper.

## 7. Checklist hoàn thành phần C

- [x] `origin/thanh` đã được xem xét/tích hợp trước khi freeze benchmark.
- [x] Raw data và sparse/dense artifacts được kiểm SHA theo manifest A/B (C0).
- [x] CC/RRF, H*/S* selection và tie/missing-score policies có kết quả fixture.
- [x] C1 được chạy trên validation của đủ 5 fold × 2 miền; report hash và toàn bộ candidate metrics đã lưu.
- [x] C2 full/general feature schema được ghim hash; materialized vectors có đủ chiều và hữu hạn.
- [x] C3 train/validation tables được tách theo fold; target/control recipes và reference provenance đã ghi.
- [x] Full/general feature schema, target recipe, scaler và model có hash/version.
- [x] Train/validation/test được tách theo fold; threshold chỉ từ validation.
- [x] SearchMethod của C chạy qua factory/TraceSink của B, không đọc quality cache.
- [x] Skip thực sự có 0 encode/vector calls; dense có đúng 1 encode/request.
- [x] Có các đối chứng bắt buộc, ablation và 30-seed random diagnostic đầy đủ cho chất lượng offline.
- [x] A nhận đủ 30 ranking-v1 + 30 sidecar và đánh giá OOF không lỗi; thêm 100 run đối chứng.
- [x] B chạy online cùng frozen methods; report tách quality, latency, CPU, RSS.
- [x] Paper C nêu rõ kết quả âm, giới hạn và provenance; script dựng lại bảng/hình.

Khi vượt quá ngân sách, bỏ adaptive alpha, tree/forest/boosting và feature mở
rộng trước. Giữ Ridge/Logistic/LinearSVC, margin/random baselines, kiểm split,
IDCG, counters và mọi đầu ra A/B cần để kết luận PE-GH một cách hợp lệ.
