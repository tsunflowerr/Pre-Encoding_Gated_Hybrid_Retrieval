# Giới thiệu đề tài PE-GH

## 1. Giới thiệu bài toán

Trong quá trình học và làm việc với lập trình, phần mềm hay hệ điều hành, nhiều người gặp những vấn đề đã từng được hỏi trước đó. Tuy nhiên, cùng một vấn đề có thể được diễn đạt theo nhiều cách khác nhau, nên việc tìm lại câu hỏi phù hợp không phải lúc nào cũng dễ.

Từ nhu cầu đó, nhóm em nghiên cứu một hệ thống **tìm kiếm các câu hỏi tương tự về lập trình, phát triển phần mềm và Unix/Linux**.

Người dùng nhập một câu hỏi bằng tiếng Anh. Hệ thống tìm trong kho dữ liệu đã có và trả về danh sách các bài viết liên quan, sắp xếp theo mức độ phù hợp để người dùng tham khảo. Hệ thống tập trung vào việc tìm và xếp hạng câu hỏi, không tự tạo câu trả lời như chatbot.

Bài toán nhóm quan tâm là làm thế nào để tìm được những câu hỏi phù hợp, kể cả khi cách diễn đạt khác nhau, đồng thời giữ thời gian phản hồi và chi phí xử lý ở mức hợp lý trên CPU.

## 2. Dữ liệu sử dụng

Nhóm em sử dụng hai tập dữ liệu thuộc bộ **CQADupStack**, gồm các câu hỏi từ cộng đồng Stack Exchange:

- **Programmers:** 32.176 bài viết về lập trình, thiết kế và phát triển phần mềm.
- **Unix:** 47.382 bài viết về Unix/Linux và các vấn đề kỹ thuật liên quan.

Tổng cộng có **79.558 bài viết** làm dữ liệu tìm kiếm. Hệ thống sử dụng tiêu đề và phần mô tả câu hỏi để tìm nội dung tương đồng.

Bên cạnh kho bài viết, dữ liệu còn có **1.948 câu hỏi đầu vào dùng cho thực nghiệm**, kèm nhãn cho biết những bài viết nào liên quan đến từng câu hỏi. Nhờ đó, nhóm có thể đánh giá kết quả tìm kiếm dựa trên dữ liệu đã được gán nhãn. Hai miền Programmers và Unix được đánh giá riêng để xem giải pháp hoạt động như thế nào ở từng lĩnh vực.

## 3. Các phương pháp hiện có và hạn chế

Trong phạm vi đề tài, nhóm tập trung vào ba cách tiếp cận: BM25, Dense Retrieval và Hybrid Retrieval.

### BM25 – tìm kiếm dựa trên từ khóa

BM25 đánh giá mức độ phù hợp thông qua các từ xuất hiện trong câu hỏi và bài viết, có xét đến độ hiếm của từ và độ dài nội dung. Phương pháp này xử lý nhanh, ít tốn tài nguyên và hữu ích khi câu hỏi chứa những thuật ngữ kỹ thuật rõ ràng.

Hạn chế là BM25 phụ thuộc nhiều vào mức độ trùng từ. Hai câu hỏi cùng nói về một vấn đề nhưng dùng cách diễn đạt khác nhau có thể chưa được xếp gần nhau trong kết quả.

### Dense Retrieval – tìm kiếm dựa trên ngữ nghĩa

Trong hệ thống của nhóm, MiniLM được dùng để chuyển nội dung thành vector, sau đó FAISS tìm những bài viết có vector gần với câu hỏi đầu vào. Cách này có thể bổ sung những kết quả tương đồng về ý nghĩa dù không dùng cùng từ khóa.

Vector của các bài viết được tính trước và lưu lại. Tuy nhiên, mỗi câu hỏi mới vẫn cần chạy qua MiniLM để tạo vector, rồi thực hiện tìm kiếm. Các bước này làm phát sinh thêm chi phí xử lý, đặc biệt khi hệ thống chạy trên CPU.

### Hybrid Retrieval – kết hợp từ khóa và ngữ nghĩa

Hybrid kết hợp kết quả của BM25 và Dense Retrieval để tận dụng thông tin từ cả hai phương pháp.

Tuy nhiên, nếu luôn chạy cả hai cho mọi câu hỏi, hệ thống vẫn phải trả toàn bộ chi phí tìm kiếm ngữ nghĩa, kể cả trong những trường hợp BM25 đã cho kết quả tốt. Đây là hạn chế mà nhóm em tập trung nghiên cứu.

