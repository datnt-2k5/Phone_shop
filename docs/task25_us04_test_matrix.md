
# Task 25 – US04: Ma trận kiểm thử bảo mật

Nguồn yêu cầu: Excel Phone Shop v2.5, dòng 26;
Task.md mục 4.2–4.5, FR4.1–FR4.2, 17.5 (ROLE01–ROLE10).

## Phạm vi đã có thể kiểm thử

| ID | Tình huống | Nơi kiểm thử | Mức độ |
|---|---|---|---|
| ROLE01 | Guest truy cập trang Admin | Unit Test | Route Guard |
| ROLE02 | Customer truy cập trang Admin | Unit + Integration | Route Guard |
| ROLE03 | Admin truy cập trang Super Admin | Unit + Integration | Route Guard |
| ROLE04 | Customer đọc đơn người khác | Integration Test | Quyền OWN; chưa có OrderService |
| ROLE05 | Super Admin tự khóa | Chưa nghiệm thu | Phụ thuộc US15 |
| ROLE06 | Giả mạo role | Unit + Integration | Role từ AuthService/DB |
| ROLE07 | Khóa tài khoản giữa phiên | Integration Test | Chặn thao tác kế tiếp |
| ROLE08 | Customer LOCKED có đơn PENDING | Integration Test | Kiểm tra quyền Admin; phụ thuộc US10 |
| ROLE09 | Customer LOCKED có đơn CONFIRMED | Integration Test | Kiểm tra quyền Admin; phụ thuộc US10/US11 |
| ROLE10 | Khóa tài khoản không tự hủy đơn | Integration Test | So sánh dữ liệu đơn trước/sau |

## Các giới hạn cần lưu ý

- Không xem quyền CONFIRM_ORDER là bằng chứng quy trình
  xác nhận đơn đã hoàn thiện.

- Không xem quyền COMPLETE_ORDER là bằng chứng
  quy trình hoàn tất đơn đã hoàn thiện.

- Không xem quyền CANCEL_ORDER là bằng chứng
  quy trình hủy đơn và hoàn tồn đã hoàn thiện.

- ROLE05 cần kiểm tra quy tắc Super Admin không
  được tự khóa tài khoản khi phát triển US15.

- OrderService của US10 phải lấy chủ sở hữu đơn
  từ database, không tin customer_id từ client.

- Test này chưa chứng minh tất cả các tình huống
  tranh chấp transaction giữa hai kết nối DB.

- Chỉ sử dụng phone_shop_test với fixture test_db.

- Không thay đổi database phone_shop.

## Lệnh nghiệm thu

```powershell
python -m pytest tests/unit/test_us04_security_routes.py -q

python -m pytest tests/integration/test_us04_security_db.py -q

python -m pytest tests -q

python -m ruff check .

flet run --web main.py
```

## Kết quả thực tế

- Unit Test: cập nhật sau khi chạy.
- Integration Test: cập nhật sau khi chạy.
- Toàn bộ pytest: cập nhật sau khi chạy.
- Ruff: cập nhật sau khi chạy.
- Flet Web: cập nhật sau khi nghiệm thu.
