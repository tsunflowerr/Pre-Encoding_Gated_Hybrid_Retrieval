# Tăng tốc tìm kiếm câu hỏi kỹ thuật bằng cách kết hợp từ khóa và ngữ nghĩa

**Tên hệ thống:** PE-GH  
**Phạm vi tài liệu:** Giới thiệu đề tài và hướng giải quyết cho người chưa biết dự án. Không trình bày tiến độ nhóm.

## Giới thiệu ngắn

Đề tài nghiên cứu công cụ PE-GH để tra cứu những câu hỏi tiếng Anh tương đồng về phần mềm và Unix/Linux trong một kho dữ liệu cố định. Người dùng nhập câu hỏi, công cụ trả danh sách câu hỏi liên quan đã xếp hạng. Hệ thống tìm theo từ khóa trước, rồi dùng một mô hình ML nhỏ để dự đoán có nên chạy thêm tìm theo ngữ nghĩa. Mục tiêu là giảm thời gian xử lý trên CPU trong khi giữ chất lượng tìm kiếm.

## Slide 1. Giới thiệu đề tài

### Nội dung trên slide

- Tên đề tài: Tăng tốc tìm kiếm câu hỏi kỹ thuật bằng cách kết hợp từ khóa và ngữ nghĩa.
- PE-GH là công cụ tra cứu các câu hỏi tiếng Anh về phần mềm và Unix/Linux trong một kho dữ liệu cố định.
- Đầu vào là một câu hỏi. Đầu ra là danh sách câu hỏi tương đồng đã xếp hạng.

### Lời trình bày

Đề tài nghiên cứu một công cụ tìm kiếm có tên PE-GH. Người dùng nhập một câu hỏi tiếng Anh về phần mềm hoặc Unix/Linux. Công cụ tìm trong kho câu hỏi đã lưu và trả về những câu hỏi tương đồng, xếp các kết quả phù hợp hơn lên trước. Người dùng có thể dùng việc tra cứu này để tìm lại vấn đề tương tự hoặc tham khảo trước khi đăng câu hỏi mới.

Mục tiêu nghiên cứu là giảm thời gian xử lý trên CPU trong khi giữ chất lượng tìm kiếm. Hướng giải quyết là kết hợp tìm theo từ khóa với tìm theo ngữ nghĩa, đồng thời dùng một mô hình ML nhỏ để lựa chọn khi nào cần tìm thêm theo ngữ nghĩa.

## Slide 2. Người dùng tìm gì, bằng công cụ nào?

### Nội dung trên slide

- Người dùng nhập câu hỏi tiếng Anh vào nguyên mẫu công cụ PE-GH.
- PE-GH tra cứu trong CQADupStack, một kho câu hỏi lấy từ Stack Exchange.
- Công cụ trả danh sách câu hỏi liên quan theo thứ tự phù hợp.
- Phạm vi tìm kiếm là kho dữ liệu đã lưu.

### Lời trình bày

Tình huống sử dụng là một người muốn tra cứu vấn đề kỹ thuật đã có người hỏi trước đó. Chẳng hạn, họ muốn tìm những câu hỏi nói về cách hiện tệp ẩn trong Linux. Họ nhập câu hỏi vào công cụ PE-GH. Hệ thống tra cứu trong kho câu hỏi CQADupStack, sử dụng nội dung tiêu đề và phần mô tả của các câu hỏi trong kho.

Kết quả là một danh sách câu hỏi liên quan đã xếp hạng để người dùng đọc và lựa chọn. Phần đánh giá của đề tài tập trung vào chất lượng danh sách này và thời gian tạo ra danh sách. Nội dung câu trả lời hay bản vá phần mềm không phải đầu ra mà benchmark này đánh giá.

## Slide 3. Dữ liệu tìm kiếm gồm những gì?

### Nội dung trên slide

- Dữ liệu thuộc CQADupStack trong benchmark BEIR, gồm hai miền programmers và unix.
- programmers: 32.176 câu hỏi trong kho, 876 câu hỏi dùng thử, 1.675 cặp câu hỏi được gán liên quan.
- unix: 47.382 câu hỏi trong kho, 1.072 câu hỏi dùng thử, 1.693 cặp câu hỏi được gán liên quan.
- Câu hỏi dùng thử dài trung bình khoảng 50–55 ký tự và đều bằng tiếng Anh.

### Lời trình bày

