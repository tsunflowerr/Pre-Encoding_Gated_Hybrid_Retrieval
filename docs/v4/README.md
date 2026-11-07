# PE-GH v2 (vòng v4) — cập nhật 01/11/2026

**Tóm tắt.** PE-GH v2 giữ nguyên ý tưởng của PE-GH: chạy BM25 trước, gate rẻ quyết định, chỉ encode khi cần. Bốn thay đổi:

- gate học dự đoán **"BM25 có thất bại không"**, trên nhiều domain cùng lúc;
- encoder **arctic-embed-xs có prefix query** (cùng chi phí MiniLM);
- nhánh rẻ P\*;
- ngưỡng trở thành **núm chỉnh ngân sách encode**.

Kiểm chứng được đăng ký trước trên **6 subforum CQADupStack chưa từng dùng** (8.303 query, ≈ 282 nghìn tài liệu). **Cả 4 giả thuyết K1–K4 đều đạt** sau hiệu chỉnh Holm:

- **K1 — gate học hơn quy tắc BM25-margin** ở 50% encode: +0,0042 [0,0003; 0,0081], p = 0,017.
  - Lần đầu tiên trong đề tài gate học thắng heuristic này trên dữ liệu mới. Ở v1 và v3, gate chưa lần nào thắng.
  - Hiệu ứng nhỏ hơn trên dev (+0,0105), dương ở 5/6 domain.
  - AUC dự đoán "BM25 thất bại": 0,764 so với 0,670 của margin.
- **K2 — PE-GH v2 (80% encode) không kém H\*** (luôn encode), biên 0,01: −0,0064 [−0,0085; −0,0043].
- **K3 — PE-GH v2 hơn PE-GH v1** +0,069 [0,063; 0,075]. Phần lớn chênh lệch đến từ encoder.
- **K4 — gate v2 hơn định tuyến ngẫu nhiên** ở 50%: +0,019 [0,015; 0,023].

**Online** (programmers + unix, 97.400 request, 0 sai lệch ranking/route so với offline):

| Cấu hình | Độ trễ TB | nDCG@10 | Giảm so với H\* v2 |
|---|---:|---:|---:|
| H\* v2 | 24,3 ms | 0,414 | — |
| PE-GH v2, 30% encode | 10,7 ms | 0,343 | −56% |
| PE-GH v2, 50% encode | 14,8 ms | 0,374 | −39% |
| PE-GH v2, 80% encode | 21,0 ms | 0,411 | −14% |
| PE-GH v1 | 14,4 ms | 0,312 | — |

**Cùng độ trễ với PE-GH v1, PE-GH v2 (50%) cao hơn +0,062 nDCG@10.**

**So sánh thăm dò với hai bài báo liên quan (§7):** trên sáu chủ đề chưa thấy, ở 50% encode CI chưa phân biệt được v2 với bản LiteGator mặc định hoặc BERT; ở 80%, BERT cao hơn v2 +0,0068 [0,0044; 0,0094]. Trong phiên online cùng harness và LODO lồng nhau, độ trễ TB ở ngân sách 50% là v2 **14,30 ms**, LiteGator chọn cấu hình **14,43 ms**, BERT **162,57 ms**; bảng mới giữ cả p95, CPU, RSS, tỷ lệ encode thực tế và chất lượng OOF.

**Giới hạn:**

- Lợi thế của gate nằm ở ngân sách 10–70%. Ở 80–90% gate ngang margin.
- R\* (encode mọi query, chỉ chấm lại ứng viên BM25) ở 14,7 ms đạt 0,381, cao hơn PE-GH v2 50% ở cùng độ trễ.
- Trên domain mới, P\* ≈ BM25.
- Gate giảm độ trễ trung bình và trung vị, không giảm p95.

## 1. Vì sao có PE-GH v2

Ý tưởng của PE-GH giữ nguyên: **chạy BM25 trước, một gate rất rẻ chỉ nhìn query và danh sách BM25, rồi chỉ encode khi cần.** Vòng v3 cho thấy ba điểm yếu của bản v1:

1. **Gate học không hơn quy tắc BM25-margin** khi so ở cùng số lần encode. Gate v1 học *lợi ích của hybrid* (gain), nhưng gain phụ thuộc vào phía dense — thứ gate không nhìn thấy trước khi encode.
2. **Tiết kiệm ít.** Ngưỡng chọn theo luật C6 encode 81% (MiniLM) và 95,4% (bge-small) query.
3. **Gate học riêng từng domain** nên cần nhãn của chính domain đó. Trên domain mới với MiniLM, gate không có tín hiệu (AUC 0,503).

PE-GH v2 sửa đúng ba điểm đó, không đổi kiến trúc BM25 → gate → (có/không) encode.

## 2. PE-GH v2 khác v1 ở đâu

| | PE-GH v1 | PE-GH v2 |
|---|---|---|
| Gate dự đoán | lợi ích hybrid so với BM25 (Ridge) | **BM25 có thất bại không** (nDCG@10 BM25 = 0; logistic) |
| Đặc trưng | 21 đặc trưng v1 | 21 v1 + 7 QPP, **chuẩn hóa theo domain** bằng thống kê không nhãn |
| Dữ liệu huấn luyện | train fold của chính domain (cần nhãn) | **6 domain đã thấy gộp lại**; domain mới không cần nhãn |
| Nhánh rẻ (không encode) | BM25 | **P\*** = BM25 top-100 xếp hạng lại bằng proxy tĩnh (không chạy transformer) |
| Nhánh đắt (encode) | H\*: MiniLM + FAISS + fusion | H\*: **arctic-embed-xs + prefix query** + FAISS chính xác + CC fusion |
| Lựa chọn fusion | chọn trên validation của domain | **cố định từ domain huấn luyện** (H\* = CC 0,7; P\* = proxy CC 0,3) |
| Ngưỡng | luật C6 trên validation có nhãn | **phân vị điểm gate** trên query không nhãn = ngân sách encode chọn trước |

**Vì sao nhãn "BM25 thất bại".** Gate chỉ thấy query và danh sách BM25, nên bài toán nó làm được là *dự đoán chất lượng của chính BM25* (bài toán QPP kinh điển). Khi BM25 thất bại thì gần như chỉ dense cứu được; khi BM25 tốt thì P\* đã đủ. Nhãn này không phụ thuộc encoder, nên **cùng một gate dùng được cho mọi encoder**: encoder chỉ quyết định độ cao của H\* và mức ngân sách nên dùng.

**Vì sao chuẩn hóa theo domain.** Thang điểm BM25 và IDF khác nhau giữa các subforum. Mỗi domain được chuẩn hóa bằng trung bình/độ lệch chuẩn đặc trưng của chính các query của nó — chỉ cần query, không cần nhãn — nên gate học trên domain này áp dụng được sang domain khác.

**Ngân sách là núm vặn.** Người vận hành chọn tỷ lệ query được encode (ví dụ 50%). Ngưỡng là phân vị tương ứng của điểm gate trên các query đã có (không cần nhãn). Query không có token BM25 hoặc toàn OOV luôn được encode.

