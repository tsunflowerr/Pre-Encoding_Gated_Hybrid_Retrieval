# PE-GH: tích hợp và tái lập phiên bản sửa lỗi

Ngày cập nhật: 26/10/2026. Lượt end-to-end từ commit `1b4c83e` đã hoàn tất: 29.220 ranking online khớp OOF, mean giảm 34,76% so H*, dense-call ratio 57,75%, quality non-inferiority đạt macro và từng domain. [Báo cáo và receipt đầy đủ](integration/2026-10-26/README.md) ghi cả hạn chế: programmers giảm mean 18,15% và p95 gộp hơi cao hơn S*.

## Mục tiêu và giới hạn kết luận

Giữ nguyên corpus, năm outer fold, model/revision, vector float32, công thức fusion và protocol chọn gate bằng train/validation. Không tăng biên non-inferiority sau khi xem test. Mục tiêu nghiên cứu vẫn là nDCG@10 giảm ít hơn 0,01 theo cận dưới một phía 95%, dense-call ratio không quá 60%, và mean latency thấp hơn H* ít nhất 20% trên cùng máy, cùng giới hạn tài nguyên. Báo cáo riêng từng domain, p95, CPU, RSS và các đối chứng đã đăng ký. Kết quả trên hai domain không chứng minh ưu thế trên mọi dataset hay mọi phương pháp SOTA.

## Những điểm đã thay đổi

1. A kiểm tra đầy đủ tập query chuẩn trước khi ghép OOF; phát hiện thiếu query dù split bị sửa nhất quán, query trùng bucket, group không khớp, retriever hash sai và sidecar sai. Tạo utility yêu cầu cùng split/fold và đủ query. Provider parity kiểm tra cả score và thứ tự. Manifest SQLite phải tự khớp checksum.
2. Dataset identity mới loại bỏ đường dẫn máy khỏi phần định danh nội dung. Manifest/split đã đóng băng vẫn được giữ nguyên byte khi nguồn dữ liệu không đổi; không tự ghi đè hash cũ để làm kết quả có vẻ hợp lệ.
3. Sparse có backend `numpy_bm25_postings_v1`: biên dịch toàn bộ postings tĩnh từ SQLite, nạp trước timer, chấm điểm lại cho từng request. Đây không phải cache ranking theo query. Giữ thứ tự phép tính float64, top-k và tie-break theo document ID. Logical retriever hash không đổi; execution hash, phiên bản NumPy, SHA mã biên dịch và SHA các mảng được ghi riêng. Cả baseline và PE-GH dùng cùng backend.
4. H* có hai cách thực thi: tuần tự với dense dùng bốn thread, hoặc sparse chạy song song với dense dùng ba thread trong cùng affinity bốn logical CPU. Pilot chỉ dùng validation để chọn cách nhanh hơn có ranking khớp cache. Cấu hình được đóng băng trước khi chạy test.
5. Online chính chỉ đo tổng thời gian request, không đặt timer chi tiết ở từng stage. Một sample riêng có stage timing để chẩn đoán. Với baseline song song, thời gian các nhánh chồng lên nhau nên không cộng stage wall time để suy ra tổng latency.
6. CI chạy cả tests A/B/C và shared. Driver tái lập có checkpoint, checksum và trạng thái failed/paused. Kết quả bị gián đoạn được giữ lại; có thể lưu trữ rồi chạy lại toàn bộ fold bằng `--restart-incomplete`, không trộn worker dở với lượt hoàn chỉnh.

## Cách chạy

Chạy trong checkout sạch của đúng commit, Python từ môi trường `uv sync --locked --extra dev`. Dữ liệu lớn, model và raw timing để ngoài Git; có thể dùng junction hoặc thư mục ignored. Không thay mã nguồn sau khi driver bắt đầu: source snapshot bao gồm `src`, contracts, configs và script A/B/C/shared. Nếu thay mã, dùng thư mục kết quả mới.

```powershell
python scripts_shared/reproduce.py --stage all `
  --dense-root C:/path/to/verified-dense-indices `
  --cache-folder C:/path/to/model-cache `
  --runtime configs/runtime/cpu4.yaml `
  --stop-file C:/path/to/STOP_INTEGRATION
```

`--dense-root` chứa `programmers/manifest.json,index.faiss,doc_ids.jsonl` và tương tự cho unix, được xây bằng model `sentence-transformers/msmarco-MiniLM-L6-cos-v5`, revision `14ca9be4bbcf1402eac0f43a2e2ccb6e0f994ba3`. Dense manifest và toàn bộ vector được kiểm tra trước khi dùng. Bốn file triển khai dense đã đóng băng không được sửa trong đợt này.

