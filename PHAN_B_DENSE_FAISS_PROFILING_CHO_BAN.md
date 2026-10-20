# Phần B dành cho bạn — Dense encoder, FAISS và đo hiệu năng

**Ngày:** 20/10/2026 · **Ngân sách:** 80 giờ trong 8 tuần.  
**Kế hoạch đầy đủ:** `PE_GH_KE_HOACH_HOAN_CHINH_3_NGUOI_V2.md`, đặc biệt mục 7, 13, 17, 19 và 21.

Bạn đã chọn thiên về kỹ thuật hệ thống. Vì vậy, phần phù hợp nhất là **xây dense retrieval đúng và chứng minh lợi ích hiệu năng của cả hệ thống bằng phép đo công bằng**. Bạn có quyền sở hữu một khối kỹ thuật rõ; A làm dữ liệu/BM25/evaluator, C làm fusion/gate/orchestrator. Cả ba cùng review nhưng không sửa chéo module tùy ý.

Tài liệu này là phiếu giao việc, chưa phải báo cáo code hoặc benchmark đã chạy. Các ví dụ code/lệnh phải được triển khai và kiểm tra trong môi trường nhóm trước sử dụng chính thức.

## 1. Kết quả cuối bạn cần nộp

1. Dense backend có cùng API cho mọi method, chạy CPU và trả top-100 document IDs đúng.
2. FAISS FlatIP indexes cho programmers/unix, kèm ID mapping, hashes và build profile.
3. Dense quality runs để A/C tạo baseline, target và chấm chất lượng.
4. Online benchmark harness cho BM25/dense/hybrid/gated methods; có encode query thật.
5. Raw logs và bảng mean/p50/p95, CPU time, RSS, dense calls, indexing cost.
6. Hình quality–latency, stage breakdown và phân tích tại sao p95/RAM có thể không giảm.
7. Một phần báo cáo về dense implementation và một phần kết quả hiệu năng, dựng lại từ script.

## 2. Cấu hình chính

| Thành phần | Chốt |
|---|---|
| Model | `sentence-transformers/msmarco-MiniLM-L6-cos-v5` |
| Revision | `14ca9be4bbcf1402eac0f43a2e2ccb6e0f994ba3` |
| Device | CPU, xác nhận tensor device thật |
| Pooling | Theo SentenceTransformer/model config; không tự đổi sang CLS |
| Dimension/dtype | 384 / float32 |
| Normalize | L2, kiểm tra norm và NaN |
| Max length | 256 wordpieces, lựa chọn chủ động của nhóm |
| Index | `faiss.IndexFlatIP` |
| Candidate | 100 sau self-filter; search 101 để có thể bỏ một self hit |
| Online | batch=1, concurrency=1, không cache query embedding |
| Tài nguyên mục tiêu | 4 logical CPUs, RAM giới hạn theo kế hoạch chính |

