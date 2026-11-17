# Kế hoạch giao diện facesort

Kế hoạch cho giai đoạn 4–6: giao diện web cục bộ giúp cấu hình dự án, dán nhãn khuôn mặt và xuất ảnh theo người.

## 1. Quyết định đã chốt

| Câu hỏi | Quyết định |
| --- | --- |
| Luồng thao tác | 3 nút: **Scan** → **Labeling** → **Export** |
| Ai dùng | Chỉ chủ dự án, chạy trên máy mình, quen venv |
| Dạng app | Trang web cục bộ: FastAPI + HTML/JS thuần, tự mở trình duyệt |
| Folder đầu ra | Mỗi nhãn là 1 folder. "Nhóm" nghĩa là nhiều người cùng mang một nhãn (ví dụ "Họ nhà gái") |
| Ảnh chụp chung | Copy vào folder của từng người có trong ảnh (giữ nguyên quy tắc xuất hiện tại) |
| Ảnh không ai có nhãn | Vào `_Khac`. Không đặt tên tạm "Người NN" |
| Export | Chạy full flow: quét lại input, xử lý ảnh mới, tự gán mặt mới vào người đã có nhãn, rồi copy |
| Mỗi người hiển thị | 1 mặt đại diện cỡ lớn kèm 5–6 mặt nhỏ ở các góc khác |

Không làm: desktop wrapper (pywebview), file `.exe` đóng gói (PyInstaller), truy cập qua LAN, nhiều người cùng sửa. Lý do: Application Control trên máy chặn exe/DLL lạ, và chỉ có một người dùng.

## 2. Kiến trúc

- **Server:** FastAPI chạy bằng uvicorn, chỉ bind `127.0.0.1`, tự tìm cổng trống và mở trình duyệt. Khởi động bằng lệnh `facesort ui`.
- **Frontend:** HTML/CSS/JS thuần trong `facesort/static/` (đã khai báo trong `package-data`). Không có bước build, không dùng npm, không dùng CDN, chạy được offline.
- **Tác vụ nặng:** `JobRunner` chạy trong một background thread. Mỗi lúc chỉ 1 job; job giữ `ProjectLock` suốt thời gian chạy. Frontend hỏi `/api/job` mỗi 500 ms để lấy tiến độ, không dùng SSE hay WebSocket.
- **Chọn folder:** endpoint mở `tkinter.filedialog.askdirectory`. Nếu tkinter không có thì vẫn còn ô dán đường dẫn.
- **Dùng chung logic:** CLI và UI gọi cùng các hàm trong `facesort/pipeline.py`. CLI có thêm lệnh tương ứng để test không cần UI.
- **Khởi động trên Windows:** `run.bat` gọi `.venv\Scripts\python.exe -m facesort ui`. Gọi qua `python.exe` để tránh `facesort.exe` bị Application Control chặn.

```
Trình duyệt ──HTTP──▶ FastAPI (127.0.0.1)
                         ├─ /api/config, /api/pick-folder
                         ├─ /api/job  ◀── JobRunner (thread) ── pipeline.scan_all / export_full
                         ├─ /api/clusters, /api/labels, /api/faces ── labels.py, cluster.py
                         └─ /static/*, /thumbs/faces/{id}.jpg
                                    │
                               facesort.db + thumbs/ (trong %LOCALAPPDATA%\facesort\<dự án>)
```

## 3. Ba nút

| Nút | Chạy gì | Kết quả hiện ra |
| --- | --- | --- |
| **1. Scan** | `scan` → `detect` → gom cụm. Lần đầu dùng DBSCAN; các lần sau gán tăng dần (task 1.3) | Số ảnh, số người tìm được, thanh tiến độ, nút Dừng |
| **2. Labeling** | Mở màn dán nhãn, mỗi người một thẻ | Số người đã đặt tên / tổng số |
| **3. Export** | Quét lại input → detect ảnh mới → gán tăng dần → lập kế hoạch → kiểm tra dung lượng ổ → copy → `export_report.csv` | Số ảnh copy theo từng folder, số mặt được gán tự động, số người mới chưa có tên (bấm để mở Labeling), nút "Mở thư mục kết quả" |

## 4. Nhận ra cùng một người ở nhiều góc mặt

Không thể đúng 100%, nên làm theo 3 lớp.