Cần phân biệt ba thành phần dữ liệu. Corpus là kho câu hỏi để tìm kiếm, tổng cộng 79.558 câu hỏi thuộc hai lĩnh vực phần mềm và Unix/Linux. Queries là 1.948 câu hỏi đưa vào hệ thống khi thử nghiệm. Qrels là các nhãn có sẵn chỉ ra câu hỏi nào trong kho liên quan hoặc trùng với từng câu hỏi đầu vào. Nhãn này dùng để chấm xếp hạng và tạo dữ liệu học cho bộ quyết định.

Phân tích dữ liệu cho thấy câu hỏi dùng thử khá ngắn, trung bình khoảng 55 ký tự ở programmers và 50 ký tự ở unix. Vì vậy, bộ dữ liệu phù hợp để nghiên cứu tìm câu hỏi tương đồng bằng những cách diễn đạt khác nhau. programmers bao gồm cả câu hỏi khái niệm và quy trình phần mềm. Phạm vi kết luận của đề tài gắn với dạng dữ liệu này; bộ dữ liệu chưa đủ để đại diện cho tìm bản vá hoặc phân tích nhật ký lỗi dài.

## Slide 4. Các cách tìm kiếm và hạn chế

### Nội dung trên slide

- BM25 tìm theo từ khóa, dựa vào tần suất từ, độ hiếm từ và độ dài nội dung.
- Dense dùng MiniLM để biểu diễn ý nghĩa và FAISS để tìm vector tương đồng.
- Hybrid kết hợp hai danh sách kết quả.
- Câu hỏi nghiên cứu: khi nào việc chạy thêm dense thực sự có ích?

### Lời trình bày

BM25 là một phương pháp tìm theo từ khóa. Nó tính điểm dựa trên các từ xuất hiện trong câu hỏi và tài liệu, có xét độ hiếm của từ và độ dài nội dung. Phương pháp này phù hợp khi người dùng dùng các từ gần với những câu hỏi đã lưu.

Dense retrieval dùng MiniLM để chuyển câu hỏi và tài liệu thành vector, rồi dùng FAISS để tìm nội dung có biểu diễn tương đồng. Cách này có thể bổ sung kết quả khi cách diễn đạt khác nhau, nhưng cần thêm bước mã hóa và tìm kiếm vector. Hybrid kết hợp hai danh sách để khai thác cả hai nguồn. Vấn đề nghiên cứu là có cần trả toàn bộ chi phí dense cho mọi câu hỏi hay không.

## Slide 5. Một ví dụ về khác biệt cách diễn đạt

### Nội dung trên slide

- Câu hỏi mới: “How can I display hidden files in Linux?”
- Câu hỏi trong kho: “How do I show dotfiles with the ls command?”
- Cùng nhu cầu: hiển thị tệp ẩn trong Linux.
- Đây là ví dụ minh họa, không phải kết quả thực nghiệm.

### Lời trình bày

Trong ví dụ này, người dùng hỏi cách hiển thị tệp ẩn trong Linux. Câu hỏi trong kho diễn đạt bằng từ dotfiles và nhắc đến lệnh ls. Hai câu có ý định gần nhau nhưng không dùng hoàn toàn cùng từ vựng. BM25 vẫn có thể tìm được kết quả, nhưng mức khớp từ khóa có thể ảnh hưởng đến thứ tự xếp hạng. Dense có thể bổ sung tín hiệu về ý nghĩa.

Ví dụ giúp giải thích động cơ của việc kết hợp hai cách tìm. Nó không chứng minh dense luôn tốt hơn BM25. Có những câu hỏi dùng từ khóa rất rõ mà BM25 đã tìm tốt, và cũng có trường hợp chạy thêm dense không cải thiện danh sách. Những khác biệt này cần được kiểm tra trên cả bộ dữ liệu.

## Slide 6. PE-GH chọn cách tìm như thế nào?

### Nội dung trên slide

- Bước 1: BM25 lấy danh sách kết quả ban đầu.
- Bước 2: lấy đặc trưng nhẹ từ câu hỏi và kết quả BM25.
- Bước 3: ML dự đoán lợi ích của việc chạy thêm dense.
- Lợi ích dự đoán thấp: trả BM25. Lợi ích dự đoán cao: chạy dense và kết hợp kết quả.

### Lời trình bày