Model ban đầu `all-MiniLM-L6-v2` có dữ liệu Stack Exchange/duplicate pairs trong [model card](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2). Chưa xác nhận overlap từng mẫu, nhưng cần công bố rủi ro. Model MS MARCO được chọn làm chính để giảm rủi ro nguồn đã nhận diện; xem [model card](https://huggingface.co/sentence-transformers/msmarco-MiniLM-L6-cos-v5). Không chọn model bằng cách chạy test rồi lấy model có số đẹp nhất.

## 3. Đường dẫn chỉ mình bạn phụ trách

```text
src/pegh/dense/
src/pegh/profiling/
configs/dense/
configs/runtime/
scripts_b/
tests/b/
docs/person_b/
paper/02b_dense_and_efficiency_background.md
paper/05b_efficiency_results.md
pyproject.toml
lockfile
.github/workflows/ci.yml
```

`contracts/` do A giữ; `app/factories` do C giữ. Bạn gửi yêu cầu interface/dependency, không tự sửa schema rồi bắt hai người khác theo. Bạn giữ lockfile chung để tránh conflict môi trường.

## 4. Việc đầu tiên: toy correctness, rồi mới build lớn

Trong buổi đầu:

1. Nhận fixture và types từ A. Nếu chưa sẵn sàng, chỉ dùng fixture tổng hợp theo schema đã chốt.
2. Dựng môi trường CPU, khóa OS benchmark mục tiêu và ghi phiên bản.
3. Load model đúng revision; encode khoảng 20 tài liệu và vài query.
4. Kiểm tra shape `(N,384)`, float32, norm gần 1, không NaN/Inf.
5. So top IDs và scores của FAISS với phép dot product NumPy.
6. Save index + ID mapping; load trong process mới và search lại.
7. Gửi C một backend toy và manifest mẫu để họ tích hợp trước.

Ví dụ cốt lõi để hiểu đường xử lý, chưa bao gồm ID mapping/self-filter/error handling:

```python
import numpy as np
import faiss
from sentence_transformers import SentenceTransformer

model = SentenceTransformer(
    'sentence-transformers/msmarco-MiniLM-L6-cos-v5',
    revision='14ca9be4bbcf1402eac0f43a2e2ccb6e0f994ba3',
    device='cpu',
)
model.max_seq_length = 256
texts = ['first technical document', 'second technical document']
vectors = model.encode(
    texts, batch_size=16, convert_to_numpy=True,
    normalize_embeddings=True, show_progress_bar=False,
).astype('float32')
assert vectors.shape == (2, 384)
assert np.isfinite(vectors).all()
assert np.allclose(np.linalg.norm(vectors, axis=1), 1.0, atol=1e-4)
index = faiss.IndexFlatIP(384)
index.add(np.ascontiguousarray(vectors))
query_vector = model.encode(
    ['example query'], convert_to_numpy=True,
    normalize_embeddings=True, show_progress_bar=False,
).astype('float32')
scores, rows = index.search(np.ascontiguousarray(query_vector), 2)
```

Ví dụ không phải một search service hoàn chỉnh. Trong implementation thật, `rows` phải được ánh xạ về document IDs. Không dùng thứ tự row làm doc ID, không encode chuỗi ID và không trộn vector hai model.

## 5. Build corpus và nghiệm thu index

Nhận từ A: iterator tài liệu theo thứ tự canonical, `doc_id`, hàm dựng `title + newline + text`, corpus hash và count. Index từng miền; không gộp hai corpus thành một chỉ để tiện code.

Bắt đầu với pilot 1.000 tài liệu. Batch 16 là điểm xuất phát; giảm nếu peak RAM quá cao. Ghi throughput và truncation rate rồi mới dự toán wall time full corpus. Cho phép resume theo chunk và kiểm tra ordering hash; nếu resume làm row/document lệch thì phải phát hiện ngay.

Điều kiện index complete:

```text
index.ntotal == len(doc_ids) == expected_corpus_count
```

Vectors thô dự kiến:

- programmers: 49.422.336 bytes ≈ 47,13 MiB.
- unix: 72.778.752 bytes ≈ 69,41 MiB.
- Tổng: 122.201.088 bytes ≈ 116,54 MiB.

Đó không phải tổng RSS. FAISS có thể giữ copy vector; còn model, sparse index, corpus text, Python objects và tensors tạm. Tránh giữ nhiều bản toàn corpus cùng lúc. Xem [FAISS indexes](https://github.com/facebookresearch/faiss/wiki/Faiss-indexes).

## 6. API bàn giao

Backend chính theo contract:

```python
def search(self, query: Query, k: int = 100) -> Ranking:
    ...
```

Backend tự encode query một lần, search `k+1`, bỏ self-ID nếu có và trả k hits. IDs đã namespaced; ranking giữ corpus/retriever hashes. C không cần biết FAISS hoặc Torch bên trong.

Với benchmark tổng, C cung cấp `SearchMethod.search -> SearchResponse`. Harness của bạn chỉ gọi interface này. Nhận factory/config trước, khởi tạo model/index ngoài timer. Dùng mock methods để hoàn thành harness trong lúc C chưa train gate.

Đường quality cache và đường online phải tách executable. Quality cache có thể chứa query vectors; online executable không được mở chúng.

## 7. Quy tắc đo quan trọng nhất

Timer bao preprocessing → sparse → features/gate → encoder nếu cần → vector search → fusion → ranking top-100. Model/index load, UI/network và disk logging nằm ngoài timer chính, được báo riêng nếu cần.

Mỗi method chạy một process, một benchmark tại một thời điểm. Warmup tối thiểu 50 query train/validation, gồm cả nhánh dense. Năm repeat cho operating point chính, cùng query order giữa các method ở mỗi repeat; cân bằng method order. Không lấy các warmup query vào statistics.

Ghi ít nhất:

```text
run_id, method, fold, domain, query_id, repetition,
total_ns, process_cpu_ns,
sparse_ns, stats_ns, features_ns, gate_ns,
encode_ns, vector_ns, fusion_ns,
use_dense, encoder_calls, fallback_reason
```

Đặc biệt kiểm tra:

- Gate skip: encoder calls thật bằng 0; không chỉ thấy `use_dense=False`.
- Gate dense: encode đúng một lần; không encode lại để dự đoán alpha.
- BM25 không chạy lại trong fusion.
- Không batch queries hoặc cache query embedding trong online benchmark.
- Counter và total request count khớp, không bỏ query chậm/lỗi khỏi mẫu.
- Process CPU time gồm công việc threads; ghi API đo và đơn vị.

Nếu làm full-hybrid song song, tổng CPU quota vẫn như PE-GH. Chọn runtime profile bằng validation, trước xem test. Nếu chỉ làm tuần tự, báo đúng phạm vi so sánh; không dùng baseline code lỗi encode lặp để tạo speedup.

## 8. Những điều bạn cần giải thích trong báo cáo

**Mean và p95 khác nhau.** Nếu còn 60% query chạy dense, p95 thường vẫn nằm trong nhánh dense. Đừng hứa giảm 45% p95 dựa trên 40% query skip.

**RAM và compute khác nhau.** Model/index vẫn resident khi skip; gate chủ yếu tiết kiệm CPU work. Giảm RSS phải đo riêng, không suy từ dense-call ratio.

**Exact search vẫn có chi phí corpus.** FlatIP không có lỗi ANN, nhưng scan 47k vector có thể chiếm phần đáng kể; phải đo encode và vector riêng.

**CPU thread settings không bằng hard resource cap.** Ghi quota/affinity/RAM limit thật. Nếu chưa enforce được, nói đúng là chỉ giới hạn cấu hình thread.

**Corpus cache là hợp lệ, query cache cần phân biệt.** Retrieval luôn có offline index. Lợi ích gating đang kiểm tra là chi phí online của query mới.

**Latency số ngoài không thể nhập vào bảng chung.** Mã nguồn tham khảo có đường QDAP-S encode lặp; hạ tầng nhóm phải encode một lần để đối chứng công bằng. Xem audit chi tiết trong kế hoạch chính.

## 9. 80 giờ phân bổ

| Công việc | Giờ |
|---|---:|
| Đọc/audit encoder, FAISS, benchmark | 6 |
| CPU environment và lockfile | 8 |
| Streaming encoding/checkpoint | 12 |
| FAISS/mapping/search/save-load | 10 |
| Harness và instrumentation | 12 |
| Pilot thread/resource/fairness | 10 |
| Final timing/CPU/RAM | 8 |
| Figures, viết, review/rerun | 8 |
| Dự phòng | 6 |
| **Tổng** | **80** |

Tuần 1–2: toy và pilot. Tuần 3: full indexes/runs. Tuần 4: harness. Tuần 5: validation profile/freeze. Tuần 6: test timing. Tuần 7–8: phân tích/viết/release. Họp/review đã nằm trong tổng.

## 10. Checklist nộp phần B

- [ ] Model/revision/device/max_length được ghi, không đổi theo kết quả test.
- [ ] FAISS khớp dot-product baseline trên fixture, IDs đúng sau save/load/resume.
- [ ] Complete counts và hashes cho hai miền.
- [ ] Không NaN, norm đúng, text đúng, pooling đúng.
- [ ] Quality run và online runtime dùng cùng retrieval config.
- [ ] Không cached query vectors; counters chứng minh skip/single encode.
- [ ] Raw timing đủ năm repeat, warmup/order/runtime metadata đầy đủ.
- [ ] Có OS RSS/CPU measurements và index build report.
- [ ] Có bảng mean/p95/CPU/RAM, stage breakdown và Pareto từ script.
- [ ] A/C chạy lại được phần của bạn từ manifest.
- [ ] Báo cáo nêu rõ tác động tới mean, p95, RAM và giới hạn profile.

Khi các mục này đạt, phần B đã hoàn chỉnh dù gate của C có tạo ra cải thiện hay không. Đánh giá một phương pháp không hiệu quả bằng hạ tầng đo đúng vẫn là đóng góp kỹ thuật có giá trị cho cả dự án.
