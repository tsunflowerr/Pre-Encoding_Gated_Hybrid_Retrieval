# Kết quả tổng hợp PE-GH — cập nhật 02/11/2026

**Đề tài:** Tìm kiếm câu hỏi kỹ thuật bằng truy xuất lai có chọn lọc.

File này gom toàn bộ kết quả của hệ thống cuối (PE-GH v2) vào một chỗ để viết báo cáo và slide. Chi tiết phương pháp, cách chạy lại và mọi bảng phụ nằm ở [v4/README.md](v4/README.md); số liệu gốc ở [v4/facts/](v4/facts/).

## Đọc nhanh

1. **Kết quả chính (đăng ký trước, 6 chủ đề chưa từng dùng): cả 4 giả thuyết K1–K4 đều đạt.**
   - Gate học hơn quy tắc BM25-margin (lần đầu trong đề tài).
   - Bỏ 20% lượt chạy Dense mà vẫn giữ chất lượng của luôn-chạy-Hybrid trong biên 0,01.
   - Hơn hẳn PE-GH v1.
2. **Online:** ở 50% chạy Dense, PE-GH v2 nhanh hơn luôn-chạy-Hybrid khoảng 39% (14,8 ms so với 24,3 ms). Ở cùng độ trễ với PE-GH v1, PE-GH v2 có nDCG@10 cao hơn +0,062.
3. **So với hai bài báo liên quan (thăm dò, đo thật):**
   - So với router BERT của Arabzadeh: chất lượng ngang nhau, nhưng **PE-GH v2 nhanh hơn 8–14 lần**.
   - So với LiteGator: tốc độ như nhau; chất lượng ngang hoặc nhỉnh hơn nhẹ nhưng chưa có ý nghĩa thống kê.
   - **Phải nói rõ:** trên 6 chủ đề mới, ở 80% chạy Dense, BERT cao hơn PE-GH v2 +0,0068, và khác biệt này có ý nghĩa.
4. **Giới hạn chính:**
   - Hiệu ứng của gate nhỏ (+0,004).
   - Gate không giảm p95.
   - Ở ngân sách cao (≥ 80%), gate chỉ ngang quy tắc BM25-margin.

## 1. Thuật ngữ

| Thuật ngữ | Nghĩa |
|---|---|
| BM25 | Tìm kiếm theo từ khóa. Rất nhanh (≈ 2 ms) nhưng trượt khi câu hỏi dùng từ khác tài liệu. |
| Dense | Tìm kiếm theo nghĩa: encoder biến câu hỏi thành vector rồi tìm vector gần nhất (FAISS). Tốn thêm ≈ 20 ms. |
| H\* (luôn chạy Hybrid) | Luôn chạy cả BM25 và Dense rồi trộn điểm. Chất lượng cao nhất, chậm nhất. |
| P\* | Nhánh rẻ: chỉ dùng BM25, sắp xếp lại bằng proxy tĩnh, không chạy encoder. Trên chủ đề mới thực chất ≈ BM25. |
| R\* | Encode câu hỏi nhưng chỉ chấm lại 100 kết quả BM25, không tìm FAISS. Là mốc đối chiếu, không phải hệ thống cuối. |
| Gate | Bộ quyết định rất rẻ (≈ 0,7 ms): nhìn câu hỏi và kết quả BM25, đoán BM25 có trượt không, rồi chọn chạy P\* hay H\*. |
| Ngân sách / tỷ lệ chạy Dense | Phần trăm câu hỏi được cho chạy Dense (ví dụ 50%). Đây là ngưỡng điều chỉnh do người vận hành chọn. |
| nDCG@10 | Điểm chất lượng của 10 kết quả đầu (0–1, càng cao càng tốt). Mọi bảng dùng trung bình macro theo chủ đề. |
| TB, p50, p95 | Thời gian trung bình, trung vị và mức mà 95% câu hỏi nhanh hơn, tính cho mỗi câu hỏi. |
| CI 95% | Khoảng tin cậy. Nếu khoảng không chứa 0 thì khác biệt được xem là có thật. |
| LODO | Huấn luyện bỏ hẳn một chủ đề rồi kiểm tra trên chính chủ đề đó, để mô phỏng chủ đề mới. |
| OOF | Chất lượng đo trên phần dữ liệu không dùng để huấn luyện. |

## 2. Hệ thống cuối: PE-GH v2

```
Câu hỏi → BM25 top-100 → Gate v2 ──(BM25 có vẻ ổn)──→ P* (không encode)
                                  └─(BM25 có vẻ trượt)─→ H* = BM25 ⊕ Dense arctic (encode + FAISS)
```

