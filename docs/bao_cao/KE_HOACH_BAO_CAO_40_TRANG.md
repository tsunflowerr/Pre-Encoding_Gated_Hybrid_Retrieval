# Kế hoạch viết báo cáo PE-GH khoảng 40 trang tổng cộng

Ngày lập: **09/11/2026**. Trạng thái: đề cương và kế hoạch viết, chưa phải bản báo cáo hoàn chỉnh.

**Yêu cầu đã chốt:** khoảng 40 trang **tính cả bìa, mục lục và tài liệu tham khảo**. Kế hoạch này dùng tiếng Việt, lấy hệ thống cuối **PE-GH v2, vòng thực nghiệm v4** làm trọng tâm. V1 và vòng v3 dùng để giải thích quá trình cải tiến và làm đối chứng.

**Định hướng biên soạn đã bổ sung:** báo cáo tập trung vào vấn đề nghiên cứu, cơ sở lựa chọn phương pháp và mức độ giải quyết được chứng minh bằng thực nghiệm. Kiến thức nền phổ biến được giới thiệu ngắn gọn. Thiết kế kỹ thuật chỉ xuất hiện khi cần để hiểu phương pháp hoặc đánh giá tính công bằng của kết quả. Câu văn không dùng dấu gạch ngang để chèn lời giải thích; các đoạn phải có đủ ngữ cảnh và liên kết nhất quán.

## 1. Định hướng của báo cáo

### 1.1. Tên đề tài dự kiến

**PE-GH: Truy xuất lai có chọn lọc trước bước mã hóa truy vấn.**

Phụ đề có thể dùng: *Ứng dụng trong tìm kiếm câu hỏi trên CQADupStack*.

Tên tiếng Anh: *Pre-Encoding Gated Hybrid Retrieval*.

Bối cảnh ban đầu là câu hỏi kỹ thuật trên Programmers/Unix; phạm vi cuối mở rộng đến 12 chủ đề, gồm cả English/Gaming. Cần nói rõ sự mở rộng này thay vì mô tả toàn bộ dữ liệu cuối đều là câu hỏi kỹ thuật.

Không cần đưa “v2” vào tên chính. Trong phần phạm vi phải nói rõ báo cáo mô tả hệ thống cuối v2; v3/v4 là tên các vòng thực nghiệm, không phải hai phiên bản hệ thống mới.

### 1.2. Mạch trình bày

Báo cáo đi theo thứ tự:

1. **Vấn đề:** tìm kiếm theo từ khóa có thể bỏ sót câu hỏi cùng nghĩa; chạy tìm kiếm ngữ nghĩa cho mọi truy vấn phát sinh chi phí.
2. **Giả thiết nghiên cứu:** thông tin rẻ từ truy vấn và kết quả BM25 có thể giúp chọn truy vấn cần nhánh Dense.
3. **Mục tiêu:** tìm quan hệ đánh đổi giữa chất lượng và chi phí, kiểm tra gate có ích hơn quy tắc đơn giản ở cùng ngân sách hay không.
4. **Phương pháp:** BM25 trước, gate quyết định trước query encoder, sau đó đi nhánh rẻ P* hoặc nhánh Hybrid H*.
5. **Bằng chứng:** kết quả chất lượng trên sáu miền xác nhận, chi phí online đo thật trên hai miền, đối chứng và khoảng tin cậy.
6. **Giới hạn:** mức cải thiện của gate nhỏ, không cải thiện rõ p95, kết quả phụ thuộc miền, encoder và điều kiện đo.

Mỗi mục phương pháp bắt đầu bằng vấn đề cần giải quyết và lý do lựa chọn cách tiếp cận, sau đó mới trình bày nguyên lý cần thiết để hiểu quyết định của hệ thống. Phần thực nghiệm bắt đầu bằng câu hỏi cần kiểm chứng, rồi đưa bằng chứng và diễn giải mức độ trả lời được câu hỏi đó.

### 1.3. Phạm vi và cách nêu đóng góp

- Bài toán là **truy xuất/xếp hạng câu hỏi liên quan hoặc trùng lặp**, không phải xây hệ thống sinh câu trả lời bằng LLM.
- Dữ liệu là CQADupStack. Sáu miền dùng phát triển/huấn luyện và sáu miền dùng xác nhận phải được nêu riêng.
- Hệ thống cuối dùng logistic, 28 đặc trưng trước Dense, encoder arctic có query prefix, nhánh P*/H* và ngân sách encode.
- Nhấn mạnh thiết kế gate nhẹ và quy trình đánh giá: cùng ngân sách, đối chứng đơn giản, đăng ký trước, đo online và đối chiếu từng request.
- Ý tưởng định tuyến sparse/dense đã có trong nghiên cứu trước. Đóng góp của nhóm cần được trình bày trong phạm vi phương pháp và bằng chứng thực nghiệm của đề tài, không gọi là ý tưởng định tuyến đầu tiên.
- Mức cải thiện toàn hệ thống v2 so với v1 không được quy hết cho gate, vì encoder và các nhánh truy xuất cũng thay đổi.

### 1.4. Mức độ trình bày kiến thức nền và kỹ thuật

Chỉ giữ một nội dung khi nội dung đó giúp người đọc hiểu vấn đề nghiên cứu, lý do lựa chọn phương pháp hoặc ý nghĩa của kết quả. Dung lượng tiết kiệm được dùng để phân tích các lựa chọn và bằng chứng của đề tài.

| Nhóm nội dung | Mức trình bày trong báo cáo |
|---|---|
| Kiến thức nền phổ biến | BM25, vector biểu diễn văn bản, cosine và hồi quy logistic chỉ được giới thiệu theo vai trò trong bài toán. Dẫn nguồn cho định nghĩa chuẩn; không diễn giải lại giáo trình hoặc chứng minh công thức. |
| Nội dung trực tiếp tạo nên phương pháp | Giải thích rõ vì sao quyết định được đặt trước encoder, gate quan sát được thông tin gì, nhãn học phản ánh điều gì và ngân sách thay đổi cách sử dụng Dense ra sao. |
| Điều kiện để hiểu và đánh giá kết quả | Giữ cách chia dữ liệu, đối chứng, thước đo, biên chất lượng, nguyên tắc kiểm định và điều kiện đo chi phí. Giải thích ý nghĩa và ảnh hưởng của các lựa chọn này. |
| Chi tiết thiết kế phần mềm | Cấu trúc module, API, schema, mapping ID, định dạng cache, checksum, cơ chế resume, đóng gói wheel và lệnh chạy để trong repo phục vụ tra cứu. Không dành mục riêng trong thân báo cáo. |
| Chi tiết thiết lập mô hình và hệ thống | Chỉ nêu những lựa chọn có ảnh hưởng đến kết luận, như encoder, thông tin dùng cho gate, nhánh truy xuất, CPU và cách đo. Thông số đầy đủ được lưu trong cấu hình bổ trợ. |