PE-GH luôn tìm theo BM25 trước. Từ câu hỏi và danh sách vừa có, hệ thống lấy một số thông tin nhẹ, chẳng hạn độ dài câu hỏi, độ hiếm từ hoặc chênh lệch điểm giữa hai kết quả đầu. Một bộ quyết định, còn gọi là gate, dùng các thông tin đó để dự đoán chạy thêm dense có giúp cải thiện xếp hạng hay không.

Nếu lợi ích dự đoán thấp, hệ thống trả danh sách BM25. Nếu lợi ích vượt ngưỡng đã chọn, hệ thống mới mã hóa câu hỏi bằng MiniLM, tìm kiếm vector và kết hợp hai danh sách. Gate nằm trước bước mã hóa câu hỏi nên có thể tránh được cả chi phí mã hóa và tìm vector. Quyết định là dự đoán, vì vậy luôn cần đánh giá những trường hợp chọn sai.

## Slide 7. Phần ML học điều gì?

### Nội dung trên slide

- MiniLM: dùng mô hình có sẵn, giữ nguyên trọng số.
- Ridge: mô hình ML có giám sát để dự đoán lợi ích của hybrid.
- Đầu vào Ridge: độ dài câu hỏi, độ hiếm từ và điểm BM25.
- Giá trị cần học: điểm chất lượng hybrid trừ điểm chất lượng BM25, đo bằng nDCG@10.

### Lời trình bày

Phần cần huấn luyện là gate dùng Ridge, một mô hình hồi quy tuyến tính có giám sát. Đầu vào là các đặc trưng đã có trước dense. Giá trị cần học là mức cải thiện chất lượng khi chuyển từ BM25 sang một phương pháp hybrid đã cố định.

Để tạo dữ liệu học, chạy BM25 và hybrid trên các câu hỏi thuộc tập train, chấm bằng qrels rồi lấy điểm hybrid trừ điểm BM25. Ridge học các trọng số để dự đoán mức chênh lệch đó. Khi gặp câu hỏi mới, nó chỉ dùng đặc trưng và so dự đoán với ngưỡng, không đọc nhãn đánh giá. MiniLM được dùng để tạo vector với trọng số có sẵn; theo model card, nhà phát triển đã huấn luyện phiên bản được chọn trên MS MARCO.

## Slide 8. Cách chia dữ liệu để học và kiểm tra

### Nội dung trên slide

- Chia 1.948 câu hỏi dùng thử, giữ nguyên toàn bộ kho 79.558 câu hỏi để tìm kiếm.
- Mỗi lượt: khoảng 60% train, 20% validation, 20% test.
- Thực hiện năm lượt chia, mỗi câu hỏi làm test một lượt.
- Chỉ học trên train, chọn ngưỡng trên validation và đánh giá cuối trên test.

### Lời trình bày

Kho câu hỏi để tìm kiếm và tập câu hỏi dùng thử có vai trò khác nhau. Toàn bộ 79.558 câu hỏi trong kho được giữ lại để xây dựng chỉ mục. Phần chia train, validation và test áp dụng cho 1.948 câu hỏi đầu vào cùng các nhãn tương ứng.

Theo thiết kế, mỗi lượt dùng khoảng 60 phần trăm để học gate, 20 phần trăm để chọn phương pháp kết hợp và ngưỡng, 20 phần trăm để kiểm tra cuối. Có năm lượt chia để mỗi câu hỏi làm test đúng một lượt. Các lựa chọn được khóa trước khi xem điểm test. Đây là quy trình đánh giá có giám sát do đề tài thiết kế trên dữ liệu BEIR, cần trình bày tách biệt với đánh giá BEIR zero-shot.

## Slide 9. Đánh giá giải pháp bằng cách nào?

### Nội dung trên slide

- Chất lượng: nDCG@10 để đánh giá thứ tự 10 kết quả đầu, kèm MRR@10 và Recall@100.
- Hiệu năng: thời gian trung bình, p95, thời gian CPU và số lần chạy dense.
- So sánh BM25, dense, hybrid luôn chạy và PE-GH trên cùng dữ liệu, cùng máy.
- So với chọn ngẫu nhiên hoặc theo chênh lệch điểm BM25 để kiểm tra giá trị của gate.

### Lời trình bày

