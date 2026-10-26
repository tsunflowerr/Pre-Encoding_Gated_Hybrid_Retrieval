# Chẩn đoán và thử sửa gate, 26/10/2026

Lượt tích hợp v1 và toàn bộ receipt tại `docs/integration/2026-10-26/` được giữ nguyên. Bản này tách hai thay đổi: tối ưu thực thi giữ nguyên model/score; thử chính sách threshold theo domain. Không đổi encoder, feature schema, model weights hay biên non-inferiority.

**Đã đo xong score-only:** [báo cáo và raw-receipt audit](refinement/inference-2026-10-26/README.md). 29.220 ranking online khớp OOF, 48.700 score khớp bit-exact. Mean quan sát PE-GH sklearn 18,492 → NumPy 18,106 ms (−2,09%), p95 35,908 → 35,394 ms; nDCG không đổi. CI theo process repetition [−0,09%, 4,23%] chứa 0, vì vậy không bảo đảm mức giảm request này ổn định qua lượt đo khác. Bản chính nhận tối ưu execution; giữ model/threshold v1.

**Kết quả thử threshold riêng:** không đưa vào bản chính. Macro nDCG@10 giảm từ 0,312163 xuống 0,308927; cận dưới một phía 95% của programmers so H* là −0,013157, không đạt biên −0,01. [Receipt và quyết định](refinement/threshold-experiment-2026-10-26/decision.json) lưu cả kết quả bất lợi. Validation tốt hơn không đủ để bảo đảm tổng quát hóa khi mỗi domain chỉ có khoảng 175–215 query validation và nhiều nhãn gain=0. Tiếp tục đo riêng tối ưu inference, với threshold/model v1 giữ nguyên.

## Bằng chứng nguyên nhân

Model Ridge được fit riêng cho từng domain nhưng C6 đặt chung một ngưỡng score cho hai model. Trên validation, mean score programmers khoảng 0,028–0,039 còn unix khoảng 0,006–0,018. Cùng ngưỡng dẫn tới tỷ lệ route khác nhau. Đây là dấu hiệu cần kiểm tra hiệu chỉnh/threshold riêng; chưa chứng minh mọi khác biệt giữa domain đều do ngưỡng.

Tương quan score–gain validation chỉ khoảng −0,076 đến 0,210. Khoảng 65–90% query có utility gain bằng 0; feature mã lỗi/đường dẫn rất hiếm. Threshold không thể tự sửa một bộ dự đoán yếu hoặc tạo ra tín hiệu không có trong dữ liệu. Không thêm model/hyperparameter chỉ để đuổi theo test cũ.

`ModelPredictor` trước đây gọi `StandardScaler.transform` rồi API estimator cho mỗi vector 21 chiều. Validation của các API này có chi phí đáng kể so với phép tính tuyến tính. Bản mới kiểm model/scaler lúc load, vẫn kiểm schema/dimension/finiteness mỗi request, thực hiện trừ mean, chia scale, nhân coefficient và cộng intercept theo đúng thứ tự. Logistic dùng `scipy.special.expit`. Không gộp coefficient vào scaler vì có thể đổi sai số ở sát threshold. Bản sklearn được giữ làm reference và có thể chọn bằng factory `score_execution="sklearn"`; mặc định mới là `"numpy"`. Provenance ghi rõ execution và code hash.

## Chính sách thử nghiệm đã chốt trước đánh giá lại

Mỗi domain có grid ngân sách 0,0…1,0 bước 0,1; thêm threshold v1 vào grid để không làm mất điểm tham chiếu vì rời rạc hóa. Tìm cặp threshold có dense-count thấp nhất, hòa ưu tiên macro quality cao hơn, sau đó tie-break số học cố định. Các điều kiện bắt buộc trên validation:

- Macro loss so H* không quá 0,005 và từng domain không quá 0,01 như protocol v1.
- Quality từng domain phải ít nhất bằng điểm threshold v1 trên cùng validation, tolerance số học 1e-12.
- Score bằng threshold đi skip; OOV/không có token buộc dense và được tính vào ngân sách.

Giữ nguyên Ridge gain full và model riêng từng fold/domain đã fit train-only. Không tìm thêm hyperparameter/model bằng kết quả test. Thử nghiệm không thay thế mặc định chọn threshold v1 của pipeline đã nghiệm thu; chỉ được dùng qua registry v2 rõ ràng.

## Phạm vi suy luận

Tập test v1 đã được xem trong quá trình phát triển. Vì vậy việc chấm lại OOF trên cùng query phải ghi `exploratory_reassessment_of_previously_observed_test_not_fresh_confirmation`. Chọn ngưỡng bằng validation không biến tập test đã xem thành một tập xác nhận mới. Cần tập holdout ngoài các query này hoặc tái lập độc lập để xác nhận đóng góp khoa học. Nếu v2 không cải thiện, giữ nguyên kết quả đó và không đổi ngưỡng sau khi xem điểm.

## Chạy lại

Từ checkout có source cố định và `uv sync --locked --extra dev`, gọi dạng module:

```powershell
python -m scripts_c.refine_gate --stage freeze `
  --base-root C:/path/to/integration-v1 `
  --output-root C:/path/to/refinement-new `
  --runtime configs/runtime/cpu4.yaml
```

`base-root` chứa `results/`, `artifacts/`, `data/raw/` của lượt v1 đã verify. `output-root` phải khác base và thư mục results cũ. Chạy tiếp `--stage quality`, `--stage online`, `--stage report` với cùng tham số và source. Stage freeze kiểm validation labels/predictions/provenance, parity mọi model và ghi hash đầu vào. Không sửa code sau freeze.

Mặc định `--policy score_only` chỉ đổi execution sklearn → NumPy, dùng nguyên threshold v1 và bắt buộc ranking khớp v1. Muốn tái lập thử nghiệm threshold đã bị loại, dùng `--policy domain_threshold` ở mọi stage; không dùng chính sách đó cho bản chính. PE-v2 trong tên method là nhánh đối chiếu của policy đã ghi trong freeze, không mặc định có nghĩa là threshold mới.

Online đo H*, PE-v1 với sklearn và PE-v2 với NumPy theo policy đã freeze, cùng baseline execution profile đã chọn bằng validation ở v1. Có 10 tổ hợp fold/domain, năm lần lặp, 29.220 request; v1/v2 và H* được đo lại cùng lượt, không ghép latency của hai lượt máy. S* v1 có cùng ranking H* nên không tạo thêm một method timing trùng chức năng trong thử nghiệm này. Main timing tắt stage instrumentation. Microbenchmark inference là phép đo riêng, không dùng thay latency request.

Có thể dùng `--stop-file` và `--restart-incomplete` như runner B: thư mục fold dở được lưu trữ rồi chạy lại nguyên fold. Source, input, runtime và các fold complete phải khớp. Raw timing giữ ngoài Git. `report.json` kiểm ranking/counters và ghi cả kết quả thuận lẫn bất lợi.
