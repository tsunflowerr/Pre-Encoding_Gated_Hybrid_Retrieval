# PE-GH — phần B

Nhánh triển khai: `codex/b-dense-profiling`.

Phần này cung cấp dense encoder CPU, FAISS exact search, resumable indexing,
quality-run export và online profiling. Các module dữ liệu/BM25/evaluator (A)
và fusion/gate/app (C) không được hiện thực thay trong nhánh này.

Kho mã ban đầu chưa có contracts. `contracts/types.py` là bootstrap theo đúng
interface của kế hoạch V2, để A/C có thể tích hợp; người A giữ ownership về sau.

## 1. Thành phần đã triển khai

- `CPUEncoder`: SentenceTransformer CPU float32, revision cố định, pooling từ model,
  384 chiều, max sequence length 256, chuẩn hóa L2. Không có query-vector cache.
- `build_index`: đọc corpus theo luồng, batch 16, checkpoint mỗi 512 documents,
  kiểm nguồn/hash/thứ tự và resume từ chunk hoàn chỉnh.
- `FaissDenseRetriever`: exact `IndexFlatIP`, mapping namespaced, loại self-hit,
  top-100, tie-break score giảm dần rồi doc ID tăng dần. Trường hợp hòa tại biên
  được mở rộng candidate để kết quả không phụ thuộc cách FAISS cắt tie.
- `DenseOnlyMethod`: adapter sang `SearchResponse` của nhóm.
- Harness: factory tùy biến cho từng method, process riêng cho từng repetition,
  timing online thật, warmup/counters/CPU/RSS/receipts, từ chối run thiếu hoặc lỗi.
- Report: mean/p50/p90/p95, CI cho mean theo query, CSV, latency CDF, stage bars;
  quality–latency và frontier theo từng domain khi A cung cấp quality CSV.

Thiết kế và nguồn tham khảo: [background](../../paper/02b_dense_and_efficiency_background.md).
Phân công tích hợp: [HANDOFF_A_C.md](HANDOFF_A_C.md).
Kết quả thực chạy: [efficiency results](../../paper/05b_efficiency_results.md).
Trạng thái và quota: [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md).

## 2. Môi trường

Python 3.11–3.13, `uv` và bản Torch CPU từ index PyTorch được khai báo trong
`pyproject.toml`. `uv.lock` là dependency set phải dùng chung; không resolve riêng
trên từng máy rồi gộp kết quả. CI khai báo Ubuntu/Python 3.11 và Windows/Python 3.12.
Hosted CI chỉ được coi là đã chạy khi thực sự có job trên GitHub; test local không
thay thế trạng thái đó.

Nếu chưa có uv, cài bằng `python -m pip install uv==0.13.3` trong môi trường
Python của bạn; sau đó dùng các lệnh dưới đây. Không cần quyền administrator.

PowerShell, đứng tại repository root:

```powershell
$env:UV_PROJECT_ENVIRONMENT = "$env:LOCALAPPDATA\pegh\venv"
uv sync --locked --extra dev
$taskPython = "$env:UV_PROJECT_ENVIRONMENT\Scripts\python.exe"
$taskCache = "$env:LOCALAPPDATA\pegh"
```

Linux:

```bash
export UV_PROJECT_ENVIRONMENT="$HOME/.cache/pegh/venv"
uv sync --locked --extra dev
PY="$UV_PROJECT_ENVIRONMENT/bin/python"
CACHE="$HOME/.cache/pegh"
```

Các lệnh bên dưới dùng PowerShell. Trong môi trường triển khai hiện tại, venv là
`C:/Users/quang/.cache/pegh/b-dense-profiling/.venv`, cache gốc là
`C:/Users/quang/.cache/pegh`; đặt `$taskPython`/`$taskCache` tương ứng để chạy lại.
Venv, model, dữ liệu, index và raw result đặt ngoài OneDrive/Git để tránh sync
file lớn. Không cần GPU, Java, Docker hoặc dịch vụ mạng khi model đã cache đủ.

