# PE-GH

PE-GH (Pre-Encoding Gated Hybrid Retrieval) tìm câu hỏi trùng lặp trên CQADupStack. Hệ thống chạy BM25 trước. Một bộ quyết định tuyến tính dùng 28 đặc trưng của truy vấn và danh sách BM25 để chọn một trong hai nhánh:

- nhánh lai **H\***: mã hóa truy vấn bằng Arctic Embed XS, tìm vector chính xác, rồi dung hợp với BM25;
- nhánh rẻ **P\***: không mã hóa, chỉ xếp hạng lại tối đa 100 ứng viên BM25 bằng biểu diễn tĩnh.

Ngân sách mã hóa là tỷ lệ truy vấn được đưa sang H\*.

Repo này là mã của báo cáo môn học *Các vấn đề hiện đại trong công nghệ thông tin* (nhóm Trần Quang Thành, Hoàng Quốc Bảo, Đầu Hồng Quang).

**Kết quả chính.** Trên 8.303 truy vấn của sáu miền xác nhận:
- ở cùng ngân sách 50%, PE-GH cao hơn BM25-margin +0,0042 nDCG@10 (KTC 95% [0,0003; 0,0081]);
- ở ngân sách 80%, PE-GH thấp hơn hệ lai luôn mã hóa 0,0064 điểm, đạt tiêu chí không thua kém với biên 0,01.

Trong phép đo tuần tự trên CPU (Programmers và Unix), độ trễ trung bình giảm 39,3% ở ngân sách 50% và 13,7% ở ngân sách 80%. Số liệu và biên nhận nằm ở [`docs/v4/facts/`](docs/v4/facts/); diễn giải nằm ở [`docs/v4/README.md`](docs/v4/README.md).

| Thư mục | Nội dung |
|---|---|
| `src/pegh/` | Thư viện: BM25 (`sparse/`), mã hóa và FAISS (`dense/`), dung hợp (`fusion/`), đặc trưng (`gating/`, `v3/features.py`), bộ quyết định PE-GH (`v4/gate.py`), phục vụ trực tuyến (`v4/online.py`), đo CPU (`profiling/`), đối chứng LiteGator và BERT (`v4/prior.py`) |
| `contracts/` | Kiểu dữ liệu, đọc/ghi JSONL, ID, mô hình ghim revision |
| `configs/` | Cấu hình đã đóng băng: BM25, encoder, bộ quyết định (`v4/gate_v2.json`), giao thức đăng ký trước (`v4/preregistration.yaml`), máy đo (`runtime/`) |
| `data/` | Chia năm phần và manifest của Programmers, Unix (dữ liệu thô tải về, không nằm trong Git) |
| `scripts_a/`, `scripts_b/`, `scripts_c/` | Chuẩn bị dữ liệu, chỉ mục và pipeline PE-GH v1 cho Programmers và Unix (đầu vào của các vòng sau) |
| `scripts_shared/` | `reproduce.py` (chạy pipeline v1), `experiment_v3.py`, `experiment_v4.py` (vòng v4 = PE-GH bản báo cáo), `demo_v4.py` |
| `docs/v4/` | Số liệu đã đóng băng (`facts/`), hình và mô tả vòng v4 |
| `docs/integration/2026-10-26/online-manifests/` | Danh sách truy vấn đo trực tuyến theo từng phần, đầu vào của bước `online-plan` |
| `tests/` | Kiểm tra tính đúng (không cần mô hình thật, trừ các test đánh dấu `model`) |

Tên `v3`/`v4` chỉ vòng thực nghiệm. Hệ thống trong báo cáo là PE-GH v2, chốt ở vòng v4; PE-GH v1 (MiniLM) là hệ tham chiếu.

## 1. Cài đặt

Python 3.11–3.13, chạy trên CPU. Thư viện được ghim trong `uv.lock`.

```bash
python -m pip install uv==0.13.3
uv sync --locked --extra dev
```

