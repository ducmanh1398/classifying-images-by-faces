# facesort

Phân loại ảnh cưới theo khuôn mặt. Chạy hoàn toàn trên máy Windows của bạn: quét một folder ảnh, gom các khuôn mặt giống nhau thành nhóm, gắn tên cho từng nhóm trên giao diện web cục bộ, rồi copy ảnh vào các thư mục theo tên để gửi cho họ hàng.

## Yêu cầu

- Windows 10 hoặc 11, 64-bit, RAM từ 8 GB. Không cần GPU.
- Python 3.11 (64-bit), có trong `PATH`.
- Dưới khoảng 10.000 ảnh. Hỗ trợ JPG, JPEG, PNG, HEIC, HEIF.
- Nếu ảnh nằm trên Google Drive: dùng Google Drive for Desktop và bật **Available offline** cho folder ảnh trước khi chạy, để file đã nằm sẵn trên máy.

## Chạy nhanh

Bấm đúp `run.bat`. Lần đầu nó tạo môi trường ảo `.venv`, cài các gói cần thiết rồi mở giao diện tại `http://127.0.0.1:8765` (chỉ máy này truy cập được). Lần chạy `Scan` đầu tiên sẽ tải model nhận diện `buffalo_l` (khoảng 280 MB) — đây là lần gọi mạng duy nhất; sau đó công cụ chạy offline. Model huấn luyện sẵn của InsightFace chỉ cho phép dùng phi thương mại.

Cài thủ công (nếu không dùng `run.bat`):

```bash
python -m venv .venv
.venv\Scripts\activate
python -m pip install -e ".[ml]"
python -m facesort ui
```

> Dùng `python -m pip` và `python -m facesort` thay vì `pip` / `facesort`. Nếu máy có chính sách Application Control hoặc Device Guard, các file `.exe` do `pip` tạo (`pip.exe`, `facesort.exe`) có thể bị chặn, còn `python.exe` thì vẫn chạy.

## Quy trình trên giao diện: 3 nút

1. **Tạo dự án** (lần đầu): chọn folder input (ảnh gốc, chỉ đọc) và folder output. Hai folder không được lồng nhau.
2. **Scan**: quét ảnh, tìm khuôn mặt, gom thành nhóm. Có thanh tiến độ và nút **Dừng**; dừng giữa chừng thì lần sau chạy tiếp từ chỗ dừng. Ảnh hỏng được báo lại, không làm dừng cả lô.
3. **Labeling**: mỗi nhóm một thẻ gồm một mặt đại diện lớn và vài mặt khác để kiểm tra.
   - Gõ tên rồi **Enter**: lưu ngay và nhảy sang nhóm kế tiếp. Không có nút Lưu.
   - Gõ trùng một tên có sẵn thì nhiều nhóm dùng chung một folder (ví dụ nhiều nhóm của cùng một người, hoặc "Họ nhà gái" cho nhiều người).
   - Sau khi đặt tên, nhóm khác trông giống sẽ được gợi ý "có thể cũng là …" kèm nút Đúng / Không. Nhóm chưa đặt tên cũng hiện "Có phải …?" nếu giống một nhóm đã có tên.
   - **Bỏ qua** dành cho người lạ, thợ ảnh, hay ảnh thờ: không tạo folder cho họ.
   - Bấm một mặt nhỏ để **tách** khỏi nhóm (nhận nhầm), xem ảnh gốc có khung đỏ quanh mặt, đặt tên riêng, hoặc bỏ qua riêng mặt đó. Tên đặt riêng cho một mặt luôn thắng tên của nhóm.
   - **Mặt lẻ** (không thuộc nhóm nào) nằm ở mục thu gọn cuối trang; không bắt buộc xử lý.
   - Phím tắt: `J`/`K` đi giữa các nhóm, `Enter` vào ô tên, `S` bỏ qua, `Esc` hủy, `Ctrl+Z` hoàn tác một bước.
