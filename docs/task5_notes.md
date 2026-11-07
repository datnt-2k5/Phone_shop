# Task 5 – Hạ tầng nền tảng

Theo dòng 6 Excel v2.5: AppError, Clock, money_utils, code_utils, Service/Repository.

- Clock: UTC naive trong Python/DB; chuyển giờ Việt Nam chỉ khi hiển thị/báo cáo.
- Tiền: Decimal, ROUND_HALF_UP và quantize 2 chữ số. Tránh float.
- Giá vốn: tính bình quân khi nhập kho và khi hoàn tồn hủy đơn CONFIRMED.
- Mã chứng từ: INSERT mã tạm UUID, FLUSH lấy ID, đổi mã từ ID, COMMIT trong một transaction.
- Service kiểm tra quyền và điều phối transaction; Repository chỉ truy vấn và không commit giữa chừng.
- Session SQLAlchemy không chia sẻ giữa các request/thread.

Kiểm tra: `python -m pytest tests/unit/test_foundation.py -v`.

Không cần sửa MariaDB hoặc `.env` ở Task này.
