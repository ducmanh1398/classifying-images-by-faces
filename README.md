# facesort

Phân loại ảnh cưới theo khuôn mặt. Chạy hoàn toàn trên máy Windows của bạn: quét một folder ảnh, gom các khuôn mặt giống nhau thành cụm, gắn tên cho từng cụm, rồi copy ảnh vào các thư mục theo tên để gửi cho họ hàng.

> **Trạng thái hiện tại (phiên bản phát triển):** đã có quét ảnh, phát hiện mặt, gom cụm và xuất thư mục. **Giao diện web gắn tên (giai đoạn 4), xuất từ giao diện, `run.bat` và gom cụm tăng dần chưa có.** Vì vậy hiện chưa gắn nhãn được bằng giao diện; xem mục [Trạng thái triển khai](#trạng-thái-triển-khai). Kế hoạch đầy đủ nằm trong đặc tả và `DECISIONS.md`.

## Yêu cầu

- Windows 10 hoặc 11, 64-bit, RAM từ 8 GB. Không cần GPU.
- Python 3.11 (64-bit).
- Dưới khoảng 10.000 ảnh. Hỗ trợ JPG, JPEG, PNG, HEIC, HEIF.
- Nếu ảnh nằm trên Google Drive: dùng Google Drive for Desktop và bật **Available offline** cho folder ảnh trước khi chạy, để file đã nằm sẵn trên máy.

## Cài đặt

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[ml]"
```

Lần chạy `detect` đầu tiên sẽ tải model `buffalo_l` (khoảng 280 MB) về `~/.insightface/models`. Đây là lần gọi mạng duy nhất; sau đó công cụ chạy offline. Model huấn luyện sẵn của InsightFace chỉ cho phép dùng phi thương mại.

## Sử dụng

Tạo dự án một lần. Folder đầu ra **không** được nằm trong folder gốc và ngược lại.

```bash
facesort init --input "G:\My Drive\Anh cuoi" --output "D:\Anh da phan loai"
```

Chạy từng bước:

```bash
facesort scan                    # quét folder gốc, tính SHA-256, phát hiện file trùng
facesort detect                  # phát hiện mặt và tạo embedding (chậm nhất)
facesort cluster                 # gom cụm khuôn mặt
facesort debug contact-sheet     # xuất trang HTML để xem các cụm
facesort status                  # số ảnh, số mặt, số cụm, ảnh lỗi
facesort export --dry-run        # xem trước kết quả xuất, không tạo file
facesort export                  # copy ảnh vào thư mục theo nhãn
```

Mọi lệnh nhận `--project <tên>`; nếu chỉ có một dự án thì tự chọn. `facesort --help` liệt kê các lệnh.

### Xem các cụm

`facesort debug contact-sheet` tạo `contact_sheet.html` trong thư mục dự án. Mở file đó bằng trình duyệt để xem mỗi cụm một hàng ảnh mặt, kèm nhóm mặt lẻ (không thuộc cụm nào).

### Quy tắc xuất

- Mỗi ảnh được copy **một lần** vào thư mục của **mỗi nhãn** có trong ảnh. Ảnh có mặt "Ông A" và "Bà B" xuất hiện ở cả hai thư mục, giống hệt bản gốc từng byte.
- Nhiều khuôn mặt hoặc nhiều cụm cùng một nhãn dùng chung một thư mục; ảnh không bị lặp.
- Tên nhãn so khớp không phân biệt hoa thường và dạng Unicode: "Ông A" và "ông a" là một nhãn.
- File giống hệt nhau (cùng SHA-256) chỉ xuất một bản. Chạy `export` lại không copy lại file đã có, kể cả khi sổ ghi của công cụ bị mất.
- Hai ảnh khác nội dung trùng tên được phân biệt bằng hậu tố: `IMG_0012__a1b2c3d4.jpg`.
- Ảnh không có nhãn nào (mặt chưa gắn nhãn, bị bỏ qua, quá nhỏ, hoặc không có mặt) vào thư mục `_Khac`.
- Folder gốc chỉ được đọc, không bao giờ bị sửa.
- Sau khi xuất có `export_report.csv` trong folder đầu ra: thư mục, tên file đích, đường dẫn gốc, SHA-256, trạng thái (`copied`, `skipped_duplicate`, `error`).

Ảnh nhân bản theo số nhãn, nên thư mục đầu ra có thể lớn hơn folder gốc nhiều lần. Hãy xem `--dry-run` để biết tổng dung lượng trước khi xuất.

## Cấu hình

`config.toml` nằm trong thư mục dự án, `%LOCALAPPDATA%\facesort\<tên dự án>`. Cùng thư mục đó có `facesort.db`, ảnh mặt đã cắt và log. Dữ liệu dự án cố ý nằm ngoài Drive.

| Khóa | Mặc định | Ý nghĩa |
| --- | --- | --- |
| `input_dir`, `output_dir` | bắt buộc | Folder ảnh gốc và folder đầu ra |
| `extensions` | `jpg, jpeg, png, heic, heif` | Đuôi file được quét |
| `det_size` | 960 | Cỡ ảnh đưa vào bộ phát hiện (bội số của 32). Lớn hơn bắt được mặt nhỏ hơn nhưng chậm hơn |
| `min_det_score` | 0.5 | Độ tin cậy tối thiểu của một khuôn mặt |
| `min_face_px` | 60 | Cạnh ngắn tối thiểu của khung mặt |
| `min_face_ratio` | 0.25 | Cạnh mặt chia cho mặt lớn nhất trong ảnh; lọc người đi ngang ở hậu cảnh |
| `cluster_eps` | 0.5 | Khoảng cách cosine tối đa giữa hai mặt cùng cụm |
| `cluster_min_samples` | 3 | Số mặt tối thiểu để thành một cụm |
| `assign_threshold` | 0.45 | Ngưỡng gán mặt mới vào nhãn đã có (dùng ở giai đoạn 5) |
| `export_unlabeled` | `true` | Bật thư mục `_Khac` |
| `unlabeled_folder` | `_Khac` | Tên thư mục cho ảnh không có nhãn |

Các ngưỡng là giá trị khởi điểm, **chưa được tinh chỉnh trên ảnh cưới thật** (task 3.8). Thiết kế ưu tiên tách một người thành nhiều cụm hơn là gộp hai người vào một cụm; nếu gặp cụm gộp nhầm, giảm `cluster_eps`.

## Trạng thái triển khai

| Giai đoạn | Nội dung | Trạng thái |
| --- | --- | --- |
| 1 | Khung dự án, cấu hình, DB, `init`, `scan`, `status` | Xong |
| 2 | Logic xuất (`plan_export`), `export`, `--dry-run` | Xong |
| 3 | Phát hiện mặt, gom cụm, trang kiểm tra | Xong 3.1–3.7; **3.8 (đo, tinh chỉnh ngưỡng trên 200+ ảnh thật) chưa làm** |
| 4 | Giao diện web gắn nhãn | Chưa |
| 5 | Xuất từ giao diện, gom cụm tăng dần, `--prune`, `detect --redo` | Chưa |
| 6 | `run.bat`, README đầy đủ có ảnh chụp màn hình | Chưa |
| 7 | Google Drive API (tùy chọn) | Chưa |

Hạn chế hiện tại:

- Chưa có cách gắn nhãn cho cụm ngoài việc ghi trực tiếp vào DB; chờ giai đoạn 4.
- `cluster` chỉ chạy lần đầu; nếu đã có nhãn thì từ chối.
- Mỗi khuôn mặt chỉ mang một nhãn.
- Chưa hỗ trợ video, RAW, Live Photo; chỉ khử file giống hệt nhau, không khử ảnh gần giống.

## Phát triển

```bash
pip install -e ".[dev,ml]"
pytest
ruff check .
```

Test không cần model hay ảnh thật: dùng `FakeFaceEngine` (`tests/fakes.py`) và bộ dựng dữ liệu giả (`tests/factories.py`). Đặt biến môi trường `FACESORT_HOME` để đổi thư mục dữ liệu dự án.

Ghi chú kỹ thuật:

- Phát hiện mặt và embedding: InsightFace `buffalo_l` (SCRFD + ArcFace, vector 512 chiều) bằng `onnxruntime` trên CPU. Kiểm chứng cài đặt xem `DECISIONS.md`.
- Gom cụm: DBSCAN khoảng cách cosine tự viết bằng numpy, vì scikit-learn bị chính sách Application Control chặn một DLL trên máy phát triển.
- `DECISIONS.md` ghi mọi chỗ làm khác đặc tả và lý do.