4. **Export**: quét lại input, xử lý ảnh mới, tự gán khuôn mặt mới vào người đã có nhãn, rồi copy. Khi xong có bảng folder → số ảnh, số mặt được gán tự động, số nhóm mới chưa có tên, danh sách lỗi và nút **Mở thư mục kết quả**. Nếu ổ đĩa không đủ chỗ, Export dừng và báo trước khi copy.

Thêm ảnh mới vào folder input rồi bấm **Export** (hoặc **Scan**) là đủ: nhãn cũ được giữ nguyên, chỉ ảnh mới được xử lý.

### Quy tắc xuất

- Mỗi ảnh được copy **một lần** vào folder của **mỗi nhãn** có trong ảnh. Ảnh có "Ông A" và "Bà B" xuất hiện ở cả hai folder, giống hệt bản gốc từng byte. Output có thể lớn hơn input nhiều lần.
- Nhiều khuôn mặt hoặc nhiều nhóm cùng một nhãn dùng chung một folder; ảnh không bị lặp.
- Tên nhãn so khớp không phân biệt hoa thường và dạng Unicode: "Ông A" và "ông a" là một nhãn. Ký tự cấm trong tên folder (`/ \ : * ? " < > |`) được thay bằng `_`.
- File giống hệt nhau (cùng SHA-256) chỉ xuất một bản. Chạy Export lại không copy lại file đã có, kể cả khi sổ ghi của công cụ bị mất.
- Hai ảnh khác nội dung trùng tên được phân biệt bằng hậu tố: `IMG_0012__a1b2c3d4.jpg`.
- Ảnh không có nhãn nào (mặt chưa gắn nhãn, bị bỏ qua, quá nhỏ, hoặc không có mặt) vào folder `_Khac` (tắt được trong Tùy chỉnh nâng cao).
- Đổi tên nhãn hoặc gộp hai nhãn rồi Export lại: công cụ đổi tên / gộp folder cũ trên đĩa. Chỉ file do chính công cụ tạo (và chưa bị sửa) mới bị di chuyển hay xóa; file bạn tự chép vào thì không bao giờ bị đụng tới.
- Folder input không bao giờ bị sửa. Sau khi xuất có `export_report.csv` trong folder output.

## Dòng lệnh

Giao diện và dòng lệnh dùng chung một lõi. Mỗi lệnh nhận `--project <tên>` (tự chọn nếu chỉ có một dự án). Nhớ thêm `python -m` phía trước nếu `facesort.exe` bị chặn.

```bash
facesort init --input "G:\My Drive\Anh cuoi" --output "D:\Anh da phan loai"
facesort ui                      # giao diện web
facesort run                     # scan + detect + gom nhóm, rồi mở giao diện
facesort scan | detect | cluster # từng bước
facesort status
facesort debug contact-sheet     # trang HTML tĩnh để xem các nhóm
facesort export --dry-run        # xem trước, không tạo file
facesort export
```

## Cấu hình

`config.toml` nằm trong `%LOCALAPPDATA%\facesort\<tên dự án>`, cùng chỗ với `facesort.db`, ảnh mặt đã cắt và log (cố ý nằm ngoài Drive). Các thiết lập thường dùng chỉnh được ở mục **Tùy chỉnh nâng cao** của giao diện.

| Khóa | Mặc định | Ý nghĩa |
| --- | --- | --- |
| `input_dir`, `output_dir` | bắt buộc | Folder ảnh gốc và folder đầu ra |
| `extensions` | `jpg, jpeg, png, heic, heif` | Đuôi file được quét |
| `det_size` | 960 | Cỡ ảnh đưa vào bộ phát hiện (bội số của 32). Lớn hơn bắt được mặt nhỏ hơn nhưng chậm hơn |
| `min_det_score` | 0.5 | Độ tin cậy tối thiểu của một khuôn mặt |
| `min_face_px` | 60 | Cạnh ngắn tối thiểu của khung mặt |
| `min_face_ratio` | 0.25 | Cạnh mặt chia cho mặt lớn nhất trong ảnh; lọc người đi ngang ở hậu cảnh |
| `cluster_eps` | 0.5 | Khoảng cách cosine tối đa giữa hai mặt cùng nhóm (Chặt 0.42 / Vừa 0.5 / Lỏng 0.58) |
| `cluster_min_samples` | 3 | Số mặt tối thiểu để thành một nhóm |
| `assign_threshold` | 0.45 | Ngưỡng tự gán mặt mới vào nhóm đã có nhãn. Số nhỏ thì chặt hơn |
| `export_unlabeled` | `true` | Bật folder cho ảnh không có nhãn |
| `unlabeled_folder` | `_Khac` | Tên folder cho ảnh không có nhãn |