```powershell
& $taskPython -m pytest tests/b -m 'not model' -q
& $taskPython -m pytest tests/b -m model -q
uv run --no-sync ruff check src contracts scripts_b tests/b --no-cache
uv run --no-sync ruff format --check src contracts scripts_b tests/b --no-cache
```

Model test cần model đã cache hoặc mạng. Các fake encoder trong `tests/b` chỉ để
kiểm tính đúng; latency của chúng không được dùng làm kết quả nghiên cứu.

## 3. Nguồn dữ liệu và canonical boundary

Nhận corpus/query/split chuẩn từ A nếu đã có. Adapter dưới đây cho phép B làm việc
khi A chưa triển khai, chỉ tải corpus và queries của BEIR, không tải qrels hay tự
chia fold:

```powershell
& $taskPython scripts_b/fetch_public_inputs.py --output "$taskCache/data" --domains programmers unix
```

Nguồn `BeIR/cqadupstack` pin revision
`e84b7220ce5a4e6c49aeb568983b0ec5a7584c2c`; checksum của Parquet và JSONL nằm trong
`source_manifest.json`. Count mong đợi: programmers 32.176 docs/876 queries;
unix 47.382 docs/1.072 queries. Corpus JSONL có `_id` string, `title`, `text`.
Query JSONL có `_id`, `text`; loader cũng nhận `query_id` dạng namespaced. Domain
được truyền tường minh từ CLI/API. ID raw chuyển thành `domain:raw_id`; không
encode ID thành nội dung.

Text document là các phần không rỗng của `title` và `text`, nối bằng một newline;
không lowercase, strip code hoặc đổi tokenizer sparse. Chuẩn bị này nằm trong
fingerprint của dense pipeline.

**`Ranking.corpus_hash` là SHA256 của đúng bytes corpus JSONL đầu vào**. Cùng count
hoặc cùng nội dung sau parse chưa đảm bảo cùng hash. A có thể dùng chính JSONL và
source manifest này làm canonical input; nếu A xuất bytes/thứ tự khác thì B dựng
lại index từ canonical input của A. Không tự sửa hash trong ranking để vượt check.

## 4. Build và nghiệm thu index

```powershell
& $taskPython scripts_b/build_dense.py --corpus "$taskCache/data/programmers/corpus.jsonl" --domain programmers --expected-count 32176 --output "$taskCache/artifacts/final-v1/programmers" --cache-folder "$taskCache/models" --runtime configs/runtime/cpu4.yaml --stop-file "$taskCache/control/STOP_PART_B"
& $taskPython scripts_b/build_dense.py --corpus "$taskCache/data/unix/corpus.jsonl" --domain unix --expected-count 47382 --output "$taskCache/artifacts/final-v1/unix" --cache-folder "$taskCache/models" --runtime configs/runtime/cpu4.yaml --stop-file "$taskCache/control/STOP_PART_B"
```

Thư mục output mới là mặc định; output đã có manifest cần `--resume`. Có thể dùng
`--max-new-chunks 2` để pilot rồi resume. Exit code 75 nghĩa là đã pause có kiểm
soát, không phải index hoàn chỉnh. Tạo STOP file trước khi cần ngừng; build hoàn
tất chunk đang chạy, flush checkpoint và nhả lock. Chỉ xóa STOP khi đã giải quyết
lý do dừng. Resume thêm `--resume`, giữ nguyên tất cả config và input.

`.build.lock` chứa PID. Chỉ dùng `--recover-stale-lock` sau khi kiểm đúng process
đã chết; code từ chối lấy lock của process còn sống. Không khởi chạy hai build
cùng output. Khi nguồn/config/phiên bản encoder khác, chọn output mới thay vì
resume cưỡng ép. Các file tạm bị ngắt không được tính là checkpoint hoàn chỉnh.

Manifest ghi source hash, model revision, embedding/config hash, phiên bản package,
hash implementation, chunk ID/vector hashes, counts, token-length audit, truncation
và các session build. Resume load chunk đã hoàn tất vào FAISS mà không encode lại.
`build_profile.json` ghi model-load time riêng và lịch sử resource config ở từng
invocation; session time không bao model load, có token-length audit.

