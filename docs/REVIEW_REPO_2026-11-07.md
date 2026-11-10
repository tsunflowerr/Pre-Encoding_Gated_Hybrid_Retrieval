# Rà soát repo sau khi merge thanh vào bao — 07/11/2026

## Cập nhật sau xử lý sáu mục

Sáu mục bên dưới đã được cập nhật trong working tree ngày 07/11/2026. Phần rà soát
ban đầu được giữ để truy vết lý do thay đổi.

| Mục | Trạng thái cập nhật |
|---|---|
| CI v3/v4 | `testpaths = ["tests"]`; CI thu thập cả các vòng mới |
| Wheel | Bổ sung package v3/v4; CI build và smoke-import trực tiếp từ wheel ngoài checkout |
| Cache/resume | Xác minh dense index, query/corpus/model/prefix và ranking checksum; features/tiers có sidecar ràng buộc inputs/schema/code |
| Gate hòa điểm | `BudgetPolicy` lưu cutoff và query ID phá hòa; evaluate, kế hoạch online và demo dùng cùng quy tắc |
| Diễn giải thống kê | Bỏ suy luận “CI chứa 0 nên ngang nhau” trong báo cáo tổng hợp |
| Phạm vi phiên bản | Có `docs/VERSIONS.md`; paper/giới thiệu gắn phạm vi; slide HTML ghi v1 và có bảng đối chiếu v1/v2 |

Lưu ý vận hành: cache NPZ cũ không có provenance cần tái tạo trong workspace mới.
Plan lịch sử chỉ có ngưỡng số vẫn đọc theo quy tắc cũ; các receipt/model/figure và số
liệu thực nghiệm đóng băng không bị viết lại. Chưa đo lại benchmark model thật.
Kết quả kiểm tra sau sửa nằm trong
[`validation/REPO_FIXES_2026-11-07.json`](validation/REPO_FIXES_2026-11-07.json).

Kiểm tra sau sửa: **203 test đạt, 1 test model được loại khỏi lượt không-model**;
Ruff 0 lỗi, 144 file Python đạt format, lockfile/dependency/compileall đạt. Wheel
build và smoke-import ngoài checkout đạt. Bộ slide HTML 17 trang qua kiểm tra
desktop/laptop/mobile và bản in; trang bìa và bảng phiên bản đã được xem trực tiếp.

## Biên bản rà soát ban đầu

Đối tượng kiểm tra: nhánh `bao`, commit `692f510`, gồm mã A/B/C và các vòng v3/v4
vừa nhận từ `thanh`. Các chỉnh sửa slide đang nằm ngoài commit được giữ nguyên.
Lượt này kiểm tra và ghi nhận vấn đề; chưa thay đổi thuật toán, cấu hình hay kết quả
thực nghiệm đã đóng băng.

## Kết luận

Repo chạy qua toàn bộ kiểm thử không cần model thật và các bước lint/format.
Tuy nhiên, cần sửa phạm vi CI, đóng gói v3/v4, xác minh artifact khi chạy lại và
xử lý điểm Gate hòa nhau trước khi coi bản tích hợp là sẵn sàng bàn giao.
Tài liệu tổng hợp cũng cần điều chỉnh cách diễn giải thống kê và phân biệt phiên bản.

## Kiểm tra đã thực hiện

| Kiểm tra | Kết quả |
|---|---|
| `uv lock --check --offline` | Đạt, dùng cache kiểm tra riêng trong workspace |
| `uv pip check` | Đạt, 58 gói tương thích |
| Ruff trên `src contracts scripts_a scripts_b scripts_c scripts_shared tests` | 0 lỗi |
| `ruff format --check` trên cùng phạm vi | 141 file đạt |
| `pytest tests -m 'not model' -q` | **162 passed, 1 deselected**, 67,92 giây |
| `compileall` trên mã nguồn và script | Đạt |
| Build wheel từ bản sao nguồn trong thư mục tạm | Build được nhưng **thiếu `pegh.v3` và `pegh.v4`** |
| Hash biên nhận đăng ký, báo cáo K1–K4 và kế hoạch online thăm dò v4 | Khớp hash tự kiểm tra |
| Protocol/gate hiện tại so với biên nhận đăng ký v4 | Khớp |
| Liên kết Markdown nội bộ | 5 đường dẫn không tồn tại, gồm 2 ở bản giới thiệu v1 và 3 ở bản trạng thái lưu trữ |

Số test theo nhóm: shared 35, A 31, B 52, C 13, v3 15, v4 16.
Đã kiểm tra nội dung facts: báo cáo online v4 ghi 97.400 request, báo cáo router
thăm dò ghi 126.620 request; cả hai ghi không có sai lệch ranking/route.
Đây là kiểm tra biên nhận hiện có, **không phải chạy lại các request thực nghiệm**.
Test cần model thật chưa chạy trong lượt này. Ma trận CI Linux/Python 3.11 và
Windows/Python 3.12 cũng chưa được chạy lại trên máy này.

