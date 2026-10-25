# C0 — Giao nhận, nguồn tham khảo và protocol trước khi triển khai C

**Ngày khóa bản đầu:** 24/10/2026 (Asia/Bangkok).  
**Nguồn quy tắc:** kế hoạch nhóm V2, `PHAN_C_FUSION_GATE_DIEU_PHOI.md` và
`configs/gating/protocol_v1.yaml`. File YAML là các lựa chọn cần thực thi; thay
đổi sau khi xem test phải có phiên bản mới và lý do, không sửa âm thầm bản này.

## 1. Tình trạng nhánh và điều kiện tích hợp

`quang` đã nhận `bao` (A, commit `522f6ba`) và `thanh` (B review, commit
`dc93e33`) qua merge commit `a73bea7`. Lần rà B trước merge thấy 16 file đổi,
không có file nào trùng với commit A. B bổ sung các điều kiện mà factory C phải
tuân thủ:

| Thay đổi B | Tác động trực tiếp tới C |
|---|---|
| Dense retriever so đầy đủ `package_versions` với index manifest | Dùng đúng môi trường đã khóa hoặc build index mới; không bỏ check để load artifact cũ. |
| Worker test đòi `.provenance` là dict không rỗng | Factory C phải bind model, index, corpus, fusion, feature, gate, split và threshold. |
| Worker từ chối hơn một scope `sparse`/request | Lấy BM25 một lần và dùng lại ranking cho feature/fusion. |
| Reporter bind `queries_hash` và `method_provenance_hash` | A/B chỉ ghép quality và latency khi hai giá trị cùng nguồn; C cung cấp provenance ổn định giữa repetitions. |
| Runner chỉ nhận một domain/run, warmup cùng domain | Tạo registry và chạy hai miền riêng; không chia RSS của một process hỗn hợp. |
| Source snapshot neo vào checkout, report kiểm request/source/runtime drift | Giữ source/config/artifacts bất biến trong một run; run mới sau khi sửa code. |

Các thay đổi này không sửa embedding fingerprint hoặc bytes của bằng chứng B v1.
Run mới dùng source snapshot mới, không đổi metadata của run v1.

## 2. Đối chiếu công trình liên quan

