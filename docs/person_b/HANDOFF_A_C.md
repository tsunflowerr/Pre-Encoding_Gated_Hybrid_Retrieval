# Handoff phần B cho A và C

Bổ sung base chung trên nhánh `codex/shared-base`: xem
[SHARED_BASE.md](../SHARED_BASE.md). A/C import `contracts` và `contracts.io` thay
vì tạo local types/loader. B v1 giữ adapter nội bộ đã khóa vào artifacts; parity
checks bảo đảm text/IDs và model config thống nhất với base mới.

## Ranh giới merge

B sở hữu `src/pegh/dense`, `src/pegh/profiling`, `configs/dense`, `configs/runtime`,
`scripts_b`, `tests/b`, `docs/person_b`, hai paper sections B và dependency/CI.
Repository ban đầu không có code, nên B bootstrap `contracts/types.py` theo plan.
A nhận ownership contracts; không tạo bản contracts khác trong từng module.
Mọi thay đổi API cần cả ba thống nhất trước. Không commit model/index/data/raw
benchmarks vào Git; small manifests, reports và figures có thể bàn giao riêng.

Nhánh B có baseline kế hoạch trên master rồi các commit triển khai riêng; merge
nhánh `codex/b-dense-profiling` vào nhánh tích hợp sau review. Nếu A/C đã phát triển
độc lập, đối chiếu root `pyproject.toml`/contracts/CI trước; không overwrite bản của
nhau. B giữ lockfile để thêm dependency mới một lần cho cả nhóm.

## A cần xác nhận

1. Canonical JSONL bytes và ordering, hash corpus, count, quy tắc namespace ID.
2. Query files theo domain/fold/split, không có duplicate query IDs.
3. Qrels độc lập với B và cách bỏ self-hit nhất quán.
4. Ranking exporter từ B có schema `schema_version,method,split,query_id,domain,
   hits,corpus_hash,retriever_hash`; hits chứa `doc_id,score,rank`.
5. Quality CSV cho đúng online run_id/query set/method/config, không nối score
   từ paper khác vào số latency local.

Nguồn adapter B và counts đã ghi README. Nếu A nhận nguồn này làm canonical,
dùng đúng file `corpus.jsonl` và `source_manifest.json`. Nếu A cần thay bytes hoặc
preprocessing, báo B rebuild artifact mới; không chỉ đổi tên field hash.
Full public reference rankings hỗ trợ kiểm tích hợp; final split vẫn do A quản.

Exporter offline hiện ghi label `method=dense`; registry mặc định dùng
`id=dense_minilm`. Đây là hai nhãn của cùng backend, không phải hai model khác.
Khi xuất quality CSV cho online report, A dùng ID từ registry và kiểm trùng
`retriever_hash`/`corpus_sha256`/query set trước khi map nhãn. Không ghép chỉ theo
tên method. Sidecar và worker provenance chứa các hash để đối chiếu.

## C dùng backend

```python
from contracts.types import Query
from pegh.dense.config import DenseConfig
from pegh.dense.encoder import CPUEncoder
from pegh.dense.retriever import FaissDenseRetriever

encoder = CPUEncoder(DenseConfig(), cache_folder="/local/model-cache")
dense = FaissDenseRetriever("/local/index/programmers", encoder, trace=trace)
ranking = dense.search(Query("programmers:example", "programmers", "query text"), k=100)
```

Factory C phải nhận keyword `trace`; loader/tạo model/index ngoài `search`, không
load lại mỗi request. Dùng config đọc từ index như `pegh.dense.factory` nếu không
dùng primary defaults; mismatch sẽ bị từ chối. `search` encode nonempty query mới
một lần. Empty query trả empty ranking và zero calls, adapter đánh dấu empty_query.

QDAP hoặc feature cần vector query dùng explicit reuse trong **cùng request**:

```python
vector = dense.encode_query(query)      # một lần, đã đếm trong trace
dense_ranking = dense.search_vector(query, vector, k=100)
# alpha/features có thể dùng chính vector này, không gọi encode lần hai.
```