1. **Embedding ArcFace** (`buffalo_l`) đã xử lý được độ nghiêng vừa phải. Mặt chính diện và hơi nghiêng của một người thường nằm chung cụm.
2. **Mặt nghiêng hẳn hay bị tách thành cụm riêng.** Thiết kế hiện tại cố ý ưu tiên tách hơn là gộp nhầm. Bù lại bằng:
   - **Gợi ý gộp:** sau khi đặt tên một cụm, tìm các cụm có centroid gần (khoảng cách cosine dưới khoảng 0,6; tinh chỉnh ở task 3.8) và hỏi "Nhóm 12 có thể cũng là Lan" với 2 nút Đúng / Không.
   - **Gõ trùng tên có sẵn thì gộp:** ô tên có gợi ý tên đã nhập (`datalist`), so khớp bằng `name_key` sẵn có.
   - **Sắp xếp:** cụm có thể là cùng người được xếp gần nhau.
3. **Mặt đại diện:**
   - **Mặt lớn:** mặt gần centroid nhất, có `det_score` cao và kích thước lớn, tức là rõ và chính diện nhất.
   - **5–6 mặt nhỏ:** chọn bằng farthest-point sampling, tức là các mặt khác nhau nhất trong cụm. Nếu máy gộp nhầm 2 người thì mặt lạ sẽ lộ ra ở đây; bấm vào để tách khỏi cụm.
   - **Mặt lẻ** (không thuộc cụm nào) nằm ở mục thu gọn cuối trang, dán nhãn từng mặt nếu muốn.

## 5. Màn hình

### 5.1 Màn chính

```
┌─────────────────────────────────────────────────────────────┐
│ facesort · Ảnh cưới Lan và Minh                             │
├─────────────────────────────────────────────────────────────┤
│ Input (chỉ đọc)                  Output                     │
│ [G:\My Drive\Anh cuoi ] [Chọn…]  [D:\Anh da phan loai] [Chọn…]│
│                                                             │
│ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐          │
│ │ 1. Scan      │ │ 2. Labeling  │ │ 3. Export    │          │
│ │ 3.802 ảnh    │ │ 14/37 đã đặt │ │ Quét lại,    │          │
│ │ 37 người  ✓  │ │ tên          │ │ gán, copy    │          │
│ └──────────────┘ └──────────────┘ └──────────────┘          │
│                                                             │
│ Đang tìm khuôn mặt · ảnh 1.240 / 3.802 · còn khoảng 18 phút │
│ ████████░░░░░░░░░░░░░░░░                          [Dừng]    │
│                                                             │
│ ▸ Tùy chỉnh nâng cao                                        │
└─────────────────────────────────────────────────────────────┘
```

- Kiểm tra form ngay khi nhập: folder không tồn tại, output nằm trong input hoặc ngược lại (dùng lại `Config.validate`).
- Tên dự án tự điền theo tên folder input. Nếu có nhiều dự án thì có menu chọn dự án.
- Nút đang làm được tô màu chính; mỗi lúc chỉ một nút nổi bật.
- Đóng tab rồi mở lại vẫn thấy tiến độ job đang chạy.

### 5.2 Labeling

```
┌─────────────────────────────────────────────────────────────┐
│ ┌────────┐  [m][m][m][m][m!]  218 ảnh · xem tất cả           │
│ │  MẶT   │  [ Lan                         ] [Bỏ qua]        │
│ │  LỚN   │  ┌───────────────────────────────────────────┐   │
│ └────────┘  │ [m] Nhóm 12 (31 ảnh) có thể cũng là Lan   │   │
│             │                          [Đúng] [Không]   │   │
│             └───────────────────────────────────────────┘   │
├─────────────────────────────────────────────────────────────┤
│ [MẶT]  [ Nhập tên, ví dụ Họ nhà gái    ]          96 ảnh    │
└─────────────────────────────────────────────────────────────┘
```

- Cụm xếp từ lớn đến nhỏ. Có bộ lọc "Ẩn nhóm đã xong".
- Lưu ngay khi nhấn Enter rồi nhảy sang cụm kế tiếp. Không có nút Save.
- Phím tắt: Enter lưu, Esc hủy, S bỏ qua, J/K di chuyển giữa các cụm, Ctrl+Z hoàn tác 1 bước.
- Bấm một mặt nhỏ để tách nó khỏi cụm. Bấm giữ hoặc nút kính lúp để xem ảnh gốc có khung mặt.
- "Bỏ qua" dành cho người lạ, thợ ảnh: cụm bị bỏ qua không tạo folder, ảnh của họ vào `_Khac` nếu không có ai khác.

### 5.3 Kết quả Export

