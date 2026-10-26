# Trạng thái triển khai phần B

## Sửa chi phí gate inference sau reset quota 26/10/2026

- Đã đo xong 150 worker/29.220 request từ source bất biến `b02191a`; fold dở được lưu và đo lại toàn fold, không trộn worker dở.
- Score NumPy khớp 48.700 score sklearn; model, threshold, ranking và quality v1 giữ nguyên. Mean quan sát giảm thêm 2,09%, nhưng CI process repetition chứa 0; không phóng đại microbenchmark thành speedup toàn request.
- [Báo cáo, CPU/RSS audit và hai bootstrap](../refinement/inference-2026-10-26/README.md). Thử threshold riêng đã loại vì chất lượng programmers không đạt biên; bản chính chỉ nhận sửa execution.

## Tích hợp toàn hệ thống 26/10/2026

- Nhánh `thanh` đã tích hợp A/B/C và sửa các lỗi review A; bốn file dense frozen giữ nguyên byte.
- Lượt mới trên i7: 29.220/29.220 ranking online khớp OOF, ba method cùng backend sparse tăng tốc, baseline chọn execution trên validation.
- Mean PE-GH giảm 34,76% so H*, dense ratio 57,75%, quality đạt biên đã đăng ký; kết quả từng domain và p95 có giới hạn cần công bố.
- [Báo cáo/receipts](../integration/2026-10-26/README.md), [hướng dẫn tái lập](../INTEGRATION_V2.md). Các nghiệm thu B ngày 20–21/10 bên dưới được giữ làm lịch sử.

## Cập nhật sau review 21/10/2026

- Nhánh `thanh` đã lấy base chung từ `main`; tên base tích hợp hiện là `main`.
- Đã sửa kiểm dependency/index, source root, domain isolation, sparse gọi lặp,
  provenance/runtime giữa workers và quality–latency binding.
- 84 tests qua gồm model thật; Ruff đúng phạm vi CI, lockfile và pip check qua.
- Kiểm lại mọi vector của hai full indices; audit 9.996 requests/1.948 rankings
  qua; số summary tính lại khớp raw. 47 archive files giữ nguyên so với Git.
- CLI smoke thật từ ngoài checkout qua: offline/online rankings và hai binding
  hashes khớp. Không dùng smoke làm số liệu nghiên cứu.
- Parent main đã qua hosted CI cả Ubuntu/Python 3.11 và Windows/Python 3.12.
- Báo cáo và machine receipt: [REVIEW_2026-10-21.md](REVIEW_2026-10-21.md),
  [REVIEW_2026-10-21.json](REVIEW_2026-10-21.json).

## Bản nghiệm thu gốc 20/10/2026

- Trạng thái: `complete` — đã triển khai, chạy dữ liệu thật và audit phần B.
- Nhánh: `thanh`.
- Ngày: 20/10/2026, Asia/Bangkok.
- Quy tắc quota: kiểm tra cửa sổ 300 phút thường xuyên; dừng khi usedPercent >=90,
  chỉ tiếp tục sau reset. Đã hoàn tất trước ngưỡng, lần kiểm gần nhất dùng 61%, còn 39%.
- Reset của cửa sổ đang theo dõi: `1792497940`.
- Heartbeat riêng: `ti-p-t-c-pe-gh-ph-n-b-sau-reset-quota` đã đặt `PAUSED` sau khi
  hoàn tất; không còn tự động tiếp tục công việc đã xong.
- Không còn build/benchmark đang chạy: session 83667 và 13742 đều exit 0.

## Đã nghiệm thu

- CPU encoder pinned, 384d/float32/L2/max_length=256; FAISS FlatIP exact và mapping.
- Streaming build/checkpoint/resume/source hashes; query fresh encode một lần.
- Full indices: programmers 32.176 docs, unix 47.382 docs; verify mọi vector passed.
- Offline exports: 876/1.072 public queries, 100 hits/query.
- Online main: 5 repeats/domain, 4.380/5.360 samples; detailed 128 query/domain riêng.
- Full audit: 9.996 online requests và 1.948 offline rankings; mọi ranking online
  khớp offline, encoder/vector calls đúng 1/request, không self-hit/fallback.
- 37 tests passed gồm pinned model thật, NumPy/FAISS, integrity/resume và resource/
  counters/skip checks. Ruff, lockfile và dependency compatibility passed.
- README/handoff/protocol, background/results sections, summary CSV/JSON/figures,
  receipts/checksums đã có. Hosted CI được khai báo, chưa push/chạy trên GitHub.
- Đã kiểm SHA256 của 44 evidence copies khớp Git blobs đã commit; archive giữ
  nguyên bytes/newlines để checkout không phá catalog hashes.

## Kết quả local

| Domain | Mean ms | p95 ms | Peak RSS MiB |
|---|---:|---:|---:|
| programmers |32,120|42,860|497,89|
| unix |48,584|63,650|522,96|

Đây là dense-only development validation trên Windows 11/i7-9850H, physical4
logical processors [0,2,4,6], process commit cap 8 GB. Không phải final protected
PE-GH test, quality scores hay chứng cứ speedup gate. Xem paper/05b_efficiency_results.md
và docs/person_b/validation/FINAL_AUDIT.json để đọc phạm vi/nguồn số.

## Artifact ngoài Git

- Venv: `C:/Users/quang/.cache/pegh/b-dense-profiling/.venv`.
- Input: `C:/Users/quang/.cache/pegh/data/{programmers,unix}`.
- Model: `C:/Users/quang/.cache/pegh/models`.
- Full indices: `C:/Users/quang/.cache/pegh/artifacts/final-v1/{programmers,unix}`.
- Quality: `C:/Users/quang/.cache/pegh/results/quality/*-top100.jsonl`.
- Raw runs: `C:/Users/quang/.cache/pegh/results/online/{domain}-{main,stages}-v1`.
- Small copied artifacts/catalog: `docs/person_b/validation/`.
- Pilot16/32 cũ được giữ ở artifacts/primary và artifacts/batch32; không resume
  chúng vì fingerprint phiên bản trước. Chúng không phải full indices.
- STOP điều khiển: `C:/Users/quang/.cache/pegh/control/STOP_PART_B` (không tồn tại
  ở thời điểm hoàn tất). Không tự tạo build/run trùng khi task này đã complete.

## Provenance và tích hợp còn lại của nhóm

- Baseline kế hoạch/contracts: 6b3bbe1; B implementation: 8888845,669da04,0c73cce,
 6d25720. Benchmark executable freeze tại 6d25720; script audit và tài liệu bàn giao
  thêm sau timing. Source snapshots/commits trong receipts ghi điều kiện thực tế.
- Programmers build có invocation đầu [0,1,2,3], đổi sau 3.584 docs sang physical4;
  lịch sử được giữ, không gọi tổng build time là một phép so affinity công bằng.
- A nhận canonical JSONL/hash/IDs, qrels/splits/evaluator; C nhận backend/factory/
  trace và bổ sung BM25/hybrid/gate/app. Không tự triển khai toàn bộ A/C trong B.
- Khi A/C có frozen methods và final query files, dùng harness đã bàn giao để chạy
  phép so đầy đủ; không tiếp tục tự động các thí nghiệm đó từ heartbeat phần B.
