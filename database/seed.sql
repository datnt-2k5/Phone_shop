-- Chỉ chạy trên database phone_shop (không chạy trên phone_shop_test).
-- Dùng UTC_TIMESTAMP() để lưu UTC; không ghi đè cấu hình đã được sửa.

INSERT INTO settings (
    setting_key,
    setting_value,
    updated_at
)
VALUES (
    'ORDER_CANCEL_WINDOW_MINUTES',
    '30',
    UTC_TIMESTAMP()
)
ON DUPLICATE KEY UPDATE
    setting_key = setting_key;