Các đường dẫn mã nguồn, trường JSON, lịch viết và phân công trong file này phục vụ người biên soạn. Chúng không mặc nhiên trở thành nội dung cần đưa vào báo cáo.

### 1.5. Quy tắc viết câu, đoạn và liên kết nội dung

1. Mỗi câu có chủ thể và quan hệ ngữ nghĩa rõ. Khi nêu kết quả, phải xác định được phương pháp, phạm vi dữ liệu, điều kiện so sánh và đại lượng đang nói đến từ câu đó hoặc các câu liền trước.
2. Không dùng dấu gạch ngang để chèn định nghĩa, lời giải thích hoặc ý bổ sung trong câu. Viết thành mệnh đề đầy đủ hoặc một câu tiếp theo có quan hệ rõ với câu trước.
3. Thuật ngữ được giới thiệu ngắn gọn ở lần xuất hiện đầu tiên và dùng thống nhất về sau. Chẳng hạn, có thể gọi gate là “bộ quyết định”, sau đó thống nhất một cách gọi thay vì luân phiên nhiều từ cho cùng khái niệm.
4. Mỗi đoạn phát triển một ý chính. Câu đầu xác định nội dung đoạn; các câu tiếp theo giải thích lý do hoặc bằng chứng; câu cuối làm rõ ý nghĩa hoặc dẫn sang vấn đề tiếp theo khi cần.
5. Những từ như “điều này”, “phương pháp này”, “kết quả trên” chỉ được dùng khi đối tượng được nhắc đến có thể xác định rõ. Nếu có nhiều đối tượng gần nhau, cần gọi tên đối tượng.
6. Các đoạn liên kết bằng quan hệ cụ thể như nguyên nhân, hệ quả, điều kiện, giới hạn hoặc nhu cầu kiểm chứng. Không dùng câu chuyển chung chung nếu chưa cho thấy quan hệ giữa hai nội dung.
7. Định nghĩa và mục tiêu ở phần đầu được giữ nguyên khi mô tả phương pháp, chọn phép so sánh, diễn giải kết quả và viết kết luận. Mỗi kết luận phải trả lời một câu hỏi đã đặt ra và chỉ dựa trên bằng chứng đã trình bày.
8. Thân báo cáo ưu tiên văn xuôi có lập luận. Bảng dùng để so sánh và tổng hợp; danh sách chỉ dùng cho những mục thực sự song song. Không ghép các ghi chú ngắn thành đoạn văn thiếu quan hệ ngữ nghĩa.

Ví dụ về câu có đủ ngữ cảnh: “Trên sáu miền xác nhận của CQADupStack, PE-GH v2 đạt nDCG@10 trung bình macro bằng 0,4159 khi sử dụng ngân sách vận hành 80%, thấp hơn 0,0064 so với phương pháp luôn chạy Hybrid. Mức suy giảm này nằm trong biên 0,01 đã đăng ký, nên kết quả hỗ trợ mục tiêu giảm lượt mã hóa truy vấn trong giới hạn chất lượng cho phép.” Các câu sau có thể phân tích ý nghĩa của kết quả mà không nhắc lại toàn bộ điều kiện nếu ngữ cảnh vẫn rõ.

## 2. Phân bổ 40 trang

Số trang dưới đây là vị trí trang trong **toàn bộ file PDF**, kể cả khi phần đầu sử dụng số La Mã. Hạn mức đã tính cả công thức, bảng và hình.

| Phần | Trang dự kiến | Số trang | Nội dung trọng tâm |
|---|---|---:|---|
| Bìa và phần đầu | 1–4 | 4 | Bìa, tóm tắt, mục lục, danh mục bảng/hình và chữ viết tắt |
| Chương 1. Giới thiệu đề tài | 5–8 | 4 | Bối cảnh, vấn đề, giả thiết, mục tiêu và phạm vi đóng góp |
| Chương 2. Cơ sở lý thuyết và nghiên cứu liên quan | 9–13 | 5 | Khái niệm cần thiết, các hướng giải quyết gần và cơ sở lựa chọn hướng nghiên cứu |
| Chương 3. Phương pháp PE-GH | 14–19 | 6 | Nguyên lý lựa chọn truy vấn, thông tin và nhãn học của gate, vai trò ngân sách |
| Chương 4. Thiết kế thực nghiệm | 20–24 | 5 | Dữ liệu, đối chứng, thước đo và điều kiện để kết quả có thể được đánh giá |
| Chương 5. Kết quả và thảo luận | 25–36 | 12 | Trả lời câu hỏi nghiên cứu, giải thích kết quả, đối chiếu và phân tích giới hạn |
| Chương 6. Kết luận và hướng phát triển | 37–38 | 2 | Trả lời câu hỏi nghiên cứu, đóng góp được chứng minh và hướng tiếp theo |
| Tài liệu tham khảo | 39–40 | 2 | Những nguồn thực sự được trích dẫn trong báo cáo |
| **Tổng** | **1–40** | **40** | **Đã tính bìa và mục lục** |

Phần đầu dự kiến: một trang bìa, một trang tóm tắt, một trang mục lục đến cấp 1.1, một trang danh mục bảng/hình và chữ viết tắt. Nếu mẫu của trường yêu cầu thêm bìa phụ, lời cam đoan hoặc lời cảm ơn, phải điều chỉnh phân bổ trong tổng 40 trang; không tự cộng thêm.

Không bố trí phụ lục riêng trong ngân sách hiện tại. Chi tiết 28 đặc trưng, cấu hình dài, toàn bộ kết quả từng miền và lệnh chạy được dẫn đến tài liệu bổ trợ trong repo. Nếu bắt buộc có phụ lục trong bản nộp, phải giảm tương ứng phần chính.

