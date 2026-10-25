# Tổng kết thực hiện phần C

C6–C8 đã hoàn tất. Freeze chất lượng, benchmark online, review chéo và các sửa đổi sau audit được ghi theo thứ tự dưới đây. Snapshot nhỏ có hash ở [C7 facts](validation/C7_FACTS.json); ranking, index và raw benchmark ở `results/` bị Git bỏ qua.

| Mốc | Kết quả chính | Bằng chứng |
|---|---|---|
| C6 | 140 run/sidecar OOF; PE-GH macro nDCG@10 `0.31216`, S* `0.31463` | `results/oof/c6_final/`, freeze hash bên dưới |
| C7 | Bốn mục paper C, bốn hình và báo cáo có thể dựng lại | [C7 facts](validation/C7_FACTS.json) |
| C8 | 10 online run, 150 worker, 29.220/29.220 ranking khớp OOF | Bảng latency/CPU/RSS và audit bên dưới |

## C6 — Threshold, freeze và test OOF

### Chọn threshold trước test

`scripts_c/select_thresholds.py` dùng duy nhất 10 bảng **validation** C3 và score validation C4. Với mỗi fold và method, 11 ngân sách đăng ký trước `0, 0.1, …, 1` được đổi thành threshold số trên score validation. Quy tắc online là `score > threshold`; score bằng threshold đi nhánh skip. Query OOV vẫn buộc đi dense và được tính vào tỷ lệ thực. Điểm được chọn có tỷ lệ dense thấp nhất trong các điểm mà mức giảm macro nDCG@10 so S* không quá `0.005` và từng miền không quá `0.01`; nếu không có điểm gate khả thi thì ghi `no_feasible_gated_point` và dùng H* luôn dense.

PE-GH (`ridge_gain_full`) đã chọn:

| Fold | Ngân sách validation | Tỷ lệ dense validation |
|---:|---:|---:|
| 0 | 0.7 | 0.700 |
| 1 | 0.5 | 0.499 |
| 2 | 0.5 | 0.499 |
| 3 | 0.8 | 0.799 |
| 4 | 0.3 | 0.299 |

File `results/thresholds/c6_validation.json` lưu đầy đủ 11 điểm, điểm được chọn, trạng thái của năm model và ba control score theo từng fold. Identifier + margin không tìm được điểm gate khả thi ở cả năm fold, nên được đánh dấu fallback H*; không gọi đây là thành công của gate.

### Freeze và run giao A

`scripts_c/freeze_c6.py` tạo `results/frozen/c6_manifest.json` với hash `07fb8825c2e3627d50a1cee5055187dca60d82e30f33905c0602c8930bbff12b`. Manifest khóa split, protocol, C1 H*/S*, threshold, model/scaler, sparse/dense index, cache ranking, mã nguồn và script export. Bản freeze được ghi **trước** khi chạy evaluator của A mở qrels test. Mỗi fold/miền có registry benchmark H*/S*/PE-GH trong `results/frozen/benchmark/`.

`scripts_c/export_c6_runs.py` đã xuất 30 ranking-v1 + 30 sidecar cho H*, S*, PE-GH; A đã materialize thêm 10 run BM25. Export chỉ đọc query, sparse stats, model đã freeze và ranking cache C0 có checksum; không đọc qrels test. Cache chỉ phục vụ đánh giá chất lượng offline, không đi vào factory đo online. `results/frozen/oof_registry.json` trỏ tới đủ 40 run, không còn đường dẫn mẫu.

### Chất lượng test qua evaluator A

`scripts_a/run_final_oof.py` chấp nhận toàn bộ run/sidecar; kết quả ở `results/oof/c6_final/`. Trên 1.948 query, PE-GH đi dense 1.125 lần, tỷ lệ `0.5775`; H*/S* đi dense mọi query.

| Method | Macro nDCG@10 |
|---|---:|
| BM25 | 0.28991 |
| H* / S* | 0.31463 |
| PE-GH | 0.31216 |

Chênh lệch PE-GH − S* là `−0.00246`; cận dưới bootstrap nhóm một phía 95% là `−0.00601` với 10.000 mẫu, cao hơn biên không thua kém `−0.01` đã đăng ký. Từng miền: programmers `−0.00043` (cận dưới `−0.00550`), unix `−0.00450` (cận dưới `−0.00960`). Có fold âm rõ, gồm programmers/0 `−0.0100` và unix/4 `−0.01466`; kết luận chỉ dựa trên phép so sánh đã đăng ký ở mức macro/miền, không chọn lại threshold theo test.

