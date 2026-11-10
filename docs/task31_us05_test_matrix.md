
# TASK 31 – US05: Product Regression Test

## Nguồn yêu cầu

- Excel Phone Shop v2.5: Task 31, dòng 32.
- Task.md: US05-T08.
- Task.md: FR5.1 đến FR5.6.
- Task.md: mục 17.6.

## Ma trận kiểm thử

| Nhóm | Tình huống | Kết quả |
|---|---|---|
| CREATE01 | Tạo sản phẩm hợp lệ | ACTIVE, stock = 0, cost = 0 |
| CREATE02 | SKU đã tồn tại | PRODUCT_EXISTS |
| CREATE03 | Trùng hãng/tên/dung lượng/màu | PRODUCT_EXISTS |
| CREATE04 | Giá bán bằng 0 hoặc âm | VALIDATION_ERROR |
| CREATE05 | Thiếu thông tin bắt buộc | VALIDATION_ERROR |
| EDIT01 | Đổi tên trùng sản phẩm khác | PRODUCT_EXISTS |
| EDIT02 | Đổi tên hợp lệ | Thành công |
| EDIT03 | Sửa giá bán không hợp lệ | Từ chối và rollback |
| EDIT04 | Sửa tên/giá/ngưỡng tồn | Không đổi stock/cost_price |
| DB01 | SQL ghi giá bán âm | CHECK từ chối |
| DB02 | SQL ghi tồn âm | CHECK từ chối |
| DB03 | SQL ghi NULL vào cột bắt buộc | NOT NULL từ chối |
| STATUS01 | ACTIVE sang DISCONTINUED | Thành công |
| STATUS02 | DISCONTINUED không còn trong public search | Thành công |
| STATUS03 | DISCONTINUED sang ACTIVE | Khôi phục |
| SECURITY01 | Customer xem dữ liệu công khai | Không có cost_price, stock thực |
| SECURITY02 | Customer gọi API quản trị | FORBIDDEN |
| SECURITY03 | Guest gọi API tạo sản phẩm | UNAUTHORIZED |
| SECURITY04 | Client truyền stock/cost_price khi tạo/sửa | Từ chối |
| STOCK07 | DISCONTINUED qua bước kiểm tra trước bán | PRODUCT_DISCONTINUED |

## Giới hạn nghiệm thu

- STOCK07 hiện được kiểm tra bằng require_active_for_sale().
  Quy trình tạo đơn hoàn chỉnh sẽ kiểm thử thêm ở US10.
- Các nghiệp vụ nhập kho và thay đổi giá vốn thuộc US07.
- Không sử dụng database phát triển phone_shop cho SQL thử lỗi.
- Mỗi Integration Test dùng transaction rollback trên phone_shop_test.
- Không sửa code Task 1–30 nếu không có lỗi thực tế.

## Kết quả thực tế

- Unit Test: cập nhật sau khi chạy.
- Integration Test: cập nhật sau khi chạy.
- Toàn bộ pytest: cập nhật sau khi chạy.
- Ruff: cập nhật sau khi chạy.
- Flet Web: cập nhật sau nghiệm thu.