- **Gate v2:** hồi quy logistic, 28 đặc trưng (21 đặc trưng v1 + 7 đặc trưng QPP), chuẩn hóa theo chủ đề bằng thống kê không nhãn. Nhãn học là "BM25 thất bại" (nDCG@10 của BM25 = 0). Huấn luyện trên 6 chủ đề đã thấy, rồi đóng băng ở [configs/v4/gate_v2.json](../configs/v4/gate_v2.json).
- **Encoder:** Snowflake arctic-embed-xs có prefix cho câu hỏi. Encode mất ≈ 8,7 ms, ngang MiniLM của v1.
- **Trộn điểm:** H\* dùng CC alpha 0,7; P\* dùng proxy CC 0,3. Cả hai cố định từ các chủ đề huấn luyện.
- **Ngưỡng:** là phân vị điểm gate trên các câu hỏi không nhãn, nên tỷ lệ chạy Dense luôn bằng ngân sách đã chọn. Ngân sách vận hành là 80%. Câu hỏi không có từ nào BM25 nhận ra thì luôn được encode.

## 3. Dữ liệu

| Vai trò | Chủ đề (CQADupStack) | Câu hỏi | Tài liệu |
|---|---|---:|---:|
| Huấn luyện gate | programmers, unix, android, gis, mathematica, webmasters | 4.842 | 174.303 |
| Đánh giá (đăng ký trước, chưa từng dùng) | english, gaming, physics, stats, tex, wordpress | 8.303 | 282.896 |
| Đo online | programmers, unix (gate huấn luyện không có chủ đề đang đo) | 1.948 câu hỏi test × 5 lần lặp | — |

Cả 12 chủ đề của CQADupStack đều đã được dùng: 2 ở v1, 4 ở v3, 6 ở v4.

## 4. Kết quả chính: đăng ký trước trên 6 chủ đề mới

Giao thức đăng ký trước được băm và ghi thời điểm (30/10/2026, 01:40 UTC) **trước khi tải dữ liệu** của 6 chủ đề mới. Kiểm định dùng bootstrap 10.000 lần theo nhóm (seed 20261019) và hiệu chỉnh Holm.

### 4.1 Bốn giả thuyết

| Giả thuyết | Chênh lệch | CI 95% | p | Kết luận |
|---|---:|---|---:|---|
| K1: gate v2 hơn BM25-margin (50% chạy Dense) | +0,0042 | [0,0003; 0,0081] | 0,017 | **Đạt** |
| K2: PE-GH v2 (80%) không kém H\* quá 0,01 | −0,0064 | [−0,0085; −0,0043] | 0,0009 | **Đạt** |
| K3: PE-GH v2 hơn PE-GH v1 | +0,0690 | [0,0629; 0,0752] | < 0,0001 | **Đạt** |
| K4: gate v2 hơn chọn ngẫu nhiên (50%) | +0,0190 | [0,0155; 0,0225] | < 0,0001 | **Đạt** |

### 4.2 Chất lượng các phương án (nDCG@10)

| Phương án | nDCG@10 | Tỷ lệ chạy Dense |
|---|---:|---:|
| BM25 | 0,3267 | 0% |
| P\* | 0,3270 | 0% |
| Chỉ Dense arctic | 0,4031 | 100% |
| **H\*** (luôn chạy Hybrid) | **0,4223** | 100% |
| **PE-GH v2, ngân sách vận hành** | **0,4159** | 80% |
| PE-GH v2, 50% | 0,3933 | 50% |
| BM25-margin, 50% | 0,3892 | 50% |
| Ngẫu nhiên, 50% | 0,3744 | 50% |
| PE-GH v1 (MiniLM, dùng nhãn của chính chủ đề) | 0,3469 | 81,8% |

Tỷ lệ chạy Dense thực tế trên dữ liệu mới là 79,9–80,2% ở mọi chủ đề, tức ngưỡng điều chỉnh giữ đúng mức đã đặt.

### 4.3 Theo ngân sách (mô tả, không kiểm định)

| Tỷ lệ chạy Dense | 10% | 30% | 50% | 70% | 80% | 90% |
|---|---:|---:|---:|---:|---:|---:|
| Gate v2 | 0,3439 | 0,3702 | 0,3928 | 0,4112 | 0,4159 | 0,4196 |
| BM25-margin | 0,3393 | 0,3651 | 0,3896 | 0,4088 | 0,4168 | 0,4204 |
| Ngẫu nhiên | 0,3365 | 0,3556 | 0,3744 | 0,3934 | 0,4031 | 0,4124 |
| Oracle (biết trước đáp án) | 0,3964 | 0,4474 | 0,4490 | 0,4490 | 0,4490 | 0,4490 |

