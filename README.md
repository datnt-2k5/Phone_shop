
# PHONE SHOP v2.5

## 1. Giới thiệu

Phone Shop là dự án xây dựng website quản lý cửa hàng
điện thoại bằng Python, Flet và MariaDB.

Phạm vi ban đầu là một cửa hàng và một kho hàng.

Dự án được phát triển theo từng Task, bám sát
tài liệu đặc tả Task.md và Excel v2.5.

## 2. Công nghệ sử dụng

- Python 3.13
- Flet 1.0.5
- flet-charts 1.0.5
- MariaDB 10.4.32
- XAMPP
- SQLAlchemy
- PyMySQL
- Pandas
- NumPy
- Matplotlib
- bcrypt
- pytest
- Ruff
- python-dotenv
- PyCharm

## 3. Kiến trúc dự án

UI (Flet)
    |
    v
Service Layer
    |
    v
Repository Layer
    |
    v
MariaDB

Nguyên tắc:

- UI hiển thị và tiếp nhận thao tác.
- Service xử lý nghiệp vụ và transaction.
- Repository truy vấn và cập nhật database.
- MariaDB lưu trữ dữ liệu.

## 4. Cấu trúc thư mục

phone_shop/
    database/
        connection.py
        check_connection.py
        check_schema.py
        schema.sql
        seed.sql
        seed_super_admin.py

    models/
        app_error.py

    utils/
        time_utils.py
        money_utils.py
        code_utils.py

    services/
        base_service.py

    repositories/
        base_repository.py

    ui/
        navigation.py
        components/
            money_format.py
            notifications.py

    spikes/
        flet_web_spike.py
        matplotlib_spike.py

    tests/
        unit/
        integration/

    docs/
        erd.md
        task7_results.md

    main.py
    .env
    .env.example
    .gitignore
    requirements.txt
    README.md

## 5. Cài đặt môi trường trên Windows

### Bước 1: Mở dự án trong PyCharm

Mở thư mục phone_shop.

### Bước 2: Tạo môi trường ảo

Chạy trong Terminal:

    python -m venv .venv

Kích hoạt:

    .\.venv\Scripts\Activate.ps1

### Bước 3: Cài đặt thư viện

    python -m pip install -r requirements.txt

Kiểm tra:

    python -m pip check

## 6. Cấu hình database

Sử dụng MariaDB trên XAMPP.

Thông số môi trường phát triển:

- Host: 127.0.0.1
- Port: 3307
- Database ứng dụng: phone_shop
- Database kiểm thử: phone_shop_test

Cả hai database sử dụng InnoDB và utf8mb4.

Tài khoản ứng dụng chỉ được cấp quyền trên phone_shop.

Tài khoản kiểm thử chỉ được cấp quyền trên phone_shop_test.

Không sử dụng tài khoản root MariaDB trong ứng dụng.

### Khởi tạo cấu hình

Sao chép .env.example thành .env.

Điền mật khẩu database và cấu hình riêng của máy.

Không đưa file .env vào Git.

### Khởi tạo bảng

Tạo hai database trong MariaDB.

Import database/schema.sql vào từng database
bằng phpMyAdmin.

Lưu ý: Chỉ import khi cần khởi tạo mới. Không
xóa bảng hoặc ghi đè dữ liệu đang sử dụng.

### Seed dữ liệu ban đầu

Import database/seed.sql vào phone_shop.

Khai báo mật khẩu seed trong .env.

Chạy:

    python -m database.seed_super_admin

Super Admin được tạo bằng bcrypt.

Sau khi seed, không cần giữ mật khẩu seed trong .env.

## 7. Kiểm tra kết nối MariaDB

    python -m database.check_connection

Kiểm tra schema và dữ liệu ban đầu:

    python -m database.check_schema

## 8. Chạy website

Trong Terminal PyCharm:

    flet run --web main.py

Website sẽ mở trên trình duyệt.

Địa chỉ và cổng Flet có thể thay đổi mỗi lần chạy.

Lưu ý: Giai đoạn hiện tại giao diện có phần chọn
vai trò mô phỏng. Đây chưa phải xác thực và phân quyền
bảo mật thật. Các chức năng này sẽ triển khai ở US01-US04.

## 9. Chạy kiểm thử

### Unit Test

    python -m pytest tests/unit -v

### Integration Test

    python -m pytest tests/integration -v

Integration Test chỉ sử dụng phone_shop_test.

Các bài kiểm thử được thiết kế để rollback
dữ liệu thử nghiệm.

Không sử dụng database phone_shop để chạy
Integration Test.

### Kiểm tra code

    python -m ruff check .

## 10. Quy tắc nghiệp vụ

- Sử dụng Decimal cho giá tiền.
- ROUND_HALF_UP đến 2 chữ số thập phân.
- Thời gian lưu database theo UTC.
- Hiển thị thời gian theo Asia/Ho_Chi_Minh.
- Không cho tồn kho âm.
- Sử dụng transaction khi cập nhật nhiều bảng.
- Có CHECK, FOREIGN KEY, UNIQUE và NOT NULL.
- Sử dụng Strict Mode trên kết nối MariaDB.
- Không lưu mật khẩu dạng văn bản thuần.
- Không tin role hoặc user_id do client tự khai báo.

## 11. Quản lý phiên bản bằng Git

Kiểm tra thay đổi:

    git status

Thêm file:

    git add .

Tạo commit:

    git commit -m "Mo ta thay doi"

Xem lịch sử:

    git log --oneline

## 12. Trạng thái phát triển

Đã triển khai các thành phần nền tảng:

- Cấu hình Python và MariaDB.
- Schema P1 và seed dữ liệu ban đầu.
- Flet Web và thử nghiệm Session.
- MatplotlibChart.
- AppError, Clock, money_utils, code_utils.
- Khung Service và Repository.
- Giao diện website cơ bản và menu mô phỏng.
- Unit Test và Integration Test.

Các chức năng đăng ký, đăng nhập, quản lý sản phẩm,
nhập kho, giỏ hàng và đặt hàng sẽ được triển khai
theo các Task tiếp theo.

## 13. Lưu ý bảo mật

Dự án hiện phục vụ phát triển và demo cục bộ.

Không triển khai công khai lên Internet khi
chưa bổ sung các kiểm soát bảo mật cần thiết.

Không commit:

- Mật khẩu.
- File .env.
- Token xác thực.
- Thông tin bí mật của người dùng.
- Database chứa dữ liệu nhạy cảm.

## 14. Tài liệu

- docs/erd.md: Sơ đồ quan hệ dữ liệu.
- docs/spike_flet_v1_0_5.md: Kiểm thử Flet.
- docs/task7_results.md: Kết quả kiểm thử database.
- Task.md: Tài liệu đặc tả gốc của dự án.
- Excel v2.5: Danh sách Task theo thứ tự triển khai.
