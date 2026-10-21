# Kiểm chứng base chung

Ngày 21/10/2026 (Asia/Bangkok), nhánh `codex/shared-base`, kế thừa B tại `9556f0d`.
Chi tiết hashes/raw paths: [SHARED_BASE_VALIDATION.json](SHARED_BASE_VALIDATION.json).

| Kiểm tra thực chạy | Kết quả |
|---|---|
| Toàn bộ `tests/shared tests/b` | **70 passed**, gồm pinned CPU model thật |
| Fixture và SHA256 | 20 documents, 6 queries, hai domain; passed |
| Shared vs B-v1 corpus `(doc_id,text)` | Khớp toàn bộ **79.558 documents** |
| Shared vs B-v1 queries | Khớp toàn bộ **1.948 queries** |
| Codec mới đọc/ghi output B-v1 | 1.948 records giữ nguyên wire content |
| B exporter dùng loader/codec mới | 3 rankings model thật, hợp schema |
| B online CLI dùng loader mới | 3 requests + 50 warmup; một encode/request; ranking khớp offline |
| B frozen encoder/config/corpus/index | 4/4 file bytes giữ nguyên so với baseline |
| Wheel | Build thành công, chứa schema/registry; isolated import chỉ với standard library passed |
| Ruff, lockfile, installed dependencies | Passed |

Fixture/smoke dùng cho correctness và integration, không phải phép so chất lượng
hoặc latency nghiên cứu. Index/model lớn và raw smoke logs vẫn ở cache ngoài Git.
Không cần rebuild các full indices B để dùng contracts này. Các benchmark v1 cũ
giữ source snapshots gốc; run mới ghi snapshot có contracts/shared loader mới.

Schema kiểm cấu trúc JSON; codec/Ranking validator kiểm thêm unique IDs, thứ tự,
namespace, self-hit, score hữu hạn và provenance. Mọi phương pháp A/C phải qua cùng
boundary, không tạo local response schema.

CI đã cập nhật để chạy shared+B tests trên Windows/Ubuntu theo workflow. Phiên
này chạy local Windows; chưa có hosted GitHub CI run.
