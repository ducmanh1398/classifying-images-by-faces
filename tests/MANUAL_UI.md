# Kiểm tra giao diện bằng tay

Chạy `python -m facesort ui`. Dùng một bộ ảnh nhiều người (nên ≥ 200 ảnh thật cho lần kiểm cuối). Đánh dấu `[x]` khi đạt, thử trên Chrome và Edge.

## Tạo dự án và cấu hình
- [ ] Chưa có dự án: hiện form "Tạo dự án mới". Folder input không tồn tại → báo "Không tìm thấy folder input…".
- [ ] Output nằm trong input (và ngược lại) → báo lỗi bằng tiếng Việt, không tạo dự án.
- [ ] Nút "Chọn…" mở hộp thoại chọn folder; nếu không có thì báo dán đường dẫn.
- [ ] Đổi folder ở dự án có sẵn: lưu ngay; giá trị sai hiện lỗi dưới ô, không lưu.
- [ ] Tên dự án tự điền theo tên folder input; hai dự án thì có menu chọn ở thanh trên.

## Scan
- [ ] Bấm Scan: thấy các bước (quét → nạp model → tìm khuôn mặt → gom nhóm), số `i / tổng`, thời gian còn lại.
- [ ] Đóng tab rồi mở lại giữa chừng: vẫn thấy tiến độ đang chạy.
- [ ] Bấm Dừng: tác vụ dừng, báo "Đã dừng"; bấm Scan lại chạy tiếp, không xử lý lại ảnh đã xong.
- [ ] Trong lúc chạy: nút Scan/Export bị khóa; đặt tên nhóm báo "Đang chạy tác vụ nền".
- [ ] Ảnh hỏng được báo ở kết quả, không làm dừng cả lô.
- [ ] Mở `run` / `ui` lần thứ hai cùng dự án khi đang Scan: báo "đang được một tiến trình khác sử dụng".

## Labeling
- [ ] Gắn tên cho 10 nhóm liên tiếp chỉ bằng bàn phím (gõ, Enter, gõ, Enter…). Tải lại trang vẫn giữ kết quả.
- [ ] Gõ trùng tên (khác hoa thường) cho nhóm thứ hai: dùng chung một nhãn; ô tên gợi ý các tên đã có.
- [ ] Sau khi đặt tên, nhóm giống hiện "có thể cũng là …": Đúng gộp vào nhãn, Không ẩn đi.
- [ ] Nhóm chưa đặt tên giống nhóm đã có tên hiện "Có phải …?" và nút Đồng ý.
- [ ] `J`/`K` di chuyển, `S` bỏ qua, `Esc` hủy, `Ctrl+Z` hoàn tác (cả khi ô tên trống), nút Hoàn tác.
- [ ] Bỏ qua một nhóm rồi bấm lại để bật lại.
- [ ] Bấm mặt nhỏ: tách khỏi nhóm; mặt vừa tách xuất hiện ở "Mặt lẻ" kèm gợi ý nhãn; hoàn tác đưa về nhóm cũ.
- [ ] "Xem ảnh gốc": khung đỏ quanh đúng mặt.
- [ ] Đặt tên riêng cho một mặt: ảnh đó vào folder của tên riêng khi Export (không theo nhãn nhóm).
- [ ] Tên `_Khac`, tên rỗng, tên `Cô Lan / Chú Tư` được xử lý đúng (báo lỗi / đổi ký tự cấm).
- [ ] "Tải thêm" khi có nhiều hơn 24 nhóm; bộ lọc Tất cả / Chưa đặt tên / Đã đặt tên / Đã bỏ qua.

## Export
- [ ] Export lần đầu: bảng folder → số ảnh; mở được thư mục kết quả; kiểm tra tay vài folder.
- [ ] Export lần hai ngay sau đó: copy 0 file.
- [ ] Thêm ảnh mới vào input rồi Export: chỉ ảnh mới được xử lý, nhãn cũ nguyên, số mặt tự gán > 0 nếu có người quen.
- [ ] Nhóm mới chưa có tên: hiện số lượng và liên kết sang Labeling.
- [ ] Đổi tên một nhãn (qua `PATCH /api/labels/{id}` hoặc gõ lại tên) rồi Export: folder cũ được đổi tên, không còn folder cũ.
- [ ] Output đặt trên ổ gần đầy: Export dừng trước khi copy và báo thiếu chỗ.
- [ ] Folder input không đổi (so sánh danh sách file trước/sau).

## Giao diện
- [ ] Màn rộng và màn hẹp (điện thoại) đều dùng được, không tràn ngang.
- [ ] Chế độ tối (theo hệ điều hành) đọc được.
- [ ] Không có lỗi trong console của trình duyệt khi đi hết luồng.