Phân bổ mới giảm phần nền tảng và mô tả phương pháp so với đề cương đầu, đồng thời tăng dung lượng đặt vấn đề và thảo luận kết quả. Hạn mức trang không phải lý do kéo dài kiến thức phổ biến, lặp lại con số hoặc bổ sung mô tả kỹ thuật không phục vụ lập luận.

## 3. Đề cương chi tiết

### Chương 1. Giới thiệu đề tài (4 trang)

**Câu hỏi chương cần trả lời:** nhóm đang giải quyết vấn đề gì, vì sao vấn đề đáng nghiên cứu và nhóm đặt mục tiêu đến đâu?

| Mục | Trang | Nội dung phải viết |
|---|---:|---|
| 1.1. Bối cảnh và bài toán tìm kiếm câu hỏi | 0,75 | Đặt câu hỏi tìm kiếm trong ngữ cảnh sử dụng thực tế, nêu đầu vào và nhu cầu nhận danh sách liên quan. Dùng ví dụ ngắn làm rõ khó khăn về diễn đạt và khớp thuật ngữ. |
| 1.2. Vấn đề chất lượng và chi phí truy xuất | 1 | Phân tích vì sao cần kết hợp từ khóa và ngữ nghĩa, đồng thời làm rõ chi phí phát sinh khi mọi truy vấn đều chạy Dense. Dẫn đến nhu cầu lựa chọn truy vấn thay vì mô tả cơ chế kỹ thuật. |
| 1.3. Giả thiết và câu hỏi nghiên cứu | 1 | Giải thích căn cứ cho giả thiết dùng thông tin rẻ để quyết định trước encoder. Từ giả thiết đó, đặt câu hỏi về lợi ích của gate, biên suy giảm chất lượng và chi phí đo được. |
| 1.4. Mục tiêu, phạm vi và đóng góp | 1 | Nêu mức độ nhóm đặt mục tiêu giải quyết, các tiêu chí đánh giá và phạm vi suy luận. Liên kết từng đóng góp dự kiến với câu hỏi nghiên cứu tương ứng. |
| 1.5. Bố cục báo cáo | 0,25 | Một đoạn dẫn sang năm chương còn lại. |

Nguồn bắt đầu: [giới thiệu v1](../../GIOI_THIEU_DE_TAI_PE_GH_v1.md), [giới thiệu trong paper](../../paper/01_introduction.md), [tổng hợp hệ cuối](../KET_QUA_TONG_HOP_PE_GH.md). Chỉ tái sử dụng phần đặt vấn đề từ v1; viết lại mục tiêu, phạm vi và đóng góp theo v2.

### Chương 2. Cơ sở lý thuyết và nghiên cứu liên quan (5 trang)

**Câu hỏi chương cần trả lời:** những hướng giải quyết đã có là gì, mỗi hướng giải quyết phần nào và còn điều gì cần nhóm kiểm chứng?

| Mục | Trang | Nội dung phải viết |
|---|---:|---|
| 2.1. Các khái niệm cần thiết cho bài toán | 1 | Giới thiệu ngắn vai trò của BM25, Dense và Hybrid. Làm rõ chi phí mã hóa truy vấn mới và tính bổ sung giữa hai kiểu truy xuất. Không trình bày lại TF/IDF, phép toán vector hoặc dẫn xuất công thức BM25. |
| 2.2. Dự báo chất lượng và lựa chọn chiến lược truy xuất | 1 | Giải thích mối liên hệ giữa tín hiệu từ kết quả BM25, dự báo chất lượng và quyết định có chạy Dense. Phân biệt quyết định trước encoder với điều chỉnh fusion sau khi đã trả chi phí Dense. |
| 2.3. Các nghiên cứu liên quan trực tiếp | 2 | Phân tích Arabzadeh, LiteGator và những công trình fusion thực sự cần cho lập luận. Với mỗi hướng, làm rõ vấn đề, thông tin dùng để quyết định, lợi ích và giới hạn liên quan đến mục tiêu đề tài. |
| 2.4. Định vị hướng tiếp cận của nhóm | 1 | Tổng hợp bằng bảng so sánh ngắn, sau đó giải thích những câu hỏi còn cần kiểm chứng trong điều kiện của đề tài. Chuyển trực tiếp sang lý do lựa chọn phương pháp ở Chương 3. |

Không kể lần lượt quá nhiều bài báo. Với mỗi công trình gần, cần có: họ giải quyết việc gì, bằng cách nào, giới hạn liên quan và nhóm kế thừa/điều chỉnh phần nào. Các phương pháp chỉ được thảo luận nhưng không chạy phải được ghi đúng vai trò.

Phần khái niệm nền được giới hạn khoảng một trang. Bốn trang còn lại phải có nội dung so sánh, tổng hợp hoặc lập luận gắn trực tiếp với lựa chọn của nhóm. Công thức, định nghĩa hoặc ví dụ chỉ được giữ khi phần phương pháp hay kết quả thực sự cần đến chúng.

Nguồn trong repo: [routing/fusion](../../paper/02a_routing_related_work.md), [Dense và hiệu năng](../../paper/02b_dense_and_efficiency_background.md), [kiểm tra nguồn ban đầu](../../research_evidence/source_audit.json). Các đoạn nói về Ridge, nhãn utility gain và hai miền trong bản thảo cũ cần sửa khi mô tả hệ cuối.

### Chương 3. Phương pháp PE-GH (6 trang)

**Câu hỏi chương cần trả lời:** vì sao PE-GH lựa chọn truy vấn trước encoder, quyết định dựa trên thông tin nào và cách tiếp cận này hướng đến mục tiêu chất lượng, chi phí ra sao?