## Các việc cần sửa

### 1. Ưu tiên cao — CI bỏ qua 31 test mới

- Vị trí: `pyproject.toml:49`, `.github/workflows/ci.yml:35`.
- `testpaths` chỉ chứa shared/A/B/C, trong khi workflow chạy pytest không chỉ định
  thư mục. Vì vậy 15 test v3 và 16 test v4 không được thu thập trong CI mặc định.
- Tác động: CI có thể xanh dù phần phát triển mới hỏng. Lượt chạy explicit `tests`
  của lần rà soát này mới bao phủ đủ 162 test không cần model.
- Cách sửa: đổi `testpaths` thành `["tests"]`, hoặc bổ sung v3/v4 và kiểm tra số test
  được thu thập. Giữ marker model để không tải model trong CI thường.

### 2. Ưu tiên cao — wheel không chứa các module mới

- Vị trí: `pyproject.toml:31`.
- Danh sách package thủ công dừng ở `pegh.profiling`, thiếu `pegh.v3`, `pegh.v4`.
- Bằng chứng: build wheel bằng setuptools từ bản sao nguồn thành công, nhưng danh
  sách bên trong wheel không có hai thư mục trên.
- Tác động: cài bản wheel sẽ không cung cấp các module cần cho experiment/demo v4;
  chạy từ checkout hoặc môi trường editable có thể che khuất lỗi này.
- Cách sửa: bổ sung package hoặc dùng package discovery; thêm smoke test đọc nội dung
  wheel/import từ bản cài độc lập, tránh lấy module từ checkout hiện tại.

### 3. Ưu tiên cao — chạy lại có thể tái sử dụng artifact chưa được xác minh

- Vị trí: `src/pegh/v4/build.py:49`, `src/pegh/v4/build.py:77`;
  v3 có cùng cách làm ở `src/pegh/v3/build.py:170` và `:211`.
- Build dense trả ngay khi manifest ghi `complete`. Quality cache trả ngay khi file
  ranking và sidecar tồn tại, không kiểm tra hash, query set, prefix hay model hiện tại
  trước khi bỏ qua bước tính.
- Bằng chứng thử trên fixture tạm: quality cache chấp nhận file không phải ranking với
  sidecar ghi checksum sai; build dense trả thành công với chỉ một manifest `complete`,
  không có `index.faiss`.
- Các loader ở bước sau có thể phát hiện một số dạng hỏng; vấn đề ở đây là bước resume
  không xác minh artifact đúng với đầu vào hiện tại. Không có bằng chứng từ thử nghiệm
  này rằng các kết quả đã công bố đang sai.
- Cách sửa: xác minh index và fingerprint đầu vào trước khi reuse; đối chiếu checksum
  ranking, corpus/query hashes, revision, prefix và feature schema. Với dữ liệu không
  khớp, báo lỗi rõ hoặc yêu cầu rebuild ở output mới. Áp dụng tương tự cho features/tiers
  đang bỏ qua chỉ vì file `.npz` đã có.

### 4. Ưu tiên vừa — quy tắc ngân sách offline và online khác nhau khi hòa điểm

- Vị trí: `src/pegh/v4/gate.py:133`, `src/pegh/v4/gate.py:145`,
  `src/pegh/v4/online.py:145`.
- `route_top` lấy đúng số lượng và phá hòa theo query ID; online dùng `score > threshold`.
- Bằng chứng: bốn điểm `[1, 1, 1, 1]`, không forced, ngân sách 50%: offline gọi Dense
  **2/4**, ngưỡng online bằng 1 nên gọi **0/4** trên chính tập hiệu chỉnh đó.
- Nếu ba trong bốn query bị buộc encode thì ngân sách 50% cũng không thể đáp ứng: cả
  hai quy tắc phải gọi ít nhất **3/4**. Đây là giới hạn của chính sách forced, cần công bố.
- Cách sửa: quy định rõ ngân sách là mục tiêu hay hạn mức cứng; xử lý tie nhất quán,
  xác thực budget trong `[0,1]`, ghi nhận mức tối thiểu do forced và thêm kiểm thử tie.
  Với luồng online, ngưỡng hiệu chỉnh cũng không bảo đảm tỷ lệ tương lai khi phân phối
  query thay đổi. Cần tránh tuyên bố tỷ lệ luôn bằng đúng ngân sách.

### 5. Ưu tiên cao trước khi viết báo cáo — CI chứa 0 chưa chứng minh tương đương

