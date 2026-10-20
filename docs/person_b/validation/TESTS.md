# Xác minh local

Ngày 20/10/2026, Windows 11, Python 3.12.14, venv B riêng. Source code tại commit
`6d25720` cùng các artifact index đã đóng băng; những thay đổi sau đó ở tài liệu
không thay executable source của phép đo.

| Kiểm tra | Kết quả thực chạy |
|---|---|
| `python -m pytest tests/b -q` | 37 passed, 38,18 giây |
| Ruff check | passed |
| Ruff format check | 32 files already formatted |
| `uv lock --check` | resolved/consistent, 56 lock packages |
| `uv pip check --python <B-venv-python>` | 52 installed packages, compatible |
| Pipeline bytes so với Git blobs | 4/4 file giống, không CRLF |
| Saved programmers index verification | passed, mọi 32.176 vector |
| Saved unix index verification | passed, mọi 47.382 vector |

Model test dùng pinned MSMARCO MiniLM thật, không dùng random embedding. FAISS
fixture tests so với dot product NumPy; kiểm self-filter, ties, k>N, corruption,
resume không encode lại, input/config/source drift, save/load. Profiling tests dùng
process riêng và kiểm quota tài nguyên/counters/coverage/STOP/failure/report.
Gated fixture chứng minh request skip thực sự có encoder/vector calls bằng 0;
đây không phải một gate nghiên cứu hoặc số latency dùng trong bài báo.

Không có hosted CI run trong phiên này vì repository chưa push lên remote. Workflow
Ubuntu/Windows đã được khai báo; kết quả local không được gọi là GitHub CI passed.

Sau khi timing hoàn tất, đã thêm script thu/audit artifact và chạy thành công trên
toàn bộ 9.996 requests +1.948 offline rankings. Ruff check/format cuối passed với
33 files; không đổi embedding/backend hoặc worker của benchmark đã ghi.

Đã so SHA256 của cả 44 copied evidence files với Git blobs sau commit: khớp tất
cả. `.gitattributes` giữ nguyên bytes archive để report/CSV không bị đổi newline
khi checkout ở máy khác.
