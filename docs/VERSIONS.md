# Phiên bản hệ thống và vòng thực nghiệm PE-GH

**Hệ thống hiện hành là PE-GH v2, được nghiên cứu trong vòng thực nghiệm v4.**
Tên thư mục v3/v4 chỉ các vòng thực nghiệm, không đánh số lại phiên bản hệ thống.

| Phạm vi | PE-GH v1 | PE-GH v2, vòng v4 |
|---|---|---|
| Gate chính | Ridge dự đoán lợi ích Hybrid so với BM25 | Logistic dự đoán BM25 thất bại, nDCG@10 = 0 |
| Đặc trưng của model đóng băng | 21 | 28, gồm 21 đặc trưng v1 và 7 QPP |
| Encoder chính | MiniLM | Snowflake arctic-embed-xs, có query prefix |
| Nhánh rẻ / đắt | BM25 / Hybrid | P* proxy / H* Hybrid |
| Phạm vi chính | Programmers và Unix | 6 miền huấn luyện và 6 miền xác nhận mới |
| Chọn điểm vận hành | Ngưỡng trên validation theo ràng buộc chất lượng | Ngân sách hiệu chỉnh trên query không nhãn |

Vòng v3 kiểm tra proxy, re-scoring R*, QPP, encoder bge-small và HNSW, trước khi
vòng v4 chốt PE-GH v2. V4 tái sử dụng mã v3 nên các test v3 vẫn cần chạy.
Trong phiên online đối chứng thăm dò, chọn model lồng nhau có thể chọn 21 đặc trưng
cho Unix; con số 28 trong bảng nói về model v2 đóng băng cho sáu miền xác nhận.

## Tài liệu nên dùng

- **Giới thiệu và kết quả hệ hiện hành:** [kết quả tổng hợp v2](KET_QUA_TONG_HOP_PE_GH.md)
  và [phương pháp, giao thức, bằng chứng v4](v4/README.md).
- **Vòng trung gian:** [báo cáo v3](v3/README.md), [chương thực nghiệm v3](../paper/06_v3_round.md).
- **Thiết kế và nghiệm thu v1:** [method](../paper/03_method.md),
  [experimental setup](../paper/04_experimental_setup.md),
  [quality](../paper/05a_quality_results.md), [nghiệm thu A](person_a/EXECUTION_SUMMARY.md).
- **Giới thiệu v1:** [bản ngắn v1](../GIOI_THIEU_DE_TAI_PE_GH_v1.md),
  [bản chi tiết v1](../GIOI_THIEU_DE_TAI_PE_GH.md).
- **Slide HTML:** [bộ trình chiếu v1](../slides/pegh/PE_GH_SLIDES.html), có trang đối chiếu
  v1/v2. Các trang phương pháp và số liệu tiếp theo của bộ này vẫn thuộc v1.

Không dùng số liệu v1 để mô tả Gate logistic/arctic, hoặc gộp latency từ các phiên
máy khác nhau. So sánh BERT/LiteGator là thăm dò sau K1–K4; CI chứa 0 không tự
chứng minh tương đương chất lượng.

## Cập nhật kỹ thuật sau merge, 07/11/2026

- CI thu thập toàn bộ `tests/`, kể cả v3/v4. Wheel bao gồm các module của hai vòng.
- Resume kiểm tra checksum, corpus, query, cấu hình model/revision/prefix và provenance
  của features/tiers. Cache không khớp hoặc NPZ cũ chưa có sidecar sẽ báo lỗi rõ.
- Cache cũ không được tự gắn provenance mới. Để tái tạo, chọn **workspace/output mới**
  bằng `--root` và `--v3-root`, dựng các phụ thuộc rồi mới chạy bước phát triển/đánh giá.
  Model, raw data và index v1 đã xác minh có thể tiếp tục làm đầu vào; NPZ thiếu biên
  nhận phải được tính lại. Để tái lập nguyên bản một receipt lịch sử, dùng đúng source
  snapshot/commit mà receipt ghi, cùng artifact và môi trường đã đóng băng của lượt đó.
- Kế hoạch online mới lưu `budget_policy`: cutoff điểm và query ID phá hòa, dùng chung
  cho dự đoán offline và quyết định online. Exact budget chỉ đúng trên tập hiệu chỉnh;
  query buộc encode tạo ra tỷ lệ tối thiểu, và phân phối query mới có thể làm lệch tỷ lệ.
- Plan lịch sử chỉ có scalar threshold vẫn đọc được theo quy tắc cũ. Không thay plan,
  model, bảng số liệu hay biên nhận thực nghiệm đã đóng băng khi cập nhật mã.

Sau khi sửa mã, dùng output mới để đo parity trước benchmark tiếp theo. Các số liệu
K1–K4 và online đã công bố không được xem là kết quả chạy lại bằng bản mã cập nhật này.
