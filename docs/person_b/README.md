# PE-GH — phần B

Nhánh triển khai: `codex/b-dense-profiling`.

Phần này cung cấp dense encoder CPU, FAISS exact search, resumable indexing,
quality-run export và online profiling. Các module dữ liệu/BM25/evaluator (A)
và fusion/gate/app (C) không được hiện thực thay trong nhánh này.

Kho mã ban đầu chưa có contracts. `contracts/types.py` là bootstrap theo đúng
interface của kế hoạch V2, để A/C có thể tích hợp; người A giữ ownership về sau.

Hướng dẫn chạy và kết quả kiểm tra sẽ được cập nhật trong quá trình triển khai.