Mô hình (Arctic Embed XS, MiniLM, BERT-base) được tải theo revision ghim trong `configs/` khi chạy lần đầu. Dữ liệu CQADupStack bản BEIR được tải bằng `scripts_a/fetch_inputs.py` và `experiment_v3.py`/`experiment_v4.py` (bước `build`, `fetch`).

## 2. Demo

### 2.1 Test (vài phút, không cần mạng)

```bash
uv run pytest -m "not model" -q
uv run pytest tests/b/test_model.py -m model -q   # cần tải mô hình thật
```

CI (`.github/workflows/ci.yml`) chạy ruff, các test trên và kiểm wheel trên Ubuntu và Windows.

### 2.2 Giao diện tìm kiếm

Sau khi có chỉ mục và bộ quyết định (mục 3):

```bash
uv run python scripts_shared/demo_v4.py --domain unix --port 8765
```

Mở `http://localhost:8765`, gõ câu hỏi để xem điểm rủi ro, nhánh được chọn, thời gian từng bước và kết quả.

## 3. Chạy lại toàn bộ

Mỗi bước ghi kết quả ra ngoài Git (mặc định `~/.cache/pegh/...`, đổi bằng `--root`, `--v3-root`, `--dev-root`, `--dev-dense-root`). Bước nào cũng kiểm checksum của đầu vào và cache, nên nên chạy vào một thư mục mới.

**Bước 1. PE-GH v1 cho Programmers và Unix.** Bước này sinh dữ liệu thô, chỉ mục BM25, chỉ mục MiniLM, các đặc trưng và lượt chạy OOF của `h_star`/`pe_gh` v1. Vòng v4 đọc lại các kết quả này: đặc trưng v1 để kiểm parity, hai cấu hình v1 trong phiên CPU chính.

```bash
uv run python scripts_a/fetch_inputs.py
uv run python scripts_a/prepare_data.py
uv run python scripts_b/build_dense.py --corpus data/raw/<miền>/corpus.jsonl --domain <miền> --output <dense-root>/<miền>   # programmers, unix
uv run python scripts_shared/reproduce.py --stage prepare --dense-root <dense-root> --cache-folder <hf-cache>
uv run python scripts_shared/reproduce.py --stage train   --dense-root <dense-root> --cache-folder <hf-cache>
uv run python scripts_shared/reproduce.py --stage quality --dense-root <dense-root> --cache-folder <hf-cache>
```

**Bước 2. Vòng v3: bốn miền phát triển còn lại** (Android, GIS, Mathematica, Webmasters) và các cache dùng chung.

```bash
uv run python scripts_shared/experiment_v3.py build
```

**Bước 3. Vòng v4: PE-GH bản báo cáo.** Thứ tự các bước:

| Bước | Nội dung | Mục báo cáo |
|---|---|---|
| `vectors`, `quality`, `proxy`, `features`, `tiers` | Vector Arctic, top-100 của từng nhánh, bảng tĩnh của P\*, 28 đặc trưng, điểm của các nhánh | 3.2–3.3 |
| `develop`, `freeze` | Chọn cấu hình bằng LODO trên sáu miền phát triển, đóng băng `configs/v4/gate_v2.json` | 3.4, 4.2 |
| `preregister`, `fetch`, `evaluate` | Băm giao thức, sau đó mới tải sáu miền xác nhận; kiểm định K1–K4, bootstrap và Holm | 5.1–5.2, 5.4 |
| `online-plan`, `online`, `online-report` | Phiên CPU chính: 10 cấu hình × 1.948 truy vấn × 5 lần lặp | 5.3 |
| `prior-*`, `prior` | Đối chứng LiteGator và BERT, phiên đo đối chiếu 13 cấu hình | 5.5 |
| `report` | Chép `facts/` và vẽ hình vào `docs/v4/` | — |

```bash
uv run python scripts_shared/experiment_v4.py <bước> --encoders arctic_xs_q
```

Phiên CPU chính dùng 4 lõi, 50 truy vấn khởi động và 5 lần lặp (`configs/runtime/cpu4.yaml`). Các số liệu trong báo cáo được đo trên Windows, Intel Core i7-9850H, RAM 16 GB.