| Mục | Trang | Nội dung phải viết |
|---|---:|---|
| 3.1. Bài toán và mục tiêu lựa chọn truy vấn | 0,75 | Xác định quyết định cần đưa ra, chất lượng muốn duy trì và phần chi phí muốn giảm. Liên kết với mục tiêu và câu hỏi đã đặt ở Chương 1. |
| 3.2. Nguyên lý hoạt động của PE-GH | 1 | Một sơ đồ thể hiện BM25, bộ quyết định và hai khả năng P*/H*. Giải thích vai trò nhánh rẻ và nhánh Hybrid, đồng thời chỉ rõ chi phí nào được tránh khi bỏ qua encoder. |
| 3.3. Thông tin dùng cho quyết định | 1 | Trình bày theo nhóm tín hiệu từ truy vấn và kết quả BM25. Nêu một vài ví dụ có ý nghĩa đối với độ tin cậy của BM25; giải thích vì sao những tín hiệu này có trước Dense. Không liệt kê hay đặc tả công thức của cả 28 đặc trưng. |
| 3.4. Cơ sở lựa chọn cách học cho gate | 1,25 | Giải thích ý nghĩa nhãn “BM25 thất bại”, lý do dùng mô hình nhẹ và huấn luyện nhiều miền. Phân biệt dự đoán BM25 thất bại với biết chắc Hybrid sẽ cải thiện; từ đó nêu giới hạn cần kiểm chứng. |
| 3.5. Vai trò của ngân sách truy xuất | 1 | Giải thích người vận hành thay đổi mức sử dụng Dense như thế nào và vì sao cần so sánh các gate ở cùng ngân sách. Nêu hai chế độ ngưỡng vận hành và khớp số lượt, cùng giới hạn do truy vấn bắt buộc dùng Dense và phân phối truy vấn thay đổi. |
| 3.6. Quá trình hình thành phương pháp cuối | 1 | Tóm tắt những quan sát từ v1 và vòng v3 dẫn đến lựa chọn v2. Phân tích lý do thay đổi nhãn, encoder hoặc nhánh, đồng thời giữ rõ điều gì chưa được cô lập bằng thực nghiệm. |

Chương này dùng sơ đồ nguyên lý và ví dụ ngắn để giải thích quyết định của hệ thống. Không yêu cầu thuật toán giả, sơ đồ module, mô tả API hoặc quy trình xây chỉ mục. Chỉ giữ ký hiệu hoặc biểu thức thực sự cần để định nghĩa nhãn học, quyết định lựa chọn và mục tiêu đánh giá; không diễn giải lại thuật toán học máy phổ biến.

Nguồn chính: [mô tả v4](../v4/README.md), [gate đóng băng](../../configs/v4/gate_v2.json), [giao thức](../../configs/v4/preregistration.yaml), [cấu hình encoder](../../configs/v4/dense_arctic_xs.yaml), [gate trong mã](../../src/pegh/v4/gate.py), [đường online](../../src/pegh/v4/online.py), [đặc trưng](../../src/pegh/v3/features.py), [proxy](../../src/pegh/v3/proxy.py).

Người biên soạn phải đối chiếu số liệu lịch sử với đúng chính sách và source snapshot của lượt đo. Việc kiểm tra cache và cập nhật phá hòa ngày 07/11/2026 được theo dõi trong hồ sơ nguồn. Thân báo cáo chỉ cần nêu khác biệt khi chúng ảnh hưởng đến cách hiểu kết quả, không mở rộng thành phần mô tả bảo trì phần mềm.

### Chương 4. Thiết kế thực nghiệm (5 trang)

**Câu hỏi chương cần trả lời:** kết quả được tạo ra trong điều kiện nào và phép so sánh có kiểm soát được yếu tố gây nhiễu không?

| Mục | Trang | Nội dung phải viết |
|---|---:|---|
| 4.1. Dữ liệu và phạm vi đánh giá | 1 | Giới thiệu CQADupStack, số truy vấn/tài liệu, vai trò sáu miền phát triển và sáu miền xác nhận. Giải thích nhãn liên quan và nguyên tắc loại kết quả trùng chính truy vấn khi cần; chi tiết chuẩn hóa dữ liệu để ở tài liệu bổ trợ. |
| 4.2. Phân chia và quy trình nghiên cứu | 1,25 | Group-aware five-fold, LODO trên miền đã thấy, chọn encoder/gate trước xác nhận, ngưỡng không nhãn, thời điểm đóng băng và vai trò của sáu miền mới. |
| 4.3. Đối chứng và tính công bằng | 1 | BM25, Dense, P*, H*, R*, v1, margin, random và oracle. Tách BERT/LiteGator là bản điều chỉnh trên cùng hạ tầng, thuộc phân tích thăm dò. |
| 4.4. Thước đo và kiểm định | 1 | nDCG@10 chính, macro đều theo miền, paired group bootstrap, biên không kém 0,01 và Holm K1–K4. Metric phụ chỉ báo cáo khi có nguồn đúng lượt. |
| 4.5. Điều kiện đo chi phí truy xuất | 0,75 | Nêu cấu hình CPU và điều kiện phục vụ truy vấn có ảnh hưởng đến phép so sánh. Giải thích hệ thống được chạy thật từ đầu đến cuối, có khởi động trước và lặp đo, kết quả được đối chiếu với đánh giá chất lượng. Không trình bày cơ chế timer, tiến trình hay ghi log. |

**Các điểm giao thức phải giải thích rõ:**

- Sáu miền xác nhận là “chưa dùng” **tại thời điểm chốt giao thức**, không phải vẫn còn dữ liệu chưa xem ở hiện tại.
- Trọng số v2 đóng băng trên sáu miền phát triển; nhánh đối chứng v1 có lựa chọn train/validation trong từng miền. K3 là so sánh toàn hệ thống với giao thức đã công bố, không phải thí nghiệm cô lập gate.
- Chuẩn hóa v2 dùng thống kê query không nhãn của miền mới, có sử dụng phân phối query miền đích. Không mô tả thành hệ thống hoàn toàn không tiếp cận dữ liệu miền đích.
- Ngân sách 50% đối chứng theo số lượt và ngưỡng vận hành 80% là hai quy tắc khác nhau. Không lấy giá trị từ hai quy tắc đổi chỗ cho nhau.
- Bootstrap trên fixed predictions chưa bao gồm mọi bất định từ huấn luyện lại, chọn model hoặc thay máy đo.

Nguồn chính: [preregistration](../../configs/v4/preregistration.yaml), [biên nhận đăng ký](../v4/facts/preregistration.json), [đánh giá sáu miền](../v4/facts/evaluation_new.json), [online v2](../v4/facts/online_report.json), [kế hoạch online đối chứng](../../configs/v4/prior_online_plan.yaml). [Setup v1](../../paper/04_experimental_setup.md) chỉ cung cấp phần nền dùng chung, không thay thế giao thức v2.

### Chương 5. Kết quả và thảo luận (12 trang)

**Câu hỏi chương cần trả lời:** nhóm giải quyết được đến đâu, bằng chứng mạnh đến mức nào, điều gì không đạt và vì sao?