## 3. Tuần 1 — chọn encoder và chốt Gate v2

### 3.1 Encoder (programmers + unix, OOF, quy tắc định trước)

Quy tắc: H\* macro cao nhất; nếu chênh không quá 0,005 thì encoder rẻ hơn thắng. Thời gian encode: trung vị một query, 4 lõi đã pin.

| Encoder | Dense | H\* | Encode (ms) |
|---|---:|---:|---:|
| MiniLM (v1) | 0,2353 | 0,3146 | 8,78 |
| bge-small | 0,3683 | 0,3971 | 15,37 |
| bge-small + prefix | 0,3849 | 0,4018 | 15,94 |
| arctic-embed-xs | 0,2505 | 0,3469 | 8,31 |
| **arctic-embed-xs + prefix** | **0,4050** | **0,4133** | **8,72** |

Chọn **Snowflake/snowflake-arctic-embed-xs** (6 lớp, 384 chiều), có prefix query `Represent this sentence for searching relevant passages: ` (chỉ thêm vào query; vector tài liệu không đổi).

- H\* hơn MiniLM +0,0986 [0,087; 0,110], cùng chi phí encode.
- H\* hơn bge-small + prefix +0,0115 [0,0023; 0,0211], với khoảng một nửa thời gian encode.
- Không có prefix, arctic chỉ đạt dense 0,2505: prefix là một phần của cấu hình, không phải chi tiết phụ.

### 3.2 Gate v2 (6 domain đã thấy, leave-one-domain-out)

Mỗi lần để riêng một domain. Gate và lựa chọn fusion fit trên 5 domain còn lại, rồi định tuyến P\* → H\* trên domain để riêng ở các ngân sách 10–90%. Tiêu chí chọn định trước: trung bình macro nDCG@10 trên ngân sách 20–80%.

| Ứng viên | Diện tích 20–80% |
|---|---:|
| **fail, v1+QPP, chuẩn hóa theo domain (chọn)** | **0,3733** |
| fail, v1, theo domain | 0,3731 |
| fail, v1, toàn cục | 0,3729 |
| fail, v1+QPP, toàn cục | 0,3728 |
| low (−nDCG BM25, Ridge), 4 biến thể | 0,3712–0,3720 |
| BM25-margin (không học) | 0,3653 |
| Ngẫu nhiên (30 seed) | 0,3573 |
| Oracle theo từng query | 0,4304 |

Các biến thể "fail" gần như bằng nhau (chênh ≤ 0,0006). Đóng góp chính đến từ **nhãn mới và huấn luyện đa domain**, không đến từ QPP hay cách chuẩn hóa.

| Ngân sách encode | Gate v2 | BM25-margin | Ngẫu nhiên | Gate v2 − margin [CI 95%] |
|---:|---:|---:|---:|---|
| 30% | 0,3474 | 0,3417 | 0,3365 | +0,0057 [0,0009; 0,0104] |
| 50% | 0,3772 | 0,3667 | 0,3577 | +0,0105 [0,0061; 0,0148] |
| 70% | 0,3986 | 0,3903 | 0,3781 | +0,0083 [0,0048; 0,0117] |
| 80% | 0,4043 | 0,4002 | 0,3882 | |
| 100% (H\*) | 0,4088 | | | |
| 0% (P\*) | 0,3053 | | | |

Lần đầu tiên trong đề tài, **gate học hơn BM25-margin với CI loại trừ 0** ở mọi ngân sách kiểm tra. Ở v3, gate v1 với bge-small kém margin −0,0014.

**Ngân sách vận hành** theo quy tắc định trước (ngân sách nhỏ nhất ≥ 30% mà kém H\* không quá 0,005) là **80%**: 0,4043 so với H\* 0,4088. Với encoder mạnh, H\* hơn P\* tới 0,10, nên muốn giữ chất lượng của H\* thì phải encode phần lớn query. Muốn tiết kiệm nhiều hơn thì đổi chất lượng lấy chi phí theo đường cong ngân sách.

Gate cuối cùng fit trên cả 6 domain, lưu ở [configs/v4/gate_v2.json](../../configs/v4/gate_v2.json) (28 trọng số tuyến tính, `gate_sha256` 009e639d…). Các đặc trưng có trọng số lớn nhất là tỷ lệ điểm BM25 cuối/đầu (QPP), độ phân tán điểm top-10, điểm hạng 1 và khoảng cách hạng 1–2. Cả bốn đều là tín hiệu "BM25 có tự tin không".

## 4. Đăng ký trước

[configs/v4/preregistration.yaml](../../configs/v4/preregistration.yaml) được băm và ghi thời điểm (2026-10-30 01:40 UTC) **trước khi tải bất kỳ file nào** của sáu subforum mới: english, gaming, physics, stats, tex, wordpress (≈ 8.300 query, ≈ 282 nghìn tài liệu). Mã chặn mọi bước chạm vào domain mới cho đến khi có biên nhận này.

- **Cố định trước:** gate (hash), encoder, prefix, lựa chọn fusion, ngân sách 50% (so khớp) và 80% (vận hành), quy tắc ngưỡng, phân tích.
- **Phân tích:** bootstrap 10.000 lần theo nhóm trong từng domain (seed 20261019), Holm trên K1–K4, α = 0,05.

| Giả thuyết | Nội dung | Trên dev |
|---|---|---|
| K1 | Ở 50% encode, gate v2 hơn BM25-margin | +0,0105 |
| K2 | PE-GH v2 (80%) không kém H\* (biên 0,01) | −0,0045 |
| K3 | PE-GH v2 hơn PE-GH v1 (cả hệ thống; chủ yếu nhờ encoder) | — |
| K4 | Ở 50% encode, gate v2 hơn định tuyến ngẫu nhiên | +0,0195 |

PE-GH v1 được chạy đúng như cũ: MiniLM, và gate Ridge, H\*/S\* cùng ngưỡng C6 được chọn trên nhãn train/validation của chính domain mới. Như vậy v1 được dùng nhãn trong domain, còn v2 thì không.

## 5. Kết quả xác nhận trên 6 subforum mới

Dữ liệu được tải sau thời điểm đăng ký (01:40:48 UTC, 28 giây sau biên nhận). Gate, encoder, fusion, ngân sách và phân tích giữ đúng như đã đăng ký. Kết quả đầy đủ ở [facts/evaluation_new.json](facts/evaluation_new.json).

### 5.1 Giả thuyết

| Giả thuyết | Ước lượng | CI 95% | p (một phía) | Ngưỡng Holm | Kết luận |
|---|---:|---|---:|---:|---|
| K1: gate v2 > BM25-margin (50%) | +0,0042 | [0,0003; 0,0081] | 0,0171 | 0,05 | **đạt** |
| K2: PE-GH v2 (80%) không kém H\* | −0,0064 | [−0,0085; −0,0043] | 0,0009 | 0,025 | **đạt** |
| K3: PE-GH v2 > PE-GH v1 | +0,0690 | [0,0629; 0,0752] | < 0,0001 | 0,0125 | **đạt** |
| K4: gate v2 > ngẫu nhiên (50%) | +0,0190 | [0,0155; 0,0225] | < 0,0001 | 0,0167 | **đạt** |