| Công trình gốc | Cơ chế liên quan | Quyết định cho PE-GH |
|---|---|---|
| [Arabzadeh, Yan & Clarke (2021)](https://arxiv.org/abs/2109.10739) | Phân loại query để chọn sparse, dense hoặc hybrid theo chi phí và utility. | Báo đây là prior work trực tiếp về routing; thêm đối chứng nhãn sparse-success, không gọi routing nói chung là mới. |
| [LiteGator (2025)](https://www.atlantis-press.com/article/126020510.pdf) | Router dùng ít feature có thể giải thích và linear SVM để chọn sparse/dense. | Chạy adaptation LinearSVC với 8 feature chung trong cùng hạ tầng; ghi rõ khác biệt về target, encoder và dữ liệu. |
| [Query-Adaptive Hybrid Search / QDAP (2026)](https://www.mdpi.com/2504-4990/8/4/91) | Dự đoán trọng số fusion theo query representation. | Tách quyết định **có encode dense hay không** khỏi bài toán chọn alpha; QDAP-inspired adaptive alpha chỉ là extension. |

**Nhận định của nhóm:** PE-GH kiểm tra xem dự đoán *lợi ích nDCG@10 của hành
động H* so với BM25* bằng tín hiệu sẵn trước dense có giảm chi phí mà vẫn giữ
chất lượng hay không. Đây là giả thuyết thực nghiệm, chưa phải kết quả hoặc
khẳng định tính mới đã được chứng minh.

## 3. Câu hỏi và quy tắc đã khóa

1. **RQ1:** H* giúp bao nhiêu query so với BM25 trên train/validation, và có
   đủ headroom cho gate? Báo phân bố `delta_U`, kể cả query hai method cùng 0.
2. **RQ2:** PE-GH giảm dense-call ratio và latency ở chất lượng chấp nhận được
   so với S*/H* không? Chọn operating point bằng validation; A chấm test và B
   đo online trên method đã đóng băng.
3. **RQ3:** Lợi ích chọn query có vượt random/margin/LiteGator-style và ablation
   cùng điều kiện không? Báo kết quả âm nếu không vượt.

Quy tắc số học và tie policy trong `protocol_v1.yaml`:

- H*: CC `alpha_dense=0.1..0.9` hoặc RRF `k=60` thắng validation nDCG@10;
  hòa trong `1e-6` ưu tiên RRF. S*: tốt nhất của BM25, dense, H* trên validation.
- Tập feature full 21 chiều, general 8 chiều; regex/tập dấu được ghi trong YAML.
  `SQLiteBM25.query_stats()` là nguồn IDF/OOV/token count duy nhất. Mọi recipe
  còn cần triển khai phải xuất schema hash và không thay sau khi train.
- Gate chính: StandardScaler fit train và Ridge `alpha=1` dự đoán
  `nDCG@10(H*) - nDCG@10(BM25)`. Hai Logistic `C=1` và LinearSVC `C=1` là
  đối chứng theo đúng target/feature đã quy định.
- 11 ngân sách mong muốn dùng score validation để tạo threshold số thực;
  online quyết định khi `score > threshold`, score hòa threshold thì skip.
  Chọn tỷ lệ dense thấp nhất trong các điểm mất macro nDCG ≤0.005 và từng miền
  ≤0.01 so S*. OOV nonempty route dense và tính vào tỷ lệ thật. Nếu không có
  điểm khả thi, ghi thất bại và dùng always-H*.
- Test so PE-GH với S* bằng nDCG@10, biên non-inferiority 0.01; kết luận thống
  kê do evaluator A, không từ CI mean latency của B.

Raw qrels/test kết quả BM25 và dense aggregate đã xuất hiện trong tài liệu A.
Vì vậy, bản này là **quy tắc tiền đăng ký cho các lựa chọn C còn lại**, không
được mô tả là một thí nghiệm hoàn toàn mù với test. Mọi fit/tune vẫn chỉ dùng
train/validation của fold hiện hành.

## 4. Giao nhận artifact và hash

| Domain | Docs | Queries | Qrel pairs | Corpus SHA256 | Query SHA256 | Qrels SHA256 |
|---|---:|---:|---:|---|---|---|
| programmers | 32.176 | 876 | 1.675 | `26d98b95e51ff6a7bd36f401c5821cab140189a4bdf2525017af66960427662d` | `707fde4c6bdce38db97e1930d8fcdc4c025536c566bc41af980245e284a7da27` | `ed69afa873c64d34298792d694c82c4293e4b7e3c6ea3edc7a73662d4b0cba76` |
| unix | 47.382 | 1.072 | 1.693 | `8d67fc0df3e01f490b38f81b72aa720644046db1e4c301900a4f4803550f4b7c` | `69d6f23726f77a2892b21ee6e98432768c42b045c5790ba79b6ef66c1b02f73b` | `a7bd24ce081b0bb892602e9b0067017dc66fd03e7593563ad095cb3cd05e92ed` |

Nguồn: `configs/data/cqadupstack.yaml` và `data/manifests/`. Split hash đã khóa:
`c6230440f00e223b04d42ba0770bee9d1b9c37d805eb8305d1c020f1d2143446`.
Các path lớn trên máy hiện tại: `data/raw/<domain>/`,
`artifacts/sparse/<domain>/`,
`C:/Users/quang/.cache/pegh/artifacts/c0-v1/<domain>/` cho FAISS,
`results/quality/{bm25,dense}/<domain>.jsonl`, `results/oof_runs/`.
Khôi phục nguồn phải qua script A/B và so hashes; không chỉ đối chiếu counts.

**Lưu ý đường dẫn Windows:** build `programmers` ban đầu ghi vào thư mục repo
có Unicode; `faiss.read_index` không mở được path đó dù file tồn tại. Đã sao
chép đầy đủ manifest/chunks/index/mapping sang cache ASCII và verifier B kiểm
toàn bộ 32.176 vector thành công. Build `unix` ghi thẳng vào cache ASCII.

| Artifact C cần nhận | Kiểm tra trước khi C1/C3 | Nguồn tạo |
|---|---|---|
| Canonical corpus/query/qrels của hai miền | SHA256 theo bảng; IDs/coverage theo A manifest | `scripts_a/fetch_inputs.py`, `prepare_data.py` |
| Sparse index + full BM25 top-100 | `corpus_sha256`, tokenizer/retriever hash, 1.948 rankings | `scripts_a/build_sparse.py`, `generate_sparse_runs.py` |
| Dense index + full dense top-100 | Exact model/config/version, corpus hash, 1.948 rankings | `scripts_b/build_dense.py`, `generate_dense_runs.py` |
| Five-fold split | `validate_five_fold_splits`, query set theo `fold_record` | `data/splits/manifest.json` |

Trước C1 chỉ cần rankings/manifest và fixture; C5/B online cần sparse/dense
index thật. Không xuất test utility trước khi H*/S*/gate/threshold của fold được
đóng băng. C bàn giao tối thiểu 30 ranking-v1 + 30 sidecar cho A theo
`docs/person_a/RUNS_REQUIRED_FROM_C.md`.

## 5. Trạng thái thực thi C0

- [x] Đã rà và merge bản sửa B từ `origin/thanh` vào `quang`.
- [x] Đã chốt quy tắc source/method/fusion/feature/model/threshold trong YAML.
- [x] Raw inputs đã khôi phục, audit đúng SHA256 và counts; split/manifests tái
  tạo giống hệt các file đã commit.
- [x] Hai SQLite BM25 index và 1.948 ranking top-100 đã hoàn tất; evaluator A
  cho metrics trùng biên bản A ở cả hai miền.
- [x] Dense `programmers` đủ 32.176 vector, verifier B kiểm mọi vector đạt;
  876 ranking top-100 cho metrics trùng baseline dense A.
- [x] Dense `unix` đủ 47.382 vector; verifier B kiểm mọi vector đạt; 1.072 ranking
  top-100 đã được tạo và có metrics trùng baseline dense A.
- [x] Biên nhận parity cuối cùng ghi hash artifact và metrics của cả hai miền;
  `results/c0_audit/receipt.json` có `status: passed`.

C0 hoàn tất ngày 24/10/2026. Bốn bộ ranking có tổng 3.896 query-ranking,
không có ranking rỗng; metrics khớp baseline A trong sai số `1e-12`.

| Domain | Dense index SHA256 | BM25 ranking SHA256 | Dense ranking SHA256 |
|---|---|---|---|
| programmers | `ec7479526e12e6e50b537d2d9c016d93ff7a2ae5cc4a6d22a799cfc0f6af9e52` | `0f8d489247c4ef261e4493c51e0ac2eabdb9798b4d7817eb11a546fe345273da` | `2025b5e9100647d98e3bd39aa6d556b5c619d8a0b93db404e6c35e8f0697b4fb` |
| unix | `52956bab711f13ddce090fdb8c4528971ba860148ea6ce91b2a3d7ceb8073b6a` | `065ca77e047a39e44389745c94a27d47f54ba3dd9f6b8824e5739c1051e38b68` | `20579ce7e96bdf2c8e50bb1493d56d54e0259bc09e75e65a97d7f05b92d1ec03` |

Biên nhận đầy đủ nằm trong thư mục kết quả bị Git bỏ qua để không commit artifact lớn.

## 6. Tái tạo và kiểm tra C0

Mở PowerShell tại gốc repository rồi chạy script có thể tiếp tục từ checkpoint:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts_c\finish_c0.ps1
Get-Content .\results\c0_audit\receipt.json
```

Script đồng bộ môi trường theo `uv.lock`, khôi phục dữ liệu còn thiếu, kiểm split/index/ranking theo hash và so chất lượng BM25/dense với baseline A. Biên nhận phải có `status: passed` cho cả `programmers` và `unix`. Build dense trên CPU có thể mất nhiều thời gian; khi bị ngắt, chạy lại cùng lệnh để tiếp tục. Nếu checksum, version hoặc metric khác, giữ artifact để điều tra; không sửa số chuẩn trong protocol để ép kiểm tra qua.