## 4. Đọc mã

Theo thứ tự các mục của báo cáo (số dòng theo nhánh này):

| Mục | Nội dung | Mã |
|---|---|---|
| 2.1, (2.1) | Điểm BM25, gồm số lần từ xuất hiện trong truy vấn; IDF | `src/pegh/sparse/fast.py:186-188`, `src/pegh/sparse/index.py:80`, tham số ở `configs/sparse/bm25.yaml` |
| 2.1, (2.3)–(2.4) | Chuẩn hóa min–max, dung hợp tuyến tính, RRF | `src/pegh/fusion/engines.py:49`, `:63`, `:104` |
| 3.2 | P\*: trọng số SIF $a/(a+p(t))$, $a=10^{-3}$; bảng vector tĩnh | `src/pegh/v3/proxy.py:50`, `:92` |
| 3.2 | Chấm lại ứng viên và dung hợp trong tập ứng viên | `src/pegh/v3/rescore.py:16`, `:42` |
| 3.3, Bảng 3.1–3.3 | 21 đặc trưng v1 | `src/pegh/gating/features.py:11`, `:123`; mẫu dấu mã, mã lỗi, đường dẫn ở `configs/gating/protocol_v1.yaml:25-28` |
| 3.3, Bảng 3.4 | 7 đặc trưng QPP (NQC, WIG, SMV, …) | `src/pegh/v3/features.py:18`, `:45-57`, `:100` |
| 3.4, (3.2)–(3.4) | Nhãn BM25 bỏ sót, chuẩn hóa hai bước, hồi quy logistic | `src/pegh/v4/gate.py:46`, `:59`, `:66`, `:106` |
| 3.5 | Cùng ngân sách (hòa điểm theo mã truy vấn); ngưỡng vận hành | `src/pegh/v4/gate.py:134`, `:147`, `:177-240` |
| Thuật toán 3.1 | Quyết định khi phục vụ: lượt bắt buộc, so ngưỡng | `src/pegh/v4/online.py:147-153` |
| 4.2 | Chia năm phần, gom truy vấn trùng nội dung hoặc cùng liên quan | `src/pegh/data/splits.py:35` |
| 4.3 | LiteGator (SVM tuyến tính), BERT | `src/pegh/v4/prior.py:32`, `:62`, `:104` |
| 4.4 | Bootstrap theo nhóm, Holm | `src/pegh/v3/pipeline.py:432`, `scripts_shared/experiment_v3.py:448`, `scripts_shared/experiment_v4.py:652` |
| 4.5, 5.3 | Đo đầu cuối trên CPU | `src/pegh/profiling/runner.py:17`, `scripts_shared/experiment_v4.py:837`, `:1052`, `:1092` |

## 5. Giới hạn

- Các biên nhận trong `docs/v4/facts/` ghi `git_commit` = `09fdcad`. Mã đối chứng LiteGator/BERT được commit ngay sau đó, ở `143cb38`.
- Sau đó, mã được bổ sung hai phần. Phần thứ nhất kiểm checksum và provenance của cache. Phần thứ hai là `BudgetPolicy` (`src/pegh/v4/gate.py:177`): phá hòa điểm ở ngưỡng bằng mã truy vấn, giống quy tắc khi so cùng ngân sách. Ở `09fdcad`, luật khi phục vụ là `bắt buộc hoặc s(q) > τ`, đúng như Thuật toán 3.1. Chạy lại bằng mã hiện tại có thể lệch ở các truy vấn có điểm đúng bằng ngưỡng. Muốn tái lập nguyên bản một biên nhận, dùng đúng commit mà biên nhận ghi.
- Chạy lại toàn bộ cần tải mô hình và dữ liệu, và mất nhiều giờ CPU. Các phiên đo thời gian chỉ có ý nghĩa trên cùng máy và cùng thiết lập.
- Thống kê chuẩn hóa ở miền xác nhận dùng truy vấn không nhãn của toàn miền. Với cộng đồng mới chưa có truy vấn, cần ước lượng và hiệu chuẩn lại.