![Giả thuyết](figures/v4_hypotheses.png)

### 5.2 Mặt bằng chất lượng (macro nDCG@10, 6 domain mới)

| Phương án | nDCG@10 | Tỷ lệ encode |
|---|---:|---:|
| BM25 | 0,3267 | 0% |
| P\* (BM25 + proxy tĩnh) | 0,3270 | 0% |
| Dense arctic (prefix) | 0,4031 | 100% |
| **H\*** (BM25 ⊕ dense arctic) | **0,4223** | 100% |
| **PE-GH v2, ngân sách vận hành** | **0,4159** | 80,0% |
| PE-GH v2, 50% | 0,3933 | 50% |
| BM25-margin, 50% | 0,3892 | 50% |
| Ngẫu nhiên, 50% | 0,3744 | 50% |
| PE-GH v1 (MiniLM, dùng nhãn trong domain) | 0,3469 | 81,8% |
| H\* MiniLM (tham khảo) | 0,3483 | 100% |

Ngưỡng phân vị lấy trên query không nhãn cho tỷ lệ encode thực tế 79,9–80,2% ở mọi domain. Núm ngân sách giữ đúng mức đặt ra trên dữ liệu mới.

### 5.3 Từng domain

| Domain | BM25 | H\* | PE-GH v2 (80%) | v2 − H\* | v2 50% | margin 50% | v2 − margin | AUC v2 / margin |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| english | 0,3375 | 0,4590 | 0,4505 | −0,0086 | 0,4241 | 0,4227 | +0,0014 | 0,774 / 0,673 |
| gaming | 0,4675 | 0,5863 | 0,5815 | −0,0048 | 0,5583 | 0,5500 | +0,0082 | 0,796 / 0,681 |
| physics | 0,3266 | 0,4388 | 0,4310 | −0,0078 | 0,3993 | 0,3938 | +0,0055 | 0,735 / 0,646 |
| stats | 0,2883 | 0,3624 | 0,3571 | −0,0054 | 0,3475 | 0,3337 | +0,0139 | 0,748 / 0,682 |
| tex | 0,2490 | 0,3185 | 0,3179 | −0,0006 | 0,3006 | 0,2970 | +0,0035 | 0,760 / 0,653 |
| wordpress | 0,2914 | 0,3686 | 0,3574 | −0,0112 | 0,3303 | 0,3377 | −0,0074 | 0,772 / 0,685 |

Gate v2 dự đoán BM25 thất bại tốt hơn margin ở **cả 6 domain**: AUC 0,735–0,796 so với 0,646–0,685. Về chất lượng định tuyến ở 50%, gate hơn margin ở 5/6 domain; wordpress (domain nhỏ nhất, 541 query) là ngoại lệ.

### 5.4 Đường cong ngân sách (thống kê mô tả, không kiểm định)

| Ngân sách | 10% | 20% | 30% | 40% | 50% | 60% | 70% | 80% | 90% |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Gate v2 | 0,3439 | 0,3565 | 0,3702 | 0,3845 | 0,3928 | 0,4029 | 0,4112 | 0,4159 | 0,4196 |
| BM25-margin | 0,3393 | 0,3532 | 0,3651 | 0,3785 | 0,3896 | 0,3995 | 0,4088 | 0,4168 | 0,4204 |
| Ngẫu nhiên | 0,3365 | 0,3460 | 0,3556 | 0,3649 | 0,3744 | 0,3842 | 0,3934 | 0,4031 | 0,4124 |
| Oracle | 0,3964 | 0,4325 | 0,4474 | 0,4490 | 0,4490 | 0,4490 | 0,4490 | 0,4490 | 0,4490 |
| v2 − margin | +0,0046 | +0,0033 | +0,0050 | +0,0061 | +0,0033 | +0,0034 | +0,0024 | −0,0009 | −0,0007 |

![Đường cong ngân sách](figures/v4_budget_curves.png)

### 5.5 Đọc kết quả

- **Gate học đã có giá trị riêng, nhưng nhỏ.**
  - Trên dev, gate hơn margin +0,0105; trên domain mới +0,0042. Hiệu ứng co lại khi sang dữ liệu mới là điều thường gặp; quan trọng là CI vẫn nằm trên 0.
  - Ở mức dự đoán, khoảng cách rõ hơn nhiều: AUC cao hơn 0,07–0,12 ở mọi domain.
  - Theo thăm dò trên dev, khác biệt so với v1/v3 chủ yếu đến từ **nhãn** (BM25 thất bại, thay vì gain). Huấn luyện đa domain là điều kiện để dùng gate trên domain mới mà không cần nhãn. QPP và cách chuẩn hóa gần như không đổi kết quả (§3.2).
- **Lợi thế tập trung ở ngân sách thấp và trung bình.**
  - Từ 10% đến 70%, gate luôn hơn margin 0,002–0,006.
  - Từ 80% trở lên, cả hai chỉ còn bỏ qua những query BM25 rất tự tin, nên gần như bỏ qua cùng một tập; khi đó gate ngang margin.
  - Ở ngân sách vận hành 80%, chọn gate hay margin không quan trọng. Gate có ích khi muốn tiết kiệm nhiều hơn.
- **Ngân sách vận hành 80% kém H\* một chút, nhưng kém có thật**: −0,0064, CI không chứa 0. Kết quả nằm trong biên không-kém 0,01, nhưng không phải "miễn phí". Đổi lại, số lần encode giảm 20%.
- **K3 chủ yếu là hiệu ứng encoder.** H\* arctic hơn H\* MiniLM 0,074, gần bằng toàn bộ chênh lệch v2 − v1 (0,069). Đây là bằng chứng rằng nâng cấp đúng encoder (cùng chi phí) đáng giá hơn mọi tinh chỉnh gate. Không nên trình bày K3 như đóng góp của gate.
- **P\* gần như không giúp trên domain mới** (+0,0003 so với BM25).
  - Proxy tĩnh của arctic yếu: tương quan Pearson với điểm của vector thật chỉ 0,28–0,39 trên cả 12 domain.
  - Ở v3, proxy bge-small từng tăng BM25 +0,0146.
  - Nhánh rẻ của PE-GH v2 vì vậy thực chất là BM25.
- **PE-GH v1** trên domain mới encode trung bình 81,8% query. Có 1/5 fold không tìm được điểm gated hợp lệ, phải lùi về S\*. Bản v1 vẫn được dùng nhãn trong domain mà vẫn thấp hơn v2 0,069.

## 6. Hiệu năng online (programmers + unix)

**Cách đo.**