`scripts_c/report_c6_diagnostics.py` dùng ngân sách dense thực tế đã freeze theo từng fold/miền để chạy random 30 seed và oracle batch sau test. File `results/oof/c6_final/random30_oracle.json` ghi đầy đủ từng seed: macro nDCG@10 trung bình random là `0.30569`, PE-GH `0.31216`, oracle exact-budget `0.33673`. Đây là đối chứng batch sau freeze, không phải router online; không chọn seed hay threshold theo test.

`scripts_c/export_c6_controls.py` đã xuất thêm 100 run/sidecar đối chứng và evaluator A đã chấp nhận toàn bộ 14 method trong `results/oof/c6_controls/`. Một số mốc macro nDCG@10 / tỷ lệ dense test:

| Method | nDCG@10 | Dense ratio |
|---|---:|---:|
| PE-GH | 0.31216 | 0.578 |
| Logistic gain full | 0.31342 | 0.629 |
| Logistic sparse-success full | 0.31209 | 0.619 |
| LinearSVC general | 0.31049 | 0.555 |
| Ridge general | 0.31131 | 0.620 |
| BM25 margin | 0.31299 | 0.698 |
| Random seed 0 online hash | 0.30956 | 0.729 |
| Identifier + margin (fallback H*) | 0.31463 | 1.000 |
| CC 0.5 | 0.31426 | 1.000 |
| RRF 60 | 0.29481 | 1.000 |
| Dense only | 0.23530 | 1.000 |

Đây là đối chứng chất lượng offline; H*/S*/PE-GH cũng đã đi qua worker online đầy đủ. Tỷ lệ dense ở bảng là từ quyết định gate trên query test, không phải thước đo latency.

### Online benchmark B

`results/frozen/benchmark_inputs/` chứa 10 cặp file query test và warmup validation rời nhau. `scripts_c/run_c6_online.ps1` chạy H*, S*, PE-GH trong process riêng trên cùng runtime của B, mặc định 5 lần lặp cho cả 10 fold, kiểm tra receipt và xuất báo cáo mean/p95/CPU/RSS/stage. Đầu ra đầy đủ đặt tại `results/benchmark/c6_full/`.

Đối chiếu fold `programmers/0`: cả ba method H*, S*, PE-GH đều khớp thứ tự doc ID online/offline ở 176/176 query; PE-GH gọi encoder 130/176 query, đúng sidecar test. Mẫu này xác nhận đường xuất ranking và phương thức online dùng cùng quyết định gate và thứ tự kết quả.

Worker B đã chạy đủ 176 query test của fold này, một lần lặp, và `scripts_b/report_efficiency.py` đã xuất `results/benchmark/c6_programmers_fold_0/summary.json`: mean `648.0 ms` cho PE-GH, `662.2 ms` cho H*, `667.8 ms` cho S*; p95 tương ứng `1215.7`, `1159.3`, `1189.6 ms`. Sparse stage chiếm khoảng `628–640 ms/request`. Đây là kiểm tra tích hợp/đo mẫu một fold và không đi vào báo cáo online đầy đủ. Lượt 10 fold × 5 repeats sau đó đã hoàn tất; bảng cuối ở [Gate analysis](../../paper/05c_gate_analysis.md) và mục C8 bên dưới.

```powershell
.\scripts_c\run_c6_online.ps1
```

Đo online và đánh giá offline có provenance khác nhau: OOF dùng ranking cache đã kiểm checksum để tránh mã hóa lại toàn bộ tập test, còn worker B dùng `SearchMethod.search` và encode query thật. Không suy thời gian hay speedup từ tỷ lệ dense-call offline.

## C7 — Review chéo và release

### Phạm vi đã kiểm