```powershell
& $taskPython scripts_b/verify_dense_index.py --index "$taskCache/artifacts/final-v1/programmers" --expected-count 32176 --output "$taskCache/artifacts/verify-programmers.json"
& $taskPython scripts_b/verify_dense_index.py --index "$taskCache/artifacts/final-v1/unix" --expected-count 47382 --output "$taskCache/artifacts/verify-unix.json"
```

Lệnh verify chạy process mới, kiểm checksum, mapping, count, type/dimension và
finite/L2 norm của **mọi** vector đã lưu, không cần load model. Full online run
cũng kiểm việc load và encode query mới với model thật.

Không sửa `encoder.py`, `config.py`, `corpus.py`, `index.py` trong lúc build/resume
artifact đã đóng băng. Byte hashes của bốn file và source lớp encoder ràng buộc
implementation vào vectors; sửa—even chỉ format—cần artifact mới. `.gitattributes`
giữ LF để checkout khác OS không vô tình đổi fingerprint. File factory, profiling,
scripts không thay nghĩa vector nhưng vẫn nằm trong source snapshot của benchmark.

## 5. Quality run offline

```powershell
& $taskPython scripts_b/generate_dense_runs.py --index "$taskCache/artifacts/final-v1/programmers" --queries "$taskCache/data/programmers/queries.jsonl" --split public_reference --output "$taskCache/results/quality/programmers-top100.jsonl" --cache-folder "$taskCache/models" --runtime configs/runtime/cpu4.yaml
```

Chạy tương tự với unix. Khi A có split chính thức, truyền đúng query file và tên
split đó; script không tự chọn query từ qrels. Mỗi record chứa `Ranking` đầy đủ,
method/split/schema version. Sidecar `.meta.json` chứa query/output/model/corpus/
retriever hashes, runtime và source snapshot; đánh dấu `quality_cache=true`,
`latency_benchmark=false`. File này phục vụ evaluator A và tạo target C. Đây
không phải chứng cứ query được encode online; harness không mở nó.

## 6. Benchmark online

Tạo registry chỉ sau khi index complete. Registry lưu đường dẫn tuyệt đối máy
hiện tại và SHA256 index; tạo lại registry trên máy mới, không commit path local.

```powershell
& $taskPython scripts_b/make_dense_registry.py --index "$taskCache/artifacts/final-v1/programmers" --cache-folder "$taskCache/models" --output "$taskCache/registries/programmers.json"
& $taskPython scripts_b/benchmark_online.py --registry "$taskCache/registries/programmers.json" --queries "$taskCache/data/programmers/queries.jsonl" --warmup-queries tests/b/fixtures/warmup_programmers.jsonl --domain programmers --split development_validation --runtime configs/runtime/cpu4.yaml --output "$taskCache/results/online/programmers-main-v1" --stop-file "$taskCache/control/STOP_PART_B"
& $taskPython scripts_b/report_efficiency.py --run "$taskCache/results/online/programmers-main-v1"
```

Các warmup fixture là sáu câu kỹ thuật tự viết mỗi domain, không phải qrels/test;
chỉ dùng smoke/development này và lặp tới 50 requests. Final experiment dùng
query train/validation của A, IDs không trùng measured set, có nhánh dense.
`require_dense_warmup=true` buộc worker xác nhận nhánh encoder đã được warmup.
Với C, bổ sung method factories vào registry như hướng dẫn handoff.

Mặc định năm repetitions, batch=concurrency=1; một method/repetition trong process
mới, chạy tuần tự. Cùng query order theo seed ở mỗi repeat giữa các method;
method order shuffle theo repeat. Model/index load và disk logging ở ngoài timer.
Timer bọc trọn `SearchMethod.search`, gồm normalization/preprocessing/sparse/
features/gate/encode/vector/fusion/ranking mà method thực hiện. Đơn vị raw ns;
CPU là `time.process_time_ns()` cộng công việc threads của process.

`TraceSink` mặc định chỉ đếm stage/calls, không lấy đồng hồ mỗi stage. Stage đã
thực hiện nhưng không đo có giá trị `null`; stage không thực hiện là 0. Để có
breakdown, chạy **run khác** với `--detailed-stages --repetitions 1 --limit 128`;
không trộn timing instrumented này vào operating point chính. `--limit` bị cấm
với `--split test` để không vô tình bỏ phần test chậm.