- Cùng harness với v1/v3: worker cô lập, 4 lõi vật lý được pin, batch 1, 50 query khởi động. Mỗi phương án 9.740 request (1.948 query test của 5 fold × 5 lần lặp).
- Gate của mỗi domain được huấn luyện **không có domain đó** (LODO). Ngưỡng là phân vị điểm gate trên query train+validation, không nhãn.
- Kiểm tra từng request: **97.400 request, 0 sai lệch** ranking hay quyết định route so với kế hoạch offline.
- Số liệu ở [facts/online_report.json](facts/online_report.json).

| Phương án | TB (ms) | p50 | p95 | Encode | nDCG@10 (OOF) | Giảm TB so với H\* v2 [CI 95%] |
|---|---:|---:|---:|---:|---:|---|
| BM25 | 2,03 | 1,96 | 3,51 | 0% | 0,2899 | 91,6% |
| P\* | 3,49 | 3,41 | 5,06 | 0% | 0,2952 | 85,6% |
| R\* (encode, chấm lại BM25 top-100) | 14,70 | 14,53 | 17,66 | 100% | 0,3811 | 39,5% |
| **H\* v2** (arctic) | 24,31 | 24,17 | 28,95 | 100% | 0,4142 | — |
| **PE-GH v2, 30%** | 10,68 | 5,27 | 26,77 | 30,1% | 0,3428 | 56,1% [54,4; 57,7] |
| **PE-GH v2, 50%** | 14,76 | 18,73 | 28,14 | 50,1% | 0,3745 | 39,3% [37,5; 41,1] |
| **PE-GH v2, 80%** | 20,98 | 23,91 | 29,52 | 79,9% | 0,4107 | 13,7% [12,2; 15,2] |
| BM25-margin, 80% | 20,58 | 23,46 | 28,88 | 80,1% | 0,4060 | 15,3% [13,9; 16,8] |
| H\* v1 (MiniLM) | 22,61 | 22,34 | 27,76 | 100% | 0,3146 | 7,0% |
| PE-GH v1 | 14,40 | 19,75 | 27,12 | 57,8% | 0,3122 | 40,7% |

![Pareto online](figures/v4_pareto_online.png)

**Thời gian từng bước** (fold 0, một lần lặp, PE-GH v2 50%):

| Đường đi | Tổng | BM25 | Thống kê + đặc trưng + gate | Encode | FAISS | Fusion |
|---|---:|---:|---:|---:|---:|---:|
| Bỏ qua encode → P\* | 4,8 ms | 2,4 | 0,7 | — | — | 1,7 |
| Encode → H\* | 24,5 ms | 2,4 | 0,7 | 13,0 | 6,9 | 1,0 |

**Đọc kết quả:**

- **PE-GH v2 trội hẳn PE-GH v1 và H\* v1.**
  - Ở cùng độ trễ với PE-GH v1 (≈ 14,5 ms), PE-GH v2 50% đạt 0,3745 so với 0,3122.
  - PE-GH v2 30% đạt 0,3428 với 10,7 ms, vượt cả H\* v1 (0,3146, 22,6 ms) với chưa tới một nửa thời gian.
- **Núm ngân sách hoạt động online.** Tỷ lệ encode thực tế khớp mục tiêu (30,1 / 50,1 / 79,9%). Độ trễ trung bình giảm gần tuyến tính theo ngân sách. Chi phí gate ≈ 0,7 ms.
- **Gate giảm trung bình và trung vị, không giảm p95.** Query được encode vẫn tốn như H\* (≈ 24–30 ms). Nếu ràng buộc là đuôi độ trễ thì cần HNSW hoặc encoder nhỏ hơn, không phải gate.
- **R\* là mốc đáng lưu ý.** Ở cùng ≈ 14,7 ms, R\* (0,3811) hơn PE-GH v2 50% (0,3745): encode mọi query nhưng không tìm FAISS. R\* chưa được kiểm định trên domain mới, nên đây là quan sát trên dev.
- H\* v2 chậm hơn H\* v1 7,5%, đổi lại chất lượng cao hơn +0,10.

## 7. So sánh với hai bài báo liên quan (thăm dò)

