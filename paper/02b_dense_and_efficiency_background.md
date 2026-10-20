# Dense retrieval và phương pháp đo hiệu năng — phần B

## Thiết kế đã hiện thực

Dense backend dùng `sentence-transformers/msmarco-MiniLM-L6-cos-v5`, revision
`14ca9be4bbcf1402eac0f43a2e2ccb6e0f994ba3`, qua SentenceTransformer với pooling
theo cấu hình gốc. Mọi phép tính chạy CPU, float32; vector 384 chiều chuẩn hóa
L2. Nhóm chủ động giới hạn 256 wordpieces và ghi tỷ lệ truncation của corpus.
Tài liệu nối title/text bằng newline, giữ nguyên code. Query mới dùng cùng encoder
và config. Cấu hình không được chọn bằng cách tối ưu điểm trên test.

Model MS MARCO thay cho `all-MiniLM-L6-v2` vì model card all-MiniLM liệt kê nguồn
Stack Exchange/duplicate pairs. Đây là biện pháp giảm rủi ro nguồn đã nhận diện,
không chứng minh toàn bộ pretraining/model không có overlap. Task hiện tại là
retrieval câu hỏi trùng về kỹ thuật trên CQADupStack, không phải stack-trace search.

Mỗi domain có một `faiss.IndexFlatIP`. Với vector L2-normalized, inner product
bằng cosine similarity; exact search loại bỏ sai số ANN nhưng vẫn scan toàn bộ
corpus. Kết quả có string document ID namespaced, bỏ self-ID của query, trả tối đa
100 hits. Tie-break dùng score giảm dần rồi docID tăng dần; khi có hòa ở vị trí
cắt, mở rộng candidates để giữ policy nhất quán. Không xem row number là docID.

Build theo chunk 512, encode batch16, ghi vector/ID/hash trước khi cập nhật manifest
atomic. Resume kiểm corpus bytes/order, config, model revision, versions và source
implementation, rồi nạp chunk đã hoàn tất; không encode lại phần đó. Count nghiệm
thu là `index.ntotal == mapping count == expected corpus count`. Artifact complete
có checksum FAISS/mapping; kiểm lại mọi saved vector hữu hạn và norm gần1 bằng
process khác trước online profiling.

## Tách chất lượng khỏi chi phí online

Offline exporter sinh top100 ranking cho evaluator A, sidecar chứa hashes/query set
và đánh dấu quality cache. Online executable không mở file đó hoặc query embeddings.
Mỗi nonempty query dense-only gọi encoder đúng một lần; trace đo observed calls ở
đường encode thật. API explicit vector reuse cho phép C tính feature/alpha từ cùng
query vector trong một request, tránh baseline vô tình encode hai lần.

SearchMethod chung bao trọn preprocessing, sparse, feature/gate, dense và fusion
nếu method có. Harness khởi tạo model/index trước timer, warmup tối thiểu50 requests,
đảm bảo có dense branch rồi đo batch1/concurrency1. Một process mới cho từng
method/repetition; năm repetitions, cùng randomized query order giữa methods mỗi
repeat, method order thay đổi theo seed. Tổng latency dùng monotonic perf counter;
process CPU time cộng công việc threads. Logging disk ngoài request timer.

Main run chỉ đếm stage/calls. Detailed profiling chạy riêng có timers encode/vector/
sparse/features/gate/fusion, tránh lẫn overhead instrumentation vào operating point
chính. Run lỗi/thiếu query/fallback không hợp lệ không được summarize. Raw rows,
memory samples và worker receipts đều có checksum; source/config drift làm run fail.

## Giới hạn tài nguyên và thống kê

Runtime chốt tối đa4 logical CPUs qua affinity, Torch/FAISS4 threads, online batch1,
strict memory budget8.000.000.000 bytes. Windows implementation dùng per-process
commit limit qua Job Object; Linux fallback dùng RLIMIT_AS address-space limit.
Hai cơ chế không tương đương cgroup RSS/memory cap; metadata ghi đúng loại áp dụng.
RSS được quan sát độc lập bằng sampling và OS high-water mark, gồm load/warmup.

Mean/p50/p90/p95 được tổng hợp từ request timings; CI mean bootstrap theo query,
giữ các repetition cùng query đi cùng. Không xem repeats là mẫu query độc lập.
Quality do A chấm và kiểm định riêng; quality/latency figures phải cùng run/method/
domain/query set. Frontier là các điểm quan sát không bị chi phối; không trộn
domain hoặc dùng latency từ paper trên máy khác làm baseline local.

Gating có thể giảm mean latency/CPU qua việc bỏ encode, nhưng p95 vẫn có thể nằm
trong nhánh dense. Model/index thường resident nên giảm calls không suy ra giảm
RSS. FlatIP cũng có chi phí vector scan tăng theo corpus. Vì vậy cần đọc stage
breakdown, tail latency và memory cùng nhau trước diễn giải lợi ích PE-GH.

## Nguồn kỹ thuật

- [Model card MS MARCO MiniLM](https://huggingface.co/sentence-transformers/msmarco-MiniLM-L6-cos-v5/tree/14ca9be4bbcf1402eac0f43a2e2ccb6e0f994ba3): model/config đã pin.
- [SentenceTransformer API](https://www.sbert.net/docs/package_reference/sentence_transformer/model.html): load revision/device, encode, normalize và max sequence length.
- [FAISS index types](https://github.com/facebookresearch/faiss/wiki/Faiss-indexes): FlatIP exact search và lưu trữ vector.
- [FAISS getting started](https://github.com/facebookresearch/faiss/wiki/Getting-started): float32 arrays, add/search, ID mapping.
- [BEIR CQADupStack snapshot](https://huggingface.co/datasets/BeIR/cqadupstack/tree/e84b7220ce5a4e6c49aeb568983b0ec5a7584c2c): corpus/query source dùng cho validation B.
- [Python time](https://docs.python.org/3/library/time.html): perf_counter_ns/process_time_ns và phạm vi CPU time.
- [Windows Job memory limits](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-jobobject_extended_limit_information): phân biệt commit limit với RSS quan sát.
- [Windows processor topology](https://learn.microsoft.com/en-us/windows/win32/api/sysinfoapi/nf-sysinfoapi-getlogicalprocessorinformationex): xác định sibling logical processors cho local profile.

Các nguồn là nền tảng cho implementation; kết quả thực nghiệm phải trích raw local
artifacts, không suy số từ các trang tài liệu này. Audit phương pháp/paper của dự
án nằm trong kế hoạch V2 và `research_evidence`.