| Mục | Trang | Nội dung phải viết |
|---|---:|---|
| 5.1. Chất lượng truy xuất trên các miền xác nhận | 2 | Phân tích kết quả BM25/P*/Dense/H*/PE-GH theo câu hỏi về lợi ích của truy xuất lai có chọn lọc. Liên hệ trung bình macro với biến động từng miền, làm rõ ngân sách áp dụng và trường hợp chất lượng giảm. |
| 5.2. Kiểm chứng các giả thuyết nghiên cứu | 1,5 | K1–K4, estimate, CI, phép kiểm định, Holm và ý nghĩa thực tế. K2 là chấp nhận mất mát nhỏ trong biên, không phải không mất chất lượng. |
| 5.3. Quan hệ chất lượng và chi phí | 2 | Online mean/p50/p95/CPU/RSS, tỷ lệ encode thực tế, đường Pareto và stage breakdown. Phân tích cả 50% và 80%, không chỉ chọn điểm đẹp nhất. |
| 5.4. Phân tích quyết định của gate | 1,5 | Đường cong ngân sách so margin/random/oracle, AUC, lợi ích tập trung ở ngân sách nào, khác biệt theo miền. Ablation chỉ kết luận theo điều thực nghiệm thực sự cô lập. |
| 5.5. Đối chiếu các router liên quan | 1,5 | BERT/LiteGator cùng P*/H* và ngân sách, cả offline lẫn phiên online riêng. Công bố giới hạn tuning và kết quả BERT tốt hơn ở 80% trên sáu miền mới. |
| 5.6. Trường hợp thành công và thất bại | 1,5 | Chọn các truy vấn thật của v2 để giải thích khi nào thông tin BM25 đủ dùng và khi nào quyết định của gate chưa phù hợp. Liên hệ từng ví dụ với giả thiết nghiên cứu, thay vì chỉ kể lại ranking. |
| 5.7. Giới hạn và ý nghĩa của kết quả | 2 | Phân tích kết quả trả lời được đến đâu so với mục tiêu ban đầu. Làm rõ giới hạn dữ liệu, máy đo, chi phí proxy, độ trễ đuôi và các lựa chọn cạnh tranh. Tách quan sát đã có bằng chứng với giả thuyết giải thích cần kiểm chứng thêm. |

Mỗi bảng/hình phải được giới thiệu bằng câu hỏi hoặc mục đích so sánh cụ thể. Đoạn sau bảng/hình giải thích phát hiện chính, liên hệ với mục tiêu nghiên cứu và nêu giới hạn khi cần. Các từ chỉ quan hệ nhân quả chỉ được dùng khi thiết kế thực nghiệm hỗ trợ quan hệ đó. Không lặp lại toàn bộ con số trong bảng thành văn bản hoặc kéo dài thảo luận để đủ hạn mức trang.

**Các mốc dùng để kiểm tra nhất quán khi viết:** những giá trị này lấy từ facts đã lưu, không phải lượt chạy lại ngày lập kế hoạch.

| Mốc | Giá trị tham chiếu | Nguồn và phạm vi |
|---|---|---|
| Chất lượng v2 ở ngân sách vận hành 80% | 0,4159 so với H* 0,4223 | `evaluation_new.json`, macro sáu miền xác nhận, ngưỡng vận hành |
| K1 ở cùng ngân sách 50% | +0,00418 so với BM25-margin | Cùng file, phép so khớp số lượt encode |
| K2 không kém trong biên 0,01 | Chênh −0,00639; lower bound một phía 95% khoảng −0,00819 | Cùng file; không thay lower bound một phía bằng CI hai phía khi mô tả kiểm định |
| Online v2 ở 50% | Mean 14,76 ms; H* cùng phiên 24,31 ms | `online_report.json`, programmers/unix |
| Online đối chứng router ở 50% | Mean v2 14,30 ms; LiteGator 14,43 ms; BERT 162,57 ms | `prior_online_report.json`, một phiên đối chứng khác |

Không ghép 14,30 ms với mốc H* 24,31 ms để tính mức giảm: hai số thuộc hai phiên. Tương tự, 0,4159 ở ngưỡng vận hành và 0,4156 ở đối chứng 80% khớp số lượt là hai kết quả khác giao thức. Lấy trường đúng từ JSON, không lựa chọn số theo kết luận mong muốn.

Nguồn chính: [tổng hợp](../KET_QUA_TONG_HOP_PE_GH.md), [facts v4](../v4/facts/), [hình v4](../v4/figures/), [so router offline](../v4/facts/prior_comparison.json), [LiteGator sau chọn cấu hình](../v4/facts/prior_litegator_tuned.json), [so router online](../v4/facts/prior_online_report.json).

### Chương 6. Kết luận và hướng phát triển (2 trang)

| Mục | Trang | Nội dung phải viết |
|---|---:|---|
| 6.1. Trả lời câu hỏi nghiên cứu | 0,75 | Trả lời lần lượt các câu hỏi ở Chương 1, viện dẫn kết quả tương ứng ở Chương 5. |
| 6.2. Đóng góp và mức độ giải quyết | 0,75 | Gate nhẹ có ích trong phạm vi đã đo; giảm lượt encode trong biên cho phép; hạ tầng đánh giá và đo online có thể truy vết. Nêu cả điều chưa giải quyết. |
| 6.3. Hướng phát triển | 0,5 | Thử BM25 thay P*, HNSW đầu-cuối, kiểm chứng dữ liệu/máy khác. Đây là đề xuất, không trình bày như kết quả đã đạt. |

Không mở một kết quả thực nghiệm mới ở phần kết luận. Tóm tắt và kết luận chỉ viết sau khi khóa bảng chính.

## 4. Liên kết câu hỏi nghiên cứu với bằng chứng

| Câu hỏi | Bằng chứng chính | Vị trí |
|---|---|---|
| Gate học có hơn quy tắc đơn giản và ngẫu nhiên ở cùng ngân sách không? | K1, K4; margin/random; đường cong theo ngân sách | 5.2, 5.4 |
| Có thể giảm Dense mà giữ chất lượng trong biên cho phép không? | K2, biên 0,01; tỷ lệ encode thực tế | 5.1–5.3 |
| Giảm lượt Dense có chuyển thành giảm chi phí online không? | Độ trễ/CPU đo thật, stage breakdown, p95 và RSS | 5.3 |
| Nâng cấp v2 có ích và giới hạn nằm ở đâu? | K3 toàn hệ thống, encoder comparison, per-domain, router liên quan và failure cases | 5.1, 5.4–5.7 |