**Phân tích này được bổ sung sau đánh giá K1–K4, không đăng ký trước.** Mục tiêu là so sánh quyết định định tuyến của gate v2 đã đóng băng với các bản triển khai điều chỉnh từ [Arabzadeh và cộng sự, CIKM 2021 [1]](https://arxiv.org/abs/2109.10739) và [LiteGator, iCAST-ES 2025 [2]](https://doi.org/10.2991/978-94-6463-926-1_77). Đây là so sánh trên hạ tầng PE-GH, không tái lập các con số của hai bài báo trên dữ liệu gốc.

### 7.1 Cách triển khai và điều chỉnh

Trong so sánh offline ở §7.2–7.4, tất cả router dùng cùng P\* = proxy CC 0,3, H\* = BM25 ⊕ arctic CC 0,7 và quy tắc buộc encode cho query không có token BM25 hoặc toàn OOV. Các router mới chỉ học trên **4.842 query của sáu chủ đề đã thấy**; đánh giá trên cùng **8.303 query của sáu chủ đề mới** ở §5. Không điều chỉnh tham số theo nhãn của sáu chủ đề đánh giá.

V2 và ablation có chuẩn hóa theo chủ đề dùng thống kê đặc trưng của toàn bộ query trong chủ đề đó, không dùng nhãn, đúng cách triển khai của gate đã đóng băng.

- **Arabzadeh [1], biến thể sparse-vs-hybrid:** BERT-base-uncased nhận cặp query và văn bản tài liệu BM25 hạng 1 (title + body), dự đoán BM25 có tìm được tài liệu liên quan trong top T hay không. Giữ một epoch và batch 8 như bài gốc; ở đây dùng **T = 10** thay cho 50 vì đánh giá nDCG@10 thay cho recall@1000, giới hạn cặp đầu vào ở **256 token**, learning rate 2×10⁻⁵. Dùng trọng số BERT cố định theo revision trong [facts/prior_bert.json](facts/prior_bert.json). Seed 42 áp dụng cho thứ tự mẫu và dropout; khởi tạo lớp phân loại chưa được đặt seed, nên huấn luyện lại từ đầu có thể cho số khác. Model và điểm đã lưu được dùng lại khi chạy tiếp.
- **LiteGator [2]:** StandardScaler + SVM tuyến tính (`LinearSVC`, C = 1), tám đặc trưng gồm entropy query; IDF min/mean/std; điểm BM25 hạng 1; chênh điểm hạng 1–2; mean/std điểm top-10. Dùng tokenizer và IDF của PE-GH. Nhãn ở đây là **nDCG@10(H\*) > nDCG@10(P\*)**; bài gốc mô tả lợi ích dense so với sparse. Huấn luyện trên toàn bộ 4.842 query đã thấy, thay cho 1.000 query Natural Questions của bài gốc; không cân bằng lại lớp hay tinh chỉnh trên chủ đề đánh giá.
- **Hai ablation:** (i) giữ tám đặc trưng và SVM của bản LiteGator, chỉ đổi sang nhãn BM25 thất bại; (ii) dùng cách học của gate v2 (logistic + chuẩn hóa theo chủ đề + nhãn thất bại), nhưng chỉ giữ tám đặc trưng đó. BM25-margin và ngẫu nhiên 30 seed là các mốc bổ sung.

Ở ngân sách 30/50/80%, mỗi router chọn **cùng số query được encode trong từng test fold của từng chủ đề**, theo điểm giảm dần; query buộc encode được tính vào ngân sách, hòa điểm xử lý bằng query ID. Đây là quy tắc so cùng ngân sách của K1, không chọn ngưỡng bằng nhãn test. Chất lượng là macro nDCG@10, mỗi chủ đề có trọng số bằng nhau. CI hai phía 95% dùng 10.000 lần bootstrap nhóm trong từng chủ đề, seed 20261019; các khoảng thăm dò không hiệu chỉnh cho nhiều so sánh và không phải bằng chứng xác nhận mới.

### 7.2 Chất lượng ở cùng ngân sách encode

| Router | 30% | 50% | 80% |
|---|---|---|---|
| **PE-GH v2 (28 đặc trưng)** | 0,3698 | 0,3933 | 0,4156 |
| LiteGator [2], bản điều chỉnh | 0,3671 | 0,3904 | 0,4172 |
| Arabzadeh [1], BERT, bản điều chỉnh | 0,3697 | 0,3924 | 0,4224 |
| BM25-margin | 0,3648 | 0,3892 | 0,4172 |
| 8 đặc trưng + SVM + nhãn thất bại | 0,3709 | 0,3928 | 0,4161 |
| 8 đặc trưng + cách học v2 | 0,3712 | 0,3931 | 0,4161 |
| Ngẫu nhiên (30 seed) | 0,3556 | 0,3744 | 0,4029 |

Mốc 80% ở đây dùng số lượt encode chính xác trong từng test fold; kết quả v2 0,4156 khác mốc vận hành 0,4159 ở §5.2, vốn dùng ngưỡng phân vị từ query train+validation không nhãn.

Chênh lệch dưới đây đều lấy **v2 trừ router đối chiếu**; giá trị âm nghĩa là router đối chiếu cao hơn.

| v2 − router [CI 95%] | 30% | 50% | 80% |
|---|---|---|---|
| LiteGator [2], bản điều chỉnh | +0,0026 [−0,0015; +0,0067] | +0,0029 [−0,0008; +0,0067] | −0,0017 [−0,0035; +0,0002] |
| Arabzadeh [1], BERT, bản điều chỉnh | +0,0000 [−0,0041; +0,0042] | +0,0010 [−0,0030; +0,0051] | −0,0068 [−0,0094; −0,0044] |
| BM25-margin | +0,0050 [+0,0009; +0,0091] | +0,0042 [+0,0003; +0,0081] | −0,0016 [−0,0039; +0,0007] |
| 8 đặc trưng + SVM + nhãn thất bại | −0,0012 [−0,0037; +0,0014] | +0,0005 [−0,0017; +0,0028] | −0,0005 [−0,0019; +0,0009] |
| 8 đặc trưng + cách học v2 | −0,0015 [−0,0042; +0,0012] | +0,0002 [−0,0019; +0,0024] | −0,0005 [−0,0020; +0,0010] |
| Ngẫu nhiên (30 seed) | +0,0141 [+0,0106; +0,0177] | +0,0190 [+0,0155; +0,0225] | +0,0126 [+0,0104; +0,0149] |

Ở 30% và 50%, CI của v2 so với cả LiteGator lẫn BERT đều chứa 0; chưa có bằng chứng rõ rằng v2 cao hơn hai bản điều chỉnh này. **Ở 80%, BERT đạt 0,4224 so với 0,4156 của v2: cao hơn +0,0068 [0,0044; 0,0094], CI loại trừ 0 trong phân tích thăm dò.** Với LiteGator ở 80%, giá trị trung bình của v2 cũng thấp hơn, nhưng CI vẫn chứa 0. Không thể kết luận v2 thắng hai router từ bài báo về chất lượng.

#### 7.2.1 LiteGator được chọn cấu hình bằng LODO

Để cho LiteGator cơ hội chọn mô hình như gate v2, thử **C ∈ {0,1; 1; 10} × class_weight ∈ {None; balanced}**, chọn bằng trung bình macro nDCG@10 qua ngân sách 20–80% khi LODO trên sáu chủ đề đã thấy; hòa điểm giữ ứng viên đầu theo thứ tự C rồi class_weight. Cấu hình được chọn là **C = 0.1, class_weight = balanced**, sau đó fit trên cả 4.842 query đã thấy; sáu chủ đề đánh giá không tham gia chọn cấu hình.

| Ngân sách | V2 | LG mặc định | LG chọn LODO | v2 − LG mặc định [CI 95%] | v2 − LG chọn LODO [CI 95%] |
|---|---|---|---|---|---|
| 30% | 0,3698 | 0,3671 | 0,3678 | +0,0026 [−0,0015; +0,0067] | +0,0020 [−0,0020; +0,0061] |
| 50% | 0,3933 | 0,3904 | 0,3913 | +0,0029 [−0,0008; +0,0067] | +0,0020 [−0,0016; +0,0057] |
| 80% | 0,4156 | 0,4172 | 0,4169 | −0,0017 [−0,0035; +0,0002] | −0,0013 [−0,0031; +0,0006] |

Đây là bổ sung thăm dò, cùng P*/H*, số lượt encode từng test fold và bootstrap nhóm như §7.2. Giữ cả bản mặc định và bản được chọn cấu hình, không chọn bản nào theo kết quả sáu chủ đề đánh giá. Chi tiết lưới và điểm LODO ở [facts/prior_litegator_tuning.json](facts/prior_litegator_tuning.json), kết quả chưa thấy ở [facts/prior_litegator_tuned.json](facts/prior_litegator_tuned.json).

### 7.3 Quy tắc quyết định riêng của từng router

| Quy tắc quyết định | Encode (macro) | nDCG@10 | v2 cùng số lượt encode | v2 − router [CI 95%] |
|---|---|---|---|---|
| LiteGator: điểm SVM > 0 | 0,049% | 0,3272 | 0,3272 | +0,000006 [−0,000014; +0,000028] |
| BERT: p(thất bại) > 0,5 | 72,104% | 0,4132 | 0,4119 | −0,0012 [−0,0043; +0,0019] |

V2 trong bảng chọn đúng số lượt H\* của router tương ứng **trên từng chủ đề**; ngân sách này khác bảng 30/50/80%. Các quy tắc đều gồm ngoại lệ buộc encode cho query không có token BM25 hoặc toàn OOV. Mốc p > 0,5 là điểm vận hành bổ sung của bản BERT ở đây; bài [1] khảo sát nhiều ngưỡng xác suất. Với lần fit này, ngưỡng SVM gần như luôn chọn P\*, nên chất lượng gần P\* (0,3270); chỉ nhìn kết quả ở ngưỡng mặc định sẽ trộn chất lượng sắp thứ tự với mức ngân sách. Nhãn H\* > P\* chiếm 31,83% mẫu huấn luyện; chưa có ablation cân bằng lớp để quy nguyên nhân cho mất cân bằng nhãn. Đây là hành vi của bản điều chỉnh trên PE-GH, không phải kết luận về LiteGator trên dữ liệu gốc.

### 7.4 Khả năng dự đoán và ablation nhãn

AUC dưới đây là trung bình không trọng số của sáu AUC theo chủ đề, không gộp tất cả query thành một tập.

| Router | AUC: BM25 thất bại | AUC: H* tốt hơn P* |
|---|---|---|
| **PE-GH v2 (28 đặc trưng)** | 0,764 | 0,570 |
| LiteGator [2], bản điều chỉnh | 0,706 | 0,587 |
| Arabzadeh [1], BERT, bản điều chỉnh | 0,759 | 0,582 |
| BM25-margin | 0,670 | 0,592 |
| 8 đặc trưng + SVM + nhãn thất bại | 0,762 | 0,566 |
| 8 đặc trưng + cách học v2 | 0,760 | 0,569 |

BERT hoàn thành 606 bước; loss trung bình 50 bước cuối **0,5282**, tỷ lệ nhãn thất bại **57,50%**. AUC thất bại trên sáu chủ đề đánh giá là **0,759**. Lần fine-tune này có tín hiệu học; không lựa chọn lại epoch hay siêu tham số theo các kết quả đánh giá.

Đổi riêng nhãn của SVM tám đặc trưng sang **BM25 thất bại** đưa AUC thất bại từ 0,706 lên 0,762, gần v2 (0,764). Ở 30/50%, chất lượng định tuyến của hai bản tám đặc trưng dùng nhãn thất bại cũng gần v2, với CI của chênh lệch đều chứa 0. Kết quả phù hợp với cách giải thích rằng **đổi nhãn đã đủ để đưa bản tám đặc trưng đến mức gần v2**, chưa cho thấy 28 đặc trưng mang lại lợi ích rõ. Bản v2 cũng chưa cao hơn LiteGator rõ ràng về nDCG@10 ở các ngân sách này; không quy toàn bộ khác biệt giữa hai bài báo cho một yếu tố.

### 7.5 Hiệu năng online đo cùng harness (thăm dò)

**Đây là phép đo đầu-cuối thật**, không cộng thời gian v2 với micro-benchmark BERT. Cả 13 phương án được đo lại bằng cùng harness, cùng code và kế hoạch đã đóng băng, nhưng **chia hai đoạn** vì máy phải tạm dừng giữa hai chủ đề: programmers **12:36–14:44 ngày 01/11/2026**, unix **14:47 02/11/2026–16:55 02/11/2026 (UTC+7)**. Chỉ dừng ở ranh giới giữa hai chủ đề; trong mỗi fold, cả 13 phương án vẫn được đo xen kẽ trong một lượt, nên so sánh giữa các phương án không bị lệch bởi lần dừng; không đo lại lượt nào đã xong; lượt unix vừa khởi động lúc dừng được giữ lại nguyên trạng và không dùng. Con số gộp hai chủ đề trộn hai đoạn đo như nhau cho mọi phương án. Thứ tự phương án được harness xáo trộn ở mỗi lần lặp, seed 42; không tái sử dụng độ trễ v2 ở §6. Kế hoạch [configs/v4/prior_online_plan.yaml](../../configs/v4/prior_online_plan.yaml) được đóng băng trước khi đo, SHA-256 `b263ff94efc3c72e1d5d3f0445628135d07e2a0be37d92d8b7cd75afafb8c5c1`, thời điểm UTC `2026-11-01T05:30:08.017878+00:00`; đây vẫn là thăm dò sau K1–K4.

**Cách giữ công bằng:** cùng programmers/unix, BM25 index, encoder arctic có prefix, FAISS, P*/H* được chọn từ năm chủ đề còn lại và quy tắc buộc encode. Mỗi ngưỡng lấy từ phân vị điểm riêng của router trên train+validation không nhãn của fold. Tất cả dùng batch 1, concurrency 1, 50 query khởi động, 5 lần lặp, 5 fold, lõi [0, 2, 4, 6]; BERT và encoder đều bốn torch thread. Weights, tokenizer, index và văn bản tài liệu hạng 1 được tải trước đồng hồ đo; BERT dùng lại ranking BM25 đã chạy, tokenize + forward trong request, không cache điểm.

Để không lọt nhãn qua **chọn mô hình**, v2 và LiteGator đều chọn cấu hình bằng LODO bên trong năm chủ đề còn lại trước khi fit năm chủ đề đó. V2 chọn tám ứng viên theo cùng luật diện tích 20–80%: **programmers: `fail_v1+qpp_domain`; unix: `fail_v1_domain`**; khác recipe 28 đặc trưng cố định ở unix của phiên cũ, nên đây là phép đo v2 với chọn mô hình lồng nhau, không thay trọng số đóng băng dùng cho bảng chưa thấy. LiteGator online chọn **programmers: C = 0.1, class_weight = balanced; unix: C = 0.1, class_weight = balanced**; chỉ bản chọn cấu hình này chạy online, không gán độ trễ của nó cho bản mặc định. Hai BERT LODO được huấn luyện riêng, seed 42 đặt **trước `from_pretrained`** để khởi tạo head xác định; model BERT học cả sáu chủ đề ở §7.2 không bị thay. **BERT giữ recipe một epoch, batch 8 do chi phí, chưa được hưởng tìm siêu tham số như hai router tuyến tính; đây là giới hạn so sánh.**

Smoke 156 request kiểm tra parity trước lượt đầy đủ. Lượt đầy đủ giữ **126.620 request**, **0 sai lệch ranking hoặc route**; không loại request chậm, không chạy lại để chọn số đẹp. Cột parity đếm số request sai so với kế hoạch; mọi sai lệch, nếu có, nằm trong `mismatch_details` của facts. nDCG@10 lấy từ **ranking thực tế ghi sau đồng hồ đo**, trung bình năm lần lặp từng query rồi macro hai chủ đề; CPU là thời gian CPU của tiến trình, RSS là đỉnh bộ nhớ quan sát cả tải model và chạy. Query IDs xếp hạng được ghi ngoài vùng đo cho mọi phương án.

| Phương án | Ngân sách | TB ms | p50 | p95 | CPU ms | RSS MiB | Encode | Sai parity | OOF nDCG@10 |
|---|---|---|---|---|---|---|---|---|---|
| BM25 | 0% | 2,23 | 2,12 | 3,96 | 2,21 | 285,6 | 0,0% | 0/9.740 | 0,2899 |
| P* | 0% | 3,75 | 3,61 | 5,80 | 3,72 | 620,6 | 0,0% | 0/9.740 | 0,2952 |
| H* v2 | 100% | 23,11 | 22,80 | 28,19 | 87,29 | 724,9 | 100,0% | 0/9.740 | 0,4142 |
| R* v2 | 100% | 13,51 | 13,39 | 16,11 | 53,58 | 654,3 | 100,0% | 0/9.740 | 0,3811 |
| PE-GH v2 | 30% | 10,54 | 5,35 | 26,43 | 39,56 | 766,8 | 30,1% | 0/9.740 | 0,3423 |
| PE-GH v2 | 50% | 14,30 | 15,22 | 26,98 | 53,55 | 767,4 | 50,0% | 0/9.740 | 0,3736 |
| PE-GH v2 | 80% | 20,31 | 23,14 | 28,04 | 76,73 | 769,7 | 80,1% | 0/9.740 | 0,4096 |
| LiteGator tuned | 30% | 10,58 | 5,08 | 27,14 | 39,80 | 767,1 | 30,2% | 0/9.740 | 0,3348 |
| LiteGator tuned | 50% | 14,43 | 18,49 | 27,56 | 54,21 | 768,7 | 50,2% | 0/9.740 | 0,3674 |
| LiteGator tuned | 80% | 20,20 | 23,03 | 27,93 | 76,30 | 770,0 | 80,2% | 0/9.740 | 0,4096 |
| BERT LODO | 30% | 150,61 | 146,69 | 233,30 | 594,37 | 1230,9 | 29,9% | 0/9.740 | 0,3395 |
| BERT LODO | 50% | 162,57 | 159,24 | 264,86 | 638,98 | 1232,7 | 50,3% | 0/9.740 | 0,3692 |
| BERT LODO | 80% | 162,24 | 158,65 | 253,17 | 635,41 | 1235,4 | 80,1% | 0/9.740 | 0,4103 |

Các tỷ lệ encode đếm lượt encoder arctic ở nhánh H*, không đếm forward của router BERT vốn vẫn nằm trong thời gian request; tỷ lệ thực tế của ngưỡng phân vị có thể lệch ngân sách mục tiêu trên test. OOF trên programmers/unix phục vụ đối chiếu của phiên đo; bảng §7.2 và §7.2.1 trên sáu chủ đề mới vẫn là so sánh chất lượng chưa thấy.

**So sánh cùng ngân sách mục tiêu** (v2 trừ router; âm về độ trễ nghĩa là v2 nhanh hơn):

| v2 − router | nDCG@10 [CI 95%] | Độ trễ TB ms [CI 95%] |
|---|---|---|
| LiteGator 30% | +0,0075 [−0,0000; +0,0148] | −0,04 [−0,48; +0,40] |
| LiteGator 50% | +0,0061 [−0,0003; +0,0127] | −0,13 [−0,55; +0,27] |
| LiteGator 80% | +0,0000 [−0,0029; +0,0030] | +0,11 [−0,13; +0,34] |
| BERT 30% | +0,0028 [−0,0051; +0,0108] | −140,06 [−142,28; −137,82] |
| BERT 50% | +0,0043 [−0,0039; +0,0125] | −148,27 [−150,65; −145,86] |
| BERT 80% | −0,0007 [−0,0045; +0,0031] | −141,93 [−144,17; −139,66] |

CI chất lượng dùng 10.000 bootstrap nhóm trong từng chủ đề, seed 20261019. CI độ trễ dùng 10.000 bootstrap theo query, giữ các lần lặp của cùng query đi cùng nhau, seed 42, như harness ở §6; không loại đuôi chậm. Đây là CI thăm dò, không hiệu chỉnh nhiều so sánh và không lượng hóa biến động giữa các máy hoặc các phiên đo. Facts còn có CI tỷ lệ giảm độ trễ so với H* được đo lại trong chính phiên này.

![Chất lượng và độ trễ online của các router](figures/v4_prior_online.png)

Trục độ trễ dùng thang log, nhãn ghi thời gian đo thật. Micro-benchmark Phase 1 chỉ là thông tin phụ: gate v2 ≈ 0,715 ms (TB), quyết định BERT 126,73 ms (trung vị), encode arctic 8,72 ms (trung vị); các số đó không được dùng để suy ra bảng online mới.

Kết quả đầy đủ: [facts/prior_online_report.json](facts/prior_online_report.json), [biên nhận kế hoạch](facts/prior_online_plan_receipt.json), [hai model BERT LODO](facts/prior_lodo_bert.json), [chọn recipe v2 không có chủ đề đang đo](facts/prior_v2_selection_audit.json). Toàn bộ phép đo là thăm dò; không thay các kết luận K1–K4 hay hồ sơ online cũ.

### 7.6 Đường cong và giới hạn diễn giải

![So sánh router từ hai bài báo liên quan](figures/v4_prior_curves.png)

Hình dùng ngân sách chính xác trên toàn bộ query của từng chủ đề; bảng §7.2 làm tròn số lượt encode trong từng test fold, nên số ở cùng ngân sách có thể lệch nhẹ. Đường cong là thống kê mô tả, không lựa chọn lại ngân sách vận hành. Các CI giữ sáu chủ đề cố định và lấy lại mẫu nhóm bên trong từng chủ đề, không lượng hóa độ bất định khi chuyển sang một chủ đề hoàn toàn mới.

Các con số đầy đủ nằm ở [facts/prior_comparison.json](facts/prior_comparison.json) và [facts/prior_bert.json](facts/prior_bert.json). [1] N. Arabzadeh, X. Yan, C. L. A. Clarke, *Predicting Efficiency/Effectiveness Trade-offs for Dense vs. Sparse Retrieval Strategy Selection*, CIKM 2021, tr. 2862–2866, [DOI](https://doi.org/10.1145/3459637.3482159). [2] *LiteGator: A Lightweight and Budget-Aware Retriever Routing Framework for Low-Resource Question Answering*, iCAST-ES 2025, Advances in Engineering Research 283, tr. 687–695, [DOI](https://doi.org/10.2991/978-94-6463-926-1_77).

## 8. Demo

```powershell
python scripts_shared/demo_v4.py --domain unix --port 8765   # mở http://127.0.0.1:8765
```

Gõ một câu hỏi tiếng Anh. Trang hiển thị:

- quyết định của gate (**Bỏ qua encode → P\*** hoặc **Encode → H\***), điểm gate và ngưỡng;
- thời gian từng bước (BM25, đặc trưng, gate, encode, FAISS, fusion);
- top-10 của PE-GH v2, đặt cạnh top-10 của BM25.

Demo dùng đúng gate đã đóng băng; ngưỡng là phân vị ngân sách vận hành trên query của domain đó. `--budget 0.5` để xem gate ở ngân sách khác. Domain chọn được: 6 domain đã thấy.

## 9. Kết luận và giới hạn

**Được hỗ trợ trên dữ liệu chưa từng dùng, bằng giao thức đăng ký trước:**

1. **Gate học v2 hơn quy tắc BM25-margin** ở cùng ngân sách (K1) và hơn ngẫu nhiên (K4). Đây là điều v1 và v3 không đạt được.
   - Hiệu ứng nhỏ: +0,004 nDCG@10 ở 50%.
   - Rõ hơn ở mức dự đoán: AUC 0,76 so với 0,67.
2. **PE-GH v2 giữ chất lượng của H\* trong biên 0,01 mà bỏ 20% lượt encode** (K2). Có một mất mát nhỏ, đo được: −0,006.
3. **PE-GH v2 hơn PE-GH v1 +0,069** (K3), chủ yếu nhờ chọn encoder đúng với cùng chi phí. Online: cùng độ trễ, cao hơn 0,062.
4. **Ngân sách encode là núm chỉnh tin được.** Ngưỡng phân vị lấy trên query không nhãn cho đúng tỷ lệ encode trên domain mới (79,9–80,2%) và online (30,1 / 50,1 / 79,9%).

**Không được hỗ trợ hoặc cần nói rõ:**

1. Ở ngân sách cao (≥ 80%), gate ngang margin. Giá trị của gate nằm ở vùng muốn tiết kiệm 30–90% lượt encode.
2. P\* với proxy arctic không giúp trên domain mới. Nhánh rẻ thực chất là BM25.
3. Ở ≈ 15 ms, R\* cho chất lượng cao hơn PE-GH v2 50% (trên dev). Định tuyến không phải cách duy nhất để giảm chi phí.
4. Gate không giảm p95.
5. Oracle ở 50% đạt 0,449, gate đạt 0,393: vẫn còn khoảng cách lớn.

**So sánh thăm dò (§7):** giữ kết quả BERT hơn v2 ở 80% chất lượng trên sáu chủ đề mới; ablation nhãn chưa cho thấy lợi ích rõ của tăng từ tám lên 28 đặc trưng. Phiên online đo trực tiếp toàn bộ phương án, chọn mô hình không có chủ đề đang đo, cho TB ở 50% là v2 14,30 ms, LiteGator 14,43 ms, BERT 162,57 ms, với 0 sai lệch trên 126.620 request; BERT chưa được tìm siêu tham số do chi phí nên không diễn giải lựa chọn recipe này như một ưu thế của v2.

**Cách trình bày đóng góp.** Có thể nói PE-GH v2 là *gate học đầu tiên trong đề tài thắng heuristic không học trên dữ liệu mới*, với điều kiện nêu rõ ba điểm:

- **Nhỏ:** +0,004 nDCG@10.
- **Từ đâu mà có:** nhãn "BM25 thất bại" (đúng thứ gate quan sát được) và huấn luyện đa domain.
- **Nằm ở đâu:** vùng ngân sách 10–70%.

Định tuyến trước khi encode dựa trên dự báo chất lượng BM25 đã có trong tài liệu (Arabzadeh và cộng sự, CIKM 2021). Điểm riêng của đề tài nằm ở:

- gate tuyến tính 28 đặc trưng, chi phí ≈ 0,7 ms;
- so sánh ở cùng ngân sách với heuristic, có CI;
- đo độ trễ online thật, đối chiếu từng request;
- xác nhận đăng ký trước trên 6 domain mới.

**Phạm vi:**

- **Dữ liệu:** CQADupStack. Đến nay **cả 12 subforum đều đã dùng**: v1 2, v3 4, v4 6. Mọi kiểm chứng tiếp theo cần tập dữ liệu khác (ví dụ các tập BEIR có tương quan dense/BM25 khác).
- **Mô hình và máy:** một encoder 384 chiều chạy CPU; một máy Windows 4 lõi pin. Online chỉ đo trên programmers/unix.

**Hướng tiếp theo** (đều là thăm dò; muốn thành kết luận cần dữ liệu mới):

1. Bỏ P\*, dùng BM25 ở nhánh rẻ. Không mất chất lượng trên domain mới, nhanh hơn ≈ 1,5 ms ở nhánh bỏ qua.
2. Ba tầng BM25 → R\* → H\*: gate quyết định có encode hay không, rồi có tìm FAISS hay không. Mục tiêu là vượt R\* ở cùng độ trễ.
3. HNSW cho nhánh H\* để giảm p95 (v3: tìm nhanh hơn 2–10 lần, chất lượng giữ trong 0,001).

## 10. Cách chạy lại

Mặc định `--root ~/.cache/pegh/v4`. Các domain đã thấy được đọc chỉ-đọc từ v3 và v1. Không sửa mã trong lúc chạy `online`.

```powershell
$py = "python"; $s = "scripts_shared/experiment_v4.py"; $E = "arctic_xs_q"
$seen = "android","gis","mathematica","webmasters"     # programmers/unix đã có từ v1
$new  = "english","gaming","physics","stats","tex","wordpress"
# Tuần 1: chọn encoder trên dev, rồi chốt gate bằng LODO trên 6 domain đã thấy
& $py $s vectors --encoders arctic_xs --domains programmers unix   # MiniLM/bge-small đã có từ v1/v3
& $py $s quality --encoders bge_small_q arctic_xs arctic_xs_q --domains programmers unix
& $py $s encode-cost --encoders minilm bge_small bge_small_q arctic_xs arctic_xs_q
& $py $s compare --encoders minilm bge_small bge_small_q arctic_xs arctic_xs_q
& $py $s vectors --encoders $E --domains $seen; & $py $s quality --encoders $E --domains $seen
foreach ($st in "proxy","features","tiers","develop") { & $py $s $st --encoders $E }
& $py $s freeze                      # ghi configs/v4/gate_v2.json
& $py $s preregister                 # chỉ hợp lệ khi chưa có dữ liệu domain mới
# Tuần 2: dựng 6 subforum mới, chấm K1–K4
& $py $s fetch
& $py $s vectors --encoders minilm $E --domains $new
& $py $s quality --encoders minilm $E --domains $new
foreach ($st in "proxy","features","tiers") { & $py $s $st --encoders $E --domains $new }
& $py $s evaluate
# Tuần 3: online trên programmers/unix (gate train không có domain được đo)
& $py $s online-plan; & $py $s online; & $py $s online --detailed; & $py $s online-report
# Thăm dò sau K1–K4: router từ hai bài báo liên quan, không tinh chỉnh trên chủ đề đánh giá
& $py $s prior-bert --threads 6     # dùng lại model/điểm đã lưu nếu có
& $py $s prior
# Phase 2: đo online thật; hoàn tất train/chọn mô hình/test trước khi đóng băng
& $py $s prior-lodo-bert --threads 6
& $py $s prior-tune; & $py $s prior-v2-audit
& $py $s prior-online-plan
& $py $s prior-online-freeze          # biên nhận bất biến trước đo
& $py $s prior-online-smoke
& $py $s prior-online                # không sửa mã trong suốt lượt đo
& $py $s prior-online-report
& $py $s report                      # sao chép facts + vẽ hình vào docs/v4
```