Có thể thêm `--source-cache` trỏ đến thư mục chứa `<domain>/corpus.jsonl,queries.jsonl,corpus.parquet,queries.parquet`; `--qrels-root` chứa `<domain>/qrels.tsv`; `--sparse-root` chứa scalar SQLite index. Mỗi bản sao phải khớp SHA nguồn đã đăng ký. Thiếu cache thì bước chuẩn bị tải hoặc xây theo script A. Cache model có sẵn có thể chạy với `HF_HUB_OFFLINE=1`.

Các stage có thể chạy lần lượt với cùng tham số:

| Stage | Công việc | Kết quả chính |
|---|---|---|
| prepare | Xác thực nguồn, split, sparse, vector; sinh ranking quality mới | `results/prepare`, `results/quality` |
| train | Fusion, feature, utility, gate, threshold; pilot execution validation; freeze | `results/frozen/c6_manifest.json` |
| quality | OOF cho bốn phương pháp chính và 14 đối chứng, bootstrap 10.000 mẫu, random30/oracle | `results/oof/c6_final`, `results/oof/c6_controls` |
| online | Sample chi tiết riêng; 10 fold × ba method × năm lần lặp | `results/benchmark/c6_full` |
| report | Kiểm tra ranking/count/provenance; bootstrap latency theo query ghép cặp | `results/reports/integration_release.json` |

Mỗi test query chỉ thuộc một outer fold. Tổng lượt đo online chính là 1.948 × 3 × 5 = 29.220 request. Query warmup lấy từ validation, tách test. Pilot dùng validation với warmup từ train. Phần chọn execution không dùng test qrels.

### Output A khi chạy quality

Driver hiện materialize BM25 vào `results/oof_runs/release_bm25/<domain>/`, tách khỏi
`results/oof_runs/bm25/` của các lượt A trước. Registry cuối vẫn dùng method `bm25`.
CLI dùng `--reuse-identical`: run và sidecar cũ chỉ được tái sử dụng khi đúng byte và
toàn bộ metadata yêu cầu. Cả năm fold được preflight trước khi ghi. Nếu có output khác
hoặc sidecar thiếu, dùng results/checkout mới hoặc archive thủ công sau khi kiểm đường dẫn;
không ghi đè hoặc sửa checksum để vượt kiểm tra.

Lượt 30/10 đã có freeze/report riêng trong `docs/person_a/validation/2026-10-30/`.
Thay đổi script A sau lượt đó làm source snapshot mới; freeze/receipt 30/10 tiếp tục là
bằng chứng của source cũ. Không dùng `reproduce.py` để resume freeze cũ sau khi sửa code.
`scripts_a/finalize_report.py` phân tích lại artifact đã lưu và kiểm provenance gốc mà
không đổi source identity của thí nghiệm.

Runtime `windows-physical4-local.yaml` chỉ dùng cho máy đã xác minh cặp SMT tương ứng. Trên máy khác dùng `cpu4.yaml` hoặc cấu hình affinity đã kiểm tra; không sao chép mù CPU ID.

## Tiếp tục sau gián đoạn

Tạo stop-file để runner dừng ở checkpoint an toàn. Xóa stop-file khi được phép tiếp tục rồi chạy lại đúng stage, đúng commit và tham số. Nếu fold chưa complete, thêm `--restart-incomplete`: driver xác minh đường dẫn nằm trong thư mục kết quả, đổi tên thư mục cũ thành `.interrupted.<timestamp>` rồi đo lại fold. Các fold complete chỉ được tái sử dụng khi source, registry, query, cấu hình và receipt khớp.

`results/pipeline_status.json` cho biết phase hiện tại. `results/reproduction_identity.json` ràng buộc source/runtime/dense manifest. Không sửa receipt để vượt kiểm tra. Nếu model hoặc code thay đổi, tạo lượt chạy mới và freeze mới.

## Cách đọc báo cáo

- Quality: nDCG@10, MRR, Recall và bootstrap ghép cặp theo query/domain; giữ cả kết quả gate tổng quát, random theo budget, margin và oracle chẩn đoán. Oracle không phải baseline triển khai được.
- Latency: raw request được gộp để tính mean/p95; không lấy trung bình các p95 fold. Bootstrap dùng trung bình năm lần lặp của từng query, giữ cặp các method và phân tầng theo domain. Báo cáo cận tin cậy của phần trăm giảm mean latency.
- Công bằng: một máy, một resource profile, cùng sparse execution identity, package/runtime, query và warmup policy. Static hybrid có thể dùng profile song song được chọn trước bằng validation; PE-GH chịu chi phí sparse, feature và gate thực tế.
- Kết quả cũ của C trên i3 là bản ghi lịch sử. Không dùng chênh lệch giữa máy i3 cũ và máy mới làm speedup của phương pháp. Evidence mới lưu thư mục mới; không ghi đè snapshot B/C đã công bố.

Các kiểm tra chức năng và parity là điều kiện cần. Chỉ receipt của lượt online hoàn chỉnh mới là bằng chứng về hiệu năng; nếu chưa đạt 20% hoặc một domain không đạt non-inferiority, báo cáo phải ghi rõ chưa đạt.
