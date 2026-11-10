# Báo cáo PE-GH theo template thesis UET

Mở **`thesis.tex`** và chọn compiler **XeLaTeX**. Đây là file chính, dùng nội dung sáu chương PE-GH đã viết trong `chapters/`. `main.tex` dẫn đến cùng file này để giữ tương thích với cách mở báo cáo trước đó.

Bản PDF sau khi rà soát nội dung có **40 trang tổng cộng**, gồm cả bìa, phần đầu và **2 trang tài liệu tham khảo**.

## Những phần được điều chỉnh

Báo cáo kế thừa bìa khung đôi, logo UET, lề trái 3 cm, phải 2 cm, trên 2,5 cm, dưới 3 cm, cỡ chữ nội dung 13 và cách gọi chương của template. Bìa được chuyển thành báo cáo đề tài cho ba thành viên. Phần đầu gồm tóm tắt tiếng Việt và tiếng Anh, mục lục, thuật ngữ và danh mục bảng/hình. Giãn dòng được điều chỉnh cho dung lượng khoảng 40 trang của báo cáo.

Thông tin tên đề tài, thành viên và MSSV nằm trong `metadata.tex`. Hình thức trình bày dùng chung nằm trong `preamble.tex`; bìa nằm trong `cover.tex`. Tên sinh viên, cán bộ hướng dẫn và nội dung mẫu của khóa luận không được đưa vào bản PDF báo cáo.

## Các chương đang được biên dịch

1. `chapters/01_gioi_thieu.tex`
2. `chapters/02_co_so_va_nghien_cuu_lien_quan.tex`
3. `chapters/03_phuong_phap_pegh.tex`
4. `chapters/04_thiet_ke_thuc_nghiem.tex`
5. `chapters/05_ket_qua_va_thao_luan.tex`
6. `chapters/06_ket_luan.tex`

Các chương mẫu khác đi kèm template vẫn được giữ để tra cứu nhưng không thuộc luồng biên dịch. Bản gốc của `thesis.tex`, `cover.tex` và README của template được lưu trong `template_reference/`.

## Biên dịch trên Windows

Từ thư mục repo:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File report\build.ps1
```

Script mặc định biên dịch `thesis.tex`, chạy BibTeX và cập nhật tham chiếu. Kết quả là `report/PE_GH_REPORT.pdf`; các file trung gian nằm trong `report/build/`. Có thể kiểm tra đầu vào tương thích bằng tùy chọn `-EntryPoint main`.

Nếu dùng Overleaf, tải thư mục `report`, chọn `thesis.tex` làm Main document và XeLaTeX làm Compiler. Font ưu tiên là Times New Roman; hệ thống không có font này dùng Latin Modern Roman. Với MiKTeX tối thiểu chưa có đủ phụ thuộc `hyperref`, báo cáo vẫn có trích dẫn và URL dạng văn bản.

## Nguồn và biên tập nội dung

`references.bib` chứa **30 bài đã xuất bản**, gồm **22 bài hội nghị và 8 bài tạp chí**, đều được trích dẫn trong nội dung. Danh mục dùng style IEEEtran: tác giả viết tắt tên, hội nghị dùng tên rút gọn như `Proc. ACM SIGIR`, tạp chí dùng tên như `ACM Trans. Inf. Syst.`. Mỗi bài có DOI hoặc liên kết đến bản ghi xuất bản; không dùng model card hay tài liệu nội bộ làm mục tham khảo học thuật.

`evidence/literature_sources.csv` và `evidence/literature_sources.json` ghi tên đầy đủ của hội nghị/tạp chí, DOI, nguồn metadata và vai trò của từng bài. Các trường hợp khác năm online/năm số tạp chí được ghi rõ trong sổ nguồn. Bài BM25 dùng thông tin trên PDF gốc để xử lý metadata đăng ký đã bị sai lệch.

`evidence/` vẫn lưu các facts đóng băng và sổ nguồn số liệu thực nghiệm; `tables/` và `figures/` chứa bảng/hình của nhóm. Nguồn số liệu của nhóm được ghi tại bảng/hình, tách với 30 công bố bên ngoài. Đây không phải lượt chạy model mới khi cập nhật tài liệu tham khảo.

File `IEEEtran.bst` được giữ nguyên từ CTAN theo giấy phép LPPL ghi trong đầu file, giúp biên dịch cùng kiểu tham khảo trên MiKTeX và Overleaf.

Để sinh lại bảng và hình từ facts trong repo, dùng `build.ps1 -PrepareEvidence`; tùy chọn này cần môi trường `.venv` có NumPy và Matplotlib. Nếu facts thay đổi, cần kiểm lại cả số liệu trong văn xuôi.

Giữ yêu cầu đã chốt: tập trung vào vấn đề, giả thiết, lý do lựa chọn phương pháp và bằng chứng; giới thiệu ngắn kiến thức phổ biến; không trình bày chi tiết triển khai kỹ thuật. Nội dung chính đã lược bỏ thông số đặc trưng, trọng số kết hợp, thư viện, công thức chia dữ liệu và tham số chạy. Các điều kiện đánh giá, số liệu kết quả và giới hạn nghiên cứu được giữ để người đọc hiểu đúng mức độ giải quyết của đề tài. Câu và đoạn phải đủ ngữ cảnh, dùng thuật ngữ nhất quán, không chèn giải thích bằng dấu gạch ngang.

Đây vẫn là bản thảo. Phân tích từng truy vấn v2 với route, ranking và qrels cần bổ sung khi có đủ artifact. Nhóm cần đọc chéo nội dung trước khi nộp. Công việc chuyển template chưa commit hay push thư mục báo cáo.