Các giả thiết được giới thiệu ở Chương 1 tạo cơ sở cho câu hỏi nghiên cứu. Khi chuyển sang thực nghiệm, cần liên kết các câu hỏi đó với giả thuyết K1–K4 đã đăng ký, đồng thời giữ nguyên định nghĩa và chiều so sánh trong giao thức gốc.

## 5. Danh sách bảng và hình dự kiến

### 5.1. Bảng

| Bảng | Nội dung | Nguồn/công việc |
|---|---|---|
| 2.1 | Đối chiếu các nghiên cứu gần theo mục tiêu và thời điểm quyết định truy xuất | Đọc nguồn gốc và làm rõ lựa chọn nào có thể tránh chi phí Dense |
| 3.1 | Nhóm thông tin gate quan sát được và ý nghĩa đối với quyết định | `gate_v2.json`, mã features; chỉ tổng hợp theo nhóm, không đặc tả đủ 28 đặc trưng |
| 3.2 | Phân biệt v1, vòng v3 và hệ cuối v2/v4 | `VERSIONS.md`, báo cáo các vòng |
| 4.1 | Phạm vi dữ liệu và vai trò các miền trong đánh giá | Manifests, preregistration, facts; cấu hình đo chỉ nêu ngắn trong mục 4.5 |
| 5.1 | Chất lượng các phương pháp chính | `evaluation_new.json` |
| 5.2 | K1–K4 và kiểm định | `evaluation_new.json` |
| 5.3 | Online cùng phiên: quality, encode ratio, mean/p50/p95, CPU, RSS | `online_report.json` |
| 5.4 | BERT/LiteGator: chất lượng và chi phí theo giao thức tương ứng | Facts `prior_*`; tách panel offline/online |
| 5.5 | Các trường hợp thành công/thất bại và utility | Cần trích riêng từ dữ liệu/ranking v2 |

### 5.2. Hình

| Hình | Nội dung | Trạng thái |
|---|---|---|
| 2.1 | So sánh thời điểm lựa chọn truy xuất ở các hướng nghiên cứu | Chỉ vẽ nếu giúp giải thích rõ sự khác nhau giữa quyết định trước và sau chi phí Dense |
| 3.1 | Sơ đồ nguyên lý PE-GH v2 và vị trí ra quyết định trước encoder | Cần vẽ theo hệ cuối, không thể hiện module hoặc API |
| 4.1 | Phát triển trên sáu miền → đóng băng → xác nhận sáu miền | Cần vẽ; tách nhánh online LODO hai miền |
| 5.1 | Khoảng tin cậy các giả thuyết | Có `v4_hypotheses.png`; kiểm tra caption và độ đọc được |
| 5.2 | Chất lượng theo ngân sách, gate/margin/random/oracle | Có `v4_budget_curves.png`; ghi đúng quy tắc ngân sách |
| 5.3 | Chất lượng–độ trễ online | Có `v4_pareto_online.png`; giữ đúng phiên đo |
| 5.4 | Các thành phần chi phí chính của hai nhánh truy xuất | Chỉ dùng khi cần giải thích lợi ích quan sát; lấy mẫu cùng phiên, không mô tả cơ chế đo kỹ thuật |
| 5.5 | Đối chứng router liên quan | Có hình `v4_prior_curves.png`/`v4_prior_online.png`; chọn một hình phù hợp để tránh lặp bảng |

Không cần sử dụng tất cả hình nếu lặp ý. Ưu tiên khoảng 6–7 hình có thông tin khác nhau và trực tiếp hỗ trợ lập luận. Các hình có sẵn cần xem trực tiếp và kiểm tra số liệu/cỡ chữ trước khi đưa vào bản nộp; lượt lập kế hoạch chưa nghiệm thu hình.

## 6. Công việc còn cần làm trước khi viết hoàn chỉnh

| Việc | Hiện trạng | Đầu ra cần có | Mức cần thiết |
|---|---|---|---|
| Chốt mẫu trình bày | Chưa có quy định font/lề/giãn dòng của trường trong yêu cầu hiện tại | Một mẫu cố định để kiểm soát 40 trang | Trước khi dàn trang chính thức |
| Lập danh mục số liệu dùng trong báo cáo | Có nhiều facts và nhiều lượt đo | Mỗi con số có file, trường JSON, phiên bản, miền, chính sách và phiên đo | Bắt buộc |
| Viết lại phần phương pháp theo v2 | Phần lớn `paper/` hiện là v1 | Chương 3 giải thích nguyên lý, cơ sở lựa chọn gate và vai trò ngân sách; thông tin về logistic/arctic/P*/H* thống nhất | Bắt buộc |
| Chuẩn hóa tài liệu tham khảo | Nguồn nằm rải rác; chưa có `.bib` chung trong repo | Danh mục nguồn với tác giả, năm, tên, venue, DOI/URL; thống nhất kiểu trích dẫn | Bắt buộc |
| Kiểm tra cách phân nhóm dữ liệu và tổng hợp kết quả | Giao thức đã có, cần diễn giải chính xác | Bảng dữ liệu, sơ đồ protocol, định nghĩa macro và CI | Bắt buộc |
| Phân tích lỗi riêng cho v2 | Có failure analysis v1; chưa xác nhận đủ case v2 cho báo cáo | Chuẩn bị 6–8 trường hợp thật theo quy tắc, chọn khoảng 4 trường hợp tiêu biểu cho mục 5.6 và lưu phần còn lại làm minh chứng bổ trợ | Bắt buộc cho mục 5.6 |
| Vẽ sơ đồ nguyên lý và biên tập hình | Có biểu đồ v4, thiếu bộ minh họa thống nhất cho báo cáo | Hình hỗ trợ giải thích vấn đề hoặc kết quả, có caption, nguồn và nhãn dễ đọc khi in A4 | Bắt buộc |
| Xác nhận nguồn của số liệu lịch sử | Facts và receipt đã đóng băng; mã sau đó có cập nhật | Ghi đúng source snapshot, model, artifact và môi trường của từng lượt | Bắt buộc |
| Chạy lại benchmark bằng mã mới | Chưa được chứng minh bởi các test không-model | Output mới, không ghi đè lịch sử; chỉ cần nếu muốn báo cáo kết quả của bản mã mới | Có điều kiện |
| Thêm dataset, ANN hoặc hệ ba tầng | Là các hướng mở | Một nghiên cứu bổ sung có protocol riêng nếu thực hiện | Không bắt buộc để hoàn thành báo cáo hiện tại |