- Vị trí: `docs/KET_QUA_TONG_HOP_PE_GH.md:184`, cùng cách nói ở dòng 15 và 215.
- Câu “chất lượng ngang nhau, CI đều chứa 0” vượt quá kết luận của phép so sánh đang
  báo cáo. CI chứa 0 cho thấy chưa phát hiện chênh lệch có ý nghĩa trong phép so sánh,
  không tự chứng minh hai router tương đương hoặc không kém nhau trong một biên.
- Cách sửa: viết “chưa phát hiện chênh lệch chất lượng có ý nghĩa thống kê”; nếu muốn
  kết luận tương đương/không kém hơn, cần nêu biên và thực hiện phép kiểm định tương ứng.
- Giữ rõ phạm vi: kết quả online trên programmers/unix; trên sáu chủ đề mới ở 80%,
  BERT cao hơn v2 theo chính facts của dự án. Các kết luận K1–K4 có quy trình đăng ký
  và hiệu chỉnh Holm riêng, không gán quy trình đó cho so sánh router thăm dò.
- Không quy chênh lệch v2–v1 hoàn toàn cho Gate: báo cáo đã ghi encoder là thành phần
  đóng góp lớn. Cũng không xem số liệu online của hai phiên đo là cùng một lượt máy.

### 6. Ưu tiên vừa — thống nhất phiên bản trong paper, giới thiệu và slide

- `paper/03_method.md:5`, `paper/04_experimental_setup.md:5` và slide HTML hiện tại
  mô tả v1: MiniLM, Ridge, 21 đặc trưng, hai miền.
- `docs/KET_QUA_TONG_HOP_PE_GH.md` mô tả hệ cuối v2 ở vòng v4: arctic, logistic,
  28 đặc trưng, sáu miền học và sáu miền xác nhận. `docs/v4/README.md` là nguồn chi tiết.
- Slide hiện tại phù hợp mục tiêu trước đó là giới thiệu theo `_v1.md`; nó không tự động
  trở thành slide cho hệ thống cuối sau khi merge. Cần gắn nhãn phiên bản hoặc cập nhật
  một bản slide/paper chính thức riêng nếu trình bày kết quả mới.
- Nên có một trang hướng dẫn ngắn phân biệt tên hệ thống **PE-GH v1/v2** với tên vòng
  thực nghiệm **v3/v4**, chỉ rõ tài liệu nào là hiện hành và tài liệu nào là lịch sử.
- Sửa hai link cuối `GIOI_THIEU_DE_TAI_PE_GH_v1.md`: từ `../paper/...` thành
  `paper/...`. Ba link còn lại nằm trong
  `docs/person_a/validation/2026-10-22/IMPLEMENTATION_STATUS.md` cần tính lại theo
  vị trí thư mục lưu trữ.

## Các nâng cấp đáng làm sau khi sửa các vấn đề trên

1. **Đơn giản hóa nhánh rẻ:** thử BM25 thay P* proxy. Facts mới cho thấy proxy chỉ hơn
   BM25 khoảng 0,0003 trên sáu miền xác nhận; cần đo trực tiếp chất lượng và latency
   thay vì mặc định giữ thêm chi phí proxy.
2. **Đo HNSW đầu-cuối với encoder arctic:** so H* và Gate trong cùng harness/index;
   kiểm tra cả mean, p95, CPU và chất lượng. Không dùng riêng thời gian FAISS đo rời
   để suy ra mức tăng tốc đầu-cuối.
3. **Kiểm chứng ngoài CQADupStack và trên máy khác:** cả 12 subforum đã được sử dụng.
   Nếu chọn thuật toán mới từ kết quả hiện tại, cần dữ liệu chưa dùng cho lần xác nhận
   tiếp theo và đăng ký thiết kế trước khi xem kết quả. Lượt Linux hoặc máy thứ hai
   sẽ giúp kiểm tra khả năng tái lập thời gian xử lý.
4. **Cân nhắc ba tầng BM25 → R* → H*:** đây là hướng thăm dò sau; chỉ đáng tiếp tục nếu
   vượt R* hoặc H*+HNSW ở cùng chất lượng/ngân sách/thời gian. Không cần thêm mô hình
   phức tạp chỉ để tăng số phương pháp trong repo.

## Thứ tự đề xuất

Sửa CI và wheel → củng cố kiểm tra cache/resume và quy tắc ngân sách → chuẩn hóa
diễn giải thống kê/tài liệu phiên bản → smoke clean install và demo → chọn tối đa
một hướng thực nghiệm bổ sung có đối chứng phù hợp. Giữ nguyên các kết quả đã đóng băng;
mọi thay đổi ảnh hưởng thuật toán cần phiên bản và output mới.
