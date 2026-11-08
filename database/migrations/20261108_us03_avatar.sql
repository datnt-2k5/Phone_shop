
-- US03 / Task 20 / P2
-- Thêm đường dẫn ảnh đại diện cho bảng users.
-- Chạy riêng trên phone_shop và phone_shop_test.
-- Sao lưu database trước khi áp dụng DDL.

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS avatar_url VARCHAR(255) NULL
    AFTER address;