Quy tắc chọn failure cases: khóa danh sách query và phiên bản trước khi viết nhận xét; chia nhóm skip đúng, encode có lợi, skip mất utility, encode không có lợi/gây hại; trong mỗi nhóm lấy case đại diện theo quy tắc công bố, không chỉ lấy trường hợp có lợi cho gate. Ghi query ID, domain, route, utility P*/H*/gate và tài liệu liên quan. Nếu thiếu raw artifacts, ghi việc thiếu và chưa viết ví dụ như kết quả thật.

## 7. Thứ tự viết và lịch dự kiến

Đây là lịch đề xuất **10 ngày làm việc**, điều chỉnh theo thời hạn nộp thực tế. Thứ tự viết khác thứ tự đọc để phần giới thiệu dựa trên bằng chứng đã chốt.

| Giai đoạn | Ngày làm việc | Công việc | Điều kiện kết thúc |
|---|---|---|---|
| 1. Khóa đề cương và nguồn | 1 | Chốt tên, 40 trang tổng, phạm vi v2, template và danh mục số liệu | Mọi bảng chính có nguồn; thống nhất cách gọi phiên bản |
| 2. Soạn cơ sở và giao thức | 2–3 | Viết Chương 2, Chương 4; chọn lọc khái niệm nền, phân tích nghiên cứu gần và làm rõ logic đánh giá | Mỗi nội dung liên quan trực tiếp đến câu hỏi nghiên cứu hoặc tính hợp lệ của phép so sánh |
| 3. Soạn phương pháp | 4–5 | Viết Chương 3 theo nguyên lý, cơ sở lựa chọn thông tin/nhãn/ngân sách và sơ đồ quyết định | Người đọc hiểu vì sao phương pháp có thể giải quyết vấn đề mà không cần đọc chi tiết thiết kế phần mềm |
| 4. Soạn kết quả | 6–7 | Khóa bảng/hình, viết Chương 5, failure cases và giới hạn | Không trộn phiên đo; mọi nhận định truy được bằng chứng |
| 5. Hoàn thiện mạch báo cáo | 8 | Viết Chương 1, Chương 6 và tóm tắt; rà logic vấn đề → mục tiêu → bằng chứng | Các câu hỏi đầu bài đều được trả lời ở cuối |
| 6. Review và dàn trang | 9–10 | Kiểm số liệu/trích dẫn, rà ngữ cảnh từng đoạn, bỏ giải thích phổ biến hoặc kỹ thuật thừa, render và xem từng trang PDF | Nội dung nhất quán, câu văn đầy đủ, bảng/hình đọc được và tổng dung lượng khoảng 40 trang |

Việc bắt đầu ngay sau kế hoạch: tạo sổ nguồn số liệu, dựng khung sáu chương và viết Chương 4 từ giao thức đã có; sau đó viết Chương 3 theo v2. Chưa cần mở thêm một vòng thực nghiệm chỉ để tăng độ dài báo cáo.

## 8. Phân công viết cho nhóm ba người

Giữ vai trò A/B/C của dự án, chưa tự gán tên thành viên vào vai trò nếu nhóm chưa chốt.

| Vai trò | Phần phụ trách chính | Review chéo |
|---|---|---|
| A (dữ liệu và đánh giá) | 4.1–4.4, 5.1–5.2; sổ nguồn số liệu, bảng chất lượng và kiểm tra thống kê | Review nhãn/giao thức Chương 3 và kết luận chất lượng |
| B (Dense, FAISS và hiệu năng) | Phần Dense trong 2.1 và nhánh Hybrid trong 3.2, mục 4.5 và 5.3; phân tích chi phí và bảng CPU/RSS | Review tính công bằng phép đo, phát biểu về tốc độ và mức cần thiết của các chi tiết kỹ thuật |
| C (fusion, gate và điều phối) | Chương 3, 2.2–2.4, 5.4–5.6; sơ đồ nguyên lý, cơ sở lựa chọn và so sánh router | Review logic phương pháp, ý nghĩa các trường hợp lỗi và phát biểu về đóng góp |
| Cả nhóm | Chương 1, 5.7, Chương 6, tóm tắt, thuật ngữ và đọc bản PDF | Mỗi người kiểm chứng lại phần thuộc chuyên môn của mình |

Chỉ định một người ghép bản thảo và chuẩn hóa văn phong; phần việc này không thay việc A/B/C phải viết và xác nhận nội dung của mình. Nếu viết song song, dùng file chương riêng để giảm xung đột.

Khi ghép bản thảo, phải rà lại những thuật ngữ được giới thiệu nhiều lần, những đoạn thiếu chủ thể và những kết luận không gắn với câu hỏi nghiên cứu. Việc từng phần đúng riêng lẻ chưa bảo đảm toàn báo cáo có một mạch lập luận thống nhất.

## 9. Cấu trúc tài liệu dự kiến

Thư mục hiện tại mới có file kế hoạch này. Khi bắt đầu soạn báo cáo, có thể tạo:

```text
docs/bao_cao/
  KE_HOACH_BAO_CAO_40_TRANG.md
  SO_NGUON_SO_LIEU.csv
  00_tom_tat.md
  01_gioi_thieu.md
  02_co_so_va_nghien_cuu_lien_quan.md
  03_phuong_phap_pegh.md
  04_thiet_ke_thuc_nghiem.md
  05_ket_qua_va_thao_luan.md
  06_ket_luan.md
  tai_lieu_tham_khao.bib
  figures/
```

Định dạng bản nộp cuối (Word hoặc LaTeX rồi PDF) chọn theo mẫu của trường. Nếu tạo cả file nguồn và bản ghép, cần một nguồn biên tập chính để tránh sửa hai bản lệch nhau. File báo cáo là tài liệu; yêu cầu trước đó về loại Markdown/kế hoạch/slide khỏi commit code vẫn áp dụng khi có thao tác Git sau này.

Các cột tối thiểu của sổ nguồn: `claim_id`, `chapter`, `system_version`, `source_file`, `json_field`, `dataset_domains`, `routing_policy`, `measurement_session`, `value`, `unit`, `source_snapshot`, `verification_status`. Chỉ đánh dấu đã kiểm khi thực sự đối chiếu.