## 4. Hướng giải quyết của nhóm: PE-GH

Từ hạn chế trên, nhóm đặt ra câu hỏi:

> Với một câu hỏi cụ thể, việc chạy thêm tìm kiếm ngữ nghĩa có mang lại đủ lợi ích để đáng với chi phí xử lý hay không?

Nhóm nghiên cứu hướng **PE-GH — Pre-Encoding Gated Hybrid Retrieval**, tức tìm kiếm kết hợp có bộ quyết định đặt trước bước mã hóa câu hỏi.

Bộ quyết định này được gọi là **Gate**. Gate sử dụng những thông tin có thể lấy từ câu hỏi và kết quả BM25, chẳng hạn độ dài câu hỏi, mức độ khớp từ khóa, độ hiếm của từ và chênh lệch điểm giữa các kết quả đứng đầu.

Quy trình hoạt động gồm:

1. Người dùng nhập câu hỏi, hệ thống chạy BM25 để lấy danh sách kết quả ban đầu.
2. Gate phân tích các đặc trưng của câu hỏi và danh sách BM25.
3. Nếu lợi ích dự đoán của việc chạy thêm ngữ nghĩa thấp, hệ thống trả kết quả BM25.
4. Nếu lợi ích dự đoán vượt ngưỡng lựa chọn, hệ thống chạy MiniLM và FAISS, rồi kết hợp với kết quả BM25 đã có.

Trong thiết kế này, nhóm sử dụng **Ridge**, một mô hình hồi quy nhẹ, để học cách dự đoán mức cải thiện chất lượng khi chuyển từ BM25 sang Hybrid. Dữ liệu học được tạo bằng cách so sánh chất lượng của hai phương pháp trên các câu hỏi thuộc tập huấn luyện.

Như vậy, Gate đưa ra một dự đoán về lợi ích của việc chạy thêm ngữ nghĩa. Độ chính xác của dự đoán và chi phí của chính Gate đều cần được kiểm tra qua thực nghiệm.

## 5. Mục tiêu và mức độ giải quyết của nhóm

Mục tiêu của nhóm là **giảm những lần chạy mô hình ngữ nghĩa ít mang lại lợi ích**, qua đó giảm chi phí xử lý và thời gian phản hồi, trong khi chất lượng tìm kiếm vẫn được giữ trong mức suy giảm cho phép.

Nhóm tập trung vào cách lựa chọn phương pháp xử lý cho từng câu hỏi. BM25, MiniLM và FAISS là các thành phần có sẵn; phần nhóm nghiên cứu thêm là Gate và cách đánh giá hiệu quả của quyết định dùng hay bỏ qua nhánh ngữ nghĩa.

Phạm vi đánh giá ban đầu là câu hỏi tiếng Anh trong hai miền Programmers và Unix, với kho dữ liệu cố định và môi trường chạy trên CPU. Kết quả sẽ cho biết giải pháp có hiệu quả đến đâu trong điều kiện này; việc mở rộng sang tiếng Việt hoặc lĩnh vực khác cần có thêm thực nghiệm.

## 6. Cách nhóm đánh giá đề tài

Nhóm so sánh **BM25, Dense Retrieval, Hybrid luôn chạy và PE-GH** trên cùng dữ liệu và điều kiện phần cứng, theo ba tiêu chí:

- **Chất lượng tìm kiếm:** Các bài viết liên quan có được tìm thấy và đưa lên những vị trí đầu hay không. Chỉ số chính là nDCG@10, đánh giá thứ tự của 10 kết quả đầu tiên.
- **Thời gian phản hồi:** Hệ thống mất bao lâu để trả kết quả, xét cả thời gian trung bình và những truy vấn xử lý chậm.
- **Chi phí tính toán:** Tỷ lệ câu hỏi cần chạy MiniLM và thời gian CPU thực tế.

Nhóm cũng đối chiếu Gate với những cách quyết định đơn giản hơn, như dựa vào chênh lệch điểm BM25, để kiểm tra xem việc dùng mô hình học có mang lại thêm lợi ích hay không.

Điều nhóm muốn kiểm chứng là: **PE-GH có thể giảm số lần chạy tìm kiếm ngữ nghĩa và thời gian xử lý, trong khi chất lượng kết quả không giảm đáng kể so với việc luôn chạy Hybrid hay không?**

## Tài liệu đối chiếu trong dự án

- [Phương pháp PE-GH](../paper/03_method.md)
- [Thiết lập thực nghiệm](../paper/04_experimental_setup.md)