Không đưa vector của query trước vào query sau hoặc mở quality cache trong online
factory. Gate skip quyết định trước dense: không gọi `encode_query` hay `search`.
Sparse results và lexical stats lấy một lần rồi tái sử dụng cho features/fusion.

Factory registry mẫu:

```json
{
  "methods": [
    {
      "id": "hybrid_rrf",
      "factory": "pegh.app.factories:create_hybrid_rrf",
      "kwargs": {"config_path": "/local/frozen-method.json"},
      "require_dense_warmup": true
    }
  ]
}
```

Đường `pegh.app.factories` trên là interface C sẽ cung cấp, chưa tồn tại trong B.
C trả object có `search(Query,k)->SearchResponse` và nên có `.provenance` JSON
serializable: model/index/corpus/sparse/fusion/gate/config/training/split hashes,
không ghi secret. Harness lưu provenance nguyên vẹn trong worker receipt.

## Instrumentation và điều kiện lỗi

`trace.stage(name)` dùng các tên `sparse`, `stats`, `features`, `gate`, `encode`,
`vector`, `fusion`. B đã wrap encode/vector thật. C/A wrap phần do mình thực hiện;
không wrap lại cùng stage phía ngoài tạo double-count. `TraceSink` không hỗ trợ
concurrent requests; batch=concurrency=1 đã chốt. Các stage phải không chồng nhau
nếu dùng stacked bars để phân tích thành phần tổng.

`SearchResponse.encoder_calls` là số lần gọi thật của request, phải bằng observed
trace. `use_dense` phải khớp 0/1 encoder calls. Gated request không có dense trả0;
dense branch trả1. Adapter gian lận trả0 trong khi encoder chạy sẽ làm worker lỗi.
Đây không chỉ là kiểm tra field gate. Mọi đường encoder mới ngoài B phải tăng
counter ở nơi thực thi thật, cùng trace mà factory nhận. Không thể kiểm một encoder
ngoài trace chỉ bằng lời khai của adapter; review code vẫn cần thiết.

Fallback ngoài empty query làm benchmark fail để không bỏ/đổi query lỗi thành số
đẹp. Điều tra lỗi rồi chạy run mới; app có thể có policy fallback khác nhưng benchmark
cuối phải ghi đủ và đối chiếu policy đã đăng ký. Output ranking unique, finite,
namespaced, consecutive ranks, score/docID sorted và không self-hit.

## Final experiment chung

- A cung cấp train/validation warmup disjoint và final test query files/folds.
- C freeze factory/config, threshold và model gate trước xem kết quả test.
- B tạo registry đúng artifact, chốt resource profile, chạy cùng máy 5 repeats.
- Chạy một method/repeat/process; không chạy build index hoặc training cùng lúc.
- Tất cả request mới encode thật nếu cần, không dùng exported quality rankings.
- Cùng seed/query order giữa methods mỗi repeat; báo source snapshots/runtime/
  power/background limitations. Windows local results không đổi nhãn thành Linux.
- A chấm chất lượng đúng run/query IDs/config; B nối vào quality CSV và vẽ riêng
  từng domain, cùng run_id. Kiểm định chất lượng do evaluator A, không do CI mean
  latency. Cùng phân tích mean, tail, calls, CPU, RSS và thất bại của gate.

## Artifact lớn và khả năng tiếp tục

Máy hiện tại dùng `C:/Users/quang/.cache/pegh`; xem status file để biết build/run
nào complete. Cần copy cả manifest,index,mapping khi chuyển máy; chunks hỗ trợ
resume nhưng không cần cho read-only retriever. Copy model cache hoặc tải lại đúng
revision. Giữ `uv.lock`/source tương ứng và chạy verify trước dùng. Registry có path
local nên tạo lại, SHA index phải giữ nguyên. Nếu thay code embedding đã đóng băng,
rebuild thay vì vô hiệu hóa compatibility check.