Gate hơn margin trong vùng 10–70%, còn từ 80% trở lên thì ngang. Ở mức dự đoán, gate tách rõ hơn: AUC dự đoán "BM25 trượt" là 0,764, so với 0,670 của margin, và gate cao hơn ở cả 6 chủ đề.

## 5. Hiệu năng online (programmers + unix)

Đo đầu-cuối thật: mỗi câu hỏi chạy riêng, 4 lõi CPU cố định, 50 câu khởi động. Mỗi phương án có 9.740 request. Đã đối chiếu 97.400 request với kết quả offline: **0 sai lệch**.

| Phương án | TB (ms) | p50 | p95 | Tỷ lệ chạy Dense | nDCG@10 | Nhanh hơn H\* v2 |
|---|---:|---:|---:|---:|---:|---:|
| BM25 | 2,03 | 1,96 | 3,51 | 0% | 0,2899 | 91,6% |
| P\* | 3,49 | 3,41 | 5,06 | 0% | 0,2952 | 85,6% |
| R\* | 14,70 | 14,53 | 17,66 | 100% | 0,3811 | 39,5% |
| **H\* v2** | 24,31 | 24,17 | 28,95 | 100% | 0,4142 | — |
| **PE-GH v2, 30%** | 10,68 | 5,27 | 26,77 | 30,1% | 0,3428 | 56,1% |
| **PE-GH v2, 50%** | 14,76 | 18,73 | 28,14 | 50,1% | 0,3745 | 39,3% |
| **PE-GH v2, 80%** | 20,98 | 23,91 | 29,52 | 79,9% | 0,4107 | 13,7% |
| H\* v1 (MiniLM) | 22,61 | 22,34 | 27,76 | 100% | 0,3146 | 7,0% |
| PE-GH v1 | 14,40 | 19,75 | 27,12 | 57,8% | 0,3122 | 40,7% |

Thời gian từng bước (PE-GH v2 50%):
- **Nhánh bỏ qua encode:** khoảng 4,8 ms, gồm BM25 2,4 + gate 0,7 + trộn điểm 1,7.
- **Nhánh encode:** khoảng 24,5 ms, gồm BM25 2,4 + gate 0,7 + encode 13,0 + FAISS 6,9 + trộn điểm 1,0.

## 6. So sánh với hai bài báo liên quan (thăm dò, không đăng ký trước)

