# Trạng thái triển khai phần B

- Trạng thái: `in_progress`.
- Nhánh: `codex/b-dense-profiling`.
- Ngày bắt đầu: 20/10/2026, Asia/Bangkok.
- Quy tắc quota của người dùng: kiểm tra cửa sổ 300 phút thường xuyên; ngừng
  triển khai khi `usedPercent >= 90`, lưu `resetsAt`, chỉ tiếp tục sau reset.
- Heartbeat: `ti-p-t-c-pe-gh-ph-n-b-sau-reset-quota`.
- Quota đầu lượt: đã dùng 1%, còn 99%; resetsAt=1792497940.

## Đã làm

- Tạo nhánh riêng; đọc kế hoạch và xác nhận chưa có code A/C.
- Bootstrap package và contracts theo kế hoạch; tạo môi trường riêng ngoài OneDrive.
- Máy phát triển: Windows 11, 12 logical CPUs, RAM khoảng 16 GiB.
- Docker daemon hiện chưa chạy; chưa có Linux distro dùng cho benchmark chính.

## Tiếp theo

1. Lock/cài dependencies CPU trong môi trường riêng.
2. Encoder, mapping/index có checkpoint/resume và kiểm tra integrity.
3. Harness đo thật, counters/stages, resource limits, reports.
4. Tests fixture và model thật; tải corpus pinned và build hai index nếu tài nguyên cho phép.
5. Hướng dẫn tích hợp A/C, báo cáo kết quả thật, commit trên nhánh riêng.

Các run Windows sẽ ghi rõ môi trường thực tế, không gọi là kết quả Linux hoặc
claim cải thiện gate khi phần C chưa có.
