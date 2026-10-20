# Protocol validation B — đóng băng trước full online results

Ngày 20/10/2026. Mục tiêu là nghiệm thu dense backend và benchmark harness trên
dữ liệu/model thật. Đây là development validation độc lập của B trước khi A/C
cung cấp phương pháp và final protected splits.

## Cấu hình và lý do chốt

- Model/embedding pipeline chốt từ commit `669da04`; source fingerprint trong
  manifest là nguồn xác nhận thực tế, không chỉ tên commit.
- CPU MSMARCO MiniLM, revision trong primary config,384d,float32,L2,max_length256,
  exact FlatIP,k100,self-filter,tie score/docID. Không chọn bằng quality test.
- Pilot batch16/32 trên 1.024 programmers docs: batch32 chậm hơn và tốn RSS hơn
  trên profile đầu, giữ batch16. Pilot không dùng qrels.
- Máy Windows11,6 lõi vật lý/12 logical, profile local4 logical `[0,2,4,6]` trên
  bốn core khác nhau, SMT topology đã kiểm bằng Windows API. Power scheme đọc lúc
  chuẩn bị là Balanced; không thay power setting máy người dùng. Chưa có CPU
  reservation độc quyền hay container Linux. Tải nền có thể ảnh hưởng số đo.
- Programmer build có invocation đầu `[0,1,2,3]`, sau checkpoint3.584 docs đổi
  sang physical4; build_profile giữ lịch sử. Không dùng tổng build time hỗn hợp
  này để kết luận speedup giữa affinity profiles.
- Main online chỉ dùng physical4, 8.000.000.000-byte process commit cap,
  Torch/FAISS4 threads, OpenBLAS1, batch/concurrency1,50warmup,5repeat,seed42.

## Inputs và runs đã đăng ký cho B

Nguồn BEIR CQADupStack pinned trong README. Không tải qrels hoặc xem relevance
labels trong đợt B này. Public corpus/query hashes được lưu ở source manifests.

| Domain | Corpus | Queries | Main requests | Run ID |
|---|---:|---:|---:|---|
| programmers |32.176|876|4.380|programmers-main-v1|
| unix |47.382|1.072|5.360|unix-main-v1|

Public query files sử dụng toàn bộ876/1072 câu; split đặt
`development_validation`, fold=null. Không gọi đây là final test hoặc kết quả
cross-validation PE-GH. Quality top100 export gắn `public_reference` để A có thể
kiểm tích hợp, không chọn model/threshold từ chúng.

Warmup là sáu câu kỹ thuật tự viết mỗi domain tại `tests/b/fixtures`, IDs prefix
B_WARM khác measured IDs, lặp vòng đủ50requests. Final A/C run sẽ thay bằng
train/validation warmup của A. Warmup không nằm trong các4.380/5.360 timing samples.

Sau khi main complete, chạy hai detailed runs `programmers-stages-v1` và
`unix-stages-v1`: cùng factory/config, đầu128 query theo thứ tự source,1repeat,
50warmup, `detailed_stages=true`. Subset này chỉ dùng stage breakdown; không
gộp vào main statistics hoặc dùng chênh mean hai query sets để suy overhead.

Nếu run fail/paused, giữ toàn bộ output lỗi và receipt để audit. Rerun mới dùng
suffixv2 kèm lý do; không ghi đè v1 và không trộn samples giữa hai run.

## Điều kiện chấp nhận

1. Full persisted indices đúng type/dimension/count/mapping/hash, tất cả vector
   finite và norm≈1; expected counts32.176/47.382.
2. Offline exports đủ876/1.072 records,100hits/query khi corpus đủ, không selfhit,
   ranking/IDs/hashes hợp lệ. Sidecar khớp SHA output và query input.
3. Main mỗi domain đủ5worker receipts complete, mỗi worker đủquerycount; không
   thiếu/trùng query, không bỏ lỗi khỏi summary. Kỳ vọng dense-only nonempty
   encoder calls=requestcount và vector search calls>=requestcount (tie expansion
   có thể gọi FAISS thêm lần nhưng không encode lại).
4. Worker actual backend Torch/FAISS4threads,affinityphysical4,memory limit đúng
   loại; model/index/query cache provenance và source snapshots được lưu.
5. Main detailed stage đã chạy nhưng khôngtiming có null, detailedrun có measured
   durations. Stage totals có thể thấp hơn tổng latency do overhead chưa gán.
6. Rebuild summary/figures từ raw checksummed output. Mean CI bootstrap1000query
   clusters giữ repeats. p95empirical, khôngcó CI p95; CI mean khôngbao hết biến
   thiên giữa máy/ngày/power/tải nền. Kết quả không có quality tới khi A chấm.

## Khi A/C hoàn tất

Dùng cùng harness với BM25,dense,fullhybrid,gate và các baseline đăng ký; freeze
validation operating point trước test, ghép quality đúng queryset/config/run_id.
Chỉ khi đó mới báo speedup, chất lượng/non-inferiority và frontier PE-GH. Không
nhập latency paper khác hoặc số fixture vào bảng local.
