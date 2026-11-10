# PE-GH — slide HTML theo mẫu UET/VNU

Mở **PE_GH_SLIDES.html** trong Edge, Chrome hoặc Firefox để trình chiếu. File chứa
toàn bộ CSS, JavaScript, logo, hình minh họa và sơ đồ, chạy offline, không cần cài
thư viện hay tải font.

Bộ slide gồm **17 trang**, tỷ lệ **16:9**, dùng
`GIOI_THIEU_DE_TAI_PE_GH_v1.md` làm nguồn đối chiếu chính cho phần giới thiệu.
`GIOI_THIEU_DE_TAI_PE_GH.md`, protocol, paper và receipt của dự án cung cấp các
chi tiết triển khai, ngưỡng định lượng và số liệu thực nghiệm bổ sung.
Trang bìa ghi **PE-GH v1**. Slide 7 đối chiếu v1 với hệ **PE-GH v2 (vòng v4)**;
các trang phương pháp và kết quả phía sau giữ phạm vi v1. Hướng dẫn toàn repo nằm ở
[`docs/VERSIONS.md`](../../docs/VERSIONS.md). Số liệu cũ không được gán cho model v2.
Mạch trình bày: bài toán → giả thuyết → đề xuất và đóng góp → phạm vi, tiêu chí →
phương pháp → thiết kế thực nghiệm → chất lượng và hiệu quả xử lý → phạm vi và tổng kết.

## Đối chiếu nội dung với bản v1

| Mục trong v1 | Slide bao quát |
|---|---|
| 1. Bài toán, đầu vào/đầu ra, CPU và phạm vi truy xuất câu hỏi | 3–6 |
| 2. CQADupStack, hai miền, tiêu đề/mô tả và số lượng dữ liệu | 8 |
| 3. BM25, Dense, Hybrid và chi phí xử lý | 4, 10 |
| 4. Gate, đặc trưng, hai nhánh, Ridge học lợi ích từ train | 5–6, 10–11 |
| 5. Mục tiêu, thành phần có sẵn, đóng góp và phạm vi áp dụng | 7, 9, 15–16 |
| 6. Bốn phương pháp, chất lượng/độ trễ/chi phí và Gate đối chứng | 12–14 |

**Phần bổ sung ngoài v1:** top-100, 21 đặc trưng, H*/S*, các ngưỡng đăng ký,
kết quả OOF, đo latency và phân tích lỗi. Những chi tiết này có nguồn ở paper,
protocol và receipt; không coi chúng là các kết quả đã được viết trong v1.
Mục thời gian CPU thực tế ở slide 12 là tiêu chí trong thiết kế đánh giá; các số đo
runtime đang trình bày ở slide 14 chỉ gồm H*, S* và PE-GH trong cùng lượt máy.

Các tiêu đề cuối dùng tên chủ đề: **Thiết kế thực nghiệm**, **Chất lượng truy xuất**,
**Hiệu quả xử lý trên CPU**, **Phạm vi và hạn chế**, **Tổng kết đề tài**.

## Mẫu thiết kế

Thiết kế được dựng lại bằng HTML/CSS từ **hai ảnh mẫu người dùng cung cấp**:

- Trang bìa: logo UET bên trái, VNU bên phải, thanh xanh dương–xanh lá phía dưới.
- Trang nội dung: nền trắng, tiêu đề xanh dương, đường kẻ xanh, số trang góc phải dưới.
- Font Arial/Segoe UI hỗ trợ tiếng Việt. Bảng và sơ đồ vẫn là nội dung HTML có thể sửa.
- Vùng nội dung nằm từ y=150 đến y=624 trên khung 1280×720. Các trang ít nội dung
  được căn giữa theo chiều dọc, tăng cỡ chữ và giãn bố cục phù hợp; trang kết luận
  dàn thông điệp và số liệu trên toàn vùng nội dung.
- Không tái tạo viền tím của trình biên tập trong ảnh mẫu.
- Không hiển thị các dòng giải thích phụ bằng chữ nhỏ. Ý cần thiết về dữ liệu,
  chất lượng và điều kiện đo nằm trong nội dung chính; chú thích lặp được bỏ.