Hai bài báo:
- [1] Arabzadeh, Yan, Clarke, CIKM 2021, [DOI 10.1145/3459637.3482159](https://doi.org/10.1145/3459637.3482159): BERT đọc câu hỏi và tài liệu BM25 hạng 1 để đoán BM25 có trượt không.
- [2] LiteGator, iCAST-ES 2025, [DOI 10.2991/978-94-6463-926-1_77](https://doi.org/10.2991/978-94-6463-926-1_77): SVM tuyến tính trên 8 đặc trưng nông.

Cả hai được cài lại trên cùng hạ tầng của PE-GH: cùng P\*/H\*, cùng dữ liệu huấn luyện, cùng ngân sách. Chỉ có bộ quyết định là khác nhau. Đây không phải tái lập con số gốc của hai bài báo.

### 6.1 Chất lượng trên 6 chủ đề mới, cùng số lượt chạy Dense

| Router | 30% | 50% | 80% |
|---|---:|---:|---:|
| **PE-GH v2** | 0,3698 | 0,3933 | 0,4156 |
| LiteGator [2] | 0,3671 | 0,3904 | 0,4172 |
| LiteGator [2], đã chọn cấu hình bằng LODO | 0,3678 | 0,3913 | 0,4169 |
| BERT, Arabzadeh [1] | 0,3697 | 0,3924 | **0,4224** |
| BM25-margin | 0,3648 | 0,3892 | 0,4172 |
| Ngẫu nhiên | 0,3556 | 0,3744 | 0,4029 |

| PE-GH v2 − router [CI 95%] | 30% | 50% | 80% |
|---|---|---|---|
| LiteGator | +0,0026 [−0,0015; +0,0067] | +0,0029 [−0,0008; +0,0067] | −0,0017 [−0,0035; +0,0002] |
| BERT | +0,0000 [−0,0041; +0,0042] | +0,0010 [−0,0030; +0,0051] | **−0,0068 [−0,0094; −0,0044]** |

- Ở 30% và 50%, không phân biệt được PE-GH v2 với hai router này.
- **Ở 80%, BERT cao hơn PE-GH v2, và khác biệt này có thật.**
- AUC dự đoán "BM25 trượt": PE-GH v2 0,764; BERT 0,759; LiteGator 0,706; margin 0,670.
- Ở ngưỡng mặc định của từng bài:
  - LiteGator gần như không bao giờ chạy Dense (0,05%), nên chất lượng chỉ ≈ P\*.
  - BERT với p > 0,5 chạy Dense 72,1% câu hỏi, đạt 0,4132.

### 6.2 Đo online thật, cùng harness (programmers + unix)

Cả 13 phương án được đo xen kẽ trong cùng từng lượt đo. Mỗi router được chọn cấu hình và huấn luyện **không có chủ đề đang đo**. Đã đối chiếu 126.620 request với kết quả offline: **0 sai lệch**; không bỏ request chậm nào.

Phép đo chia hai đoạn: programmers đo ngày 01/11, unix đo ngày 02/11. Máy chỉ dừng ở ranh giới giữa hai chủ đề, và không lượt nào được đo lại.

| Tỷ lệ chạy Dense | | PE-GH v2 | LiteGator | BERT |
|---|---|---:|---:|---:|
| 30% | nDCG@10 | **0,3423** | 0,3348 | 0,3395 |
| | TB / p95 (ms) | **10,54** / 26,43 | 10,58 / 27,14 | 150,61 / 233,30 |
| 50% | nDCG@10 | **0,3736** | 0,3674 | 0,3692 |
| | TB / p95 (ms) | **14,30** / 26,98 | 14,43 / 27,56 | 162,57 / 264,86 |
| 80% | nDCG@10 | 0,4096 | 0,4096 | 0,4103 |
| | TB / p95 (ms) | 20,31 / 28,04 | 20,20 / 27,93 | 162,24 / 253,17 |
| | CPU TB (ms) | 39,6 – 76,7 | 39,8 – 76,3 | 594 – 639 |
| | Bộ nhớ đỉnh (MiB) | 767 – 770 | 767 – 770 | 1.231 – 1.235 |

Mốc tham chiếu đo cùng phiên: BM25 2,23 ms (0,2899); P\* 3,75 ms (0,2952); R\* 13,51 ms (0,3811); H\* 23,11 ms (0,4142).

| PE-GH v2 − router | nDCG@10 [CI 95%] | Thời gian TB, ms [CI 95%] |
|---|---|---|
| LiteGator 30% | +0,0075 [−0,0000; +0,0148] | −0,04 [−0,48; +0,40] |
| LiteGator 50% | +0,0061 [−0,0003; +0,0127] | −0,13 [−0,55; +0,27] |
| LiteGator 80% | +0,0000 [−0,0029; +0,0030] | +0,11 [−0,13; +0,34] |
| BERT 30% | +0,0028 [−0,0051; +0,0108] | **−140,06 [−142,28; −137,82]** |
| BERT 50% | +0,0043 [−0,0039; +0,0125] | **−148,27 [−150,65; −145,86]** |
| BERT 80% | −0,0007 [−0,0045; +0,0031] | **−141,93 [−144,17; −139,66]** |

Số âm ở cột thời gian nghĩa là PE-GH v2 nhanh hơn.

**Cách hiểu:**
- **So với BERT:** chất lượng ngang nhau, CI đều chứa 0. PE-GH v2 nhanh hơn khoảng 140–148 ms mỗi câu, tức 8–14 lần. Riêng phần ra quyết định của BERT đã chậm hơn cả việc luôn chạy Hybrid (23 ms).
- **So với LiteGator:** tốc độ như nhau. Ở 30% và 50%, chất lượng PE-GH v2 nhỉnh hơn khoảng +0,007, nhưng CI chạm 0 nên chưa đủ chắc. Ở 80% thì bằng nhau.
- **Chưa kết luận PE-GH v2 có chất lượng tốt hơn.** Đặt cạnh kết quả §6.1, BERT vẫn hơn PE-GH v2 ở 80% trên 6 chủ đề mới.

## 7. Các vòng trước (để kể quá trình)

| Vòng | Dữ liệu kiểm chứng | Kết quả chính |
|---|---|---|
| v1 | programmers, unix | Gate Ridge học "lợi ích của Hybrid". Online: nhanh hơn H\* 34,8%, chạy Dense 57,8%, chất lượng không kém H\*. Nhưng ở cùng số lượt chạy Dense, gate không hơn quy tắc BM25-margin. |
| v3 | android, gis, mathematica, webmasters | Gate vẫn không hơn margin (bge-small: −0,0014 [−0,0034; 0,0004]); với MiniLM gate không có tín hiệu (AUC 0,503). P\* là kết quả dương bền nhất (+0,0063 với MiniLM, +0,0146 với bge-small). R\* nhanh hơn H\* 42,9% khi encoder yếu; khi encoder mạnh thì nên dùng HNSW (tìm nhanh hơn 2–10 lần). |
| v4 (PE-GH v2) | english, gaming, physics, stats, tex, wordpress | Đổi nhãn sang "BM25 thất bại", học trên nhiều chủ đề, dùng encoder arctic có prefix. K1–K4 đều đạt (§4). |

Chi tiết: [INTEGRATION_V2.md](INTEGRATION_V2.md) cho v1, [v3/README.md](v3/README.md) cho v3, [v4/README.md](v4/README.md) cho v4.

## 8. Giới hạn cần nêu trong báo cáo

1. **Hiệu ứng của gate nhỏ:** +0,004 nDCG@10 so với margin ở 50%. Lợi thế nằm ở ngân sách 10–70%; từ 80% trở lên thì ngang margin.
2. **K3 chủ yếu nhờ encoder:** H\* arctic hơn H\* MiniLM 0,074, gần bằng toàn bộ chênh lệch v2 − v1 (0,069). Không trình bày K3 là công của gate.
3. **Gate không giảm p95,** vì câu hỏi được encode vẫn tốn như H\*.
4. **R\* đáng lưu ý:** ở ≈ 14,7 ms, R\* (0,3811) cao hơn PE-GH v2 50% (0,3745). Kết quả này mới đo trên programmers/unix.
5. **P\* gần như không giúp trên chủ đề mới:** chỉ hơn BM25 +0,0003.
6. **Còn cách xa oracle:** ở 50%, oracle đạt 0,449, gate đạt 0,393.
7. **So sánh với bài báo là thăm dò:**
   - BERT giữ cấu hình huấn luyện như bài gốc (1 epoch, batch 8), không được tìm siêu tham số như LiteGator và PE-GH v2.
   - Ở 80%, BERT hơn PE-GH v2 về chất lượng trên 6 chủ đề mới.
8. **Phạm vi:** một bộ dữ liệu (CQADupStack), một máy Windows 4 lõi, một encoder 384 chiều chạy CPU. Online chỉ đo trên 2 chủ đề.

## 9. Câu chốt gợi ý cho slide và báo cáo

- "PE-GH v2 là gate học đầu tiên trong đề tài thắng quy tắc BM25-margin trên dữ liệu chưa từng dùng, theo giao thức đăng ký trước. Mức thắng nhỏ (+0,004) và nằm ở vùng ngân sách 10–70%."
- "Bỏ 20% lượt chạy Dense mà chất lượng chỉ giảm 0,006, nằm trong biên 0,01."
- "So với router BERT của Arabzadeh: chất lượng ngang nhau, nhanh hơn 8–14 lần và chạy thuần CPU. So với LiteGator: tốc độ như nhau, chất lượng ngang hoặc nhỉnh hơn nhẹ (chưa có ý nghĩa thống kê)."
- Khi nêu điểm khác so với tài liệu, ghi rõ: ý tưởng định tuyến trước khi encode dựa trên dự báo chất lượng BM25 đã có ở [1]. Điểm riêng của PE-GH nằm ở:
  - gate tuyến tính 28 đặc trưng, ≈ 0,7 ms;
  - so sánh ở cùng ngân sách, có CI;
  - đo độ trễ online thật, đối chiếu từng request;
  - xác nhận đăng ký trước trên 6 chủ đề mới.

## 10. Nguồn số liệu

| Nội dung | File |
|---|---|
| K1–K4, chất lượng 6 chủ đề mới | [v4/facts/evaluation_new.json](v4/facts/evaluation_new.json), [v4/facts/preregistration.json](v4/facts/preregistration.json) |
| Chọn encoder, phát triển gate (LODO) | [v4/facts/encoder_comparison.json](v4/facts/encoder_comparison.json), [v4/facts/develop.json](v4/facts/develop.json) |
| Online PE-GH v2 | [v4/facts/online_report.json](v4/facts/online_report.json) |
| So sánh với bài báo, offline | [v4/facts/prior_comparison.json](v4/facts/prior_comparison.json), [v4/facts/prior_bert.json](v4/facts/prior_bert.json), [v4/facts/prior_litegator_tuned.json](v4/facts/prior_litegator_tuned.json) |
| So sánh với bài báo, online đo thật | [v4/facts/prior_online_report.json](v4/facts/prior_online_report.json), [v4/facts/prior_online_plan_receipt.json](v4/facts/prior_online_plan_receipt.json) |
| Hình | [v4/figures/](v4/figures/) |