- C6 freeze hash: `07fb8825c2e3627d50a1cee5055187dca60d82e30f33905c0602c8930bbff12b`; source snapshot vẫn khớp sau khi viết paper C7.
- A chấp nhận 40 run chính và 100 run đối chứng, mỗi run có sidecar; 1.948 query test xuất hiện đúng một lần qua 5 fold. Bảng chính và bảng 14 method khớp nhau ở bốn method trùng.
- B worker trên `programmers/fold_0` xác nhận 176/176 ranking ID khớp run offline cho H*, S*, PE-GH; PE-GH có 130/176 encode, H*/S* có 176/176. `quality_cache_used=false` trong worker.
- C7 report `021273732b6bfba891ce13eeda6d36fa866b97ddd927657426c771994109b13e` và bốn PNG có hash trong [snapshot](validation/C7_FACTS.json). Script `scripts_c/report_gating.py` xác minh thêm đủ 10 online run, 29.220 ranking/request và số encoder call theo sidecar trước khi tổng hợp latency.
- Random 30 seed và oracle được ghi là batch diagnostic sau freeze. Không dùng seed hoặc oracle để chọn gate test.
- Rerun release local trước khi thêm fixture C1: `pytest -q` đạt **99 passed**. Sau đó `pytest -q tests/c` đạt **3 passed** (gồm hai fixture C1 mới); `ruff check .`, `ruff format --check` phần C và `git diff --check` đạt.

### Điểm cần chủ phần A/B xem lại

| Ưu tiên | Chủ | Phát hiện | Việc cần làm |
|---|---|---|---|
| Đã đóng | B/C | Benchmark H*/S*/PE-GH đủ 10 fold × 5 repeats hoàn tất; 150/150 worker, 29.220 request có receipt hợp lệ và ranking khớp offline. | Bản thảo `paper/05c_gate_analysis.md` đã cập nhật bảng online đầy đủ; kết quả latency khác nhau theo miền. |
| Đã đóng | B/C | Lượt `programmers_fold_0` ban đầu bị `KeyboardInterrupt`. | Script đã lưu bản dang dở thành `programmers_fold_0.interrupted.20261024-194030` rồi chạy lại fold hoàn chỉnh. |
| P2 | A | `paper/05a_quality_results.md` và `docs/person_a/IMPLEMENTATION_STATUS.md` vẫn ghi thiếu H*/S*/PE-GH theo audit cũ. | A đối chiếu `results/oof/c6_final/` và thay trạng thái cũ bằng bảng final; giữ ngày và provenance của audit baseline. |
| P2 | B | `paper/05b_efficiency_results.md` chỉ mô tả dense-only development run trên CPU i7 khác máy C6 i3. | Giữ run lịch sử riêng; bổ sung bảng H*/S*/PE-GH từ full C6 online cùng runtime, không nối hai máy thành một speedup. |
| P2 | A/B/C | `README.md` còn nói C phải cung cấp run, trong khi 140 run đã tồn tại local dưới thư mục Git bỏ qua. | Khi bàn giao, gắn snapshot nhỏ đã track và hướng dẫn tái tạo artifact lớn; A/B xác nhận cập nhật README. |
| P2 | B | `pyproject.toml`/`uv.lock` do B sở hữu đã có dependency scikit-learn và package C từ C4–C6. | B review trước khi merge; `uv sync --locked` và test toàn repo là release gate. |

Đây là ghi nhận review trong workspace, chưa gửi tin nhắn tới chủ phần A/B. Các file A/B cũ chưa bị C sửa. Paper C (`01`, `02a`, `03`, `05c`) dùng ngữ cảnh kết quả mới và ghi rõ giới hạn benchmark online.

### Release gate