Giải pháp cần được đánh giá cả chất lượng và chi phí. Qrels cho biết những câu hỏi nào trong kho được gán liên quan với đầu vào. nDCG@10 đo việc đưa các kết quả đó lên vị trí cao trong mười kết quả đầu. Recall@100 kiểm tra mức độ tìm được các kết quả liên quan trong danh sách dài hơn.

Về hiệu năng, đo thời gian trung bình, p95, thời gian CPU và số lần gọi dense trên cùng máy. Đường đo phải mã hóa câu hỏi thật khi cần, không đọc lại vector câu hỏi đã lưu. So với hybrid luôn chạy để xem việc bỏ qua dense có lợi không, và so với các cách chọn rẻ hơn để xem Ridge có chọn tốt hơn không. Mục tiêu 60% dense và biên chất lượng 0,01 là tiêu chí cần kiểm chứng, không phải kết luận sẵn.

## Slide 10. Giá trị và phạm vi của đề tài

### Nội dung trên slide

- Sản phẩm hướng tới: công cụ tìm câu hỏi tương đồng trong kho cố định.
- Trọng tâm: dùng dự đoán lợi ích để lựa chọn khi nào chạy thêm ngữ nghĩa.
- Bối cảnh: tra cứu câu hỏi kỹ thuật trên CPU.
- Phạm vi đánh giá: hai miền dữ liệu tiếng Anh, cần thêm thực nghiệm để kết luận rộng hơn.

### Lời trình bày

Đề tài hướng tới một công cụ tra cứu câu hỏi kỹ thuật tương đồng. Giá trị cần kiểm chứng là việc dự đoán lợi ích có giúp dành chi phí dense cho những câu hỏi cần nó hơn, qua đó giảm thời gian xử lý mà vẫn giữ chất lượng tìm kiếm trong biên cho phép.

Ý tưởng định tuyến truy xuất đã có trong các nghiên cứu trước. Trọng tâm của PE-GH là cách học lợi ích xếp hạng và kiểm chứng trong miền kỹ thuật trên CPU, với đối chứng và điều kiện đo rõ ràng. Kết luận gắn với hai miền dữ liệu tiếng Anh đã chọn. Cần thử trên dữ liệu khác trước khi mở rộng sang tiếng Việt, nhiều lĩnh vực hoặc nhật ký lỗi dài.

## Câu hỏi thầy có thể đặt ra

### Đề tài tìm kiếm điều gì và bằng công cụ gì?

Đề tài đề xuất nguyên mẫu công cụ PE-GH để tìm những câu hỏi tiếng Anh tương đồng về phần mềm và Unix/Linux trong kho CQADupStack đã lưu. Người dùng nhập một câu hỏi, công cụ trả danh sách câu hỏi liên quan đã xếp hạng.

### Đầu ra có phải câu trả lời do AI viết không?

Đầu ra được đánh giá là danh sách câu hỏi trong kho. Benchmark dùng nội dung câu hỏi và nhãn quan hệ giữa các câu hỏi để chấm khả năng tìm kiếm. Việc tạo câu trả lời hoặc tìm bản vá nằm ngoài phạm vi đánh giá này.

### 79.558 và 1.948 khác nhau thế nào?

79.558 là số câu hỏi trong kho để hệ thống tìm kiếm. 1.948 là số câu hỏi dùng làm đầu vào thí nghiệm. Qrels là nhãn nối từng đầu vào với các câu hỏi liên quan trong kho. Tài liệu dùng để tìm và câu hỏi dùng để thử có vai trò khác nhau.

### Dữ liệu có đặc điểm gì đáng chú ý?

Dữ liệu bằng tiếng Anh, gồm hai miền programmers và unix. Câu hỏi dùng thử ngắn, trung bình khoảng 50–55 ký tự, và phù hợp với tìm câu hỏi trùng/tương đồng. programmers có cả câu hỏi khái niệm và quy trình phần mềm. Dữ liệu không đủ để đại diện cho toàn bộ tác vụ chẩn đoán lỗi hoặc tìm bản vá.

### Tại sao không chỉ dùng BM25 hoặc luôn dùng dense?

BM25 và dense có thể bổ sung cho nhau. BM25 khai thác khớp từ khóa, còn dense thêm tín hiệu về ý nghĩa. Luôn dùng dense phải trả chi phí mã hóa và tìm vector cho mọi câu hỏi. Đề tài kiểm tra xem có thể chọn lọc các lần chạy thêm mà vẫn giữ chất lượng hay không. Nếu đối chứng BM25 đã đủ tốt và rẻ hơn, kết quả đó cũng cần được thừa nhận.

