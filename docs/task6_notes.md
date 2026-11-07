# Task 6 – Giao diện khung Phone Shop

Task theo dòng 7, Excel v2.5: tạo giao diện khung website, menu theo quyền, thông báo và định dạng giá tiền VND.

## Chạy

```powershell
flet run --web main.py
python -m pytest tests/unit/test_ui_shell.py -v
python -m ruff check main.py ui tests/unit/test_ui_shell.py
```

## Kiểm tra thủ công

- [ ] Trang chủ hiển thị AppBar, menu, khung nội dung.
- [ ] Bốn nút mô phỏng GUEST, CUSTOMER, ADMIN, SUPER_ADMIN thay đổi menu tương ứng.
- [ ] Menu chung có Trang chủ, Sản phẩm; khách vãng lai còn có Đăng nhập, Đăng ký (màn hình mẫu).
- [ ] CUSTOMER có giỏ hàng/đơn của tôi, không có trang quản trị.
- [ ] ADMIN có Dashboard/báo cáo, không có menu Super Admin.
- [ ] SUPER_ADMIN có menu tài khoản và cấu hình hệ thống.
- [ ] Chuyển URL và Back trên trình duyệt hoạt động.
- [ ] Nút thông báo thành công/lỗi hiển thị SnackBar.
- [ ] Nhập 12500000.50 được kết quả 12.500.001 ₫.
- [ ] Nhập chữ hoặc ký tự sai thì thông báo lỗi.
- [ ] Thu nhỏ cửa sổ, menu tự xuống dòng.

## Giới hạn

Đây là bản DEMO GIAO DIỆN. Nút chọn vai trò chỉ dùng kiểm tra cách hiển thị menu, không xác thực ai đang đăng nhập, không chứng minh quyền với Service và không có SQL nghiệp vụ. Các chức năng đăng nhập, phân quyền thật sẽ triển khai ở US01, US02, US04.

File `main.py` ở đây thay cho màn hình "Hello World" trong Task 1. Không đụng các thư mục `database/`, `models/`, `utils/`, `services/`, `repositories/`, hay `spikes/` đã hoàn thành.