- Trước khi copy: tóm tắt dry-run gồm số file và tổng dung lượng. **Nếu ổ không đủ chỗ thì dừng và báo**, không copy dở dang.
- Sau khi copy: bảng folder → số ảnh, số mặt được gán tự động (để kiểm tra ngưỡng), số người mới chưa có tên, danh sách lỗi, nút "Mở thư mục kết quả" (`os.startfile`).

### 5.4 Tùy chỉnh nâng cao (thu gọn mặc định)

| Hiển thị | Khóa config | Ghi chú |
| --- | --- | --- |
| Độ chặt khi gom nhóm: Chặt / Vừa / Lỏng | `cluster_eps` = 0.42 / 0.5 / 0.58 | Giá trị chốt sau task 3.8 |
| Bỏ mặt nhỏ ở hậu cảnh | `min_face_ratio` | |
| Độ chặt khi tự gán ảnh mới | `assign_threshold` | |
| Thư mục cho ảnh không có nhãn | `unlabeled_folder` | Tắt bằng `export_unlabeled` |

Mỗi mục có 1 dòng giải thích. Không hiện tên khóa kỹ thuật trên giao diện.

### 5.5 Nguyên tắc chung

- Toàn bộ chữ tiếng Việt. Không dùng từ "embedding" hay "cluster"; dùng "nhóm", "khuôn mặt".
- Lỗi viết thành câu hướng dẫn ("Không tìm thấy folder input. Kiểm tra lại đường dẫn."), không hiện stack trace.
- Thao tác dán nhãn lưu ngay vào DB.

## 6. API

| Method | Đường dẫn | Việc |
| --- | --- | --- |
| GET | `/api/projects` | Danh sách dự án |
| GET / PUT | `/api/config` | Đọc / lưu config (validate trước khi lưu) |
| POST | `/api/pick-folder` | Mở hộp thoại chọn folder (tkinter) |
| POST | `/api/jobs/scan` | Bắt đầu Scan |
| POST | `/api/jobs/export` | Bắt đầu Export |
| GET | `/api/job` | Trạng thái job: bước, i/tổng, thời gian còn lại, lỗi, kết quả |
| POST | `/api/job/cancel` | Dừng job |
| GET | `/api/clusters` | Danh sách cụm (phân trang), kèm mặt đại diện và mặt nhỏ |
| GET | `/api/clusters/{id}/faces` | Toàn bộ mặt trong cụm |
| GET | `/api/clusters/{id}/suggest-merge` | Cụm có thể cùng người |
| PUT | `/api/clusters/{id}/label` | Đặt tên (gõ trùng tên thì gộp) |
| POST | `/api/clusters/{id}/ignore` | Bỏ qua cụm |
| POST | `/api/faces/{id}/detach` | Tách mặt khỏi cụm |
| PUT | `/api/faces/{id}/label` | Đặt tên cho từng mặt (dùng cho mặt lẻ) |
| GET | `/api/labels` | Danh sách nhãn, dùng cho gợi ý tên |
| POST | `/api/undo` | Hoàn tác thao tác dán nhãn gần nhất |
| GET | `/thumbs/faces/{id}.jpg` | Ảnh mặt, chỉ nhận id số nguyên |
| GET | `/api/photos/{sha}/preview` | Ảnh gốc thu nhỏ có khung mặt (cache vào `thumbs/photos`) |
| POST | `/api/open-output` | Mở folder output trong Explorer |

## 7. Giai đoạn và task

Thứ tự: **G1 → G0 → G2 → G3 → G4**. Làm lõi trước để test được bằng pytest mà không cần UI. Mỗi task kèm tiêu chí kiểm chứng (→).

### G1. Logic lõi (khoảng 2–3 ngày)

- **1.1** `representatives(cluster_id, k=6)` trả về 1 mặt đại diện và k mặt đa dạng.
  → Test với embedding giả: mặt đại diện là mặt gần centroid nhất; các mặt nhỏ trải đủ mọi nhóm con.
- **1.2** `suggest_merges(cluster_id)` tính khoảng cách centroid tới các cụm khác.
  → Test: 2 cụm của cùng một người giả lập được gợi ý; cụm của người khác thì không.
- **1.3** Gán tăng dần: mặt mới gán vào nhãn gần nhất nếu khoảng cách ≤ `assign_threshold`; phần còn lại chạy DBSCAN thành cụm mới. Gỡ chặn ở `cluster_first_run`. Dùng chung cho Scan lần 2 trở đi và cho Export.
  → Test: thêm ảnh mới của người đã có nhãn thì ảnh vào đúng folder; người mới thì tạo cụm mới chưa có tên; nhãn cũ không bị mất.
