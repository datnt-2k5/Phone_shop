# TASK 7 – KẾT QUẢ KIỂM THỬ DB VÀ QUY TẮC CỐT LÕI

- Dự án: Phone Shop, Excel v2.5 – US00, dòng 8
- Môi trường: Windows / PyCharm / Python 3.13.15 / MariaDB 10.4.32, cổng 3307
- Database thử nghiệm: `phone_shop_test` (KHÔNG chạy trên `phone_shop`)
- Người thực hiện: ...
- Ngày thử nghiệm: ...

| Mã kiểm thử | Nội dung | PASS/FAIL | Ghi chú |
|---|---|---|---|
| DB01 | MariaDB phiên bản 10.4.32 | | |
| DB02 | 11 bảng P1 sử dụng InnoDB và utf8mb4_unicode_ci | | |
| DB03 | CHECK từ chối stock âm | | |
| DB04 | NOT NULL từ chối NULL | | |
| DB05 | Kết nối SQLAlchemy có Strict Mode | | |
| DB06 | Chuỗi vượt VARCHAR bị từ chối trong Strict Mode | | |
| DB07 | Giữ nguyên SQL Mode cũ | | Unit test |
| DB08 | Tự bổ sung STRICT_TRANS_TABLES khi thiếu | | Unit test |
| DB09 | UNIQUE từ chối dữ liệu trùng | | |
| FK | FOREIGN KEY từ chối tham chiếu không tồn tại | | |
| STOCK16 | quantity_change = 0 bị từ chối | | |
| CLOCK | FixedClock độc lập, đổi UTC sang giờ Việt Nam | | Unit test |
| MONEY | ROUND_HALF_UP 2 chữ số | | Unit test |
| COST | Giá vốn bình quân nhập và hoàn tồn | | Unit test |

## Các lệnh và kết quả

```powershell
python -m pytest tests/unit/test_task7_rules.py tests/unit/test_foundation.py -v
python -m pytest tests/integration/test_database_constraints.py -v
python -m ruff check tests/integration tests/unit/test_task7_rules.py
```

- Unit Test: ... passed
- Integration Test: ... passed
- Ruff: ...
- Nhận xét: ...

**Lưu ý:** Test chỉ thực hiện INSERT/UPDATE trong transaction và rollback. Các bộ đếm AUTO_INCREMENT có thể tăng dù dữ liệu test đã rollback, điều này không làm sai tồn kho hoặc lịch sử nghiệp vụ.
