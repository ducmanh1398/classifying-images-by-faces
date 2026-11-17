# Quyết định

## 2026-11-17

- **Cài Python.** Máy chưa có Python; cài Python 3.11.9 bằng `winget install Python.Python.3.11 --scope user`. Môi trường ảo dự án ở `.venv`.
- **Bảng `exports` thêm `size`, `mtime_ns`.** Đặc tả mục 7 yêu cầu dùng lại SHA-256 khi kích thước và mtime khớp, nhưng mục 4 không có cột này. Thêm vào schema v1.
- **`label_id = 0` trong `exports`** dành cho thư mục `_Khac` (không có nhãn), vì khóa chính không nhận NULL.
- **Bảng `meta`** (khóa-giá trị) lưu `scan_id`. Một file là "còn sống" khi `last_seen_scan = scan_id` hiện tại; `has_live_file` của ảnh dựa trên đó.
- **`files.mtime_ns`** thay cho `mtime` (số nguyên nano giây, so sánh chính xác).
- **`plan_export()`** trả về `Plan(actions, skipped)` thay vì chỉ danh sách, để bản xem trước đếm được file trùng bị bỏ qua. Tham số `labels` bỏ đi vì nhãn hiệu lực đã nằm trong `FaceInfo`. Thêm tham số tùy chọn `existing_names` để đặt tên file đích không phân biệt hoa thường.
- **Trùng `folder_name`** giữa hai nhãn khác nhau (ví dụ `a:b` và `a/b`) được xử lý bằng hậu tố ` (2)`, ` (3)`... vì cột `folder_name` là duy nhất.
- **Khóa tiến trình** dùng khóa file của hệ điều hành (`msvcrt.locking`), tự nhả khi tiến trình chết; không dùng `os.kill(pid, 0)` vì trên Windows nó có thể kết thúc tiến trình.
- **`--prune`** và các tùy chọn của giai đoạn 5 chưa có; `export` hiện chỉ có `--dry-run`.
- Thiếu `ml`/`ui` trong phụ thuộc mặc định: `insightface`, `onnxruntime`, `scikit-learn` nằm nhóm `ml`; `fastapi`, `uvicorn` nằm nhóm `ui`. Sẽ gộp lại khi đóng gói (giai đoạn 6).

## 2026-11-17 — 3.1 kiểm chứng cài InsightFace

- **Quyết định: dùng gói `insightface`**, không cần nạp ONNX trực tiếp.
- Môi trường: Windows 11, Python 3.11.9, venv mới. Lệnh đã chạy được, không cần Microsoft C++ Build Tools (có sẵn wheel):
  `pip install insightface onnxruntime scikit-learn` → insightface 2.1, onnxruntime 1.32.0, scikit-learn 1.9.1, opencv-python 5.0.0.93.
- `FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"], allowed_modules=["detection","recognition"])` rồi `prepare(ctx_id=-1, det_size=(960,960))`. Model tự tải về `~/.insightface/models` lần đầu (~280 MB, mất ~45 giây).
- Thử trên ảnh mẫu `t1` của insightface (1280x886): tìm 6 mặt, 0,89 giây/ảnh trên CPU (ảnh đầu, đã gồm khởi động), embedding 512 chiều, độ dài L2 = 1,0.
- Chỉ nạp `detection` + `recognition` để bỏ qua các model landmark/giới tính-tuổi không cần, chạy nhanh hơn.
- `insightface.get()` nhận ảnh BGR (ndarray); `detect.py` phải đổi từ RGB của Pillow sang BGR.
- Cảnh báo `FutureWarning` từ scikit-image (`estimate` deprecated) vô hại; có thể lọc bằng `warnings.filterwarnings`.
- Tốc độ thật trên 100 ảnh gốc sẽ đo ở task 3.8.

## 2026-11-17 — giai đoạn 3 (3.2–3.7)

- **Bỏ scikit-learn, tự viết DBSCAN bằng numpy** (`cluster.dbscan_cosine`). Lý do: trên máy này chính sách Application Control của Windows chặn `sklearn\svm\_libsvm_sparse` ("DLL load failed ... blocked"), nên `from sklearn.cluster import DBSCAN` lỗi. Không vượt chính sách; đặc tả mục 11 cho phép đổi thư viện. Cùng ngữ nghĩa DBSCAN (eps tính cả bằng, `min_samples` tính cả điểm đó), tính ma trận khoảng cách theo khối 2048 hàng. `scikit-learn` bỏ khỏi nhóm `ml` trong `pyproject.toml`. (scipy, onnxruntime, insightface nạp bình thường.)
- **`detect` chỉ xử lý ảnh còn file sống** và đọc theo đường dẫn sống nhỏ nhất; ảnh `error` được thử lại ở lần sau. Nếu không, ảnh cũ đã bị thay nội dung sẽ bị đọc nhầm file mới.
- **`cluster` hiện chỉ chạy lần đầu**: nếu đã có nhãn hoặc mặt/cụm bị bỏ qua thì từ chối, vì gán tăng dần thuộc 5.3.
- Thử thật qua CLI (`scan`, `detect`, `cluster`, `debug contact-sheet`) trên ảnh mẫu insightface thu nhỏ 4 cỡ: 24 mặt, 6 cụm × 4 mặt, 0 mặt lẻ, 0 lỗi.
