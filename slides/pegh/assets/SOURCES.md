# Logo và mẫu tham chiếu

Mẫu bố cục: hai ảnh trang bìa/trang nội dung do người dùng đính kèm ngày 30/10/2026.
Các logo dùng tài nguyên gốc, giữ nguyên biểu tượng và cụm chữ.

## UET — `uet-lockup.png`

- Nguồn: [2022 Introduction to CS Department, Khoa CNTT, UET](https://www.fit.uet.vnu.edu.vn/wp-content/uploads/2022/10/2022_Introduction-to-CS-Department.pdf).
- Trang 1, vùng PDF `(12, 8, 274, 75)` pt, render ở tỷ lệ 4× bằng PyMuPDF.
- Giữ nguyên logo và cụm chữ gốc, có dòng nhỏ “Since 2004”.
- Kích thước: 1048 × 268 px; nền trắng; không kéo méo khi hiển thị.

## VNU — `vnu-logo.png`

- Nguồn: [Trang logo chính thức của ĐHQGHN](https://vnu.edu.vn/gioi-thieu/logo-dhqghn).
- [Tệp PNG do trang chính thức liên kết](https://cdnportal.vnu.edu.vn/data/0/images/2025/09/09/upload_2/logo-vnu.png?dpi=150&quality=100&w=1920).
- Giữ nguyên PNG, kể cả khoảng trống của tệp gốc; 1920 × 768 px.
- Có “Since 1906”, Huân chương Sao vàng, tên tiếng Việt và tiếng Anh.

`build.mjs` nhúng các tài nguyên vào HTML độc lập bằng data URL. Không cần kết nối
mạng để xem logo khi trình chiếu hoặc in.

## Hình minh họa và sơ đồ chủ đề

- `technical-retrieval.png`: minh họa câu hỏi kỹ thuật và kho bài viết, tạo bằng
  built-in imagegen. [Prompt, chế độ và tệp lưu](IMAGE_PROMPT.md).
- `retrieval-methods.svg`: sơ đồ BM25/Dense/Hybrid; các từ tiếng Anh chỉ minh họa,
  không mô phỏng một kết quả benchmark.
- `pegh-architecture.svg`: luồng online BM25, Gate, MiniLM, FAISS và fusion,
  dựa trên `paper/03_method.md`.
- `gate-learning.svg`: phân biệt học Ridge offline và quyết định online,
  dựa trên `paper/03_method.md` và `configs/gating/protocol_v1.yaml`.

Các sơ đồ SVG giữ chữ và cấu trúc trong mã nguồn; không dùng hình tạo sinh để biểu
diễn số liệu hoặc khẳng định thực nghiệm.