- Trang bìa chỉ có nhận diện UET/VNU, tên đề tài và bảng thành viên Họ và tên/MSSV.

Hình minh họa truy xuất ở slide 3 dùng built-in imagegen. Slide 4 có sơ đồ
BM25/Dense/Hybrid; slide 10 thể hiện Gate trước encoder và hai nhánh xử lý; slide 11
phân biệt học offline với quyết định online. Ba sơ đồ là SVG có thể sửa trong mã
nguồn. [Tệp hình và prompt](assets/IMAGE_PROMPT.md).

Đây là bản dựng theo hình ảnh tham chiếu, không phải file Canva hoặc PowerPoint được
import nguyên master. Cụm UET lấy từ tài liệu chính thức của khoa, có thêm chữ nhỏ
“Since 2004” so với ảnh mẫu. Nguồn logo và cách trích xuất được ghi trong
[`assets/SOURCES.md`](assets/SOURCES.md). Link Canva ban đầu từng trả HTTP 403;
hai ảnh người dùng gửi là căn cứ thiết kế của bản hiện tại.

## Điều khiển

| Phím / nút | Chức năng |
|---|---|
| ← / → / Space | Chuyển trang |
| Home / End | Trang đầu / cuối |
| F | Toàn màn hình; có thể dùng F11 nếu trình duyệt chặn |
| O | Tổng quan 17 slide |
| N | Ghi chú và nguồn của trang hiện tại |
| Esc | Đóng ghi chú hoặc cửa sổ đang mở |
| PDF | In hoặc lưu toàn bộ slide thành PDF |

Trên điện thoại có thể vuốt ngang. Khi in PDF, bỏ header/footer của trình duyệt và
bật background graphics nếu cần. Controls và notes không xuất hiện trong bản in.
Liên kết tài liệu nội bộ hoạt động khi giữ file ở `slides/pegh/` trong repo. Nếu gửi
riêng HTML, phần trình chiếu vẫn hoạt động đầy đủ; cần repo để đọc nguồn nội bộ.

## Sửa và build

- `index.html`: nội dung, ghi chú và nguồn từng trang.
- `styles.css`: hai bố cục chuẩn, font, màu và thành phần nội dung.
- `deck.js`: chuyển trang, notes, overview, touch và kiểm layout.
- `assets/`: logo gốc, hình minh họa, sơ đồ và thông tin nguồn.
- `build.mjs`: nhúng CSS/JS và mọi hình vào `PE_GH_SLIDES.html`.

Chạy từ thư mục repo sau khi sửa:

```powershell
node slides/pegh/build.mjs
```

## Số liệu và phạm vi kết luận

Chỉ dùng lượt runtime **30/10/2026**, Ryzen 7 8745H, Windows 11, bốn logical CPU,
năm repetitions. Không trộn với số i3/i7 cũ. Mean latency giảm **33,80% so H*** cho
tập gộp; riêng Programmers **19,73%** và p95 hơi cao hơn H*/S*.
Quality là noninferiority trong biên −0,01, không khẳng định bằng hệt hoặc vượt S*.
Bảng chất lượng trình bày đủ BM25, Dense, Hybrid H*/S* và PE-GH, lấy từ
`paper/figures/final-a/quality-final.csv`; H*/S* được gộp vì trùng bảng xếp hạng.
Các gate đối chứng chưa có full online cùng lượt. Qrels xác định câu hỏi trùng lặp.
Câu tiếng Anh trên **slide 3** chỉ minh họa bài toán, không phải kết quả benchmark.

## Kiểm tra

`?qa=1` kiểm tra bounds cả 17 trang, vùng nội dung và khoảng trống trên/dưới,
tiêu đề một dòng, hình tải thành công, giới hạn
chuyển trang, phím mũi tên/Home, nút next, notes, overview và ID trùng. Kết quả nằm
trong `window.__SLIDE_QA__` và phần tử `#qa-report` ẩn. Dùng `?slide=14` để chọn
trang mở đầu; bản in luôn chứa toàn bộ deck.

Kết quả kiểm tra cuối cùng và hash HTML nằm trong `validation.json`.
