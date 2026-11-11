
# Task 41 – US07 Import and Stock Regression

## 1. Nguồn yêu cầu

- Excel Phone Shop v2.5: Task 41.
- Task.md: US07-T09.
- Task.md: FR6 – Quản lý nhập kho.
- Task.md: Kiểm thử sản phẩm, kho và tiền.
- Mốc nền: Task 1–40 hoàn thành, 1.353 pytest PASS.

## 2. Ma trận kiểm thử

| ID | Tình huống | Kết quả mong đợi |
|---|---|---|
| MONEY01 | Giá trị 1.005 | HALF_UP = 1.01 |
| MONEY02 | Giá trị 1.025 | HALF_UP = 1.03 |
| MONEY03 | Giá vốn 10 máy + nhập 5 máy | 5.166.666,67 |
| MONEY04 | Tồn đầu bằng 0 | Giá vốn bằng giá nhập |
| MONEY05 | Truyền float hoặc bool | Từ chối |
| VAL01 | Sản phẩm trùng trong phiếu | VALIDATION_ERROR |
| VAL02 | Tổng tiền vượt giới hạn | VALIDATION_ERROR |
| VAL03 | Sản phẩm đầu vào đảo thứ tự | Sắp xếp ID tăng dần |
| ROLL01 | Lỗi sau khi tạo phiếu | Không lưu phiếu |
| ROLL02 | Lỗi ở movement thứ hai | Rollback toàn bộ |
| ROLL03 | Có lỗi giữa transaction | Không cập nhật một phần tồn |
| DB01 | UPDATE stock = -1 | MariaDB từ chối |
| DB02 | quantity_change = 0 | MariaDB từ chối |
| DB03 | stock_after = -1 | MariaDB từ chối |
| DB04 | operation_key trùng | UNIQUE từ chối |
| MOVE01 | Một chi tiết nhập hợp lệ | Đúng một IMPORT movement |
| MOVE02 | Hai phiếu khác nhau | Hai operation_key khác nhau |
| CON01 | Hai Admin cùng nhập một SKU | Tổng tồn chính xác |
| CON02 | Hai Admin nhập cùng SKU khác giá | Giá vốn bình quân chính xác |
| CON03 | Hai phiếu nhập hai SKU đảo thứ tự | Khóa ID tăng dần |
| CON04 | Connection đang giữ FOR UPDATE | Connection khác phải chờ |
| CON05 | Giải phóng khóa | Transaction chờ hoàn thành |

## 3. Nguyên tắc kiểm thử

- Kiểm thử chỉ sử dụng phone_shop_test.
- Dùng tài khoản phone_shop_tester.
- Không ghi thử vào database phone_shop.
- Unit Test không kết nối MariaDB.
- Rollback Test sử dụng test_db và savepoint.
- Concurrency Test sử dụng các connection độc lập.
- Dữ liệu Concurrency Test được tạo tạm thời và dọn dẹp theo ID.
- Mỗi worker có SQLAlchemy Session riêng.
- Không chia sẻ một Session cho nhiều thread.
- Không xóa toàn bộ bảng hoặc tắt Foreign Key.
- Không thay đổi schema để ép kiểm thử PASS.

## 4. Giới hạn

- Chưa triển khai cơ chế idempotency mới cho lập phiếu nhập.
- Hai lần chủ động gửi create_import() là hai nghiệp vụ độc lập.
- Mỗi phiếu nhập chỉ ghi một movement cho mỗi product_id.
- Không giả định mọi lỗi deadlock đều được retry tự động.
- Chưa thực hiện nghiệp vụ kiểm kê và điều chỉnh tồn P2.
- Task 41 chỉ bổ sung kiểm thử hồi quy.

## 5. Kết quả nghiệm thu

- Unit Test: [điền kết quả thực tế].
- Integration Test: [điền kết quả thực tế].
- Toàn bộ pytest: [điền kết quả thực tế].
- Ruff: [điền kết quả thực tế].
- Flet Web: [điền kết quả thực tế].

## 6. Kết luận

[Điền kết luận sau khi hoàn thành toàn bộ kiểm thử.]
