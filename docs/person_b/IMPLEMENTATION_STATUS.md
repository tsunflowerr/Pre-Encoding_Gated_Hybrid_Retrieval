# Trạng thái triển khai phần B

- Trạng thái: `in_progress`.
- Nhánh: `codex/b-dense-profiling`.
- Ngày bắt đầu: 20/10/2026, Asia/Bangkok.
- Quy tắc quota của người dùng: kiểm tra cửa sổ 300 phút thường xuyên; ngừng
  triển khai khi `usedPercent >= 90`, lưu `resetsAt`, chỉ tiếp tục sau reset.
- Heartbeat: `ti-p-t-c-pe-gh-ph-n-b-sau-reset-quota`.
- Quota đầu lượt: đã dùng 1%, còn 99%; resetsAt=1792497940.
- Quota gần nhất: đã dùng 23%, còn 77%; cùng cửa sổ reset.

## Đã làm

- Tạo nhánh riêng; đọc kế hoạch và xác nhận chưa có code A/C.
- Bootstrap package và contracts theo kế hoạch; tạo môi trường riêng ngoài OneDrive.
- Máy phát triển: Windows 11, 12 logical CPUs, RAM khoảng 16 GiB.
- Docker daemon hiện chưa chạy; chưa có Linux distro dùng cho benchmark chính.

## Đã kiểm tra thêm

- `uv.lock` đã resolve và cài thành công trong môi trường riêng Python 3.12.
- Torch 2.14.1+cpu, FAISS 1.15.1; CUDA không khả dụng.
- Toàn bộ 32 test đã qua, gồm model pinned thật và resource cap trong subprocess.
- Đã tải/kiểm tra Parquet pinned đầy đủ: programmers 32.176 docs/876 queries;
  unix 47.382 docs/1.072 queries. Không tải qrels hay tạo split thay người A.
- Pilot batch16: 1.024 document, 2 checkpoint; khoảng 48,37 giây indexing.
- Đã commit nền `6b3bbe1` trên master; phần B ở nhánh riêng, commit `8888845`.
- Pilot batch32: 1.024 docs/50,94 giây, peak RSS OS khoảng 691 MB;
  batch16: 48,37 giây, peak khoảng 594 MB. Giữ batch16, không tune theo quality.
- Đã bổ sung validation provenance/checksums, warmup counter và chống overwrite output khác.
- Pipeline embedding hiện đã đóng băng. Hai index đầy đủ dùng thư mục `final-v1`,
  giữ nguyên các pilot cũ; không resume pilot có fingerprint phiên bản cũ.

## Artifact ngoài OneDrive

- Môi trường: `C:/Users/quang/.cache/pegh/b-dense-profiling/.venv`.
- Dữ liệu: `C:/Users/quang/.cache/pegh/data/{programmers,unix}`.
- Model cache: `C:/Users/quang/.cache/pegh/models`.
- Pilot16: `C:/Users/quang/.cache/pegh/artifacts/primary/programmers` (building, 1.024 docs).
- Pilot32: `C:/Users/quang/.cache/pegh/artifacts/batch32/programmers`.
- Full artifacts: `C:/Users/quang/.cache/pegh/artifacts/final-v1/{programmers,unix}`.
- STOP điều khiển riêng: `C:/Users/quang/.cache/pegh/control/STOP_PART_B`.
- Kiểm `.build.lock`/manifest và PID thực trước khởi chạy; không tạo build trùng.

## Tiếp theo

1. Build đủ hai index final-v1 tuần tự; giữ nguyên encoder/pipeline code trong lúc build.
2. Nếu job còn sống thì chỉ theo dõi manifest/PID; không khởi chạy job trùng.
3. Export quality top100; chạy online profiling bằng model thật và nguồn query rõ ràng.
4. Hoàn thiện report/figures/README và kết quả test; commit các thay đổi bổ sung.
5. Hoàn thành thì tắt riêng heartbeat; nếu quota >=90% thì checkpoint và ghi paused_quota.

Các run Windows sẽ ghi rõ môi trường thực tế, không gọi là kết quả Linux hoặc
claim cải thiện gate khi phần C chưa có.