### Nhóm huấn luyện cái gì, bằng dữ liệu nào?

Huấn luyện Ridge cho gate trên phần train của các câu hỏi programmers và unix. Ridge học từ đặc trưng câu hỏi và điểm BM25, với mục tiêu là nDCG@10(hybrid) − nDCG@10(BM25), tính bằng qrels train. MiniLM dùng trọng số có sẵn; theo model card, phiên bản msmarco-MiniLM-L6-cos-v5 đã được nhà phát triển huấn luyện trên MS MARCO.

### Vì sao dùng Ridge?

Ridge là mô hình hồi quy tuyến tính có điều chuẩn, phù hợp với mục tiêu dự đoán một giá trị lợi ích liên tục và có chi phí tính toán nhỏ. Đây là lựa chọn thiết kế để hạn chế chi phí của gate. Hiệu quả cần so với heuristic, random và router nhẹ khác; tính đơn giản chưa bảo đảm dự đoán tốt.

### Làm sao biết khi nào BM25 đã đủ?

Gate chỉ ước lượng lợi ích của việc chuyển từ BM25 sang hybrid từ các đặc trưng có sẵn. Nó không biết chắc câu hỏi nào đã đủ tốt. Vì vậy phải chấm bằng dữ liệu giữ riêng, đo phần chất lượng mất do bỏ qua dense và kiểm tra hiệu quả so với đối chứng.

### Có bị học và kiểm tra trên cùng dữ liệu không?

Quy trình dùng các phần train/validation/test tách theo nhóm câu hỏi. Chỉ train được dùng để học trọng số; validation để chọn cấu hình và ngưỡng; test để đánh giá sau khi khóa lựa chọn. Kho tài liệu được giữ đầy đủ để tìm kiếm, còn nhãn và các thành phần được học phải tuân thủ split. Mỗi câu hỏi chỉ góp điểm test ở lượt chưa dùng nó để học hoặc chọn ngưỡng.

### Làm thế nào chứng minh giải pháp có ích?

So chất lượng và hiệu năng của BM25, dense, hybrid luôn chạy và PE-GH trên cùng câu hỏi, cùng máy. Đánh giá thêm gate ngẫu nhiên và gate theo chênh lệch điểm BM25 ở ngân sách tương đương. Giải pháp có giá trị khi chi phí thực tế giảm và chất lượng đáp ứng biên đã đăng ký. Nếu chưa đạt hoặc bằng chứng chưa đủ, cần trình bày đúng kết quả đó.

### Điểm đóng góp của đề tài là gì?

Trọng tâm là kiểm tra nhãn lợi ích xếp hạng, giá trị của đặc trưng và hiệu quả định tuyến trong miền câu hỏi kỹ thuật trên CPU. Định tuyến truy xuất và gate nhẹ đã có trong nghiên cứu trước. PE-GH cần so với các đối chứng gần và tách ảnh hưởng từng thành phần để xác định đóng góp.

### Có hỗ trợ tiếng Việt, Google Search hoặc tìm trên Internet không?

Phạm vi đánh giá hiện tại dùng câu hỏi tiếng Anh trong kho CQADupStack cố định. Để hỗ trợ tiếng Việt hoặc tìm kiếm trực tiếp trên Internet cần bổ sung nguồn dữ liệu, thành phần thu thập và quy trình đánh giá phù hợp. Các ví dụ tiếng Việt trong lời giải thích chỉ giúp người nghe hiểu bài toán.

## Nguồn đối chiếu

- [Kế hoạch nghiên cứu PE-GH, đặc biệt mục 3–4 và 7–13](../PE_GH_KE_HOACH_HOAN_CHINH_3_NGUOI_V2.md)
- [Biên bản kiểm tra nguồn và dữ liệu](../research_evidence/source_audit.json)
- [Bộ dữ liệu CQADupStack](https://huggingface.co/datasets/BeIR/cqadupstack)
- [Model card msmarco-MiniLM-L6-cos-v5](https://huggingface.co/sentence-transformers/msmarco-MiniLM-L6-cos-v5)
- [Nghiên cứu lựa chọn chiến lược truy xuất, Arabzadeh và cộng sự](https://arxiv.org/abs/2109.10739)
- [LiteGator](https://www.atlantis-press.com/proceedings/icast-es-25/126020510)