Chất lượng OOF và hash artifact đã qua. Kết luận *quality noninferiority* có căn cứ theo test đã đăng ký. Online run đầy đủ cho thấy mean/p95 gộp chỉ giảm nhẹ và Programmers chậm hơn, nên không kết luận có speedup ổn định. Lệnh dựng lại C7:

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts_c\report_gating.py
```

`online_status=complete`, `online_complete_fold_count=10` và các số trong `paper/05c_gate_analysis.md` đã được đối chiếu từ raw request sau khi hoàn tất benchmark.

Release gate một lệnh là `.\scripts_c\release_c7.ps1`: khóa môi trường, chạy toàn bộ test, Ruff, dựng lại C7 và kiểm đủ benchmark. Người dùng đã chạy lệnh; snapshot kết quả có `online_status=complete`. Sau khi bổ sung audit ranking đầy đủ, `report_gating.py` được chạy lại thành công.

Lệnh đã dùng để tiếp tục benchmark sau lượt bị ngắt:

```powershell
.\scripts_c\run_c6_online.ps1 -RestartIncomplete
```

Lệnh giữ nguyên các fold đã hoàn tất, lưu thư mục dang dở trước khi đo lại và chạy tiếp các fold còn thiếu. Mục C8 bên dưới ghi audit và các sửa đổi tài liệu sau lần đo đầy đủ.

## C8 — Audit tích hợp online

### Bằng chứng và kết quả

- Freeze C6: `07fb8825c2e3627d50a1cee5055187dca60d82e30f33905c0602c8930bbff12b`.
- C7 report sau audit: `021273732b6bfba891ce13eeda6d36fa866b97ddd927657426c771994109b13e`; [snapshot](validation/C7_FACTS.json) chứa hash của cả 10 summary online và số gộp tính lại từ raw request. `scripts_c/report_gating.py` là lệnh tái tạo.
- `results/benchmark/c6_full/` có 10 run complete, mỗi run 3 method × 5 worker; tổng cộng 150 worker. `load_complete_run` kiểm checksum receipt/request, nguồn thực thi, query coverage, repeat và runtime của từng run.
- 29.220/29.220 request có thứ tự doc ID online khớp run OOF đã freeze; mỗi fold/method có số encoder call bằng 5 × `dense_count` trong sidecar. Worker không dùng quality cache.
- Cả 10 run ghi cùng CPU i3-1005G1, Python 3.12.13, Torch 2.14.1+cpu, affinity `0,1,2,3` và giới hạn bộ nhớ 8 GB; các worker trong từng run đã qua kiểm tra runtime của B.
- Lượt `programmers_fold_0` bị ngắt trước đó được giữ ở thư mục `.interrupted.20261024-194030`; lượt đo lại đủ 15 worker và summary.

### Số liệu online cuối

Mean/p95 tính trên toàn bộ request của 5 lần lặp trong từng miền, không lấy trung bình p95 của các fold. CPU là thời gian process trên mỗi request; RSS là mức peak cao nhất trong các worker của miền đó, gồm cả load và warmup. Các lượt lặp của cùng query không phải quan sát độc lập.

| Miền | Method | Query | Dense % | Mean ms | p95 ms | CPU ms | Peak RSS MiB |
|---|---|---:|---:|---:|---:|---:|---:|
| Programmers | S* | 876 | 100.0 | 691.9 | 1442.2 | 1121.5 | 521.5 |
| Programmers | PE-GH | 876 | 74.7 | 737.9 | 1465.5 | 996.9 | 520.1 |
| Unix | S* | 1072 | 100.0 | 648.8 | 1224.6 | 1185.7 | 549.5 |
| Unix | PE-GH | 1072 | 43.9 | 606.0 | 1183.9 | 841.8 | 546.8 |
| Gộp | S* | 1948 | 100.0 | 668.2 | 1317.7 | 1156.8 | 549.5 |
| Gộp | PE-GH | 1948 | 57.8 | 665.3 | 1302.8 | 911.5 | 546.8 |

PE-GH chậm hơn S* trên Programmers 46,0 ms mean và 23,3 ms p95, nhanh hơn trên Unix 42,9 ms mean và 40,8 ms p95. Chênh lệch gộp chỉ 2,9 ms mean và 14,9 ms p95 theo hướng PE-GH nhanh hơn. Sparse stage chiếm phần lớn latency và dao động giữa các worker dù cùng backend. Vì vậy báo cáo **giảm dense calls và CPU**, nhưng không kết luận speedup wall-clock ổn định trên hai miền.

### Vấn đề tích hợp đã xử lý

1. Benchmark dừng giữa `programmers_fold_0`: `run_c6_online.ps1 -RestartIncomplete` lưu bản dang dở và đo lại từ đầu; không ghép worker của hai lượt.
2. Bản C7 trước đây chỉ báo trạng thái đủ fold, chưa đối chiếu toàn bộ ranking và chưa tính pooled p95: `report_gating.py` nay xác minh từng request với OOF đã freeze, encoder count với sidecar, rồi mới tạo bảng gộp.
3. Introduction, Gate analysis và tài liệu C6/C7 còn ghi full online đang chờ: đã cập nhật theo dữ liệu cuối và giữ kết quả bất lợi của Programmers.

Paper của A/B vẫn do chủ phần tương ứng cập nhật theo review C7 ở trên; C không sửa bảng lịch sử của họ. `release_c7.ps1` đã được người dùng chạy sau khi đủ 10 fold; đầu ra test của lệnh không được lưu thành receipt riêng. Sau sửa báo cáo C8, script report, test phần C, Ruff và kiểm tra whitespace được chạy lại tại workspace này.
