# PE-GH

Reproducible implementation for a three-person pre-encoding gated hybrid retrieval study.

- [Sửa gate inference và kết quả đối chiếu 26/10/2026](docs/refinement/inference-2026-10-26/README.md)
- [Chẩn đoán gate và thử nghiệm threshold đã loại](docs/GATE_REFINEMENT_V2.md)
- [Kết quả tích hợp đã kiểm chứng 26/10/2026](docs/integration/2026-10-26/README.md)
- [Chạy lại toàn bộ pipeline A/B/C](docs/INTEGRATION_V2.md)
- [Kế hoạch nhóm](PE_GH_KE_HOACH_HOAN_CHINH_3_NGUOI_V2.md)
- [Phần A: dữ liệu, BM25 và đánh giá](docs/person_a/README.md)
- [Trạng thái phần A](docs/person_a/IMPLEMENTATION_STATUS.md)
- [Phần B: dense encoder, FAISS và profiling](docs/person_b/README.md)
- [Handoff B cho A/C](docs/person_b/HANDOFF_A_C.md)
- [Phần C: fusion, gate và app](docs/person_c/README.md)
- [Shared contracts](docs/SHARED_BASE.md)
- [Experimental setup](paper/04_experimental_setup.md)
- [Quality results](paper/05a_quality_results.md)
- [Efficiency results](paper/05b_efficiency_results.md)

Lượt tích hợp trước sửa inference trên nhánh `thanh` đã chạy đủ 29.220 request online trên 1.948 query,
10 tổ hợp fold/domain và ba phương pháp. PE-GH giảm mean latency 34,76% so H*, dùng dense
57,75% và đạt biên non-inferiority đã đăng ký. Đây là kết quả gộp trên hai domain;
programmers chỉ giảm mean 18,15%, p95 gộp hơi cao hơn S*. Xem báo cáo để biết đầy đủ
khoảng tin cậy, đối chứng và giới hạn; chưa có kết luận thắng mọi phương pháp SOTA.

Lượt sửa inference sau đó cũng đo đủ 29.220 request: giữ nguyên mọi ranking và chất lượng,
mean quan sát giảm thêm 2,09% so PE-GH sklearn. CI theo process repetition còn chứa 0,
nên chưa bảo đảm mức giảm request này ổn định. Thử threshold riêng theo domain làm giảm
chất lượng và không được đưa vào bản chính; xem báo cáo refinement ở đầu trang.

A/B/C dùng chung canonical IDs, text policy, ranking-v1 schema và lockfile. A phụ trách
dữ liệu/BM25/evaluation, B phụ trách dense/FAISS/profiling, C phụ trách fusion/gate/app.
Các chỉ mục, raw timing và model lớn ở ngoài Git; snapshot kết quả mới và hướng dẫn
tái lập nằm trong các liên kết đầu trang. Kết quả lịch sử B/C được giữ riêng.