- **1.4** `pipeline.scan_all()` và `pipeline.export_full()` nhận callback tiến độ và cờ dừng.
  → Test e2e bằng `FakeFaceEngine`: chạy Export 2 lần thì lần 2 không copy lại file nào; dừng giữa chừng thì DB vẫn nhất quán.
- **1.5** Đổi tên nhãn sau khi đã xuất: Export đổi tên folder cũ trên đĩa và cập nhật `exports.dest_rel_path`. Gộp nhãn thì chuyển file sang folder đích, trùng SHA-256 thì bỏ qua.
  → Test: đổi tên rồi export lại thì không còn folder cũ, số file giữ nguyên.
- **1.6** Kiểm tra dung lượng ổ trước khi copy (`shutil.disk_usage`).
  → Test với giá trị dung lượng giả lập.

### G0. Nền server (khoảng 1 ngày)

- **0.1** `facesort/server.py` và lệnh `facesort ui`.
  → `TestClient` GET `/` trả 200.
- **0.2** Bảo mật: chỉ bind 127.0.0.1, kiểm header `Host`/`Origin` để chặn DNS rebinding, ảnh mặt phục vụ theo id số nguyên (không nhận path).
  → Test trả 403 với Host lạ và 404 với id không tồn tại.
- **0.3** `JobRunner`: trạng thái, tiến độ, dừng, lỗi; mỗi lúc 1 job.
  → Test với `FakeFaceEngine`: job chạy xong; job thứ hai bị từ chối khi job đầu đang chạy.
- **0.4** Config qua form: đọc, validate, lưu; chọn folder bằng tkinter.
  → Test PUT config sai (output nằm trong input) trả lỗi tiếng Việt.

### G2. API dán nhãn (khoảng 1–2 ngày)

- Các endpoint ở mục 6, cùng nhật ký thao tác để hoàn tác 1 bước.
  → Mỗi endpoint có test, kể cả tên trùng `_Khac`, tên chứa ký tự cấm (đã có `labels.validate`), và gộp khi gõ trùng tên.

### G3. Frontend (khoảng 3–4 ngày)

- **3.1** Khung trang, ô folder, chọn dự án, 3 nút có trạng thái.
- **3.2** Màn tiến độ (polling).
- **3.3** Màn Labeling: thẻ người, phím tắt, gợi ý tên, gợi ý gộp ngay trong thẻ, tải ảnh lười.
- **3.4** Xem ảnh gốc có khung mặt.
- **3.5** Màn kết quả Export và Tùy chỉnh nâng cao.

→ Chạy thật trên trình duyệt với bộ ảnh mẫu: đi hết luồng Scan → Labeling → Export mà không cần đụng CLI; kiểm tra cả màn rộng và màn hẹp.

### G4. Đóng gói và tài liệu (khoảng 1 giờ)

- `run.bat` gọi `.venv\Scripts\python.exe -m facesort ui`.
- Gộp nhóm phụ thuộc `ui` vào phụ thuộc mặc định.
- Cập nhật README (ảnh chụp màn hình, bảng trạng thái) và `DECISIONS.md`.

→ Bấm đúp `run.bat` là thấy giao diện.

## 8. Rủi ro

- **Ngưỡng chưa tinh chỉnh.** Chất lượng gợi ý gộp và gán tự động phụ thuộc `cluster_eps`, `assign_threshold` và ngưỡng gợi ý gộp. Task 3.8 (đo trên 200+ ảnh cưới thật) nên làm ngay sau 1.2. Cần chuẩn bị sẵn một bộ ảnh thật để thử.
- **Gán nhầm lúc Export.** Nếu `assign_threshold` quá lỏng thì ảnh người lạ lọt vào folder người quen. Màn kết quả hiện số mặt được gán tự động để kiểm tra.
- **Thao tác trên dữ liệu thật trên đĩa.** Task 1.5 (đổi tên, gộp folder đã xuất) dễ sinh bug nhất; cần test kỹ trước khi làm UI. Folder input không bao giờ bị sửa.
- **tkinter có thể không có** trong một số bản cài Python. Ô dán đường dẫn là phương án dự phòng.
- **Dung lượng output lớn.** Ảnh được nhân theo số nhãn có trong ảnh; task 1.6 chặn trường hợp hết ổ.