Các ngưỡng là giá trị khởi điểm, **chưa được tinh chỉnh trên ảnh cưới thật** (task 3.8). Thiết kế ưu tiên tách một người thành nhiều nhóm hơn là gộp hai người vào một nhóm; nếu gặp nhóm gộp nhầm, chọn độ chặt "Chặt" rồi Scan lại (nhãn đã gắn được giữ). Đổi `det_size`, `min_det_score` hoặc `min_face_px` chưa tự xử lý lại ảnh cũ (`detect --redo` chưa có).

## Trạng thái triển khai

| Phần | Trạng thái |
| --- | --- |
| Khung dự án, quét, SHA-256, file trùng | Xong |
| Logic xuất, đổi tên / gộp nhãn sau khi xuất, kiểm tra dung lượng ổ | Xong |
| Phát hiện mặt, gom nhóm, gán tăng dần, gợi ý gộp | Xong; **chưa đo và tinh chỉnh ngưỡng trên 200+ ảnh thật (task 3.8)** |
| Giao diện web: Scan, Labeling, Export, Tùy chỉnh nâng cao | Xong, đã thử trên trình duyệt với ảnh mẫu; chưa thử trên bộ ảnh cưới thật |
| `run.bat` | Viết xong, **chưa thử trên máy Windows sạch** |
| README có ảnh chụp màn hình, thử cài trên máy sạch (6.3, 6.4) | Chưa |
| Google Drive API (giai đoạn 7, tùy chọn) | Chưa |

Hạn chế hiện tại:

- Mỗi khuôn mặt chỉ mang một nhãn.
- Chưa có `--prune` (xóa file thừa ở output) và `detect --redo`.
- Chưa hỗ trợ video, RAW, Live Photo; chỉ khử file giống hệt nhau, không khử ảnh gần giống.
- Nhóm chưa gắn nhãn được gom lại từ đầu ở mỗi lần Scan; nhóm đã có nhãn, nhóm đã bỏ qua, và mặt gán tay thì được giữ nguyên.

## Phát triển

```bash
python -m pip install -e ".[dev,ml]"
python -m pytest
python -m ruff check .
```

Test không cần model hay ảnh thật: dùng `FakeFaceEngine` (`tests/fakes.py`) và bộ dựng dữ liệu giả (`tests/factories.py`). Đặt biến môi trường `FACESORT_HOME` để đổi thư mục dữ liệu dự án. Danh sách kiểm tra giao diện bằng tay nằm ở `tests/MANUAL_UI.md`.

Ghi chú kỹ thuật:

- Phát hiện mặt và embedding: InsightFace `buffalo_l` (SCRFD + ArcFace, vector 512 chiều) bằng `onnxruntime` trên CPU.
- Gom nhóm: DBSCAN khoảng cách cosine tự viết bằng numpy, vì scikit-learn bị chính sách Application Control chặn một DLL trên máy phát triển.
- Máy chủ: FastAPI + uvicorn, chỉ bind `127.0.0.1`, kiểm header `Host`/`Origin` để chặn truy cập từ trang web khác. Giao diện là HTML/CSS/JS thuần, không build, không CDN.
- `DECISIONS.md` ghi mọi chỗ làm khác đặc tả và lý do. `UI_PLAN.md` là kế hoạch giao diện.