Harness từ chối counters lệch, encode hơn một lần/request, self-hit, ranking lỗi,
fallback ngoài empty query, source drift, thiếu worker/request/repetition hoặc
raw checksum sai. STOP file dừng giữa requests/worker, đánh dấu paused. Run
paused/failed không được summarize; bắt đầu run mới đầy đủ sau xử lý nguyên nhân
(không gộp một nửa run cũ với một nửa run mới).

## 7. CPU/RAM và điều kiện tái lập

`cpu4.yaml` dùng affinity tối đa 4 logical CPUs khả dụng. Torch/FAISS 4 threads,
OpenBLAS 1, tokenizer parallelism tắt; strict memory limit 8.000.000.000 bytes.
Affinity là giới hạn CPU IDs thật, không chỉ biến môi trường. Trên Windows,
Windows Job Object áp **per-process commit memory limit**; đây không phải RSS cap.
Trên Linux fallback là `RLIMIT_AS` giới hạn address space, không phải cgroup RAM.
Nếu nhóm dùng container 8GB chính thức thì chạy lại toàn bộ methods trong cùng
container và lưu metadata; không gọi các loại memory cap này là tương đương.

`windows-physical4-local.yaml` chỉ cho máy đã kiểm topology: 6 lõi/12 luồng,
cặp SMT `(0,1)...(10,11)`, chọn `[0,2,4,6]`. Không copy CPU IDs sang máy khác
khi chưa xác nhận. Một invocation đầu programmers dùng `[0,1,2,3]`; lịch sử build
giữ cả hai điều kiện. Online run dùng một profile cố định cho mọi repetition.

RSS có sampled peak và OS high-water mark khi API có sẵn; gồm import/model/index/
warmup, không chỉ requests. CPU và RAM phải đo riêng: skip encode có thể giảm CPU
mà model/index vẫn resident. Giữ cùng máy/nguồn điện/profile, tránh job CPU khác
trong lúc đo; đây vẫn là desktop chưa có CPU reservation độc quyền. Chênh lệch
máy, OS, BLAS, version, power mode và tải nền có thể làm latency khác.

## 8. Report và quality–latency

`summary.json`, `summary.csv`, `REPORT.md`, `latency-cdf-DOMAIN.png` được tái tạo
từ raw có checksum. Mean CI bootstrap lấy **query** làm đơn vị và giữ các repeat
đi cùng; không xem 5 lần đo một query là 5 query độc lập. p95 là empirical quantile
trên các timing samples, chưa có CI p95. Không dùng CI mean này làm kiểm định
non-inferiority chất lượng.

Khi A đã chấm đúng cùng query set/method/config/run, xuất CSV:

```csv
method,domain,ndcg_at_10,run_id
dense_minilm,programmers,VALUE_FROM_EVALUATOR,programmers-main-v1
```

```powershell
& $taskPython scripts_b/report_efficiency.py --run "$taskCache/results/online/programmers-main-v1" --quality-csv "$taskCache/results/quality/quality-for-main.csv"
```

CSV không được dùng placeholder khi chạy thật. nDCG phải nằm 0..1, đúng run_id,
không trùng method/domain, đủ coverage. Script vẽ từng domain riêng và đường nối
các điểm không bị chi phối về mean latency/nDCG. Đây là frontier quan sát, không
nội suy hệ thống mới hoặc tuyên bố ý nghĩa thống kê. Khi chưa có quality A thì
không dựng số nDCG hoặc Pareto giả.

## 9. Phạm vi nghiệm thu

B cung cấp backend/harness có thể chạy các method của A/C. Khi nhánh này được
bàn giao, chưa có BM25, fusion, gate train hoặc app; vì vậy dense-only development
run xác nhận hạ tầng, không chứng minh PE-GH nhanh hơn hybrid. A/C cần cung cấp
split/evaluator/factory để chạy so sánh cuối bằng đúng harness này. Những kết quả
đó là tích hợp chung sau bàn giao, không phải code B bị thiếu.