## 10. Nguồn nghiên cứu để xây danh mục tham khảo

Đã đối chiếu tiêu đề và thông tin mô tả trên trang nguồn ngày 09/11/2026 cho bốn tài liệu dưới đây. Khi viết related work vẫn cần đọc phương pháp và thực nghiệm đầy đủ; kiểm tra abstract không thay thế việc đó.

1. Arabzadeh, Yan, Clarke (2021), [Predicting Efficiency/Effectiveness Trade-offs for Dense vs. Sparse Retrieval Strategy Selection](https://arxiv.org/abs/2109.10739). Nguồn gần cho bài toán lựa chọn chiến lược truy xuất.
2. Ar-Razy Muhammad Darmanto và Rizqia Lestika Atimi (2025), [LiteGator: A Lightweight and Budget-Aware Retriever Routing Framework for Low-Resource Question Answering](https://www.atlantis-press.com/proceedings/icast-es-25/126020510). Trang xuất bản ghi **hai tác giả**; không tách tên tác giả thứ nhất thành hai người khi lập thư mục tham khảo.
3. Thakur và cộng sự (2021), [BEIR: A Heterogenous Benchmark for Zero-shot Evaluation of Information Retrieval Models](https://arxiv.org/abs/2104.08663). Nguồn cho bối cảnh benchmark truy xuất đa miền.
4. Bruch, Gai, Ingber (2023), [An Analysis of Fusion Functions for Hybrid Retrieval](https://arxiv.org/abs/2210.11934). Nguồn cho phân tích CC/RRF; năm bản xuất bản khác năm đăng bản arXiv đầu tiên.

Cần bổ sung nguồn gốc BM25, CQADupStack, RRF, FAISS, QPP, encoder arctic và tài liệu evaluator; kiểm tra metadata và nội dung trước khi trích. Chỉ đưa tài liệu thực sự dùng vào danh mục. Hai trang tham khảo là hạn mức dàn trang dự kiến, không phải chỉ tiêu số lượng bài phải đủ.

## 11. Quy tắc diễn giải và nghiệm thu

### 11.1. Những phát biểu cần giữ đúng

- Khi khoảng tin cậy của chênh lệch chứa 0, chỉ kết luận **chưa phát hiện khác biệt có ý nghĩa thống kê theo phân tích này**. Kết quả đó chưa chứng minh hai phương pháp tương đương.
- Giả thuyết K2 cho phép chất lượng suy giảm trong biên 0,01. Nếu kết quả đạt tiêu chí này, cần nói rõ mức suy giảm quan sát và biên cho phép, thay vì viết rằng chất lượng không giảm.
- Việc giảm số lượt mã hóa truy vấn cần được đối chiếu với chi phí online đo thật trước khi kết luận về độ trễ hoặc CPU. Tỷ lệ mã hóa thấp hơn không tự chứng minh p95 hay bộ nhớ đỉnh cũng giảm.
- K3 so sánh hai hệ thống có nhiều thành phần thay đổi. Chênh lệch quan sát không thể được quy hoàn toàn cho gate.
- BERT và LiteGator được điều chỉnh để chạy trong cùng hạ tầng và được so sánh theo phân tích thăm dò. Các kết quả này chưa chứng minh tái lập đầy đủ công bố gốc hoặc vượt mọi phương pháp hiện có.
- Nếu p-value bootstrap được lưu bằng 0, người biên soạn phải trình bày theo độ phân giải số lần lặp và quy tắc báo cáo đã nêu. Giá trị lưu đó không có nghĩa xác suất thật bằng 0.
- Các miền từng được gọi là mới trong giao thức lịch sử đều đã được sử dụng ở hiện tại. Việc xác nhận một thay đổi nghiên cứu tiếp theo cần thiết kế mới và dữ liệu chưa được dùng cho lựa chọn thay đổi đó.
- Kiểm thử phần mềm được lưu trong hồ sơ kỹ thuật để kiểm tra việc triển khai. Chúng không thay thế phép đo chất lượng, chi phí hoặc khả năng tái lập thực nghiệm chưa được thực hiện.

### 11.2. Checklist bản nộp

- [ ] PDF khoảng 40 trang tổng cộng, đã tính phần đầu và tài liệu tham khảo.
- [ ] Chương 1 làm rõ vấn đề, giả thiết, mục tiêu và giới hạn trước khi nói cách làm.
- [ ] Kiến thức nền phổ biến chỉ được giới thiệu ngắn trong ngữ cảnh đề tài; không có phần diễn giải lại giáo trình.
- [ ] Phương pháp tập trung vào nguyên lý và cơ sở lựa chọn; chi tiết module, API, cache, checksum và lệnh chạy nằm trong tài liệu bổ trợ.
- [ ] Câu văn có đủ chủ thể, ngữ cảnh và quan hệ ngữ nghĩa; không dùng dấu gạch ngang để chèn lời giải thích.
- [ ] Mỗi đoạn có một ý chính, bằng chứng hoặc lập luận phù hợp và liên kết rõ với nội dung liền trước.
- [ ] Thuật ngữ, định nghĩa, mục tiêu, phép so sánh và kết luận thống nhất từ đầu đến cuối.
- [ ] Cách gọi v1/v2 và vòng v3/v4 thống nhất trong toàn văn.
- [ ] Phương pháp mô tả hệ cuối; phần lịch sử được đánh dấu rõ.
- [ ] Mỗi câu hỏi nghiên cứu có bằng chứng và câu trả lời tương ứng.
- [ ] Mọi số liệu quan trọng có file và trường dữ liệu đối chiếu được.
- [ ] Không trộn miền, chính sách, encoder hoặc phiên đo trong một phép so sánh.
- [ ] Phân biệt kết quả đăng ký trước, phân tích mô tả và so sánh thăm dò.
- [ ] Có kết quả âm, p95, giới hạn và failure cases thật của đúng hệ thống.
- [ ] Mọi tài liệu tham khảo được trích; tác giả, năm và DOI/URL đã kiểm tra.
- [ ] Hình/bảng được dẫn trong văn bản, có caption và đọc được khi in.
- [ ] Đã xem từng trang bản render cuối, không có bảng tràn, hình mờ hoặc trang trống bất thường.
- [ ] Cả ba thành viên đã đọc chéo và xác nhận nội dung thuộc phần của mình.
