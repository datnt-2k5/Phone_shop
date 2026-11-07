"""Tạo duy nhất một Super Admin để demo, không chứa mật khẩu trong source code.

Chạy từ thư mục gốc dự án: python -m database.seed_super_admin
"""

import os
from datetime import UTC, datetime

import bcrypt
from sqlalchemy import text

from database.connection import engine


def main() -> None:
    if os.getenv("APP_ENV") != "dev" or os.getenv("DB_NAME") != "phone_shop":
        raise RuntimeError("Chỉ seed Super Admin trên phone_shop trong môi trường dev")

    email = os.getenv("SEED_SUPER_ADMIN_EMAIL", "superadmin@example.com").strip().lower()
    password = os.environ["SEED_SUPER_ADMIN_PASSWORD"]
    password_bytes = password.encode("utf-8")

    if not 8 <= len(password) or len(password_bytes) > 72:
        raise ValueError("Mật khẩu Super Admin phải từ 8 ký tự, tối đa 72 byte UTF-8")
    if not any(char.isalpha() for char in password):
        raise ValueError("Mật khẩu Super Admin phải có chữ")
    if not any(char.isdigit() for char in password):
        raise ValueError("Mật khẩu Super Admin phải có số")

    password_hash = bcrypt.hashpw(password_bytes, bcrypt.gensalt()).decode("ascii")
    now_utc = datetime.now(UTC).replace(tzinfo=None)

    with engine.begin() as connection:
        existing = connection.execute(
            text("SELECT id, role FROM users WHERE email = :email FOR UPDATE"),
            {"email": email},
        ).mappings().first()

        if existing is not None:
            if existing["role"] != "SUPER_ADMIN":
                raise RuntimeError("Email đã được sử dụng bởi tài khoản không phải Super Admin")
            print("Super Admin đã tồn tại; không tạo trùng hoặc đổi mật khẩu.")
            return

        another_super_admin = connection.execute(
            text("SELECT id FROM users WHERE role = 'SUPER_ADMIN' LIMIT 1")
        ).first()
        if another_super_admin is not None:
            raise RuntimeError("Database đã có Super Admin khác; không tạo thêm.")

        connection.execute(
            text("""
                INSERT INTO users (
                    email, password_hash, full_name, phone,
                    role, status, created_at, updated_at, updated_by
                ) VALUES (
                    :email, :password_hash, :full_name, :phone,
                    'SUPER_ADMIN', 'ACTIVE', :now_utc, :now_utc, NULL
                )
            """),
            {
                "email": email,
                "password_hash": password_hash,
                "full_name": "Quản trị hệ thống",
                "phone": "0900000000",
                "now_utc": now_utc,
            },
        )
    print("Đã tạo Super Admin thành công (mật khẩu đã được hash bằng bcrypt).")


if __name__ == "__main__":
    main()
